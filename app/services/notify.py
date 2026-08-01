"""Fan-out helpers for notifying every admin (env + DB) about something."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import Order, ReferralWithdrawal, User
from app.keyboards.admin_kb import admin_order_action_kb, admin_referral_withdraw_kb
from app.repositories.admin_repo import AdminRepository
from app.utils.formatting import fmt_price

logger = logging.getLogger(__name__)


async def _all_admin_ids(session: AsyncSession) -> set[int]:
    ids = set(settings.admin_ids)
    admins = AdminRepository(session)
    for admin in await admins.list_active():
        ids.add(admin.telegram_id)
    return ids


async def notify_admins_new_order(
    bot: Bot,
    session: AsyncSession,
    order: Order,
    screenshot_file_id: str,
) -> None:
    preorder_line = "\n⏳ <b>OLDINDAN BUYURTMA</b> (mahsulot hozircha stokda yo'q)" if order.is_preorder else ""
    qty_line = f"\n\U0001F522 Miqdor: {order.quantity} dona" if order.quantity and order.quantity > 1 else ""
    caption = (
        f"\U0001F6CE️ <b>Yangi buyurtma</b>\n\n"
        f"\U0001F464 {order.user.full_name or '-'} (@{order.user.username or '-'})\n"
        f"\U0001F194 Telegram ID: <code>{order.user.telegram_id}</code>\n"
        f"\U0001F4E6 Mahsulot: {order.product.name}\n"
        f"\U0001F4B0 Narxi: {fmt_price(float(order.price_at_purchase))} {order.currency}\n"
        f"\U0001F196 Buyurtma: <code>{order.order_uuid}</code>"
        f"{qty_line}{preorder_line}"
    )
    for admin_id in await _all_admin_ids(session):
        try:
            await bot.send_photo(
                admin_id,
                photo=screenshot_file_id,
                caption=caption,
                reply_markup=admin_order_action_kb(order.id),
            )
        except TelegramAPIError:
            logger.warning("Failed to notify admin %s about order %s", admin_id, order.order_uuid)


async def notify_admins_text(bot: Bot, session: AsyncSession, text: str) -> None:
    for admin_id in await _all_admin_ids(session):
        try:
            await bot.send_message(admin_id, text)
        except TelegramAPIError:
            logger.warning("Failed to notify admin %s", admin_id)


async def notify_admins_referral_withdrawal(
    bot: Bot, session: AsyncSession, withdrawal: ReferralWithdrawal, user: User
) -> None:
    text = (
        f"\U0001F4B0 <b>Referral pul yechish so'rovi</b>\n\n"
        f"\U0001F464 {user.full_name or '-'} (@{user.username or '-'})\n"
        f"\U0001F194 Telegram ID: <code>{user.telegram_id}</code>\n"
        f"\U0001F4B5 Miqdor: {fmt_price(float(withdrawal.amount))}\n"
        f"\U0001F196 So'rov: <code>{withdrawal.id}</code>"
    )
    kb = admin_referral_withdraw_kb(withdrawal.id)
    for admin_id in await _all_admin_ids(session):
        try:
            await bot.send_message(admin_id, text, reply_markup=kb)
        except TelegramAPIError:
            logger.warning("Failed to notify admin %s about referral withdrawal %s", admin_id, withdrawal.id)
