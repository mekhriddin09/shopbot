"""Telegram Business connection diagnostics.

When the bot is connected to a user account as a "business bot" (BotFather
-> Bot Settings -> Secretary Mode, then Telegram app -> Settings ->
Telegram Business -> Chatbots), Telegram delivers that account's private
chat messages to the bot as `business_message` updates.

Right now this module exists to answer one specific question: **does the
business connection also cover the account's chat with another bot**, i.e.
with @CardXabarBot? Telegram's own docs describe bot-to-bot delivery over
business connections, but don't state plainly whether a bot chat is
included in the connection's recipient set — so rather than assume, this
probe forwards every business message it receives to the admins, with the
sender's id/username and `is_bot` flag spelled out.

Two outcomes, both useful:
  * CardXabar messages show up here -> the official Business route works,
    and we build the card-payment listener on it (no userbot, no session
    string, no ban risk).
  * They never show up -> fall back to a Telethon userbot for the listener.

Either way this also captures the exact CardXabar message text, which is
what the payment-amount parser has to be written against.

This is read-only: it never replies to anyone through the connection.
"""
from __future__ import annotations

import html
import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BusinessConnection, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.notify import notify_admins_text

router = Router(name="business_probe")

logger = logging.getLogger("business")


@router.business_connection()
async def business_connection_changed(
    connection: BusinessConnection, session: AsyncSession
) -> None:
    """Fires when the user connects/disconnects/reconfigures the bot in
    Telegram Business -> Chatbots. Mostly a "yes, the link is live"
    confirmation — and it carries the `connection_id` that any future
    send-on-behalf-of-user call would need."""
    enabled = getattr(connection, "is_enabled", None)
    logger.info(
        "business_connection id=%s user=%s enabled=%s",
        connection.id, connection.user.id if connection.user else "?", enabled,
    )
    await notify_admins_text(
        connection.bot,
        session,
        "🔌 <b>Business ulanish yangilandi</b>\n\n"
        f"Holat: {'✅ faol' if enabled else '❌ o‘chirilgan'}\n"
        f"Foydalanuvchi: <code>{connection.user.id if connection.user else '-'}</code>\n"
        f"Connection ID: <code>{html.escape(str(connection.id))}</code>",
    )


@router.business_message()
async def business_message_probe(message: Message, session: AsyncSession) -> None:
    """Forward every business message to the admins so we can see exactly
    what does (and doesn't) come through the connection."""
    sender = message.from_user
    text = message.text or message.caption or ""

    logger.info(
        "business_message from=%s is_bot=%s chat=%s len=%s",
        sender.id if sender else "?",
        sender.is_bot if sender else "?",
        message.chat.id if message.chat else "?",
        len(text),
    )

    header = (
        "📡 <b>Business xabar keldi</b>\n\n"
        f"👤 Kimdan: {html.escape(sender.full_name or '-') if sender else '-'} "
        f"(@{html.escape(sender.username or '-') if sender else '-'})\n"
        f"🆔 ID: <code>{sender.id if sender else '-'}</code>\n"
        f"🤖 Botmi: <b>{'HA' if (sender and sender.is_bot) else 'yo‘q'}</b>\n"
        f"💬 Chat ID: <code>{message.chat.id if message.chat else '-'}</code>\n"
        f"🔗 Connection: <code>{html.escape(str(message.business_connection_id or '-'))}</code>\n"
    )
    body = (
        f"\n📝 <b>Matn:</b>\n<pre>{html.escape(text)}</pre>"
        if text
        else "\n📝 (matnsiz xabar — rasm/fayl/boshqa tur)"
    )

    try:
        await notify_admins_text(message.bot, session, header + body)
    except TelegramAPIError:
        logger.exception("Failed to forward business message to admins")


__all__ = ["router"]
