from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.keyboards.callback_data import ReferralCB
from app.keyboards.user_kb import referral_profile_kb
from app.repositories.referral_repo import ReferralRepository
from app.repositories.setting_repo import SettingRepository
from app.services.notify import notify_admins_referral_withdrawal
from app.utils.formatting import fmt_price
from app.utils.i18n import t

router = Router(name="user_referral")


@router.message(F.text.in_({t(l, "btn_referral") for l in ("uz", "ru", "en")}))
async def referral_menu(message: Message, session: AsyncSession, user: User, lang: str) -> None:
    settings_repo = SettingRepository(session)
    if not await settings_repo.get_bool("referral_enabled", False):
        await message.answer(t(lang, "msg_referral_disabled"))
        return

    stats = await ReferralRepository(session).get_stats(user.id)
    me = await message.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref{user.id}"
    currency = await settings_repo.get("referral_currency", "UZS")
    withdraw_min = float(await settings_repo.get("referral_withdraw_min", "0") or 0)
    balance = float(user.referral_balance)
    can_withdraw = withdraw_min > 0 and balance >= withdraw_min

    text = t(
        lang,
        "msg_referral_profile",
        link=link,
        invited=stats["invited"],
        purchased=stats["purchased"],
        first_rewards=stats["first_rewards"],
        balance=fmt_price(balance),
        currency=currency,
    )
    await message.answer(text, reply_markup=referral_profile_kb(lang, can_withdraw))


@router.callback_query(ReferralCB.filter(F.action == "withdraw"))
async def referral_withdraw(callback: CallbackQuery, session: AsyncSession, user: User, lang: str) -> None:
    settings_repo = SettingRepository(session)
    withdraw_min = float(await settings_repo.get("referral_withdraw_min", "0") or 0)
    balance = float(user.referral_balance)
    if withdraw_min <= 0 or balance < withdraw_min:
        await callback.answer(t(lang, "msg_referral_withdraw_not_enough"), show_alert=True)
        return

    withdrawal = await ReferralRepository(session).create_withdrawal(user.id, balance)
    await notify_admins_referral_withdrawal(callback.bot, session, withdrawal, user)
    currency = await settings_repo.get("referral_currency", "UZS")
    await callback.message.edit_text(
        t(lang, "msg_referral_withdraw_requested", amount=fmt_price(balance), currency=currency)
    )
    await callback.answer()


__all__ = ["router"]
