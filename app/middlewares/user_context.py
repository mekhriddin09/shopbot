from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.config.settings import settings
from app.repositories.user_repo import UserRepository


class UserContextMiddleware(BaseMiddleware):
    """Ensures every inbound update from a real Telegram user has a `User`
    row, and injects `user` + `lang` into handler data. Also blocks banned
    users at the door."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)

        session = data["session"]
        users = UserRepository(session)
        user, _created = await users.get_or_create(
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
            language=settings.DEFAULT_LANGUAGE,
        )

        if user.is_blocked and tg_user.id not in settings.admin_ids:
            return  # silently ignore blocked users

        data["user"] = user
        data["user_created"] = _created
        data["lang"] = user.language or settings.DEFAULT_LANGUAGE
        return await handler(event, data)
