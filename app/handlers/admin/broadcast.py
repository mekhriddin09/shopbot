"""Admin broadcast: send a message to a filtered slice of users.

Audience filters:
  - all: every non-blocked user
  - bought / not_bought: has-vs-hasn't received at least one DELIVERED order
    (across any product) — this is the bot's definition of "a customer"
  - product_bought / product_not_bought: same, scoped to one specific product

Flow: pick audience (optionally pick a product first) -> type the message
(dispatched through the shared AdminInput.waiting_text state, see
generic_input.py's "broadcast_send" branch) -> confirm with a live recipient
count -> fan out with a small per-message delay so we stay well under
Telegram's outgoing rate limits, skipping/counting any user who has blocked
the bot instead of letting one failure abort the whole run.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.filters.is_admin import IsAdmin
from app.keyboards.admin_kb import (
    admin_broadcast_menu_kb,
    admin_broadcast_product_audience_kb,
    admin_broadcast_product_pick_kb,
)
from app.keyboards.callback_data import AdminBroadcastCB
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.user_repo import UserRepository
from app.states.admin_states import AdminInput

router = Router(name="admin_broadcast")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

admin_actions_logger = logging.getLogger("admin_actions")

_AUDIENCE_LABELS = {
    "all": "\U0001F465 Barchaga",
    "bought": "✅ Xarid qilganlarga",
    "not_bought": "\U0001F6AB Xarid qilmaganlarga",
    "product_bought": "✅ Shu mahsulotni xarid qilganlarga",
    "product_not_bought": "\U0001F6AB Shu mahsulotni xarid qilmaganlarga",
}


async def _resolve_recipients(session: AsyncSession, audience: str, product_id: int) -> list[User]:
    users = await UserRepository(session).list_all()
    if audience == "all":
        return users
    scoped_product_id = product_id if audience in ("product_bought", "product_not_bought") else None
    buyer_ids = await OrderRepository(session).list_buyer_user_ids(scoped_product_id)
    if audience in ("bought", "product_bought"):
        return [u for u in users if u.id in buyer_ids]
    return [u for u in users if u.id not in buyer_ids]  # not_bought / product_not_bought


@router.callback_query(AdminBroadcastCB.filter(F.action == "menu"))
async def broadcast_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "\U0001F4E2 Kimga xabar yubormoqchisiz?", reply_markup=admin_broadcast_menu_kb()
    )
    await callback.answer()


@router.callback_query(AdminBroadcastCB.filter(F.action == "by_product"))
async def broadcast_pick_product(callback: CallbackQuery, session: AsyncSession) -> None:
    products = await ProductRepository(session).list_all()
    if not products:
        await callback.answer("Mahsulotlar yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "\U0001F4E6 Qaysi mahsulot bo'yicha?", reply_markup=admin_broadcast_product_pick_kb(products)
    )
    await callback.answer()


@router.callback_query(AdminBroadcastCB.filter(F.action == "product_pick"))
async def broadcast_product_audience(callback: CallbackQuery, callback_data: AdminBroadcastCB) -> None:
    await callback.message.edit_text(
        "Ushbu mahsulot bo'yicha kimga yuborilsin?",
        reply_markup=admin_broadcast_product_audience_kb(callback_data.product_id),
    )
    await callback.answer()


@router.callback_query(
    AdminBroadcastCB.filter(
        F.action.in_({"all", "bought", "not_bought", "product_bought", "product_not_bought"})
    )
)
async def broadcast_ask_text(
    callback: CallbackQuery, callback_data: AdminBroadcastCB, session: AsyncSession, state: FSMContext
) -> None:
    recipients = await _resolve_recipients(session, callback_data.action, callback_data.product_id)
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(
        panel_chat_id=callback.message.chat.id, panel_message_id=callback.message.message_id, 
        action="broadcast_send", audience=callback_data.action, product_id=callback_data.product_id
    )
    await callback.message.edit_text(
        f"{_AUDIENCE_LABELS[callback_data.action]} — {len(recipients)} ta foydalanuvchi.\n\n"
        f"✍️ Endi yuboriladigan xabar matnini yozing:"
    )
    await callback.answer()


@router.callback_query(AdminBroadcastCB.filter(F.action == "cancel"))
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("❌ Xabar yuborish bekor qilindi.")
    await callback.answer()


@router.callback_query(AdminBroadcastCB.filter(F.action == "confirm"))
async def broadcast_confirm(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    audience = data.get("audience")
    product_id = data.get("product_id", 0)
    text = data.get("message_text")
    await state.clear()

    if not audience or not text:
        await callback.answer("Ma'lumot topilmadi, qaytadan urinib ko'ring.", show_alert=True)
        return

    recipients = await _resolve_recipients(session, audience, product_id)
    await callback.message.edit_text(f"\U0001F4E4 Yuborilmoqda... (0/{len(recipients)})")
    await callback.answer()

    sent, failed = 0, 0
    for u in recipients:
        try:
            await callback.bot.send_message(u.telegram_id, text)
            sent += 1
        except TelegramAPIError:
            failed += 1
        await asyncio.sleep(0.05)  # stay well under Telegram's ~30 msg/sec limit

    admin_actions_logger.info(
        "broadcast_sent audience=%s product_id=%s sent=%s failed=%s admin=%s",
        audience, product_id, sent, failed, callback.from_user.id,
    )
    await callback.message.edit_text(
        f"✅ Xabar yuborildi.\n\nYetkazildi: {sent}\nXato (bloklangan/o'chirilgan): {failed}"
    )


__all__ = ["router"]
