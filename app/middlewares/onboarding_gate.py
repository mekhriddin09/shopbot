from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.filters.is_admin import is_admin_telegram_id
from app.keyboards.user_kb import (
    captcha_kb,
    channel_check_kb,
    oferta_accept_kb,
    request_contact_kb,
)
from app.repositories.setting_repo import SettingRepository
from app.services.onboarding_service import generate_captcha, user_needs_referral_confirmation
from app.utils.i18n import t

logger = logging.getLogger(__name__)

_ACTIVE_CHANNEL_STATUSES = {"member", "administrator", "creator"}

# Callback-data prefixes belonging to the gate's own buttons. These must
# always be let through, or there'd be no way to ever pass the gate:
#   "ogate:" -> oferta accept / channel re-check
#   "capt:"  -> captcha answer buttons
_GATE_CALLBACK_PREFIXES = ("ogate:", "capt:")


class OnboardingGateMiddleware(BaseMiddleware):
    """Blocks every update from a non-admin user until they've completed the
    onboarding steps that apply *to them*, in order:

      1. Accept the oferta (everyone, if the gate is on)
      2. Subscribe to the mandatory channel (everyone, if one is configured)
      3. Share a phone number + pass a math captcha (ONLY users who arrived
         via someone's referral link and haven't confirmed yet)

    Step 3 is deliberately scoped to referred users: an organic visitor has
    no referrer, so there is no referral fraud to prevent by making them
    hand over a phone number — it would only cost conversions. Meanwhile,
    forcing it at the door (rather than offering an ignorable menu button)
    is what actually makes it effective, since a fake account can't simply
    skip it and still count toward its referrer.

    Same short-circuit-with-bare-`return` pattern already used by
    `UserContextMiddleware` for banned users. Registered last in main.py's
    stack — it needs `session`/`user`/`lang` already present in `data`.
    """

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
        if cq and cq.data and cq.data.startswith(_GATE_CALLBACK_PREFIXES):
            return await handler(event, data)

        # A shared contact is only ever sent as part of step 3 — always let
        # it reach its handler, otherwise the gate would block the very
        # message needed to get past it.
        if event.message is not None and event.message.contact is not None:
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

        if await settings_repo.get_bool("onboarding_gate_enabled", False):
            if not user.oferta_accepted:
                offer_text = (
                    await settings_repo.get(f"oferta_text_{lang}") or await settings_repo.get("oferta_text_uz")
                )
                if not (offer_text or "").strip():
                    # Admin flipped the gate on but never actually wrote any
                    # oferta text — fail open rather than wall everyone off
                    # with an empty message and no way through.
                    logger.warning("onboarding_gate_enabled but oferta_text is empty — failing open")
                else:
                    await target.answer(offer_text, reply_markup=oferta_accept_kb(lang))
                    if cq:
                        await cq.answer()
                    return None

            required_channel = await settings_repo.get("required_channel", "")
            if required_channel and not await self._is_subscribed(bot, required_channel, user.telegram_id):
                channel_url = await settings_repo.get("required_channel_url", "")
                await target.answer(
                    t(lang, "msg_channel_subscribe_required"), reply_markup=channel_check_kb(lang, channel_url)
                )
                if cq:
                    await cq.answer()
                return None

        # Step 3 — referral confirmation. Checked independently of
        # `onboarding_gate_enabled` (it has its own
        # `referral_verification_enabled` toggle) so the admin can run the
        # anti-fraud check with or without the oferta/channel wall.
        if await user_needs_referral_confirmation(session, user):
            if not user.phone_number:
                await target.answer(t(lang, "msg_referral_confirm_intro"), reply_markup=request_contact_kb(lang))
            else:
                question, correct, options = generate_captcha()
                await target.answer(
                    t(lang, "msg_captcha_prompt", question=question), reply_markup=captcha_kb(options, correct)
                )
            if cq:
                await cq.answer()
            return None

        return await handler(event, data)

    @staticmethod
    async def _is_subscribed(bot, channel: str, telegram_id: int) -> bool:
        """Fails *open* (returns True) on any error — a misconfigured
        channel or a bot that isn't an admin there must never brick the
        whole bot for every user."""
        try:
            member = await bot.get_chat_member(channel, telegram_id)
            return member.status in _ACTIVE_CHANNEL_STATUSES
        except Exception:  # noqa: BLE001
            logger.warning(
                "channel_membership_check_failed channel=%s user=%s", channel, telegram_id, exc_info=True
            )
            return True
