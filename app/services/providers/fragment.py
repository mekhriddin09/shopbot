"""Telegram Stars / Premium delivery via Fragment.com.

Uses the `fragment-api-py` library in **KYC mode only**: the wallet seed is
used purely locally (it derives the key with `tonutils` and signs with
PyNaCl), and only the signed transaction reaches a public TON RPC node. The
library's alternative "no-KYC" mode hands the seed to a separate
third-party package/service, so `marketapp_token` is deliberately never
passed here — see the audit notes in AGENTS/README.

Two things about this integration that shape the code below:

1. It is **unofficial**. Fragment has no public API; the library logs in
   with wallet-proof cookies and parses HTML. It has shipped twelve major
   versions in a year, which is what adapting to site changes looks like.
   So every failure path here is treated as expected, not exceptional:
   `fetch()` never raises, and a failure is reported clearly enough for the
   caller to fall back to manual fulfilment.

2. The seed is a secret that must never be logged. `ProviderResult`'s
   `raw_request`/`raw_response` go into `provider_logs`, so nothing derived
   from credentials is ever put in them.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.providers.base import BaseProvider, ProviderResult

logger = logging.getLogger("providers")

# Telegram's own limits, mirrored here so a bad product config is caught
# before any money moves.
_MIN_STARS = 50
_MAX_STARS = 1_000_000
_PREMIUM_MONTHS = (3, 6, 12)

# fragment-api-py refuses to start without all three of these, so we check
# them up front and name the missing one.
REQUIRED_COOKIES = ("stel_ssid", "stel_token", "stel_dt")

# Column titles from the Chrome DevTools cookie table, which get copied
# along with the rows more often than not.
_COOKIE_TABLE_HEADERS = frozenset(
    {"name", "value", "domain", "path", "expires", "max-age", "size",
     "httponly", "secure", "samesite", "partition", "priority"}
)


def parse_external_ref(ref: str | None) -> tuple[str, int] | None:
    """`"stars:100"` -> `("stars", 100)`, `"premium:3"` -> `("premium", 3)`.

    Returns None when the product's external ID isn't a shape this provider
    understands, so the caller can report a configuration problem instead
    of attempting a purchase.
    """
    if not ref:
        return None
    raw = ref.strip().lower().replace(" ", "")
    if ":" not in raw:
        return None
    kind, _, value = raw.partition(":")
    if kind not in ("stars", "premium"):
        return None
    try:
        amount = int(value)
    except ValueError:
        return None
    if kind == "stars" and not (_MIN_STARS <= amount <= _MAX_STARS):
        return None
    if kind == "premium" and amount not in _PREMIUM_MONTHS:
        return None
    return kind, amount


def normalize_username(username: str | None) -> str | None:
    """`"@Durov "` -> `"durov"`. Returns None if it can't be a username."""
    if not username:
        return None
    cleaned = username.strip().lstrip("@").strip()
    if cleaned.startswith("https://t.me/"):
        cleaned = cleaned[len("https://t.me/"):]
    elif cleaned.startswith("t.me/"):
        cleaned = cleaned[len("t.me/"):]
    cleaned = cleaned.strip("/")
    if not (5 <= len(cleaned) <= 32):
        return None
    if not all(ch.isalnum() or ch == "_" for ch in cleaned):
        return None
    return cleaned.lower()


