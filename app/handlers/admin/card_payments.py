"""Admin side of automatic card payments: confirm/reject a matched payment
that was held back for review."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enums import OrderStatus
from app.filters.is_admin import IsAdmin
from app.keyboards.callback_data import CardAutoCB
from app.repositories.order_repo import OrderRepository
from app.states.admin_states import AdminInput
from app.utils.formatting import fmt_price

router = Router(name="admin_card_payments")
router.callback_query.filter(IsAdmin())

admin_actions_logger = logging.getLogger("admin_actions")


async def _strip_buttons(callback: CallbackQuery, suffix: str) -> None:
    try:
        body = callback.message.text or callback.message.caption or ""
        await callback.message.edit_text(f"{body}\n\n{suffix}")
    except TelegramBadRequest:
        pass
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass


@router.callback_query(CardAutoCB.filter(F.action == "admin_confirm"))
async def card_admin_confirm(
    callback: CallbackQuery, callback_data: CardAutoCB, session: AsyncSession
) -> None:
    order = await OrderRepository(session).get_by_id(callback_data.order_id)
    if order is None:
        await callback.answer("Buyurtma topilmadi.", show_alert=True)
        return
    if order.status != OrderStatus.PENDING_APPROVAL:
        await callback.answer(f"Bu buyurtma allaqachon ko'rib chiqilgan ({order.status.value}).", show_alert=True)
        return

    from app.services.card_payment.flow import deliver_paid_order  # local import avoids a cycle

    amount = float(order.expected_amount or order.price_at_purchase)
    await deliver_paid_order(callback.bot, session, order, amount)
    admin_actions_logger.info(
        "card_payment_confirmed order=%s admin=%s", order.order_uuid, callback.from_user.id
    )
    await _strip_buttons(callback, f"✅ Tasdiqlandi ({fmt_price(amount)})")
    await callback.answer("Yetkazildi ✅")


@router.callback_query(CardAutoCB.filter(F.action == "admin_reject"))
async def card_admin_reject(
    callback: CallbackQuery, callback_data: CardAutoCB, session: AsyncSession, state: FSMContext
) -> None:
    """Reuses the ordinary rejection flow (asks for a reason, notifies the
    customer, releases stock) rather than inventing a card-specific one."""
    order = await OrderRepository(session).get_by_id(callback_data.order_id)
    if order is None:
        await callback.answer("Buyurtma topilmadi.", show_alert=True)
        return

    await state.set_state(AdminInput.waiting_text)
    await state.update_data(action="reject_reason", order_id=order.id)
    await _strip_buttons(callback, "❌ Rad etilmoqda…")
    await callback.message.answer("❌ Rad etish sababini yozing (yoki '-' yuboring):")
    await callback.answer()


__all__ = ["router"]
