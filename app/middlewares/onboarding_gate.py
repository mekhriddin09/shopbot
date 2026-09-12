from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.filters.is_admin import is_admin_telegram_id
from app.keyboards.user_kb import channel_check_kb, oferta_accept_kb
from app.repositories.setting_repo import SettingRepository
from app.utils.i18n import t

logger = logging.getLogger(__name__)

_ACTIVE_CHANNEL_STATUSES = {"member", "administrator", "creator"}


class OnboardingGateMiddleware(BaseMiddleware):
    """Blocks every update from a non-admin user until they've (1) accepted
    the oferta and (2) subscribed to the mandatory channel — same
    short-circuit-with-bare-`return` pattern already used by
    `UserContextMiddleware` for banned users. Registered *after* that
    middleware (needs `session`/`user`/`lang` already in `data`) and after
    `DbSessionMiddleware`, so it must come last in main.py's middleware
    stack. Its own "✅ Roziman" / "✅ Tekshirish" buttons (prefix "ogate:")
    are always allowed through — otherwise there would be no way to ever
    pass the gate."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("user")
        if user is None or not isinstance(event, Update):
            return await handler(event, data)

        cq = event.callback_query
        if cq and cq.data and cq.data.startswith("ogate:"):
            return await handler(event, data)

        target = cq.message if cq else event.message
        if target is None:
            return await handler(event, data)

        session = data["session"]
        bot = data["bot"]
        lang = data.get("lang", "uz")

        if await is_admin_telegram_id(user.telegram_id, session):
            return await handler(event, data)

        settings_repo = SettingRepository(session)
        if not await settings_repo.get_bool("onboarding_gate_enabled", False):
            return await handler(event, data)

        if not user.oferta_accepted:
            offer_text = (
                await settings_repo.get(f"oferta_text_{lang}") or await settings_repo.get("oferta_text_uz")
            )
            if not (offer_text or "").strip():
                # Admin flipped the gate on but never actually wrote any
                # oferta text — fail open rather than wall everyone off
                # with an empty message and no way through.
                logger.warning("onboarding_gate_enabled but oferta_text is empty — failing open")
                return await handler(event, data)
            await target.answer(offer_text, reply_markup=oferta_accept_kb(lang))
            if cq:
                await cq.answer()
            return None

        required_channel = await settings_repo.get("required_channel", "")
        if required_channel:
            subscribed = True
            try:
                member = await bot.get_chat_member(required_channel, user.telegram_id)
                subscribed = member.status in _ACTIVE_CHANNEL_STATUSES
            except Exception:  # noqa: BLE001 - misconfigured channel/bot-not-admin must never brick the bot
                logger.warning(
                    "channel_membership_check_failed channel=%s user=%s",
                    required_channel, user.telegram_id, exc_info=True,
                )
                subscribed = True
            if not subscribed:
                channel_url = await settings_repo.get("required_channel_url", "")
                await target.answer(t(lang, "msg_channel_subscribe_required"), reply_markup=channel_check_kb(lang, channel_url))
                if cq:
                    await cq.answer()
                return None

        return await handler(event, data)
