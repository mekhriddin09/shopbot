"""Admin "Foydalanuvchilar" (Users) section: look up a customer by Telegram
ID or username, see their purchase + referral stats, manually adjust their
referral balance, message them directly, and export the full sales history
as a CSV file.

The actual free-text steps (search query, balance amount, message text) are
handled by the shared `AdminInput` dispatch in `generic_input.py` — this
file only owns the menu/profile-card rendering and the callback buttons
that kick those text flows off (same split used by every other admin
section in this project)."""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.models.enums import OrderStatus
from app.filters.is_admin import IsAdmin
from app.keyboards.admin_kb import (
    ADMIN_BTN_USERS,
    admin_user_profile_kb,
    admin_user_search_results_kb,
    admin_users_menu_kb,
)
from app.keyboards.callback_data import AdminUserCB
from app.repositories.order_repo import OrderRepository
from app.repositories.referral_repo import ReferralRepository
from app.repositories.setting_repo import SettingRepository
from app.repositories.user_repo import UserRepository
from app.states.admin_states import AdminInput
from app.utils.formatting import fmt_datetime, fmt_price

router = Router(name="admin_users")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

admin_actions_logger = logging.getLogger("admin_actions")

_STATUS_LABELS = {
    OrderStatus.AWAITING_PROOF: "⏳ To'lov kutilmoqda",
    OrderStatus.AWAITING_CRYPTO_PAYMENT: "⏳ Kripto to'lov kutilmoqda",
    OrderStatus.AWAITING_STARS_PAYMENT: "⏳ Stars to'lov kutilmoqda",
    OrderStatus.PENDING_APPROVAL: "🔍 Tekshirilmoqda",
    OrderStatus.APPROVED: "✅ Tasdiqlangan",
    OrderStatus.REJECTED: "❌ Rad etilgan",
    OrderStatus.DELIVERED: "📦 Yetkazilgan",
    OrderStatus.CANCELLED: "🛑 Bekor qilingan",
    OrderStatus.FAILED: "⚠️ Xatolik",
}


async def _build_user_profile_text(session: AsyncSession, user: User) -> str:
    orders_repo = OrderRepository(session)
    total_orders = await orders_repo.count_by_user(user.id)
    delivered_count = await orders_repo.count_delivered_by_user(user.id)
    total_spent = await orders_repo.total_spent_by_user(user.id)
    ref_stats = await ReferralRepository(session).get_stats(user.id)
    currency = await SettingRepository(session).get("referral_currency", "UZS")

    lines = [
        f"👤 <b>{user.full_name or '-'}</b> (@{user.username or '-'})",
        f"🆔 Telegram ID: <code>{user.telegram_id}</code>",
        f"🌐 Til: {user.language}",
        f"🚫 Bloklangan: {'ha' if user.is_blocked else 'yo‘q'}",
        f"📅 Ro'yxatdan o'tgan: {fmt_datetime(user.created_at)}",
        "",
        "🛒 <b>Xaridlari</b>",
        f"Jami buyurtmalar: {total_orders} ta (yetkazilgan: {delivered_count} ta)",
        f"Jami xarid summasi: {fmt_price(total_spent)}",
        "",
        "🤝 <b>Referal faoliyati</b>",
        f"Taklif qilgan: {ref_stats['invited']} kishi",
        f"Ulardan xarid qilgan: {ref_stats['purchased']} kishi",
        f"1-buyurtma mukofotlari: {ref_stats['first_rewards']} ta",
        f"Referral balansi: {fmt_price(float(user.referral_balance))} {currency}",
    ]

    if user.referred_by_id:
        inviter = await session.get(User, user.referred_by_id)
        if inviter:
            lines.append(f"👆 Kim taklif qilgan: @{inviter.username or '-'} ({inviter.telegram_id})")

    return "\n".join(lines)


async def _send_user_profile(message: Message, session: AsyncSession, user: User) -> None:
    text = await _build_user_profile_text(session, user)
    await message.answer(text, reply_markup=admin_user_profile_kb(user.id))


