from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters.is_admin import IsAdmin
from app.keyboards.admin_kb import (
    SETTINGS_GROUPS,
    admin_settings_menu_kb,
    settings_language_pick_kb,
)
from app.keyboards.callback_data import AdminReferralWithdrawCB, AdminSettingsCB
from app.repositories.referral_repo import ReferralRepository
from app.repositories.setting_repo import SettingRepository
from app.states.admin_states import AdminInput
from app.utils.formatting import fmt_price
from app.utils.i18n import t

logger = logging.getLogger("admin")

router = Router(name="admin_settings")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

_LANGS = ("uz", "ru", "en")


def _short(value: str, limit: int = 40) -> str:
    """One-line preview of a possibly long/multi-line setting value."""
    flat = " ".join((value or "").split())
    if not flat:
        return "—"
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


async def render_settings_group(session: AsyncSession, group: str) -> tuple[str, object]:
    """Build the text + keyboard for one settings group, listing each
    setting's *current value* inline. Driven entirely by SETTINGS_GROUPS
    (see app/keyboards/admin_kb.py) so the summary can never drift out of
    sync with the buttons actually shown."""
    spec = SETTINGS_GROUPS.get(group) or SETTINGS_GROUPS["root"]
    settings_repo = SettingRepository(session)

    lines = [spec["title"]]
    if spec.get("intro"):
        lines.append("")
        lines.append(spec["intro"])

    value_lines: list[str] = []
    for kind, key, label in spec["items"]:
        if kind == "toggle":
            state = "✅ yoqilgan" if await settings_repo.get_bool(key, False) else "❌ o'chirilgan"
            value_lines.append(f"• {label}: <b>{state}</b>")
        elif kind == "edit":
            value_lines.append(f"• {label}: <code>{_short(await settings_repo.get(key))}</code>")
        elif kind == "masked":
            value_lines.append(f"• {label}: <code>{_mask_secret(await settings_repo.get(key))}</code>")
        elif kind == "lang":
            filled = [
                code.upper() for code in _LANGS if (await settings_repo.get(f"{key}_{code}", "")).strip()
            ]
            value_lines.append(
                f"• {label}: {('✅ ' + ', '.join(filled)) if filled else '❌ hech biri kiritilmagan'}"
            )
        # "group" / "phones" / "test_reseller" / "test_fragment" hold no
        # value of their own.

    if value_lines:
        lines.append("")
        lines.extend(value_lines)

    return "\n".join(lines), admin_settings_menu_kb(group)


@router.callback_query(AdminSettingsCB.filter(F.action == "group"))
async def settings_open_group(callback: CallbackQuery, callback_data: AdminSettingsCB, session: AsyncSession) -> None:
    """Navigate between settings groups (including "back"), editing the
    same message in place so the admin doesn't end up with a long trail of
    menu messages in the chat."""
    text, kb = await render_settings_group(session, callback_data.key or "root")
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            # Can't edit (e.g. the message was a photo/too old) — send fresh.
            await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(AdminSettingsCB.filter(F.action == "pick_lang"))
async def settings_pick_lang(callback: CallbackQuery, callback_data: AdminSettingsCB) -> None:
    try:
        await callback.message.edit_reply_markup(
            reply_markup=settings_language_pick_kb(callback_data.key, callback_data.group or "root")
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
    await callback.answer()


@router.callback_query(AdminSettingsCB.filter(F.action == "edit"))
async def settings_edit_start(callback: CallbackQuery, callback_data: AdminSettingsCB, session: AsyncSession, state: FSMContext) -> None:
    current = await SettingRepository(session).get(callback_data.key)
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(action="settings_edit", key=callback_data.key, group=callback_data.group or "root")
    shown = current if current else "(bo'sh)"
    await callback.message.answer(
        f"Joriy qiymat:\n\n{shown}\n\n"
        f"👇 Yangi matnni yozing, YOKI matn juda uzun bo'lsa, .txt fayl qilib yuboring:"
    )
    await callback.answer()


def _mask_secret(value: str) -> str:
    if not value:
        return "(o'rnatilmagan — .env dagi qiymat ishlatiladi)"
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * (len(value) - 4)}{value[-4:]}"


@router.callback_query(AdminSettingsCB.filter(F.action == "edit_masked"))
async def settings_edit_masked_start(
    callback: CallbackQuery, callback_data: AdminSettingsCB, session: AsyncSession, state: FSMContext
) -> None:
    """Same as `settings_edit_start`, but for secrets (API keys/tokens) —
    shows only the last 4 characters instead of the full value, so it
    doesn't sit fully exposed in the chat every time someone opens this
    menu. Saving works exactly the same as a normal setting (dispatches to
    the shared "settings_edit" action in generic_input.py)."""
    current = await SettingRepository(session).get(callback_data.key)
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(action="settings_edit", key=callback_data.key, group=callback_data.group or "root")
    await callback.message.answer(
        f"Joriy qiymat (oxirgi 4 belgi): {_mask_secret(current)}\n\n"
        f"👇 Yangi qiymatni yozing (bekor qilish uchun '-' yuboring — o'zgarishsiz qoladi):"
    )
    await callback.answer()


