from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.services.exceptions import DomainError
from app.utils.i18n import t

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseMiddleware):
    """The bot must never crash. Every handler call is wrapped:

    - `DomainError` (expected business-rule violation, e.g. "already
      approved") -> shown to the user as a friendly message.
    - Anything else -> logged with full traceback to errors.log, and the
      user gets a generic apologetic message instead of a stack trace / a
      silently hanging request.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        lang = data.get("lang", "uz")
        try:
            return await handler(event, data)
        except DomainError as exc:
            await self._notify(event, str(exc))
            return None
        except Exception:  # noqa: BLE001 - top-level safety net
            logger.exception("Unhandled exception while processing update")
            await self._notify(event, t(lang, "msg_error_generic"))
            return None

    @staticmethod
    async def _notify(event: TelegramObject, text: str) -> None:
        try:
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(text)
        except Exception:  # noqa: BLE001 - never let error reporting itself crash
            logger.exception("Failed to notify user about an error")
