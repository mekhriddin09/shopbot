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

# fragment-api-py refuses to start without the first three, and every
# wallet-backed operation (which is all of ours — reading the balance and
# paying with TON both go through the wallet) additionally needs
# stel_ton_token. That last one only exists once a TON wallet has been
# connected on fragment.com, which makes it the one cookie people miss:
# they log in with Telegram, copy three cookies, and only discover the
# fourth when a purchase fails. So it's required here, up front.
REQUIRED_COOKIES = ("stel_ssid", "stel_token", "stel_dt", "stel_ton_token")

# Column titles from the Chrome DevTools cookie table, which get copied
# along with the rows more often than not.
_COOKIE_TABLE_HEADERS = frozenset(
    {"name", "value", "domain", "path", "expires", "max-age", "size",
     "httponly", "secure", "samesite", "partition", "priority"}
)


CUSTOM_REF = "stars:custom"


def is_custom_stars(ref: str | None) -> bool:
    """A product whose Stars amount the customer types in themselves.

    Fixed packages (50/100/1000) can't cover everyone — someone always wants
    137 Stars, and big buyers deserve a keener per-star price than a small
    package. For these products the UZS price field means "price of ONE
    star" and the order quantity carries the number of stars.
    """
    return (ref or "").strip().lower() in (CUSTOM_REF, "stars:*", "stars:any")


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
                    "api_provider": (
                        await settings.get("fragment_api_provider", "auto")
                    ).strip().lower() or "auto",
                }
        except Exception:  # noqa: BLE001 - never let config lookup break a purchase path
            logger.exception("fragment_config_read_failed")
            return {}

    @staticmethod
    def detect_api_provider(api_key: str, configured: str = "auto") -> str:
        """Which RPC the TON key belongs to: "tonapi" or "toncenter".

        The library defaults to tonapi.io and sends the key as-is, so a
        Toncenter key produces a baffling `401 illegal base32 data` from
        tonapi — an error that names neither the key nor the provider. The
        two key formats are easy to tell apart, so guess by default and let
        the admin override when the guess is wrong.

        Toncenter keys are exactly 64 hex characters; tonapi/tonconsole
        keys are much longer base64url strings.
        """
        if configured in ("tonapi", "toncenter"):
            return configured
        key = (api_key or "").strip()
        if len(key) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in key):
            return "toncenter"
        return "tonapi"

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
            hint = (
                "fragment.com'da TON hamyonni ulang (Connect TON), so'ng cookie'larni "
                "qayta ko'chiring — stel_ton_token faqat hamyon ulangach paydo bo'ladi."
                if "stel_ton_token" in missing
                else "Brauzerda fragment.com → F12 → Application → Cookies dan ko'chiring."
            )
            return None, f"Fragment: cookie'lar to'liq emas — yetishmayapti: {', '.join(missing)}. {hint}"

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
        provider_name = self.detect_api_provider(cfg["api_key"], cfg.get("api_provider", "auto"))
        try:
            client = FragmentClient(
                cookies=cookies,
                seed=cfg["seed"],
                api_key=cfg["api_key"],
                wallet_version=cfg["wallet_version"],
                api_provider=provider_name,
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

    async def get_wallet_info(self) -> tuple[bool, str | None, float | None]:
        """(ok, address, TON balance) for the shop's own wallet.

        Deliberately does NOT use the library's `get_wallet()`. That call
        also reads the wallet's USDT balance, and on a wallet that has never
        held USDT the jetton contract simply doesn't exist — the get-method
        fails with `exit code -13` and takes the whole call down with it,
        hiding the TON balance we actually care about. A fresh, correctly
        configured shop wallet is exactly the case that breaks, so we read
        the TON side ourselves and fall back to the library only if that
        fails.
        """
        client, reason = await self._client()
        if client is None:
            return False, reason, None

        try:
            async with client as c:
                # Same wallet construction the library uses internally to
                # sign, so the address shown here is precisely the one that
                # will pay — which is the whole point of showing it.
                try:
                    # Imported inside the try on purpose: these are the
                    # library's internals, so a version that moves or
                    # renames them must fall back, not crash.
                    from FragmentAPI.types.constants import WALLET_CLASSES
                    from FragmentAPI.utils.wallet import _make_ton_client

                    async with _make_ton_client(c) as ton:
                        wallet_cls = WALLET_CLASSES[c.wallet_version]
                        wallet, _, _, _ = wallet_cls.from_mnemonic(client=ton, mnemonic=c.seed)
                        await wallet.refresh()
                        address = wallet.address.to_str(is_user_friendly=True, is_bounceable=False)
                        return True, address, round(wallet.balance / 1_000_000_000, 4)
                except Exception as exc:  # noqa: BLE001 - fall back below
                    logger.warning("fragment_wallet_direct_read_failed err=%s", type(exc).__name__)

                info = await c.get_wallet()
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}", None

        balance = getattr(info, "gram_balance", None)
        if balance is None:
            balance = getattr(info, "balance_ton", None)
        return True, getattr(info, "address", None), float(balance) if balance is not None else None

    async def derive_addresses(self) -> tuple[dict[str, str], str | None]:
        """Address this seed produces under *each* wallet version.

        One seed gives a different address per wallet version, so "the bot
        shows a different address than my wallet app" usually means the
        version setting is wrong — not that the seed is wrong. Showing both
        turns a guessing game into a glance: if one of them matches the
        wallet app, switch the setting; if neither does, the seed itself is
        for a different wallet (e.g. a 12-word multichain account whose TON
        address is derived differently).
        """
        client, reason = await self._client()
        if client is None:
            return {}, reason

        found: dict[str, str] = {}
        try:
            async with client as c:
                from FragmentAPI.types.constants import WALLET_CLASSES
                from FragmentAPI.utils.wallet import _make_ton_client

                async with _make_ton_client(c) as ton:
                    for version, wallet_cls in WALLET_CLASSES.items():
                        try:
                            wallet, _, _, _ = wallet_cls.from_mnemonic(client=ton, mnemonic=c.seed)
                            found[version] = wallet.address.to_str(
                                is_user_friendly=True, is_bounceable=False
                            )
                        except Exception as exc:  # noqa: BLE001
                            found[version] = f"(xato: {type(exc).__name__})"
        except Exception as exc:  # noqa: BLE001
            return found, f"{type(exc).__name__}: {exc}"
        return found, None

    async def search_recipient(self, username: str, kind: str = "stars") -> tuple[bool, str | None]:
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
                # NOT search_usernames() — that searches the marketplace for
                # usernames on sale, which has nothing to do with whether a
                # gift can be delivered to this person.
                if kind == "premium":
                    info = await c.get_premium_recipient(handle)
                else:
                    info = await c.get_stars_recipient(handle)
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

        # StarsPrice/PremiumPriceOption carry `gram_price` (a string, with
        # `ton_price` kept as an alias); there is no `.price`.
        raw = None
        if kind == "stars":
            raw = getattr(quote, "gram_price", None) or getattr(quote, "ton_price", None)
        else:
            options = getattr(quote, "options", None) or []
            for option in options:
                if int(getattr(option, "months", 0) or 0) == amount:
                    raw = getattr(option, "gram_price", None) or getattr(option, "ton_price", None)
                    break
        if raw is None:
            return True, None, None
        try:
            return True, float(str(raw).replace(",", "").strip()), None
        except ValueError:
            return True, None, None

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
                # show_sender=False: Fragment defaults to showing the
                # paying account's own name/profile to the recipient as
                # "gifted by ...". The shop's Fragment account is the
                # admin's own personal account, so every gift was leaking
                # their identity to the customer — always send anonymously.
                if kind == "stars":
                    result = await c.purchase_stars(handle, amount, show_sender=False)
                else:
                    result = await c.purchase_premium(handle, amount, show_sender=False)
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

        Every branch appends the library's own message. An earlier version
        replaced it entirely and that cost real debugging time: a KYC
        rejection was matched by a loose "Verification" check and reported
        as "cookies expired", sending the admin to re-copy cookies that were
        perfectly fine. Never hide the original text.
        """
        raw = str(exc).strip()
        detail = f"\n\nAsl xabar: {raw[:400]}" if raw else ""

        if "Verification" in exc_name or "need_verify" in raw or "KYC" in raw.upper():
            return (
                "\u26d4 KYC TASDIQLANMAGAN. Fragment bu hamyon/akkaunt uchun shaxsni "
                "tasdiqlashni talab qilyapti.\n"
                "fragment.com/my/profile \u2192 Verify \u2192 tasdiqdan o'ting, keyin qayta urinib ko'ring."
                + detail
            )
        if "AlreadySubscribed" in exc_name:
            return "Bu foydalanuvchida Premium allaqachon faol." + detail
        if "UserNotFound" in exc_name:
            return "Qabul qiluvchi username topilmadi." + detail
        if "Cookie" in exc_name:
            return (
                "\u26a0\ufe0f KIRISH: fragment.com cookie'lari eskirgan yoki to'liq emas. "
                "Sozlamalardan yangilash kerak." + detail
            )
        if "Wallet" in exc_name:
            if "401" in raw or "403" in raw:
                return (
                    "\u26a0\ufe0f TON API kaliti rad etildi (401). Sozlamalarda 'TON API turi'ni "
                    "kalitingizga moslang." + detail
                )
            if "exit code -13" in raw or "get_wallet_data" in raw:
                return "\u26a0\ufe0f Hamyonning USDT hisobi yo'q (odatiy holat)." + detail
            return "\u26a0\ufe0f HAMYON: balans yetarli emas yoki hamyonda muammo." + detail
        if "ConfirmationTimeout" in exc_name:
            return (
                "\u26a0\ufe0f Tranzaksiya vaqtida tasdiqlanmadi. Pul yechilgan bo'lishi mumkin \u2014 "
                "Fragment tarixini tekshiring, takrorlamang." + detail
            )
        if "FragmentPage" in exc_name or "Parse" in exc_name:
            return (
                "\u26a0\ufe0f Fragment sayti o'zgargan ko'rinadi (kutubxona moslashishi kerak). "
                "Qo'lda bajarish lozim." + detail
            )
        return f"{exc_name}: {raw}"


__all__ = ["FragmentProvider", "parse_external_ref", "normalize_username"]
