from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters.is_admin import IsAdmin
from app.keyboards.admin_kb import (
    admin_settings_menu_kb,
    settings_language_pick_kb,
)
from app.keyboards.callback_data import AdminReferralWithdrawCB, AdminSettingsCB
from app.repositories.referral_repo import ReferralRepository
from app.repositories.setting_repo import SettingRepository
from app.states.admin_states import AdminInput
from app.utils.formatting import fmt_price
from app.utils.i18n import t

router = Router(name="admin_settings")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

TOGGLE_LABELS = {
    "automatic_delivery_enabled": "Avto-yetkazish (inventar)",
    "manual_delivery_enabled": "Qo'lda yetkazish",
    "api_delivery_enabled": "API orqali yetkazish",
    "crypto_payment_enabled": "Kripto to'lov",
    "stars_payment_enabled": "Telegram Stars to'lov",
    "referral_enabled": "Referral tizimi",
    "referral_first_order_enabled": "1-buyurtma mukofoti",
    "referral_recurring_enabled": "Doimiy mukofot",
    "preorder_enabled": "Oldindan buyurtma",
}


@router.callback_query(AdminSettingsCB.filter(F.action == "pick_lang"))
async def settings_pick_lang(callback: CallbackQuery, callback_data: AdminSettingsCB) -> None:
    try:
        await callback.message.edit_reply_markup(reply_markup=settings_language_pick_kb(callback_data.key))
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
    await callback.answer()


@router.callback_query(AdminSettingsCB.filter(F.action == "edit"))
async def settings_edit_start(callback: CallbackQuery, callback_data: AdminSettingsCB, session: AsyncSession, state: FSMContext) -> None:
    current = await SettingRepository(session).get(callback_data.key)
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(action="settings_edit", key=callback_data.key)
    await callback.message.answer(
        f"Joriy qiymat:\n\n{current}\n\n👇 Yangi matnni yozing:"
    )
    await callback.answer()


@router.callback_query(AdminSettingsCB.filter(F.action == "toggle"))
async def settings_toggle(callback: CallbackQuery, callback_data: AdminSettingsCB, session: AsyncSession) -> None:
    settings_repo = SettingRepository(session)
    current = await settings_repo.get_bool(callback_data.key, True)
    await settings_repo.set(callback_data.key, "0" if current else "1")
    label = TOGGLE_LABELS.get(callback_data.key, callback_data.key)
    state_text = "o'chirildi" if current else "yoqildi"
    await callback.answer(f"{label}: {state_text} ✅")
    try:
        await callback.message.edit_reply_markup(reply_markup=admin_settings_menu_kb())
    except TelegramBadRequest as exc:
        # Markup is static text regardless of toggle state, so Telegram often
        # reports "message is not modified" — harmless, the toggle itself
        # already succeeded above.
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