@router.callback_query(AdminSettingsCB.filter(F.action == "test_fragment"))
async def settings_test_fragment(callback: CallbackQuery, session: AsyncSession) -> None:
    """Dry-run the whole Fragment setup without spending a coin.

    Reports in TWO messages on purpose. The first (config summary) is sent
    immediately, before anything touches the network, because the network
    part talks to an unofficial site through a library that can hang or
    raise anything at all — and a diagnostic tool that goes silent when the
    thing it's diagnosing misbehaves is worse than no tool. Every live call
    is therefore wrapped in both a timeout and a bare except, and whatever
    happens gets reported, including the exception type.
    """
    import asyncio

    from app.services.providers.fragment import FragmentProvider

    await callback.answer("Tekshirilmoqda…")

    try:
        provider = FragmentProvider()
        cfg = await provider._config()  # noqa: SLF001 - same module family
        cookies = provider._parse_cookies(cfg.get("cookies_raw", ""))  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        await callback.message.answer(
            f"❌ Sozlamalarni o'qib bo'lmadi:\n<code>{type(exc).__name__}: {exc}</code>"
        )
        return

    lines = ["\U0001F50C <b>1/2 — Sozlamalar</b>", ""]
    lines.append(("✅" if cfg.get("seed") else "❌") + " Hamyon seed iborasi")
    lines.append(("✅" if cfg.get("api_key") else "❌") + " TON API kaliti")
    from app.services.providers.fragment import REQUIRED_COOKIES

    missing_cookies = [name for name in REQUIRED_COOKIES if not cookies.get(name)]
    if missing_cookies:
        # Show what WAS read, not only what's missing: when a paste is
        # mangled the admin needs to see how the bot actually understood it.
        read = ", ".join(sorted(cookies)) if cookies else "hech narsa o'qilmadi"
        lines.append(f"❌ Cookie'lar — yetishmayapti: {', '.join(missing_cookies)}")
        lines.append(f"   O'qilgani: {read}")
    else:
        lines.append(f"✅ Cookie'lar ({', '.join(sorted(cookies))})")
    version = cfg.get("wallet_version") or "-"
    lines.append(f"\U0001F45B Hamyon versiyasi: <code>{version}</code>")

    ready = bool(cfg.get("seed") and cfg.get("api_key") and not missing_cookies)
    if not ready:
        lines += ["", "Avval yuqoridagi ❌ bandlarni to'ldiring."]
        await callback.message.answer("\n".join(lines))
        return

    lines += ["", "⏳ Endi Fragment bilan aloqa tekshirilmoqda (30 soniyagacha)…"]
    await callback.message.answer("\n".join(lines))

    # ---- live checks, each isolated: a hang or a crash still reports ----
    out = ["\U0001F50C <b>2/2 — Fragment bilan aloqa</b>", ""]

    try:
        ok, price, error = await asyncio.wait_for(provider.get_price("stars:50"), timeout=30)
        if ok:
            out.append(f"✅ Aloqa bor. 50 Stars narxi: <b>{price if price is not None else '?'} TON</b>")
        else:
            out.append(f"❌ Fragment rad etdi:\n<code>{error}</code>")
    except asyncio.TimeoutError:
        ok = False
        out.append(
            "❌ 30 soniyada javob bo'lmadi.\n"
            "Sabablari: TON API kaliti noto'g'ri, cookie'lar eskirgan, yoki Fragment javob bermayapti."
        )
    except Exception as exc:  # noqa: BLE001
        ok = False
        logger.exception("fragment_test_price_failed")
        out.append(f"❌ Kutilmagan xato:\n<code>{type(exc).__name__}: {exc}</code>")

    handle = callback.from_user.username
    if handle:
        try:
            found, note = await asyncio.wait_for(provider.search_recipient(handle), timeout=30)
            out.append(
                f"✅ Username tekshiruvi: @{handle}{' — ' + note if note else ''}"
                if found
                else f"❌ Username tekshiruvi: @{handle} — {note}"
            )
        except asyncio.TimeoutError:
            out.append(f"❌ Username tekshiruvi 30 soniyada javob bermadi (@{handle}).")
        except Exception as exc:  # noqa: BLE001
            logger.exception("fragment_test_search_failed")
            out.append(f"❌ Username tekshiruvi xato berdi:\n<code>{type(exc).__name__}: {exc}</code>")
    else:
        out.append("ℹ️ Sizda username yo'q, shu sabab username tekshiruvi o'tkazilmadi.")

    if ok:
        out += [
            "",
            "Hammasi joyida. Endi <code>stars:50</code> mahsulotini yaratib, o'zingizga "
            "bitta sinov xaridi qiling — to'lov zanjiri faqat haqiqiy xaridda tekshiriladi.",
        ]
    await callback.message.answer("\n".join(out))


