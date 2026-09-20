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
from app.utils.formatting import fmt_price

logger = logging.getLogger(__name__)


async def _all_admin_ids(session: AsyncSession) -> set[int]:
    ids = set(settings.admin_ids)
    admins = AdminRepository(session)
    for admin in await admins.list_active():
        ids.add(admin.telegram_id)
    return ids


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
    caption = (
        f"\U0001F6CE️ <b>Yangi buyurtma</b>\n\n"
        f"\U0001F464 {order.user.full_name or '-'} (@{order.user.username or '-'})\n"
        f"\U0001F194 Telegram ID: <code>{order.user.telegram_id}</code>\n"
        f"\U0001F4E6 Mahsulot: {html_escape(order.product.name)}\n"
        f"\U0001F4B0 Narxi: {fmt_price(float(order.price_at_purchase))} {order.currency}\n"
        f"\U0001F196 Buyurtma: <code>{order.order_uuid}</code>"
        f"{qty_line}{preorder_line}"
    )
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


async def notify_admins_text(bot: Bot, session: AsyncSession, text: str) -> None:
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
    for admin_id in await _all_admin_ids(session):
        try:
            await bot.send_message(admin_id, text, reply_markup=kb)
        except TelegramAPIError:
            logger.warning("Failed to notify admin %s about referral redemption %s", admin_id, redemption.id)
