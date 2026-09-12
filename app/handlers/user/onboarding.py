"""User side of the onboarding gate's own buttons (oferta accept / channel
re-check — the mandatory, applies-to-everyone half, actually intercepted
and shown by OnboardingGateMiddleware; these handlers are what run once the
admin's "ogate:" buttons are tapped) plus the separate, referral-only
confirmation flow (phone number + math captcha) that protects a referrer's
stats/rewards from fake-account farming. See app/services/onboarding_service.py
for the phone/captcha logic and app/middlewares/onboarding_gate.py for the
mandatory gate itself."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.filters.is_admin import is_admin_telegram_id
from app.keyboards.callback_data import CaptchaCB, OnboardingCB
from app.keyboards.user_kb import (
    captcha_kb,
    channel_check_kb,
    main_menu_kb,
    request_contact_kb,
)
from app.repositories.setting_repo import SettingRepository
from app.repositories.user_repo import UserRepository
from app.services.onboarding_service import (
    generate_captcha,
    is_phone_allowed,
    normalize_phone,
    user_needs_referral_confirmation,
)
from app.utils.i18n import t

router = Router(name="user_onboarding")

_ACTIVE_CHANNEL_STATUSES = {"member", "administrator", "creator"}


async def _show_main_menu(target, session: AsyncSession, user: User, lang: str) -> None:
    settings_repo = SettingRepository(session)
    welcome = await settings_repo.get(f"welcome_message_{lang}") or await settings_repo.get("welcome_message_en")
    is_admin = await is_admin_telegram_id(user.telegram_id, session)
    needs_confirm = await user_needs_referral_confirmation(session, user)
    await target.answer(welcome, reply_markup=main_menu_kb(lang, is_admin=is_admin, needs_referral_confirmation=needs_confirm))


@router.callback_query(OnboardingCB.filter(F.action == "accept_offer"))
async def accept_offer(callback: CallbackQuery, session: AsyncSession, user: User, lang: str) -> None:
    await UserRepository(session).mark_oferta_accepted(user)
    settings_repo = SettingRepository(session)
    required_channel = await settings_repo.get("required_channel", "")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001 - best effort
        pass
    if required_channel:
        channel_url = await settings_repo.get("required_channel_url", "")
        await callback.message.answer(t(lang, "msg_channel_subscribe_required"), reply_markup=channel_check_kb(lang, channel_url))
        await callback.answer()
        return
    await _show_main_menu(callback.message, session, user, lang)
    await callback.answer()


@router.callback_query(OnboardingCB.filter(F.action == "check_channel"))
async def check_channel(callback: CallbackQuery, session: AsyncSession, user: User, lang: str) -> None:
    settings_repo = SettingRepository(session)
    required_channel = await settings_repo.get("required_channel", "")
    subscribed = True
    if required_channel:
        try:
            member = await callback.bot.get_chat_member(required_channel, user.telegram_id)
            subscribed = member.status in _ACTIVE_CHANNEL_STATUSES
        except Exception:  # noqa: BLE001 - fail open, same reasoning as the middleware
            subscribed = True
    if not subscribed:
        await callback.answer(t(lang, "msg_channel_still_not_subscribed"), show_alert=True)
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001 - best effort
        pass
    await _show_main_menu(callback.message, session, user, lang)
    await callback.answer()


# ------------------------------------------------------------------
# Referral confirmation: phone + captcha — only for users who came via a
# referral link, to protect the referrer's stats/rewards from fake accounts.
# ------------------------------------------------------------------


@router.message(F.text.in_({t(l, "btn_referral_confirm") for l in ("uz", "ru", "en")}))
async def referral_confirm_start(message: Message, lang: str) -> None:
    await message.answer(t(lang, "msg_referral_confirm_intro"), reply_markup=request_contact_kb(lang))


async def _awaiting_referral_confirmation(message: Message, user: User) -> bool:
    """Custom filter (not just an `if` inside the handler) so that a contact
    share from a user who ISN'T in this flow falls through to whatever else
    might want it (e.g. the support relay) instead of being silently
    swallowed here — an aiogram handler that runs and returns `None` counts
    as "handled", so scoping this at the filter level is what actually
    matters, not an early-return inside the function body."""
    return bool(user.referred_by_id) and not user.referral_confirmed


@router.message(F.contact, _awaiting_referral_confirmation)
async def contact_received(message: Message, session: AsyncSession, user: User, lang: str) -> None:
    contact = message.contact
    if contact.user_id and contact.user_id != message.from_user.id:
        # Someone shared a saved contact card that isn't their own number —
        # exactly the kind of spoofing this gate exists to prevent.
        await message.answer(t(lang, "msg_phone_must_be_own"))
        return

    if not await is_phone_allowed(session, contact.phone_number):
        await message.answer(t(lang, "msg_phone_rejected"))
        return

    await UserRepository(session).set_phone_number(user, normalize_phone(contact.phone_number))

    question, correct, options = generate_captcha()
    await message.answer(
        t(lang, "msg_captcha_prompt", question=question),
        reply_markup=captcha_kb(options, correct),
    )


@router.callback_query(CaptchaCB.filter(F.action == "answer"))
async def captcha_answer(
    callback: CallbackQuery, callback_data: CaptchaCB, session: AsyncSession, user: User, lang: str
) -> None:
    if user.referral_confirmed or not user.referred_by_id:
        await callback.answer()
        return

    if not callback_data.correct:
        question, correct, options = generate_captcha()
        try:
            await callback.message.edit_text(t(lang, "msg_captcha_wrong") + "\n\n" + t(lang, "msg_captcha_prompt", question=question))
            await callback.message.edit_reply_markup(reply_markup=captcha_kb(options, correct))
        except Exception:  # noqa: BLE001 - best effort re-render
            pass
        await callback.answer()
        return

    await UserRepository(session).mark_referral_confirmed(user)
    try:
        await callback.message.edit_text(t(lang, "msg_referral_confirmed"))
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001 - best effort
        pass
    is_admin = await is_admin_telegram_id(user.telegram_id, session)
    await callback.message.answer(
        t(lang, "main_menu_hint"),
        reply_markup=main_menu_kb(lang, is_admin=is_admin, needs_referral_confirmation=False),
    )
    await callback.answer()


__all__ = ["router"]