@router.callback_query(AdminSettingsCB.filter(F.action == "test_reseller"))
async def settings_test_reseller(callback: CallbackQuery, session: AsyncSession) -> None:
    """Calls the reseller's own /v1/balance right now, with whatever
    key/URL is currently active (DB override if set, else .env), and shows
    the live result directly in the chat — the fastest way for the admin
    to confirm a newly-pasted key actually works, no Railway/logs needed."""
    from app.services.providers.reseller_api import ResellerApiProvider

    await callback.answer("Tekshirilmoqda…")
    provider = ResellerApiProvider()
    ok, balance, error = await provider.get_balance()
    if ok:
        await callback.message.answer(
            f"✅ Reseller API bilan ulanish muvaffaqiyatli!\n\n💰 Balans: {fmt_price(float(balance or 0))}"
        )
    else:
        await callback.message.answer(
            f"❌ Reseller API bilan ulanishda xatolik:\n\n<code>{error}</code>\n\n"
            f"Kalitni va manzilni tekshirib qayta urinib ko'ring."
        )


def _label_for(key: str) -> str:
    """Human label for a settings key, taken from whichever group lists it
    (see SETTINGS_GROUPS) — no separate label dict to keep in sync."""
    for spec in SETTINGS_GROUPS.values():
        for kind, item_key, label in spec["items"]:
            if item_key == key and kind in ("toggle", "edit", "masked", "lang"):
                return label
    return key


@router.callback_query(AdminSettingsCB.filter(F.action == "toggle"))
async def settings_toggle(callback: CallbackQuery, callback_data: AdminSettingsCB, session: AsyncSession) -> None:
    settings_repo = SettingRepository(session)
    # Default False, not True: every toggle's real default now lives in
    # DEFAULT_SETTINGS (seeded at startup), and defaulting to True here made
    # an unseeded key read as "on" and flip to "off" on its first tap.
    current = await settings_repo.get_bool(callback_data.key, False)
    await settings_repo.set(callback_data.key, "0" if current else "1")
    state_text = "o'chirildi" if current else "yoqildi"
    await callback.answer(f"{_label_for(callback_data.key)}: {state_text} ✅")

    # Re-render the whole group so the "current value" line next to this
    # toggle updates too — not just the keyboard.
    text, kb = await render_settings_group(session, callback_data.group or "root")
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


@router.callback_query(AdminReferralWithdrawCB.filter(F.action == "paid"))
async def referral_withdraw_paid(
    callback: CallbackQuery, callback_data: AdminReferralWithdrawCB, session: AsyncSession
) -> None:
    referrals = ReferralRepository(session)
    withdrawal = await referrals.get_withdrawal(callback_data.withdrawal_id)
    if withdrawal is None:
        await callback.answer("So'rov topilmadi.", show_alert=True)
        return
    await referrals.mark_paid(withdrawal, callback.from_user.id)
    await callback.message.edit_text(callback.message.text + "\n\n✅ TO'LANDI")
    await callback.message.edit_reply_markup(reply_markup=None)
    try:
        await callback.bot.send_message(
            withdrawal.user.telegram_id,
            t(withdrawal.user.language, "msg_referral_withdraw_paid", amount=fmt_price(float(withdrawal.amount))),
        )
    except Exception:  # noqa: BLE001 - user may have blocked the bot
        pass
    await callback.answer("To'landi deb belgilandi ✅")


@router.callback_query(AdminReferralWithdrawCB.filter(F.action == "reject"))
async def referral_withdraw_reject(
    callback: CallbackQuery, callback_data: AdminReferralWithdrawCB, session: AsyncSession
) -> None:
    referrals = ReferralRepository(session)
    withdrawal = await referrals.get_withdrawal(callback_data.withdrawal_id)
    if withdrawal is None:
        await callback.answer("So'rov topilmadi.", show_alert=True)
        return
    await referrals.mark_rejected(withdrawal, callback.from_user.id)
    await callback.message.edit_text(callback.message.text + "\n\n❌ RAD ETILDI")
    await callback.message.edit_reply_markup(reply_markup=None)
    try:
        await callback.bot.send_message(
            withdrawal.user.telegram_id,
            t(withdrawal.user.language, "msg_referral_withdraw_rejected", amount=fmt_price(float(withdrawal.amount))),
        )
    except Exception:  # noqa: BLE001 - user may have blocked the bot
        pass
    await callback.answer("Rad etildi")


