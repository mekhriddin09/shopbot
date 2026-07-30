"""Entrypoint for the Telegram Digital Product Sales Bot."""
from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config.settings import settings
from app.database.bootstrap import bootstrap_database
from app.handlers.admin import admin_router
from app.handlers.user import user_router
from app.middlewares.db_session import DbSessionMiddleware
from app.middlewares.error_handling import ErrorHandlingMiddleware
from app.middlewares.throttling import ThrottlingMiddleware
from app.middlewares.user_context import UserContextMiddleware
from app.services.crypto_poller import crypto_poller_loop
from app.utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


async def main() -> None:
    setup_logging()
    logger.info("Starting Telegram Digital Product Sales Bot...")

    await bootstrap_database()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Outer middlewares run for every update, before routing/filters.
    # Order matters: error handling wraps everything, throttling rejects
    # spam before we touch the DB, then the DB session + user context are
    # made available to filters and handlers.
    dp.update.outer_middleware(ErrorHandlingMiddleware())
    dp.update.outer_middleware(ThrottlingMiddleware())
    dp.update.outer_middleware(DbSessionMiddleware())
    dp.update.outer_middleware(UserContextMiddleware())

    dp.include_router(admin_router)
    dp.include_router(user_router)

    poller_task = asyncio.create_task(crypto_poller_loop(bot))

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Bot is polling...")
        await dp.start_polling(bot)
    finally:
        poller_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poller_task
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