@router.message(F.text == ADMIN_BTN_USERS)
async def goto_users(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("👤 Foydalanuvchilar bo'limi:", reply_markup=admin_users_menu_kb())


@router.callback_query(AdminUserCB.filter(F.action == "search_prompt"))
async def search_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(action="user_search")
    await callback.message.answer("🔎 Foydalanuvchini qidirish uchun Telegram ID yoki @username yuboring:")
    await callback.answer()


@router.callback_query(AdminUserCB.filter(F.action == "profile"))
async def open_profile(callback: CallbackQuery, callback_data: AdminUserCB, session: AsyncSession) -> None:
    user = await UserRepository(session).get_by_id(callback_data.user_id)
    if user is None:
        await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    text = await _build_user_profile_text(session, user)
    await callback.message.edit_text(text, reply_markup=admin_user_profile_kb(user.id))
    await callback.answer()


@router.callback_query(AdminUserCB.filter(F.action == "orders"))
async def show_user_orders(callback: CallbackQuery, callback_data: AdminUserCB, session: AsyncSession) -> None:
    user = await UserRepository(session).get_by_id(callback_data.user_id)
    if user is None:
        await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    orders = await OrderRepository(session).list_by_user(user.id, limit=20)
    if not orders:
        await callback.answer("Bu foydalanuvchida buyurtmalar yo'q.", show_alert=True)
        return
    for order in orders:
        status_label = _STATUS_LABELS.get(order.status, order.status.value)
        await callback.message.answer(
            f"🔹 <b>{order.product.name if order.product else '-'}</b>\n"
            f"🆔 <code>{order.order_uuid}</code>\n"
            f"Holat: {status_label}\n"
            f"Narx: {fmt_price(float(order.price_at_purchase))} {order.currency} x{order.quantity}\n"
            f"📅 {fmt_datetime(order.created_at)}"
        )
    await callback.answer()


@router.callback_query(AdminUserCB.filter(F.action.in_({"balance_add", "balance_sub"})))
async def balance_adjust_start(callback: CallbackQuery, callback_data: AdminUserCB, state: FSMContext, session: AsyncSession) -> None:
    user = await UserRepository(session).get_by_id(callback_data.user_id)
    if user is None:
        await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    sign = 1 if callback_data.action == "balance_add" else -1
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(action="user_balance_adjust", user_id=user.id, sign=sign)
    verb = "qo'shmoqchi" if sign > 0 else "ayirmoqchi"
    await callback.message.answer(f"✏️ Necha birlik {verb}bo'lsangiz, raqamda yozing:")
    await callback.answer()


@router.callback_query(AdminUserCB.filter(F.action == "message"))
async def message_start(callback: CallbackQuery, callback_data: AdminUserCB, state: FSMContext, session: AsyncSession) -> None:
    user = await UserRepository(session).get_by_id(callback_data.user_id)
    if user is None:
        await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(action="user_send_message", user_id=user.id)
    await callback.message.answer("✍️ Ushbu foydalanuvchiga yuboriladigan xabarni yozing:")
    await callback.answer()


@router.callback_query(AdminUserCB.filter(F.action == "export_sales"))
async def export_sales(callback: CallbackQuery, session: AsyncSession) -> None:
    orders = await OrderRepository(session).list_all()
    if not orders:
        await callback.answer("Buyurtmalar yo'q.", show_alert=True)
        return

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "order_id", "order_uuid", "telegram_id", "username", "full_name",
            "product", "quantity", "price", "currency", "payment_method",
            "status", "created_at", "delivered_at",
        ]
    )
    for o in orders:
        writer.writerow(
            [
                o.id,
                o.order_uuid,
                o.user.telegram_id if o.user else "",
                (o.user.username or "") if o.user else "",
                (o.user.full_name or "") if o.user else "",
                o.product.name if o.product else "",
                o.quantity,
                float(o.price_at_purchase),
                o.currency,
                o.payment_method.value,
                o.status.value,
                fmt_datetime(o.created_at),
                fmt_datetime(o.delivered_at),
            ]
        )
    # utf-8-sig so Excel opens Cyrillic/Latin-extended (uz/ru) text correctly.
    content = buf.getvalue().encode("utf-8-sig")
    filename = f"sales_export_{datetime.now(timezone.utc):%Y%m%d_%H%M}.csv"
    file = BufferedInputFile(content, filename=filename)
    caption = f"📤 Jami {len(orders)} ta buyurtma."
    if len(orders) >= 5000:
        caption += "\n⚠️ Faqat so'nggi 5000 ta buyurtma eksport qilindi."
    await callback.message.answer_document(file, caption=caption)
    await callback.answer()


__all__ = ["router"]
