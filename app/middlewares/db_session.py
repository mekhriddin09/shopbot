from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.database.engine import async_session_maker


class DbSessionMiddleware(BaseMiddleware):
    """Opens one AsyncSession per update and injects it as `session`.

    Registered as an *outer* middleware so the session is available to
    filters as well as handlers (e.g. the admin-auth filter needs DB
    access to check the `admins` table).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with async_session_maker() as session:
            data["session"] = session
            return await handler(event, data)
