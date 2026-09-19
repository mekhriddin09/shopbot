"""What happens after a card alert is matched to an order: deliver it, or
ask an admin first — plus the expiry sweeper for orders nobody paid.

Kept separate from `service.py` (which is pure matching logic with no
Telegram involvement) so the matching rules stay unit-testable without a
bot object.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order
from app.database.models.enums import CardTransactionStatus, OrderStatus
from app.keyboards.admin_kb import admin_card_confirm_kb
from app.keyboards.user_kb import buy_again_kb
from app.repositories.card_transaction_repo import CardTransactionRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.setting_repo import SettingRepository
from app.services.card_payment.service import CardPaymentService
from app.services.delivery_service import DeliveryService
from app.services.exceptions import DeliveryFailedError, InvalidOrderStateError
from app.services.notify import notify_admins_text, notify_delivery_failure
from app.services.referral_service import ReferralService
from app.utils.formatting import build_delivered_message, fmt_price
from app.utils.i18n import t

logger = logging.getLogger("card_payment")


async def _should_auto_deliver(session: AsyncSession, order: Order) -> bool:
    """Auto-delivery needs BOTH the global switch on AND this product not
    flagged as manual-confirm. The per-product flag exists so higher-value
    items keep a human in the loop even once the shop is confident enough
    to auto-deliver everything else."""
    if order.product is not None and order.product.card_manual_confirm:
        return False
    return await SettingRepository(session).get_bool("card_auto_deliver_enabled", False)


async def _order_summary(order: Order, amount: float) -> str:
    return (
        f"\U0001F4B3 <b>Karta to'lovi keldi</b>\n\n"
        f"\U0001F4B0 Summa: <b>{fmt_price(amount)} {order.currency}</b>\n"
        f"\U0001F4E6 Mahsulot: {order.product.name if order.product else '-'}\n"
        f"\U0001F464 @{order.user.username or '-'} (<code>{order.user.telegram_id}</code>)\n"
        f"\U0001F196 Buyurtma: <code>{order.order_uuid}</code>"
    )


async def complete_matched_payment(
    bot: Bot, session: AsyncSession, order: Order, amount: float
) -> None:
    """Either deliver immediately, or park the order and ask an admin."""
    if not await _should_auto_deliver(session, order):
        await OrderRepository(session).set_status(order, OrderStatus.PENDING_APPROVAL)
        reason = (
            "mahsulot \"qo'lda tasdiqlash\" deb belgilangan"
            if (order.product is not None and order.product.card_manual_confirm)
            else "avtomatik yetkazish o'chirilgan"
        )
        await notify_admins_text(
            bot,
            session,
            await _order_summary(order, amount)
            + f"\n\n✅ To'lov summasi <b>to'g'ri keldi</b>.\n"
            f"⏸ Yetkazish kutilmoqda — {reason}.",
        )
        # Buttons need their own message so the summary stays readable.
        from app.services.notify import _all_admin_ids  # local import avoids a cycle

        for admin_id in await _all_admin_ids(session):
            try:
                await bot.send_message(
                    admin_id,
                    "Yetkazib beraymi?",
                    reply_markup=admin_card_confirm_kb(order.id),
                )
            except Exception:  # noqa: BLE001 - admin may have blocked the bot
                pass
        return

    await deliver_paid_order(bot, session, order, amount)


async def deliver_paid_order(bot: Bot, session: AsyncSession, order: Order, amount: float) -> None:
    """Approve + deliver an order whose card payment is confirmed. Reuses
    the single delivery path every other payment method goes through, so
    inventory/API/manual modes all behave identically here."""
    # `approve_order` only accepts orders sitting in PENDING_APPROVAL. On the
    # auto-deliver path the order is still AWAITING_CARD_PAYMENT at this
    # point, so move it across first — the payment *is* confirmed, we're
    # just skipping the human step. Harmless no-op when an admin confirmed
    # manually, since the order is already in that state.
    if order.status != OrderStatus.PENDING_APPROVAL:
        await OrderRepository(session).set_status(order, OrderStatus.PENDING_APPROVAL)

    delivery = DeliveryService(session)
    try:
        result = await delivery.approve_order(order.id, admin_id=None)
    except InvalidOrderStateError as exc:
        logger.warning("card_delivery_invalid_state order=%s err=%s", order.order_uuid, exc)
        await notify_admins_text(
            bot, session, f"⚠️ <code>{order.order_uuid}</code>: {exc}"
        )
        return
    except DeliveryFailedError as exc:
        logger.error("card_delivery_failed order=%s err=%s", order.order_uuid, exc)
        fresh = await OrderRepository(session).get_by_id(order.id) or order
        await notify_delivery_failure(bot, session, fresh, str(exc))
        return

    fresh = result.order
    lang = fresh.user.language

    if result.delivered_now and result.payload:
        try:
            await bot.send_message(
                fresh.user.telegram_id,
                build_delivered_message(lang, fresh, result.payload),
                reply_markup=buy_again_kb(lang, fresh.product_id),
            )
        except Exception:  # noqa: BLE001 - customer may have blocked the bot
            logger.warning("card_delivery_notify_failed order=%s", fresh.order_uuid)
        await ReferralService(session).credit_for_delivered_order(fresh, bot)
        await notify_admins_text(
            bot, session, await _order_summary(fresh, amount) + "\n\n✅ <b>Avtomatik yetkazildi.</b>"
        )
    elif result.needs_manual_message:
        from app.keyboards.admin_kb import admin_write_manual_kb
        from app.services.notify import _all_admin_ids

        await notify_admins_text(
            bot,
            session,
            await _order_summary(fresh, amount)
            + "\n\n✅ To'lov tasdiqlandi. ✍️ Mahsulotni qo'lda yuborishingiz kerak.",
        )
        for admin_id in await _all_admin_ids(session):
            try:
                await bot.send_message(
                    admin_id, "Xabarni yozish:", reply_markup=admin_write_manual_kb(fresh.id)
                )
            except Exception:  # noqa: BLE001
                pass


async def notify_unmatched(bot: Bot, session: AsyncSession, tx) -> None:
    """Money arrived that no awaiting order claimed.

    Always recorded in `card_transactions` for audit, but by default the
    admin is NOT pinged: this card also receives plenty of deposits that
    have nothing to do with the shop, so alerting on each one is noise. An
    earlier version additionally guessed at "near-miss" orders (in case a
    customer rounded 29 973 up to 30 000) — that was removed deliberately:
    against a stream of unrelated deposits those guesses are mostly wrong,
    and a wrong guess invites the admin to hand out a product nobody paid
    for. A customer whose payment isn't recognised already has their own
    route out (wait for the window to close, then "I did pay" -> receipt).

    Set `card_notify_unmatched` to "1" to get the alerts anyway.
    """
    if not await SettingRepository(session).get_bool("card_notify_unmatched", False):
        return

    amount = float(tx.amount) if tx.amount is not None else 0.0
    await notify_admins_text(
        bot,
        session,
        f"\U0001F4B8 <b>Karta to'lovi keldi, mos buyurtma topilmadi</b>\n\n"
        f"\U0001F4B0 Summa: <b>{fmt_price(amount)} {tx.currency or ''}</b>\n"
        f"\U0001F4B3 Karta: ***{tx.card_last4 or '-'}\n\n"
        f"Agar bu mijozning to'lovi bo'lsa, u chek yuborishi mumkin "
        f"yoki buyurtmani ID orqali topib qo'lda tasdiqlang.",
    )


async def sweep_expired_card_orders(bot: Bot, session: AsyncSession) -> int:
    """Cancel orders whose payment window closed, releasing both their
    reserved inventory and their reserved amount. The customer still gets
    an "I did pay" button so a late payer isn't stranded."""
    from app.keyboards.user_kb import card_auto_expired_kb
    from app.services.order_service import OrderService

    service = CardPaymentService(session)
    expired = await service.list_expired_orders()
    order_service = OrderService(session)

    for order in expired:
        await order_service.cancel_pending(order.id)
        full = await OrderRepository(session).get_by_id(order.id)
        if full is None:
            continue
        lang = full.user.language
        try:
            await bot.send_message(
                full.user.telegram_id,
                t(lang, "msg_card_auto_expired", order_uuid=full.order_uuid),
                reply_markup=card_auto_expired_kb(lang, full.id),
            )
        except Exception:  # noqa: BLE001 - customer may have blocked the bot
            pass

    if expired:
        logger.info("card_orders_expired count=%s", len(expired))
    return len(expired)


__all__ = [
    "complete_matched_payment",
    "deliver_paid_order",
    "notify_unmatched",
    "sweep_expired_card_orders",
]
