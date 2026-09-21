"""Fan-out helpers for notifying every admin (env + DB) about something."""
from __future__ import annotations

import logging
from html import escape as html_escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import Order, ReferralRedemption, ReferralWithdrawal, User
from app.keyboards.admin_kb import (
    admin_order_action_kb,
    admin_referral_redemption_kb,
    admin_referral_withdraw_kb,
)
from app.repositories.admin_repo import AdminRepository
from app.utils.formatting import fmt_datetime, fmt_price

logger = logging.getLogger(__name__)


async def _all_admin_ids(session: AsyncSession) -> set[int]:
    ids = set(settings.admin_ids)
    admins = AdminRepository(session)
    for admin in await admins.list_active():
        ids.add(admin.telegram_id)
    return ids


def _parse_chat_target(raw: str) -> int | str:
    """A log-channel ID as the admin typed it: numeric ("-1001234567890")
    or a @username. `send_message`/`send_photo` accept both directly, but
    only the numeric form should be coerced to `int` — a username must
    stay a string, and Telegram requires it prefixed with "@" or the send
    fails outright (a bare "mychannel" is NOT accepted). Admins very
    commonly paste/type a channel's username without the leading "@" —
    unlike the numeric channel id case, there's no ambiguity in adding it
    back, so this is done defensively rather than silently failing every
    send to that channel."""
    raw = raw.strip()
    stripped = raw[1:] if raw.startswith("-") else raw
    if stripped.isdigit():
        return int(raw)
    return raw if raw.startswith("@") else f"@{raw}"


async def _log_channel_target(session: AsyncSession) -> int | str | None:
    """The configured log channel, or None if it isn't set.

    Per the admin's explicit instructions: the log channel is a clean,
    read-only order-history database — every order, manual or auto, ends up
    there. Anything that needs a human to actually act on it (approving/
    rejecting a payment proof or balance order, a support message, a
    referral withdrawal/redemption request, a delivery-failure alert) must
    always keep landing in every admin's own chat regardless of whether a
    log channel is set — see `_all_admin_ids`, used everywhere else in this
    module. A plain confirmation with nothing to act on (an auto-delivered
    Stars/crypto/card_auto order — see `notify_admins_order_delivered`)
    goes ONLY to the log channel, falling back to every admin only if no
    log channel is configured at all."""
    from app.repositories.setting_repo import SettingRepository  # local import avoids a cycle

    log_channel = (await SettingRepository(session).get("log_channel_id", "")).strip()
    return _parse_chat_target(log_channel) if log_channel else None


