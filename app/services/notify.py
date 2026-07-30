"""Fan-out helpers for notifying every admin (env + DB) about something."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import Order
from app.keyboards.admin_kb import admin_order_action_kb
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
    caption = (
        f"\U0001F6CE️ <b>Yangi buyurtma</b>\n\n"
        f"\U0001F464 {order.user.full_name or '-'} (@{order.user.username or '-'})\n"
        f"\U0001F194 Telegram ID: <code>{order.user.telegram_id}</code>\n"
        f"\U0001F4E6 Mahsulot: {order.product.name}\n"
        f"\U0001F4B0 Narxi: {fmt_price(float(order.price_at_purchase))} {order.currency}\n"
        f"\U0001F196 Buyurtma: <code>{order.order_uuid}</code>"
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
