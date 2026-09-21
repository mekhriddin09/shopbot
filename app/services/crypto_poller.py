"""Background task that polls pending crypto invoices and auto-delivers
paid orders — no webhook server required.

Runs as an asyncio task alongside the bot's polling loop (see main.py).
Each iteration opens its own short-lived DB session so it never competes
with request-handling sessions for a single connection.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from app.config.settings import settings
from app.database.engine import async_session_maker
from app.database.models.enums import OrderStatus
from app.keyboards.admin_kb import admin_write_manual_kb
from app.keyboards.user_kb import buy_again_kb
from app.repositories.order_repo import OrderRepository
from app.services.crypto.registry import get_crypto_provider
from app.services.delivery_service import DeliveryService
from app.services.exceptions import DeliveryFailedError, InvalidOrderStateError
from app.services.notify import notify_admins_text, notify_delivery_failure
from app.services.order_service import OrderService
from app.services.referral_service import ReferralService
from app.utils.formatting import build_delivered_message
from app.utils.i18n import t
from app.utils.locks import lock_for

logger = logging.getLogger("providers")
order_logger = logging.getLogger("orders")


def _age_minutes(created_at: datetime) -> float:
    """Minutes elapsed since `created_at`, tolerant of both naive and
    timezone-aware datetimes (SQLite/aiosqlite may hand back either
    depending on how the row was written)."""
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return (now - created_at).total_seconds() / 60.0


async def crypto_poller_loop(bot: Bot) -> None:
    logger.info("Crypto payment poller started (interval=%ss)", settings.CRYPTO_POLL_INTERVAL_SECONDS)
    while True:
        try:
            await _poll_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - poller must never die silently crash the bot
            logger.exception("Crypto poller iteration failed")
        await asyncio.sleep(settings.CRYPTO_POLL_INTERVAL_SECONDS)


async def _poll_once(bot: Bot) -> None:
    async with async_session_maker() as session:
        orders_repo = OrderRepository(session)
        await _sweep_stale_stars_orders(bot, session, orders_repo)

        pending = await orders_repo.list_awaiting_crypto_payment()
        if not pending:
            return

        for order in pending:
            if _age_minutes(order.created_at) >= settings.CRYPTO_PAYMENT_TIMEOUT_MINUTES:
                # Abandoned invoice: give up on it instead of holding a
                # reserved inventory code hostage forever. Release the
                # reservation, mark the order cancelled, and let the
                # customer know so they can start over if they still want it.
                cancelled = await OrderService(session).cancel_pending(order.id)
                if cancelled:
                    order_logger.info(
                        "crypto_payment_timeout order=%s provider=%s", order.order_uuid, order.crypto_provider
                    )
                    try:
                        await bot.send_message(
                            order.user.telegram_id,
                            t(order.user.language, "msg_crypto_payment_timeout", order_uuid=order.order_uuid),
                        )
                    except Exception:  # noqa: BLE001 - user may have blocked the bot
                        logger.warning("Failed to notify user %s about crypto timeout", order.user.telegram_id)
                continue

            provider = get_crypto_provider(order.crypto_provider)
            if provider is None or not order.crypto_invoice_id:
                continue

            status = await provider.check_invoice(order.crypto_invoice_id)
            if not status.success or not status.paid:
                continue

            order_logger.info("crypto_payment_confirmed order=%s provider=%s", order.order_uuid, order.crypto_provider)

            delivery = DeliveryService(session)
            try:
                result = await delivery.auto_deliver_crypto(order.id)
            except (InvalidOrderStateError, DeliveryFailedError) as exc:
                logger.error("crypto auto-delivery failed for order=%s: %s", order.order_uuid, exc)
                await notify_delivery_failure(bot, session, order, str(exc))
                continue

            lang = order.user.language
            if result.delivered_now and result.payload:
                await bot.send_message(
                    order.user.telegram_id,
                    build_delivered_message(lang, order, result.payload),
                    reply_markup=buy_again_kb(lang, order.product_id),
                )
                await ReferralService(session).credit_for_delivered_order(order, bot)
                # Same gap as Stars: crypto is fully automatic and push/poll
                # based, so without this an admin never sees any
                # notification at all for a successful crypto sale.
                from app.services.notify import notify_admins_order_delivered

                fresh_order = await orders_repo.get_by_id(order.id)
                if fresh_order is not None:
                    await notify_admins_order_delivered(bot, session, fresh_order)
            elif result.needs_manual_message:
                # Crypto payment confirmed, but this product is delivered
                # manually — give admins a one-tap way to write the message.
                await _notify_admins_with_manual_button(bot, session, order.id, order.order_uuid, order.product.name)


async def _sweep_stale_stars_orders(bot: Bot, session, orders_repo: OrderRepository) -> None:
    """Telegram Stars payments are push-based — there's no "check invoice"
    API call to poll like with crypto, Telegram just sends a
    `successful_payment` update the moment the user pays. So the only job
    here is the same abandoned-invoice timeout as crypto: release any
    reserved stock for Stars invoices nobody ever paid.

    Uses its own STARS_PAYMENT_TIMEOUT_MINUTES (longer than crypto's) since
    a Stars invoice never shows the customer any expiry, unlike a crypto
    invoice's visible countdown — a short shared timeout meant a customer
    who simply took their time deciding could still tap "Pay" after we'd
    already cancelled the order and released its reserved stock.

    Also takes the same per-order lock DeliveryService.auto_deliver_stars
    uses (`lock_for`) before cancelling, so this can never race an
    in-flight successful_payment that's already mid-delivery for the same
    order — whichever gets the lock first, the other sees the now-updated
    status and correctly no-ops."""
    pending = await orders_repo.list_awaiting_stars_payment()
    for order in pending:
        if _age_minutes(order.created_at) < settings.STARS_PAYMENT_TIMEOUT_MINUTES:
            continue
        async with lock_for(f"order:{order.id}"):
            # Re-check under the lock: a delivery that started just before
            # we acquired it may have already moved this order past
            # AWAITING_STARS_PAYMENT.
            fresh = await orders_repo.get_by_id(order.id)
            if fresh is None or fresh.status != OrderStatus.AWAITING_STARS_PAYMENT:
                continue
            cancelled = await OrderService(session).cancel_pending(order.id)
        if cancelled:
            order_logger.info("stars_payment_timeout order=%s", order.order_uuid)
            try:
                await bot.send_message(
                    order.user.telegram_id,
                    t(order.user.language, "msg_crypto_payment_timeout", order_uuid=order.order_uuid),
                )
            except Exception:  # noqa: BLE001 - user may have blocked the bot
                logger.warning("Failed to notify user %s about stars timeout", order.user.telegram_id)


async def _notify_admins_with_manual_button(
    bot: Bot, session, order_id: int, order_uuid: str, product_name: str
) -> None:
    # Needs an admin's action -- always every admin, never the log channel
    # (log channel is order-history only).
    from app.services.notify import _all_admin_ids

    ids = await _all_admin_ids(session)

    text = (
        f"💰 Kripto to'lov tasdiqlandi: <code>{order_uuid}</code> ({product_name}).\n"
        f"Bu mahsulot qo'lda yetkaziladi — mijozga yuboriladigan xabarni yozing:"
    )
    for admin_id in ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=admin_write_manual_kb(order_id))
        except Exception:  # noqa: BLE001
            logger.warning("Failed to notify admin %s about manual crypto delivery", admin_id)