async def notify_admins_new_order(
    bot: Bot,
    session: AsyncSession,
    order: Order,
    proof_file_id: str,
    *,
    is_document: bool = False,
) -> None:
    """`is_document=True` when the customer's payment proof was uploaded as
    a file (png-as-document, pdf, docx, ...) rather than a native Telegram
    photo — see `app/handlers/user/shop.py:receive_screenshot`, which now
    accepts either. Sent via `send_document` in that case so it reaches the
    admin as the original file (a `send_photo` call would silently fail or
    mangle non-image documents)."""
    preorder_line = "\n⏳ <b>OLDINDAN BUYURTMA</b> (mahsulot hozircha stokda yo'q)" if order.is_preorder else ""
    qty_line = f"\n\U0001F522 Miqdor: {order.quantity} dona" if order.quantity and order.quantity > 1 else ""
    # Everything an admin needs about this order (who, what, how much, how
    # they paid, when) in one message — so the admin chat/log channel
    # doesn't turn into a scattered trail of half-messages per order.
    caption = (
        f"\U0001F6CE️ <b>Yangi buyurtma</b>\n\n"
        f"\U0001F464 {order.user.full_name or '-'} (@{order.user.username or '-'})\n"
        f"\U0001F194 Telegram ID: <code>{order.user.telegram_id}</code>\n"
        f"\U0001F4E6 Mahsulot: {html_escape(order.product.name)}\n"
        f"\U0001F4B0 Narxi: {fmt_price(float(order.price_at_purchase))} {order.currency}\n"
        f"\U0001F4B3 To'lov usuli: {order.payment_method.value}\n"
        f"\U0001F551 Vaqti: {fmt_datetime(order.created_at)}\n"
        f"\U0001F196 Buyurtma: <code>{order.order_uuid}</code>"
        f"{qty_line}{preorder_line}"
    )
    # This needs an admin's decision (approve/reject the payment proof) —
    # always every admin, never *only* the log channel.
    for admin_id in await _all_admin_ids(session):
        try:
            if is_document:
                await bot.send_document(
                    admin_id,
                    document=proof_file_id,
                    caption=caption,
                    reply_markup=admin_order_action_kb(order.id),
                )
            else:
                await bot.send_photo(
                    admin_id,
                    photo=proof_file_id,
                    caption=caption,
                    reply_markup=admin_order_action_kb(order.id),
                )
        except TelegramAPIError:
            logger.warning("Failed to notify admin %s about order %s", admin_id, order.order_uuid)

    # Additionally, a read-only copy for the order-history log channel, if
    # one is configured — no action buttons here on purpose: approving or
    # rejecting the order still only happens from an admin's own chat above.
    log_target = await _log_channel_target(session)
    if log_target is not None:
        try:
            if is_document:
                await bot.send_document(log_target, document=proof_file_id, caption=caption)
            else:
                await bot.send_photo(log_target, photo=proof_file_id, caption=caption)
        except TelegramAPIError:
            logger.warning("Failed to log order %s to log channel", order.order_uuid)


async def notify_admins_text(bot: Bot, session: AsyncSession, text: str) -> None:
    # Always every admin, never the log channel — this is the generic
    # "something needs your attention" helper (manual-confirm prompts,
    # delivery-status updates), not order history.
    for admin_id in await _all_admin_ids(session):
        try:
            await bot.send_message(admin_id, text)
        except TelegramAPIError:
            logger.warning("Failed to notify admin %s", admin_id)


async def notify_delivery_failure(
    bot: Bot,
    session: AsyncSession,
    order: Order,
    error_text: str,
    *,
    tell_customer: bool = True,
) -> None:
    """The single failure path for automatic delivery.

    Every automated supplier we use (Fragment for Stars/Premium, reseller
    APIs, crypto confirmation) is expected to break sooner or later —
    unofficial integrations always do. The rule is therefore: a broken
    supplier turns into a *manual* order, never into silence. So this
    always does three things at once:

      1. Tells every admin exactly what failed, on which order, for whom,
         with the supplier's own error text (not a sanitised version — the
         admin needs to know whether to top up the wallet, refresh cookies,
         or ask the customer for another username).
      2. Attaches the one-tap "send by hand" button, so recovering the
         order is a single press rather than a hunt through the panel.
      3. Reassures the customer that their money isn't lost and a human is
         on it, because from their side an auto-shop that goes quiet after
         payment looks exactly like a scam.

    Kept here, rather than in DeliveryService, because DeliveryService has
    no Bot and must stay usable from tests without one.
    """
    from app.keyboards.admin_kb import admin_order_detail_kb
    from app.utils.i18n import t

    product = order.product.name if order.product is not None else "-"
    user = order.user
    lines = [
        "🚨 <b>AVTOMATIK YETKAZISH BAJARILMADI</b>",
        "",
        f"🆖 Buyurtma: <code>{order.order_uuid}</code> (ID: {order.id})",
        f"📦 Mahsulot: {product}",
    ]
    if order.recipient_username:
        lines.append(f"🎁 Qabul qiluvchi: @{order.recipient_username}")
    if user is not None:
        lines.append(f"👤 Mijoz: @{user.username or '-'} (<code>{user.telegram_id}</code>)")
    lines += [
        f"💰 To'lov: {fmt_price(float(order.expected_amount or order.price_at_purchase))} "
        f"{order.currency}",
        "",
        f"⚠️ Xato: {error_text}",
        "",
        "To'lov o'z joyida. Qo'lda yetkazib bering ↓",
    ]
    text = "\n".join(lines)

    # A broken delivery needs a human to act on it — always every admin,
    # never the log channel (see resolve_order_log_targets' docstring).
    for admin_id in await _all_admin_ids(session):
        try:
            await bot.send_message(admin_id, text, reply_markup=admin_order_detail_kb(order))
        except TelegramAPIError:
            logger.warning("Failed to alert admin %s about failed delivery %s", admin_id, order.order_uuid)

    if tell_customer and user is not None:
        try:
            await bot.send_message(
                user.telegram_id,
                t(user.language, "msg_delivery_manual_fallback", order_uuid=order.order_uuid),
            )
        except TelegramAPIError:
            logger.warning("Failed to reassure customer about failed delivery %s", order.order_uuid)


