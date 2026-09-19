from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.filters.is_admin import is_admin_telegram_id
from app.keyboards.user_kb import channel_check_kb, oferta_accept_kb
from app.repositories.setting_repo import SettingRepository
from app.services.onboarding_service import user_needs_referral_confirmation
from app.utils.i18n import t

logger = logging.getLogger(__name__)

_ACTIVE_CHANNEL_STATUSES = {"member", "administrator", "creator"}

# Callback-data prefixes belonging to the gate's own buttons. These must
# always be let through, or there'd be no way to ever pass the gate:
#   "ogate:" -> oferta accept / channel re-check
#   "capt:"  -> captcha answer buttons
_GATE_CALLBACK_PREFIXES = ("ogate:", "capt:")


class OnboardingGateMiddleware(BaseMiddleware):
    """Runs the onboarding steps that apply to each non-admin user, in order.

    BLOCKING steps (update never reaches its handler until satisfied), and
    only while `onboarding_gate_enabled` is on:
      1. Accept the oferta
      2. Subscribe to the mandatory channel (if one is configured)

    NON-BLOCKING step, on its own `referral_verification_enabled` toggle:
      3. Offer phone + captcha confirmation, once, to users who arrived via
         someone's referral link. The update proceeds to its handler either
         way — declining or failing this only means the user doesn't count
         toward their referrer's invite stats/Ball reward. The bot stays
         fully usable and they can still refer others themselves.

    Step 3 is scoped to referred users because an organic visitor has no
    referrer, so demanding their phone number prevents no fraud and only
    costs conversions.

    Blocking uses the same short-circuit-with-bare-`return` pattern already
    used by `UserContextMiddleware` for banned users. Registered last in
    main.py's stack — needs `session`/`user`/`lang` already in `data`.
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
                    # Long oferta texts used to crash here with "message is
                    # too long", walling every new user out of the bot. The
                    # accept button rides on the final chunk so it is always
                    # the last thing on screen.
                    from app.utils.formatting import split_text

                    chunks = split_text(offer_text)
                    for chunk in chunks[:-1]:
                        await target.answer(chunk)
                    await target.answer(chunks[-1], reply_markup=oferta_accept_kb(lang))
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

        # Step 3 — referral confirmation. Deliberately NOT a block: it's
        # offered once, up front, and then the update continues to its
        # normal handler either way. Failing or ignoring it only costs the
        # user their "counts as a referral" status — the bot itself stays
        # fully usable, they can still buy, and they can still invite
        # others with their own link. (An earlier version did block here,
        # which meant e.g. anyone with a foreign phone number was locked
        # out of the shop entirely — losing a paying customer to protect a
        # referral statistic, exactly the wrong trade.) They can come back
        # to it any time from the 🤝 Referral section.
        if not user.referral_prompt_shown and await user_needs_referral_confirmation(session, user):
            # Local imports avoid an import cycle (handlers import keyboards
            # which import... — the middleware is loaded before routers).
            from app.handlers.user.onboarding import prompt_referral_confirmation
            from app.repositories.user_repo import UserRepository

            await UserRepository(session).mark_referral_prompt_shown(user)
            result = await handler(event, data)
            # Prompt *after* the normal handler so the user sees their
            # /start welcome + menu first, then the optional ask — rather
            # than the ask appearing to be a wall in front of the bot.
            await prompt_referral_confirmation(target, session, user, lang)
            return result

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
