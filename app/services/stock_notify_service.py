"""Ping customers who asked to be notified when an out-of-stock product
gets restocked. Called after admin adds inventory codes (single or bulk) —
see app/handlers/admin/generic_input.py — and available from an explicit
"notify everyone waiting" admin button for manual restocks (e.g. a reseller
sale that doesn't go through the bot's own inventory feature)."""
from __future__ import annotations

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Product
from app.repositories.product_repo import ProductRepository
from app.repositories.stock_waiter_repo import StockWaiterRepository
from app.utils.formatting import product_name
from app.utils.i18n import t


async def notify_waiters_if_in_stock(session: AsyncSession, bot: Bot, product: Product) -> int:
    """No-op (returns 0) if the product is still out of stock. Otherwise
    notifies every not-yet-notified waiter exactly once and flips them to
    notified — they must tap "notify me" again for a future restock."""
    if product.delivery_mode.value == "inventory":
        stock = await ProductRepository(session).available_stock(product.id)
        if stock <= 0:
            return 0
    return await notify_all_waiters(session, bot, product)


async def notify_all_waiters(session: AsyncSession, bot: Bot, product: Product) -> int:
    """Unconditional version — used by the admin's manual "📢 Kelganini
    xabar berish" button for restocks that happen outside the bot's own
    inventory feature (e.g. a reseller-sourced product)."""
    waiters = await StockWaiterRepository(session).mark_all_notified(product.id)
    for waiter in waiters:
        try:
            await bot.send_message(
                waiter.user.telegram_id,
                t(waiter.user.language, "msg_stock_back_in_stock", name=product_name(product, waiter.user.language)),
            )
        except Exception:  # noqa: BLE001 - user may have blocked the bot
            pass
    return len(waiters)