async def notify_admins_referral_withdrawal(
    bot: Bot, session: AsyncSession, withdrawal: ReferralWithdrawal, user: User
) -> None:
    card_line = f"\n\U0001F4B3 Karta: <code>{withdrawal.card_note}</code>" if withdrawal.card_note else ""
    text = (
        f"\U0001F4B0 <b>Referral pul yechish so'rovi</b>\n\n"
        f"\U0001F464 {user.full_name or '-'} (@{user.username or '-'})\n"
        f"\U0001F194 Telegram ID: <code>{user.telegram_id}</code>\n"
        f"\U0001F4B5 Miqdor: {fmt_price(float(withdrawal.amount))}\n"
        f"\U0001F196 So'rov: <code>{withdrawal.id}</code>"
        f"{card_line}"
    )
    kb = admin_referral_withdraw_kb(withdrawal.id)
    # Needs action from an admin — always every admin, never the log channel.
    for admin_id in await _all_admin_ids(session):
        try:
            await bot.send_message(admin_id, text, reply_markup=kb)
        except TelegramAPIError:
            logger.warning("Failed to notify admin %s about referral withdrawal %s", admin_id, withdrawal.id)


async def notify_admins_referral_redemption(
    bot: Bot, session: AsyncSession, redemption: ReferralRedemption, user: User
) -> None:
    from app.database.models.enums import ReferralCurrency  # local import avoids a cycle
    from app.repositories.setting_repo import SettingRepository

    settings_repo = SettingRepository(session)
    if redemption.currency_type == ReferralCurrency.POINTS:
        unit = await settings_repo.get("referral_points_name", "Ball")
    else:
        unit = await settings_repo.get("referral_currency", "UZS")

    note_line = f"\n\U0001F4DD Izoh: {redemption.note}" if redemption.note else ""
    text = (
        f"\U0001F381 <b>Referral do'koni — yangi so'rov</b>\n\n"
        f"\U0001F464 {user.full_name or '-'} (@{user.username or '-'})\n"
        f"\U0001F194 Telegram ID: <code>{user.telegram_id}</code>\n"
        f"\U0001F3F7️ Sovg'a: {redemption.reward_name_snapshot}\n"
        f"\U0001F4B0 Narxi: {fmt_price(float(redemption.cost_snapshot))} {unit}\n"
        f"\U0001F196 So'rov: <code>{redemption.id}</code>"
        f"{note_line}"
    )
    kb = admin_referral_redemption_kb(redemption.id)
    # Needs action from an admin — always every admin, never the log channel.
    for admin_id in await _all_admin_ids(session):
        try:
            await bot.send_message(admin_id, text, reply_markup=kb)
        except TelegramAPIError:
            logger.warning("Failed to notify admin %s about referral redemption %s", admin_id, redemption.id)


