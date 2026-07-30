from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config.settings import settings


class ThrottlingMiddleware(BaseMiddleware):
    """Simple per-user rate limiter to protect against spam / flood /
    repeated callback taps. Not a full anti-flood solution, but stops the
    common case of accidental or malicious rapid-fire requests."""

    def __init__(self, rate_seconds: float | None = None) -> None:
        self.rate_seconds = rate_seconds or settings.THROTTLE_RATE_SECONDS
        self._last_seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        now = time.monotonic()
        last = self._last_seen.get(tg_user.id)
        self._last_seen[tg_user.id] = now

        if last is not None and (now - last) < self.rate_seconds:
            if isinstance(event, CallbackQuery):
                await event.answer()
            return  # drop silently to avoid feeling "broken" on fast taps

        return await handler(event, data)
