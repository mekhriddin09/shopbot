from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.models.enums import ReferralCurrency
from app.keyboards.callback_data import ReferralCB, ReferralRewardCB
from app.keyboards.user_kb import (
    referral_profile_kb,
    referral_reward_detail_kb,
    referral_reward_list_kb,
    referral_reward_skip_note_kb,
)
from app.repositories.referral_repo import ReferralRepository
from app.repositories.setting_repo import SettingRepository
from app.services.exceptions import InsufficientBalanceError, RewardUnavailableError
from app.services.notify import notify_admins_referral_redemption
from app.services.onboarding_service import user_needs_referral_confirmation
from app.services.referral_service import ReferralService
from app.states.user_states import ReferralRewardStates
from app.utils.button_filters import menu_button_filter
from app.utils.formatting import fmt_price
from app.utils.i18n import t

router = Router(name="user_referral")


async def _build_referral_profile(session: AsyncSession, user: User, lang: str, bot) -> tuple[str, object]:
    settings_repo = SettingRepository(session)
    stats = await ReferralRepository(session).get_stats(user.id)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref{user.id}"
    currency = await settings_repo.get("referral_currency", "UZS")
    points_name = await settings_repo.get("referral_points_name", "Ball")
    withdraw_min = float(await settings_repo.get("referral_withdraw_min", "0") or 0)
    balance = float(user.referral_balance)
    points = float(user.referral_points)
    can_withdraw = withdraw_min > 0 and balance >= withdraw_min
    has_rewards = bool(await ReferralRepository(session).list_active_rewards())
    rules_text = await settings_repo.get(f"referral_rules_{lang}", "")
    has_rules = bool((rules_text or "").strip())
    needs_confirmation = await user_needs_referral_confirmation(session, user)

    text = t(
        lang,
        "msg_referral_profile",
        link=link,
        invited=stats["invited"],
        purchased=stats["purchased"],
        first_rewards=stats["first_rewards"],
        balance=fmt_price(balance),
        currency=currency,
        points=fmt_price(points),
        points_name=points_name,
    )
    # Auto-generated "what do I actually get" block — built live from the
    # admin's real settings/per-product configuration (see
    # ReferralService.describe_referral_rewards) so a user always sees
    # accurate numbers without the admin having to type them out by hand.
    reward_lines = await ReferralService(session).describe_referral_rewards(lang)
    if reward_lines:
        text += "\n\n" + t(lang, "msg_referral_info_title") + "\n" + "\n".join(reward_lines)
    if needs_confirmation:
        # Tell them plainly that they themselves aren't counted yet — this
        # is the one place the confirmation state is visible/actionable
        # after the one-time prompt at entry.
        text += "\n\n" + t(lang, "msg_referral_not_confirmed_notice")
    kb = referral_profile_kb(
        lang,
        can_withdraw,
        has_rewards=has_rewards,
        has_rules=has_rules,
        needs_confirmation=needs_confirmation,
    )
    return text, kb


@router.message(menu_button_filter("menu_referral"))
async def referral_menu(message: Message, session: AsyncSession, user: User, lang: str) -> None:
    if not await SettingRepository(session).get_bool("referral_enabled", False):
        await message.answer(t(lang, "msg_referral_disabled"))
        return
    text, kb = await _build_referral_profile(session, user, lang, message.bot)
    await message.answer(text, reply_markup=kb)


@router.callback_query(ReferralCB.filter(F.action == "profile_back"))
async def referral_profile_back(callback: CallbackQuery, session: AsyncSession, user: User, lang: str) -> None:
    text, kb = await _build_referral_profile(session, user, lang, callback.bot)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(ReferralCB.filter(F.action == "rules"))
async def referral_rules(callback: CallbackQuery, session: AsyncSession, lang: str) -> None:
    # A regular chat message, not a callback alert — Telegram's alert popup
    # is capped at 200 characters, far too short for real rules text (it
    # was silently truncating admin's text and rendering in a cramped
    # popup instead of a normal, fully readable message).
    rules_text = await SettingRepository(session).get(f"referral_rules_{lang}", "")
    text = (rules_text or "").strip() or t(lang, "msg_referral_rules_empty")
    await callback.message.answer(t(lang, "msg_referral_rules_title") + "\n\n" + text)
    await callback.answer()


@router.callback_query(ReferralCB.filter(F.action == "confirm"))
async def referral_confirm_from_profile(
    callback: CallbackQuery, session: AsyncSession, user: User, lang: str
) -> None:
    """Retry/complete the phone+captcha confirmation on demand. Entry point
    for the button on the referral profile — the one-time prompt at entry
    is skippable and non-blocking, so this is how a user who declined it
    (or whose number was rejected at the time) comes back to it."""
    if not await user_needs_referral_confirmation(session, user):
        await callback.answer()
        return
    from app.handlers.user.onboarding import prompt_referral_confirmation  # local import avoids a cycle

    await prompt_referral_confirmation(callback.message, session, user, lang)
    await callback.answer()