async def notify_admins_balance_order(bot: Bot, session: AsyncSession, order: Order, user: User) -> None:
    """A purchase paid from the customer's own referral cash balance still
    waits for an admin's approve/reject tap, exactly like a manual card
    payment — the balance itself was earned through the referral program,
    so it gets the same human check rather than auto-delivering. Uses the
    same approve/reject buttons (OrderCB) as every other pending order, so
    tapping them runs through the normal admin/orders.py approval flow
    unchanged; a reject additionally refunds the balance (see
    DeliveryService.reject_order)."""
    currency_repo_value = order.currency
    text = (
        f"\U0001F4B0 <b>Referal balansidan to'lov</b>\n\n"
        f"\U0001F464 {user.full_name or '-'} (@{user.username or '-'})\n"
        f"\U0001F194 Telegram ID: <code>{user.telegram_id}</code>\n"
        f"\U0001F4E6 Mahsulot: {html_escape(order.product.name)}\n"
        f"\U0001F4B5 Summa (balansdan yechildi): {fmt_price(float(order.price_at_purchase))} {currency_repo_value}\n"
        f"\U0001F196 Buyurtma: <code>{order.order_uuid}</code>\n\n"
        f"Tasdiqlansa — yetkaziladi. Rad etilsa — summa mijozning balansiga qaytariladi."
    )
    kb = admin_order_action_kb(order.id)
    # Needs action from an admin — always every admin.
    for admin_id in await _all_admin_ids(session):
        try:
            await bot.send_message(admin_id, text, reply_markup=kb)
        except TelegramAPIError:
            logger.warning("Failed to notify admin %s about balance order %s", admin_id, order.order_uuid)

    # Also a plain read-only copy to the log channel (order history), same
    # as every other new-order event — see notify_admins_new_order.
    log_target = await _log_channel_target(session)
    if log_target is not None:
        try:
            await bot.send_message(log_target, text)
        except TelegramAPIError:
            logger.warning("Failed to log balance order %s to log channel", order.order_uuid)


async def notify_admins_order_delivered(bot: Bot, session: AsyncSession, order: Order) -> None:
    """Fired once an order that never needed admin approval (Telegram
    Stars, crypto, card_auto) finishes auto-delivering. There's nothing to
    approve here — it's a plain confirmation, pure order history — so per
    the admin's explicit instruction it now goes ONLY to the log channel,
    never to every admin's own chat (that chat is reserved for things that
    actually need a human: manual/proof payments awaiting approval,
    support messages, referral withdrawal/redemption requests). If no log
    channel is configured yet, it falls back to notifying every admin
    directly — otherwise a successful sale would be completely invisible
    with nothing configured to catch it."""
    text = (
        f"✅ <b>Buyurtma avtomatik yetkazildi</b>\n\n"
        f"\U0001F464 {order.user.full_name or '-'} (@{order.user.username or '-'})\n"
        f"\U0001F194 Telegram ID: <code>{order.user.telegram_id}</code>\n"
        f"\U0001F4E6 Mahsulot: {html_escape(order.product.name)}\n"
        f"\U0001F4B0 Narxi: {fmt_price(float(order.price_at_purchase))} {order.currency}\n"
        f"\U0001F4B3 To'lov usuli: {order.payment_method.value}\n"
        f"\U0001F551 Vaqti: {fmt_datetime(order.created_at)}\n"
        f"\U0001F196 Buyurtma: <code>{order.order_uuid}</code>"
    )
    log_target = await _log_channel_target(session)
    if log_target is not None:
        try:
            await bot.send_message(log_target, text)
        except TelegramAPIError:
            logger.warning("Failed to log delivered order %s to log channel", order.order_uuid)
        return

    # No log channel configured — fall back to every admin so this isn't
    # silently lost.
    for admin_id in await _all_admin_ids(session):
        try:
            await bot.send_message(admin_id, text)
        except TelegramAPIError:
            logger.warning("Failed to notify admin %s about delivered order %s", admin_id, order.order_uuid)