class FragmentProvider(BaseProvider):
    key = "fragment"
    requires_recipient = True

    # ------------------------------------------------------------------
    # Credentials: read fresh from the DB on every call, same pattern as
    # ResellerApiProvider, so rotating them from the admin panel takes
    # effect immediately with no redeploy.
    # ------------------------------------------------------------------

    async def _config(self) -> dict[str, Any]:
        from app.database.engine import async_session_maker
        from app.repositories.setting_repo import SettingRepository

        try:
            async with async_session_maker() as session:
                settings = SettingRepository(session)
                return {
                    "seed": (await settings.get("fragment_seed", "")).strip(),
                    "api_key": (await settings.get("fragment_ton_api_key", "")).strip(),
                    "cookies_raw": (await settings.get("fragment_cookies", "")).strip(),
                    "wallet_version": (
                        await settings.get("fragment_wallet_version", "V5R1")
                    ).strip().upper() or "V5R1",
                }
        except Exception:  # noqa: BLE001 - never let config lookup break a purchase path
            logger.exception("fragment_config_read_failed")
            return {}

    @staticmethod
    def _parse_cookies(raw: str) -> dict[str, str]:
        """Read cookies out of whatever the admin actually pasted.

        This is deliberately forgiving, because the realistic input isn't a
        tidy header string — it's whatever came out of Chrome DevTools.
        Copying a row from the Cookies *table* gives tab- or space-separated
        "name value" lines with no `=` and no `;` at all, which the strict
        `name=value; ...` parser silently dropped. A cookie quietly going
        missing here surfaces much later as an unexplained login failure, so
        every plausible shape is accepted:

            stel_dt=-300; stel_ssid=abc; stel_token=def
            stel_dt=-300
            stel_ssid=abc
            stel_dt    -300
            stel_ssid  abc
            {"stel_dt": "-300", ...}

        Values may legitimately start with "-" (stel_dt is a UTC offset), so
        nothing is stripped beyond whitespace and surrounding quotes.
        """
        raw = (raw or "").strip()
        if not raw:
            return {}

        if raw.startswith("{"):
            import json

            try:
                data = json.loads(raw)
                return {str(k).strip(): str(v).strip() for k, v in data.items() if str(v).strip()}
            except Exception:  # noqa: BLE001
                return {}

        cookies: dict[str, str] = {}
        # Newlines are separators too — a pasted multi-line block is the
        # single most common form and used to be read as one giant value.
        for chunk in raw.replace("\r", "\n").replace(";", "\n").split("\n"):
            part = chunk.strip()
            if not part:
                continue
            if "=" in part:
                name, _, value = part.partition("=")
            else:
                # "name<TAB>value" or "name value" from the DevTools table.
                split = part.split(None, 1)
                if len(split) != 2:
                    continue
                name, value = split
            name = name.strip().strip('"').strip("'")
            value = value.strip().strip('"').strip("'")
            # Only keep things that look like cookie names, and drop the
            # DevTools table's own header row ("Name  Value  Domain …"),
            # which otherwise sails through as a cookie called "Name".
            if not name or not value:
                continue
            if name.lower() in _COOKIE_TABLE_HEADERS:
                continue
            if all(ch.isalnum() or ch in "_-" for ch in name):
                cookies[name] = value
        return cookies

    async def _client(self):
        """Build a configured FragmentClient, or return (None, reason).

        The library is imported lazily: it pulls in curl_cffi/tonutils and
        is only needed when this provider is actually used, so a missing
        install must degrade to a clear message rather than stopping the
        whole bot from starting.
        """
        cfg = await self._config()
        if not cfg.get("seed"):
            return None, "Fragment: hamyon seed iborasi sozlanmagan."
        if not cfg.get("api_key"):
            return None, "Fragment: TON API kaliti (Toncenter/Tonconsole) sozlanmagan."
        cookies = self._parse_cookies(cfg.get("cookies_raw", ""))
        # The library demands all three; checking here (instead of letting it
        # raise deep inside) means the admin is told exactly which one is
        # missing rather than a generic "cookies are invalid".
        missing = [name for name in REQUIRED_COOKIES if not cookies.get(name)]
        if missing:
            return None, (
                f"Fragment: cookie'lar to'liq emas — yetishmayapti: {', '.join(missing)}. "
                "Brauzerda fragment.com → F12 → Application → Cookies dan uchalasini ko'chiring."
            )

        try:
            from FragmentAPI import FragmentClient  # type: ignore
        except ImportError as exc:
            # Either the package itself or one of its binary deps
            # (curl_cffi, tonutils, PyNaCl) is missing — say which, because
            # "not installed" and "installed but broken" need different fixes.
            return None, f"Fragment: kutubxona yuklanmadi — {exc}"
        except Exception as exc:  # noqa: BLE001 - import-time crash, not just absence
            return None, f"Fragment: kutubxona import qilishda xato — {type(exc).__name__}: {exc}"

        # NOTE: marketapp_token is intentionally NOT passed. That would
        # switch the library into no-KYC mode, which forwards the seed to a
        # third-party service. Local signing only.
        try:
            client = FragmentClient(
                cookies=cookies,
                seed=cfg["seed"],
                api_key=cfg["api_key"],
                wallet_version=cfg["wallet_version"],
            )
        except Exception as exc:  # noqa: BLE001
            # Most often a malformed seed or an unsupported wallet version.
            # The message must never echo the seed itself.
            logger.error("fragment_client_init_failed err=%s", type(exc).__name__)
            return None, (
                f"Fragment: hamyonni ochib bo'lmadi — {type(exc).__name__}: {exc}. "
                "Seed iborasi (24 so'z) va hamyon versiyasini tekshiring."
            )
        return client, None

    # ------------------------------------------------------------------
    # Pre-purchase checks
    # ------------------------------------------------------------------

    async def search_recipient(self, username: str) -> tuple[bool, str | None]:
        """Confirm Fragment can deliver to this username *before* the
        customer is asked to pay. Fails open (returns ok) when the check
        itself can't run — a flaky check must not block sales, since the
        purchase call validates again anyway."""
        handle = normalize_username(username)
        if not handle:
            return False, "Username formati noto'g'ri."

        client, reason = await self._client()
        if client is None:
            logger.warning("fragment_search_unavailable reason=%s", reason)
            return True, None

        try:
            async with client as c:
                info = await c.search_stars_recipient(handle) if hasattr(
                    c, "search_stars_recipient"
                ) else await c.search_usernames(handle)
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            if "UserNotFound" in name:
                return False, "Bunday username topilmadi."
            logger.warning("fragment_search_failed user=%s err=%s", handle, name)
            return True, None

        if info is None:
            return False, "Bunday username topilmadi."
        display = getattr(info, "name", None) or getattr(info, "recipient", None)
        return True, str(display) if display else None

    async def get_price(self, external_ref: str | None) -> tuple[bool, float | None, str | None]:
        """Live Fragment price for this product, used by the admin to check
        the real margin. (ok, price, error)."""
        parsed = parse_external_ref(external_ref)
        if parsed is None:
            return False, None, "Tashqi ID formati noto'g'ri (masalan: stars:100 yoki premium:3)."
        kind, amount = parsed

        client, reason = await self._client()
        if client is None:
            return False, None, reason

        try:
            async with client as c:
                if kind == "stars":
                    quote = await c.get_stars_price(amount)
                else:
                    quote = await c.get_premium_prices()
        except Exception as exc:  # noqa: BLE001
            return False, None, f"{type(exc).__name__}: {exc}"

        price = getattr(quote, "price", None) or getattr(quote, "ton", None)
        return True, float(price) if price is not None else None, None

    # ------------------------------------------------------------------
    # The purchase itself
    # ------------------------------------------------------------------

    async def fetch(
        self,
        *,
        product_external_ref: str | None,
        order_uuid: str,
        recipient: str | None = None,
    ) -> ProviderResult:
        parsed = parse_external_ref(product_external_ref)
        if parsed is None:
            return ProviderResult(
                success=False,
                error=(
                    "Mahsulotning Tashqi ID'si noto'g'ri. "
                    "Kutilgan format: stars:100 yoki premium:3 (3/6/12 oy)."
                ),
            )
        kind, amount = parsed

        handle = normalize_username(recipient)
        if not handle:
            return ProviderResult(
                success=False,
                error="Qabul qiluvchi username ko'rsatilmagan yoki formati noto'g'ri.",
            )

        client, reason = await self._client()
        if client is None:
            return ProviderResult(success=False, error=reason)

        # Logged (and stored in provider_logs) deliberately WITHOUT any
        # credential material — just what was ordered and for whom.
        request_note = f"fragment {kind}:{amount} -> @{handle} (order {order_uuid})"

        try:
            async with client as c:
                if kind == "stars":
                    result = await c.purchase_stars(handle, amount)
                else:
                    result = await c.purchase_premium(handle, amount)
        except Exception as exc:  # noqa: BLE001 - see module docstring: breakage is expected
            name = type(exc).__name__
            logger.error(
                "fragment_purchase_failed order=%s kind=%s amount=%s err=%s: %s",
                order_uuid, kind, amount, name, exc,
            )
            return ProviderResult(
                success=False,
                raw_request=request_note,
                error=self._friendly_error(name, exc),
            )

        tx_id = getattr(result, "transaction_id", None) or getattr(result, "tx_id", None)
        logger.info(
            "fragment_purchase_ok order=%s kind=%s amount=%s to=%s tx=%s",
            order_uuid, kind, amount, handle, tx_id,
        )

        if kind == "stars":
            payload = f"⭐ {amount} Telegram Stars → @{handle}"
        else:
            payload = f"💎 Telegram Premium {amount} oy → @{handle}"
        if tx_id:
            payload += f"\n\n🔗 TX: <code>{tx_id}</code>"

        return ProviderResult(
            success=True,
            payload=payload,
            raw_request=request_note,
            raw_response=f"tx={tx_id}" if tx_id else "ok",
        )

    @staticmethod
    def _friendly_error(exc_name: str, exc: Exception) -> str:
        """Turn the library's exception into something an admin can act on.

        The distinction that matters most: "our wallet is empty / our login
        expired" (admin must fix something) vs "this recipient can't
        receive it" (customer-side, refund or ask for another username).
        """
        if "AlreadySubscribed" in exc_name:
            return "Bu foydalanuvchida Premium allaqachon faol."
        if "UserNotFound" in exc_name:
            return "Qabul qiluvchi username topilmadi."
        if "Wallet" in exc_name:
            return "⚠️ HAMYON: balans yetarli emas yoki hamyonda muammo. To'ldirish kerak."
        if "Cookie" in exc_name or "Verification" in exc_name:
            return "⚠️ KIRISH: fragment.com cookie'lari eskirgan. Sozlamalardan yangilash kerak."
        if "ConfirmationTimeout" in exc_name:
            return (
                "⚠️ Tranzaksiya vaqtida tasdiqlanmadi. Pul yechilgan bo'lishi mumkin — "
                "Fragment tarixini tekshiring, takrorlamang."
            )
        if "FragmentPage" in exc_name or "Parse" in exc_name:
            return (
                "⚠️ Fragment sayti o'zgargan ko'rinadi (kutubxona moslashishi kerak). "
                "Qo'lda bajarish lozim."
            )
        return f"{exc_name}: {exc}"


__all__ = ["FragmentProvider", "parse_external_ref", "normalize_username"]
