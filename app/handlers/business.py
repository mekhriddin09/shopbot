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

from app.database.models.enums import CardTransactionStatus
from app.repositories.setting_repo import SettingRepository
from app.services.notify import notify_admins_text

router = Router(name="business_probe")

logger = logging.getLogger("business")


@router.business_connection()
async def business_connection_changed(
    connection: BusinessConnection, session: AsyncSession
) -> None:
    """Fires when someone connects/disconnects/reconfigures this bot in
    their Telegram Business -> Chatbots settings.

    Note that *anyone* can do this — a business bot is connectable by any
    user, not just the owner. So this handler never grants trust; it only
    reports the connection and tells the admin how to approve it if it's
    the real card account (see `_is_approved_connection`).
    """
    enabled = getattr(connection, "is_enabled", None)
    user_id = connection.user.id if connection.user else None
    logger.info(
        "business_connection id=%s user=%s enabled=%s", connection.id, user_id, enabled
    )

    approved = (await SettingRepository(session).get("card_business_connection_id", "")).strip()
    is_approved = approved and approved == str(connection.id)

    if is_approved:
        status_line = "✅ Bu ulanish <b>tasdiqlangan</b> karta hisobi."
    else:
        status_line = (
            "⚠️ Bu ulanish <b>tasdiqlanmagan</b> — undan kelgan karta xabarlari hisobga olinmaydi.\n\n"
            "Agar bu sizning karta hisobingiz bo'lsa, quyidagi Connection ID'ni nusxalab, "
            "Admin panel → Sozlamalar → 💳 To'lov usullari → "
            "<b>Karta hisobi ulanishi</b> ga joylashtiring."
        )

    await notify_admins_text(
        connection.bot,
        session,
        "🔌 <b>Business ulanish yangilandi</b>\n\n"
        f"Holat: {'✅ faol' if enabled else '❌ o‘chirilgan'}\n"
        f"Foydalanuvchi: <code>{user_id if user_id is not None else '-'}</code>\n"
        f"Connection ID:\n<code>{html.escape(str(connection.id))}</code>\n\n"
        f"{status_line}",
    )


async def _is_approved_connection(session: AsyncSession, connection_id: str | None) -> bool:
    """SECURITY: only the admin-approved business connection may deliver
    card notifications.

    Without this check the payment flow is trivially exploitable: any
    stranger can connect this bot to their own Telegram account, transfer
    money to *their own* card, and let the resulting genuine @CardXabarBot
    alert flow through their connection. The amount would match a pending
    order and the bot would hand over the product for free. Filtering on
    the sender alone cannot catch that — the sender really is CardXabar.

    Fails closed: if nothing is approved yet, nothing is accepted.
    """
    approved = (await SettingRepository(session).get("card_business_connection_id", "")).strip()
    return bool(approved) and approved == (connection_id or "")


async def _is_card_notifier(session: AsyncSession, sender) -> bool:
    """True only for the configured card-notification sender (CardXabar).

    PRIVACY: the business connection carries *every* private chat of the
    connected account, including personal conversations. Everything that
    isn't the card notifier is dropped here and never logged, forwarded or
    stored — the bot has no business reading the owner's private messages
    just because it needs to see bank alerts.

    Matched by username (case-insensitive) or numeric id, so the admin can
    set either in the "card_notify_sender" setting.
    """
    if sender is None:
        return False
    configured = (await SettingRepository(session).get("card_notify_sender", "CardXabarBot")).strip()
    if not configured:
        return False
    configured = configured.lstrip("@").lower()
    if configured.isdigit():
        return str(sender.id) == configured
    return (sender.username or "").lower() == configured


@router.business_message()
async def business_message_probe(message: Message, session: AsyncSession) -> None:
    """Forward card-notification messages to the admins.

    Still a diagnostic at this stage: it shows the raw CardXabar text so
    the payment-amount parser can be written against the real format. Once
    that parser exists this same entry point becomes the card-payment
    listener (parse -> match a pending order -> deliver).
    """
    sender = message.from_user
    if not await _is_card_notifier(session, sender):
        # Not the card notifier — ignore silently (see _is_card_notifier).
        return

    # Right sender, but is it the right *account*? Both locks must hold.
    if not await _is_approved_connection(session, message.business_connection_id):
        logger.warning(
            "card_notification_from_unapproved_connection connection=%s sender=%s",
            message.business_connection_id, sender.id if sender else "?",
        )
        await notify_admins_text(
            message.bot,
            session,
            "🚨 <b>Tasdiqlanmagan ulanishdan karta xabari keldi — E'TIBORSIZ QOLDIRILDI</b>\n\n"
            f"Connection ID: <code>{html.escape(str(message.business_connection_id or '-'))}</code>\n\n"
            "Agar bu siz emas bo'lsangiz, kimdir botni o'z hisobiga ulab, "
            "o'z kartasiga tushgan pul bilan mahsulot olishga urinayotgan bo'lishi mumkin. "
            "Hech qanday buyurtma to'langan deb belgilanmadi.",
        )
        return

    text = message.text or message.caption or ""
    if not text.strip():
        return

    logger.info(
        "card_notification from=%s chat=%s len=%s",
        sender.id if sender else "?",
        message.chat.id if message.chat else "?",
        len(text),
    )

    if not await SettingRepository(session).get_bool("card_payment_enabled", False):
        # Feature switched off: show the alert so the admin still sees
        # what's arriving, but never touch any order.
        await _forward_raw(message, session, text, note="ℹ️ Avtomatik karta to'lovi o'chirilgan.")
        return

    # Stable per-alert key: the same message redelivered after a reconnect
    # produces the same key and is rejected as a duplicate.
    message_key = (
        f"{message.business_connection_id}:{message.chat.id if message.chat else '?'}:{message.message_id}"
    )

    from app.services.card_payment.flow import complete_matched_payment, notify_unmatched
    from app.services.card_payment.service import CardPaymentService

    transaction, order = await CardPaymentService(session).process_notification(message_key, text)

    if order is not None:
        await complete_matched_payment(message.bot, session, order, float(transaction.amount))
        return

    if transaction.status == CardTransactionStatus.DUPLICATE:
        return
    if transaction.status == CardTransactionStatus.IGNORED:
        return  # outgoing debit — not a customer payment
    if transaction.status == CardTransactionStatus.UNPARSED:
        await _forward_raw(
            message, session, text,
            note="⚠️ Bu xabardan summani o'qib bo'lmadi — qo'lda tekshiring.",
        )
        return

    # UNMATCHED / AMBIGUOUS -> money arrived, needs a human
    await notify_unmatched(message.bot, session, transaction)


async def _forward_raw(message: Message, session: AsyncSession, text: str, note: str = "") -> None:
    """Show the admin the raw alert (used when the feature is off or the
    text couldn't be parsed)."""
    sender = message.from_user
    header = (
        "💳 <b>Karta xabari keldi</b>\n\n"
        f"👤 Kimdan: {html.escape(sender.full_name or '-') if sender else '-'} "
        f"(@{html.escape(sender.username or '-') if sender else '-'})\n"
    )
    body = f"\n📝 <b>Matn:</b>\n<pre>{html.escape(text)}</pre>"
    tail = f"\n\n{note}" if note else ""
    try:
        await notify_admins_text(message.bot, session, header + body + tail)
    except TelegramAPIError:
        logger.exception("Failed to forward card alert to admins")


__all__ = ["router"]
