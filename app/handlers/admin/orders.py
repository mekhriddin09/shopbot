from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enums import DeliveryMode, OrderStatus
from app.filters.is_admin import IsAdmin
from app.keyboards.admin_kb import admin_write_manual_kb
from app.keyboards.callback_data import AdminOrderListCB, OrderCB
from app.repositories.order_repo import OrderRepository
from app.services.delivery_service import DeliveryService
from app.services.exceptions import DeliveryFailedError, InvalidOrderStateError
from app.states.admin_states import AdminInput
from app.utils.formatting import build_delivered_message, fmt_datetime, fmt_price

router = Router(name="admin_orders")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

admin_actions_logger = logging.getLogger("admin_actions")

_STATUS_MAP = {
    "pending": OrderStatus.PENDING_APPROVAL,
    "approved": OrderStatus.APPROVED,
    "delivered": OrderStatus.DELIVERED,
    "failed": OrderStatus.FAILED,
    "rejected": OrderStatus.REJECTED,
}
# Statuses where the order is approved-but-not-yet-delivered — the admin may
# still need to push the product through by hand (e.g. API delivery failed,
# or it's a manual-mode product waiting for its message).
_NEEDS_MANUAL_BUTTON = {OrderStatus.APPROVED, OrderStatus.FAILED}


def _order_line(order) -> str:
    return (
        f"🔹 <b>{order.product.name}</b>\n"
        f"🆔 <code>{order.order_uuid}</code>\n"
        f"\U0001F464 @{order.user.username or '-'} ({order.user.telegram_id})\n"
        f"\U0001F4B0 {fmt_price(float(order.price_at_purchase))} {order.currency}\n"
        f"📅 {fmt_datetime(order.created_at)}"
    )


@router.callback_query(AdminOrderListCB.filter())
async def list_orders(callback: CallbackQuery, callback_data: AdminOrderListCB, session: AsyncSession) -> None:
    status = _STATUS_MAP.get(callback_data.action)
    if status is None:
        await callback.answer()
        return
    orders = await OrderRepository(session).list_by_status(status)
    if not orders:
        await callback.message.answer("Bu bo'limda buyurtmalar yo'q.")
        await callback.answer()
        return
    if len(orders) == 50:
        await callback.message.answer("ℹ️ Faqat so'nggi 50 ta buyurtma ko'rsatilmoqda.")
    for order in orders:
        if status in _NEEDS_MANUAL_BUTTON:
            await callback.message.answer(_order_line(order), reply_markup=admin_write_manual_kb(order.id))
        else:
            await callback.message.answer(_order_line(order))
    await callback.answer()


@router.callback_query(OrderCB.filter(F.action == "approve"))
async def approve_order(callback: CallbackQuery, callback_data: OrderCB, session: AsyncSession, state: FSMContext) -> None:
    admin_id = callback.from_user.id
    delivery = DeliveryService(session)
    try:
        result = await delivery.approve_order(callback_data.order_id, admin_id)
    except InvalidOrderStateError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except DeliveryFailedError as exc:
        # Order was already marked APPROVED before delivery was attempted
        # (see DeliveryService.approve_order), so it's now stuck: re-tapping
        # "Approve" will just hit the "already reviewed" guard above. Give
        # the admin a way out — write the delivery message by hand instead
        # of leaving the order paid-for-but-undelivered with no recovery
        # path in the UI.
        await callback.answer(str(exc), show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001 - best-effort, message may not support it
            pass
        await callback.message.answer(
            f"⚠️ Buyurtma <code>{callback_data.order_id}</code> tasdiqlandi, lekin avtomatik yetkazib "
            f"bo'lmadi:\n{exc}\n\nQo'lda yetkazib berishingiz mumkin:",
            reply_markup=admin_write_manual_kb(callback_data.order_id),
        )
        return

    admin_actions_logger.info("order_approved order=%s admin=%s", callback_data.order_id, admin_id)

    order = result.order
    lang = order.user.language

    if result.delivered_now and result.payload:
        await callback.bot.send_message(
            order.user.telegram_id,
            build_delivered_message(lang, order, result.payload),
        )
        await callback.message.edit_text(callback.message.text + "\n\n✅ TASDIQLANDI VA YETKAZILDI")
        await callback.message.edit_reply_markup(reply_markup=None)
    elif result.needs_manual_message:
        await state.set_state(AdminInput.waiting_text)
        await state.update_data(action="manual_deliver", order_id=order.id)
        await callback.message.answer(
            f"✏️ Buyurtma <code>{order.order_uuid}</code> uchun mijozga yuboriladigan xabarni yozing:"
        )
        await callback.message.edit_reply_markup(reply_markup=None)

    await callback.answer("Tasdiqlandi ✅")


@router.callback_query(OrderCB.filter(F.action == "reject"))
async def reject_order_start(callback: CallbackQuery, callback_data: OrderCB, state: FSMContext) -> None:
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(action="reject_reason", order_id=callback_data.order_id)
    await callback.message.answer("❌ Rad etish sababini yozing (yoki '-' yuboring):")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()


@router.callback_query(OrderCB.filter(F.action == "write_manual"))
async def write_manual_start(callback: CallbackQuery, callback_data: OrderCB, state: FSMContext) -> None:
    """Entry point used after a crypto payment is auto-confirmed for a
    manually-delivered product (see services/crypto_poller.py) — the order
    is already APPROVED, the admin just needs to type the message."""
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(action="manual_deliver", order_id=callback_data.order_id)
    await callback.message.answer("✍️ Mijozga yuboriladigan xabarni yozing:")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
