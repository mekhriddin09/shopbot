"""User side of the onboarding gate: the oferta-accept / channel-recheck
buttons, and the referral-confirmation step (phone number + math captcha)
that protects a referrer's stats/rewards from fake-account farming.

The gate itself (which steps apply to whom, and blocking everything else
until they're done) lives in `app/middlewares/onboarding_gate.py`; these
handlers just process the taps/uploads that flow *out* of it. Phone/captcha
logic is in `app/services/onboarding_service.py`."""
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
    await target.answer(welcome, reply_markup=main_menu_kb(lang, is_admin=is_admin))


async def _advance_after_gate_step(target, session: AsyncSession, user: User, lang: str) -> None:
    """Called after a gate step is satisfied: move the user to whichever
    step is still outstanding, or show the main menu if the gate is fully
    cleared. Keeps the whole thing a single continuous flow instead of
    dumping the user back to a menu they'd have to poke at again."""
    settings_repo = SettingRepository(session)

    if await settings_repo.get_bool("onboarding_gate_enabled", False):
        required_channel = await settings_repo.get("required_channel", "")
        if required_channel and not await _is_subscribed(target.bot, required_channel, user.telegram_id):
            channel_url = await settings_repo.get("required_channel_url", "")
            await target.answer(
                t(lang, "msg_channel_subscribe_required"), reply_markup=channel_check_kb(lang, channel_url)
            )
            return

    if await user_needs_referral_confirmation(session, user):
        if not user.phone_number:
            await target.answer(t(lang, "msg_referral_confirm_intro"), reply_markup=request_contact_kb(lang))
        else:
            question, correct, options = generate_captcha()
            await target.answer(
                t(lang, "msg_captcha_prompt", question=question), reply_markup=captcha_kb(options, correct)
            )
        return

    await _show_main_menu(target, session, user, lang)


async def _is_subscribed(bot, channel: str, telegram_id: int) -> bool:
    """Fails open on any error, exactly like the middleware's own check —
    see app/middlewares/onboarding_gate.py."""
    try:
        member = await bot.get_chat_member(channel, telegram_id)
        return member.status in _ACTIVE_CHANNEL_STATUSES
    except Exception:  # noqa: BLE001
        return True


@router.callback_query(OnboardingCB.filter(F.action == "accept_offer"))
async def accept_offer(callback: CallbackQuery, session: AsyncSession, user: User, lang: str) -> None:
    await UserRepository(session).mark_oferta_accepted(user)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001 - best effort
        pass
    await _advance_after_gate_step(callback.message, session, user, lang)
    await callback.answer()


@router.callback_query(OnboardingCB.filter(F.action == "check_channel"))
async def check_channel(callback: CallbackQuery, session: AsyncSession, user: User, lang: str) -> None:
    required_channel = await SettingRepository(session).get("required_channel", "")
    if required_channel and not await _is_subscribed(callback.bot, required_channel, user.telegram_id):
        await callback.answer(t(lang, "msg_channel_still_not_subscribed"), show_alert=True)
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001 - best effort
        pass
    await _advance_after_gate_step(callback.message, session, user, lang)
    await callback.answer()


# ------------------------------------------------------------------
# Referral confirmation: phone + captcha — only for users who came via a
# referral link, to protect the referrer's stats/rewards from fake accounts.
# ------------------------------------------------------------------


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
        await message.answer(t(lang, "msg_phone_must_be_own"), reply_markup=request_contact_kb(lang))
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
            await callback.message.edit_text(
                t(lang, "msg_captcha_wrong") + "\n\n" + t(lang, "msg_captcha_prompt", question=question)
            )
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
    await _show_main_menu(callback.message, session, user, lang)
    await callback.answer()


__all__ = ["router"]
