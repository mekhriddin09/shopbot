"""Telegram Stars (XTR) native payment flow.

Telegram Stars are Telegram's own in-app currency — payment is handled
entirely inside Telegram via `bot.send_invoice(currency="XTR", ...)` with an
empty `provider_token`. Unlike crypto (CryptoBot/xRocket), there's no
external provider to poll: Telegram sends a `PreCheckoutQuery` right before
charging the user (which we must answer within 10 seconds) and then a
`successful_payment` update the instant the charge succeeds. So this flow is
push-based end to end — the only background-poller involvement is sweeping
abandoned/unpaid invoices after a timeout (see crypto_poller._sweep_stale_stars_orders).
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Product, User
from app.database.models.enums import OrderStatus, PaymentMethod
from app.keyboards.callback_data import StarsCB
from app.keyboards.user_kb import stars_invoice_kb
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.setting_repo import SettingRepository
from app.services.exceptions import DeliveryFailedError, InvalidOrderStateError
from app.services.referral_service import ReferralService
from app.utils.formatting import build_delivered_message, product_name
from app.utils.i18n import t

router = Router(name="user_stars")

order_logger = logging.getLogger("orders")
payment_logger = logging.getLogger("payments")


async def start_stars_purchase(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    lang: str,
    product: Product,
    qty: int,
    preorder: bool = False,
) -> None:
    settings_repo = SettingRepository(session)
    if not await settings_repo.get_bool("stars_payment_enabled", False):
        await callback.answer(t(lang, "msg_stars_disabled"), show_alert=True)
        return
    if product.price_stars is None:
        await callback.answer(t(lang, "msg_stars_disabled"), show_alert=True)
        return

    total_stars = int(product.price_stars) * qty
    orders = OrderRepository(session)
    order = await orders.create(
        user_id=user.id,
        product_id=product.id,
        price=float(total_stars),
        currency="XTR",
        payment_method=PaymentMethod.STARS,
        status=OrderStatus.AWAITING_STARS_PAYMENT,
        quantity=qty,
        is_preorder=preorder,
    )

    if not preorder and product.delivery_mode.value == "inventory":
        # Reserve the actual code(s) now — same reasoning as the crypto flow:
        # they must not be promised to another customer while this invoice
        # is still unpaid.
        inventory = InventoryRepository(session)
        reserved = await inventory.reserve_many(product.id, order.id, qty)
        if reserved is None:
            await orders.set_status(order, OrderStatus.CANCELLED)
            await callback.answer(t(lang, "msg_out_of_stock"), show_alert=True)
            return

    title = product_name(product, lang) + (f" × {qty}" if qty > 1 else "")
    description = product.description or title
    try:
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=title[:32] or title,
            description=description[:255],
            payload=str(order.id),
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=title[:32] or title, amount=total_stars)],
            reply_markup=stars_invoice_kb(lang, order.id),
        )
    except Exception:  # noqa: BLE001 - surface a clean error instead of a raw traceback to the user
        logging.getLogger("providers").exception("Failed to send Stars invoice for order=%s", order.order_uuid)
        await orders.set_status(order, OrderStatus.CANCELLED)
        if not preorder and product.delivery_mode.value == "inventory":
            await InventoryRepository(session).release_reservation(order.id)
        await callback.answer(t(lang, "msg_stars_disabled"), show_alert=True)
        return

    await callback.answer()


@router.callback_query(StarsCB.filter(F.action == "buy"))
async def stars_buy(
    callback: CallbackQuery, callback_data: StarsCB, session: AsyncSession, user: User, lang: str
) -> None:
    products = ProductRepository(session)
    product = await products.get_by_id(callback_data.product_id)
    if product is None or not product.is_visible or product.price_stars is None:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return
    if not callback_data.preorder and product.delivery_mode.value == "inventory":
        stock = await products.available_stock(product.id)
        if stock <= 0:
            await callback.answer(t(lang, "msg_out_of_stock"), show_alert=True)
            return
    await start_stars_purchase(
        callback, session, user, lang, product, qty=callback_data.qty or 1, preorder=callback_data.preorder
    )


@router.callback_query(StarsCB.filter(F.action == "cancel"))
async def stars_cancel(callback: CallbackQuery, callback_data: StarsCB, session: AsyncSession, lang: str) -> None:
    from app.services.order_service import OrderService

    order = await OrderRepository(session).get_by_id(callback_data.order_id)
    if order is None:
        await callback.answer(t(lang, "msg_order_not_found"), show_alert=True)
        return
    cancelled = await OrderService(session).cancel_pending(callback_data.order_id)
    if not cancelled:
        await callback.answer(t(lang, "msg_crypto_already_processed"), show_alert=True)
        return
    await callback.message.edit_text(t(lang, "msg_crypto_cancelled_by_user", order_uuid=order.order_uuid))
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery, session: AsyncSession) -> None:
    """Telegram calls this right before charging the user — we have 10
    seconds to confirm the order is still valid (payload = our order id,
    still awaiting payment, amount matches) or the payment is rejected."""
    order_id_raw = pre_checkout_query.invoice_payload
    error: str | None = None
    try:
        order_id = int(order_id_raw)
    except ValueError:
        order_id = None
        error = "Invalid order reference."

    order = await OrderRepository(session).get_by_id(order_id) if order_id else None
    if order is None:
        error = error or "Order not found."
    elif order.status != OrderStatus.AWAITING_STARS_PAYMENT:
        error = "This order is no longer awaiting payment."
    elif int(order.price_at_purchase) != pre_checkout_query.total_amount:
        error = "Price mismatch, please start over."

    if error:
        payment_logger.warning("stars_pre_checkout_rejected payload=%s error=%s", order_id_raw, error)
        await pre_checkout_query.answer(ok=False, error_message=error)
        return
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message, session: AsyncSession, lang: str) -> None:
    payment = message.successful_payment
    try:
        order_id = int(payment.invoice_payload)
    except ValueError:
        logging.getLogger("payments").error("stars_successful_payment_bad_payload payload=%s", payment.invoice_payload)
        return

    orders = OrderRepository(session)
    order = await orders.get_by_id(order_id)
    if order is None:
        return

    order.stars_charge_id = payment.telegram_payment_charge_id
    await session.commit()
    payment_logger.info(
        "stars_payment_confirmed order=%s charge_id=%s", order.order_uuid, payment.telegram_payment_charge_id
    )

    from app.services.delivery_service import DeliveryService

    delivery = DeliveryService(session)
    try:
        result = await delivery.auto_deliver_stars(order.id)
    except (InvalidOrderStateError, DeliveryFailedError) as exc:
        await message.answer(exc.localized(lang))
        return

    if result.delivered_now and result.payload:
        await message.answer(build_delivered_message(lang, order, result.payload))
        await ReferralService(session).credit_for_delivered_order(order, message.bot)
    elif result.needs_manual_message:
        await message.answer(t(lang, "msg_crypto_confirmed_manual_pending"))
        from app.services.crypto_poller import _notify_admins_with_manual_button

        await _notify_admins_with_manual_button(
            message.bot, session, order.id, order.order_uuid, order.product.name
        )
