from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

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
        # This middleware is registered via `dp.update.outer_middleware(...)`
        # (see main.py), so the `event` aiogram hands us here is always the
        # raw `Update` envelope — never the unwrapped `CallbackQuery` /
        # `Message` directly. The isinstance checks below used to compare
        # against `CallbackQuery`/`Message` without ever unwrapping the
        # `Update` first, so they never matched anything: every unhandled
        # exception during a callback-query handler was logged but the
        # callback was never answered, leaving the button stuck on
        # Telegram's "loading" spinner forever instead of showing the
        # friendly error alert. Unwrap `Update.callback_query`/`.message`
        # first so the alert actually reaches the user.
        try:
            if isinstance(event, Update):
                if event.callback_query is not None:
                    await event.callback_query.answer(text, show_alert=True)
                    return
                if event.message is not None:
                    await event.message.answer(text)
                    return
                return
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(text)
        except Exception:  # noqa: BLE001 - never let error reporting itself crash
            logger.exception("Failed to notify user about an error")
