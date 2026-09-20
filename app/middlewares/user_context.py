from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

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

        # Capture a referral deep-link's payload ("/start ref<id>") the
        # instant the user is first seen — registered before
        # OnboardingGateMiddleware, so this runs regardless of whether the
        # oferta/channel/phone gate is about to intercept this exact
        # /start and prevent cmd_start's own handler from ever running on
        # it. Without this, a gate blocking a referred user's very first
        # /start meant referred_by_id never got set in time for the
        # captcha/phone-confirmation step to notice them as referred —
        # the referral protection silently never triggered. Still
        # idempotent (see ReferralService.set_referrer_if_new), so
        # cmd_start's own re-check on every /start remains harmless.
        if user.referred_by_id is None and isinstance(event, Update) and event.message is not None:
            text = event.message.text or ""
            if text.startswith("/start"):
                parts = text.split(maxsplit=1)
                if len(parts) > 1:
                    from app.services.referral_service import (  # local import avoids a cycle
                        ReferralService,
                        parse_start_referral_payload,
                    )

                    referrer_id = parse_start_referral_payload(parts[1])
                    if referrer_id is not None:
                        await ReferralService(session).set_referrer_if_new(user, referrer_id)

        data["user"] = user
        data["user_created"] = _created
        data["lang"] = user.language or settings.DEFAULT_LANGUAGE
        return await handler(event, data)
