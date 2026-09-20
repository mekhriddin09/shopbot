"""Admin side of the support relay: when an admin replies (Telegram
"Reply") to a message that was forwarded from a user's Support chat, that
reply is sent back to the user. See app/handlers/user/support.py for the
user side."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters.is_admin import IsAdmin
from app.repositories.support_repo import SupportRelayRepository

router = Router(name="admin_support")
router.message.filter(IsAdmin())

admin_actions_logger = logging.getLogger("admin_actions")


@router.message(F.reply_to_message)
async def relay_admin_reply(message: Message, session: AsyncSession) -> None:
    """Matches by the CHAT the reply was sent in, not the replying admin's
    own id: in a private admin chat those are the same thing (Telegram
    chat ids equal user ids there), but this also makes it work correctly
    when support messages are routed through a shared log channel/group —
    any admin can reply there, and the lookup still finds the right
    original message regardless of who taps reply."""
    relay = SupportRelayRepository(session)
    user_telegram_id = await relay.find_user_telegram_id(
        message.chat.id, message.reply_to_message.message_id
    )
    if user_telegram_id is None:
        return  # this reply isn't attached to a support message — ignore

    try:
        if message.text:
            await message.bot.send_message(user_telegram_id, message.text)
        else:
            await message.copy_to(user_telegram_id)
        admin_actions_logger.info(
            "support_reply_relayed admin=%s user=%s", message.from_user.id, user_telegram_id
        )
        await message.reply("✅ Yuborildi")
    except TelegramAPIError:
        await message.reply("⚠️ Yuborib bo'lmadi — foydalanuvchi botni bloklagan bo'lishi mumkin.")