@router.callback_query(ReferralCB.filter(F.action == "withdraw"))
async def referral_withdraw(callback: CallbackQuery, session: AsyncSession, user: User, lang: str) -> None:
    settings_repo = SettingRepository(session)
    withdraw_min = float(await settings_repo.get("referral_withdraw_min", "0") or 0)
    balance = float(user.referral_balance)
    if withdraw_min <= 0 or balance < withdraw_min:
        await callback.answer(t(lang, "msg_referral_withdraw_not_enough"), show_alert=True)
        return

    withdrawal = await ReferralRepository(session).create_withdrawal(user.id, balance)
    from app.services.notify import notify_admins_referral_withdrawal

    await notify_admins_referral_withdrawal(callback.bot, session, withdrawal, user)
    currency = await settings_repo.get("referral_currency", "UZS")
    await callback.message.edit_text(
        t(lang, "msg_referral_withdraw_requested", amount=fmt_price(balance), currency=currency)
    )
    await callback.answer()


# ------------------------------------------------------------------
# Referral "shop" — browse + redeem catalog rewards with referral balance
# ------------------------------------------------------------------


async def _reward_currency(session: AsyncSession, reward, user: User) -> tuple[str, float]:
    """(display name, the user's balance) for whichever of the two
    currencies this particular reward is priced in."""
    settings_repo = SettingRepository(session)
    if reward.currency_type == ReferralCurrency.POINTS:
        return await settings_repo.get("referral_points_name", "Ball"), float(user.referral_points)
    return await settings_repo.get("referral_currency", "UZS"), float(user.referral_balance)


@router.callback_query(ReferralRewardCB.filter(F.action == "list"))
async def referral_reward_list(callback: CallbackQuery, session: AsyncSession, lang: str) -> None:
    rewards = await ReferralRepository(session).list_active_rewards()
    if not rewards:
        await callback.answer(t(lang, "msg_referral_shop_empty"), show_alert=True)
        return
    settings_repo = SettingRepository(session)
    currency = await settings_repo.get("referral_currency", "UZS")
    points_name = await settings_repo.get("referral_points_name", "Ball")
    await callback.message.edit_text(
        t(lang, "msg_referral_shop_intro"),
        reply_markup=referral_reward_list_kb(lang, rewards, currency_name=currency, points_name=points_name),
    )
    await callback.answer()


@router.callback_query(ReferralRewardCB.filter(F.action == "open"))
async def referral_reward_open(
    callback: CallbackQuery, callback_data: ReferralRewardCB, session: AsyncSession, user: User, lang: str
) -> None:
    reward = await ReferralRepository(session).get_reward(callback_data.reward_id)
    if reward is None or not reward.is_active:
        await callback.answer(t(lang, "msg_referral_reward_unavailable"), show_alert=True)
        return
    currency, balance = await _reward_currency(session, reward, user)
    can_afford = balance >= float(reward.cost)
    description_block = f"\n{reward.description}" if reward.description else ""
    text = t(
        lang,
        "msg_referral_reward_detail",
        name=reward.name,
        description_block=description_block,
        cost=fmt_price(float(reward.cost)),
        balance=fmt_price(balance),
        currency=currency,
    )
    await callback.message.edit_text(
        text, reply_markup=referral_reward_detail_kb(lang, reward.id, can_afford)
    )
    await callback.answer()


@router.callback_query(ReferralRewardCB.filter(F.action == "buy"))
async def referral_reward_buy(
    callback: CallbackQuery,
    callback_data: ReferralRewardCB,
    session: AsyncSession,
    user: User,
    lang: str,
    state: FSMContext,
) -> None:
    reward = await ReferralRepository(session).get_reward(callback_data.reward_id)
    if reward is None or not reward.is_active:
        await callback.answer(t(lang, "msg_referral_reward_unavailable"), show_alert=True)
        return
    _, balance = await _reward_currency(session, reward, user)
    if balance < float(reward.cost):
        await callback.answer(t(lang, "msg_referral_reward_insufficient_balance"), show_alert=True)
        return

    await state.set_state(ReferralRewardStates.waiting_note)
    await state.update_data(reward_id=reward.id)
    await callback.message.answer(
        t(lang, "msg_referral_reward_note_prompt"), reply_markup=referral_reward_skip_note_kb(lang, reward.id)
    )
    await callback.answer()


async def _finalize_redemption(
    session: AsyncSession, user: User, lang: str, reward_id: int, note: str | None, bot
) -> str:
    """Shared by both the "skip note" button and the free-text note
    message handler. Returns the confirmation/error text to show the user."""
    try:
        redemption = await ReferralService(session).redeem_reward(user, reward_id, note)
    except RewardUnavailableError as exc:
        return exc.localized(lang)
    except InsufficientBalanceError as exc:
        return exc.localized(lang)

    await notify_admins_referral_redemption(bot, session, redemption, user)
    return t(lang, "msg_referral_reward_requested", name=redemption.reward_name_snapshot)


@router.callback_query(ReferralRewardCB.filter(F.action == "skip_note"))
async def referral_reward_skip_note(
    callback: CallbackQuery, callback_data: ReferralRewardCB, session: AsyncSession, user: User, lang: str, state: FSMContext
) -> None:
    result_text = await _finalize_redemption(session, user, lang, callback_data.reward_id, None, callback.bot)
    await state.clear()
    await callback.message.edit_text(result_text)
    await callback.answer()


@router.message(ReferralRewardStates.waiting_note, F.text)
async def referral_reward_note_received(message: Message, session: AsyncSession, user: User, lang: str, state: FSMContext) -> None:
    data = await state.get_data()
    reward_id = data.get("reward_id")
    if not reward_id:
        await state.clear()
        return
    result_text = await _finalize_redemption(session, user, lang, reward_id, message.text.strip(), message.bot)
    await state.clear()
    await message.answer(result_text)


__all__ = ["router"]
