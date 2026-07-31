from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.models.enums import OrderStatus, PaymentMethod
from app.keyboards.callback_data import CryptoCB, ShopCB
from app.keyboards.user_kb import (
    cancel_kb,
    crypto_invoice_kb,
    main_menu_kb,
    payment_kb,
    product_detail_kb,
    shop_list_kb,
)
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.setting_repo import SettingRepository
from app.services.crypto.registry import available_crypto_providers, get_crypto_provider
from app.services.exceptions import (
    InvalidOrderStateError,
    OutOfStockError,
    ProductUnavailableError,
)
from app.services.notify import notify_admins_new_order
from app.services.order_service import OrderService
from app.services.product_service import ProductService
from app.states.user_states import PurchaseStates
from app.utils.formatting import build_delivered_message, fmt_price, product_description, product_name
from app.utils.i18n import t

router = Router(name="user_shop")


def _product_card_text(lang: str, product, stock: int) -> str:
    if stock < 0:
        stock_line = t(lang, "msg_unlimited_label")
    elif stock == 0:
        stock_line = t(lang, "msg_out_of_stock_label")
    else:
        stock_line = t(lang, "msg_stock_label", stock=stock)
    return t(
        lang,
        "msg_product_card",
        emoji=product.emoji,
        name=product_name(product, lang),
        description=product_description(product, lang),
        price=fmt_price(float(product.price)),
        currency=product.currency,
        stock_line=stock_line,
    )


@router.message(F.text.in_({t(l, "btn_shop") for l in ("uz", "ru", "en")}))
async def open_shop(message: Message, session: AsyncSession, lang: str) -> None:
    service = ProductService(session)
    views = await service.list_shop()
    if not views:
        await message.answer(t(lang, "msg_shop_empty"))
        return
    await message.answer(
        t(lang, "main_menu_hint"), reply_markup=shop_list_kb([v.product for v in views], lang)
    )


@router.callback_query(ShopCB.filter(F.action == "back_to_list"))
async def back_to_list(callback: CallbackQuery, session: AsyncSession, lang: str, state: FSMContext) -> None:
    data = await state.get_data()
    pending_order_id = data.get("order_id")
    if pending_order_id:
        # User backed out of the "upload screenshot" step without paying —
        # release any inventory code reserved for this order back to stock.
        await OrderService(session).cancel_pending(pending_order_id)
    await state.clear()
    service = ProductService(session)
    views = await service.list_shop()
    empty_text = t(lang, "msg_shop_empty") if not views else None
    text = empty_text or t(lang, "main_menu_hint")
    kb = None if empty_text else shop_list_kb([v.product for v in views], lang)

    if callback.message.photo:
        # We got here from a product card, which is a photo message — those
        # can't be edited into a text message, so replace it instead.
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=kb)
    else:
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(ShopCB.filter(F.action == "open"))
async def open_product(callback: CallbackQuery, callback_data: ShopCB, session: AsyncSession, lang: str) -> None:
    service = ProductService(session)
    view = await service.get_view(callback_data.product_id)
    if view is None or not view.product.is_visible:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return

    settings_repo = SettingRepository(session)
    crypto_enabled = await settings_repo.get_bool("crypto_payment_enabled", False)
    crypto_providers = available_crypto_providers() if crypto_enabled and view.product.price_usd is not None else []
    show_crypto = bool(crypto_providers)

    text = _product_card_text(lang, view.product, view.stock)
    if show_crypto:
        text += "\n" + t(lang, "msg_crypto_price_label", price=f"{float(view.product.price_usd):.2f}")
    kb = product_detail_kb(
        lang, view.product.id, view.in_stock, show_crypto=show_crypto, crypto_providers=crypto_providers
    )
    if view.product.image_file_id:
        await callback.message.delete()
        await callback.message.answer_photo(view.product.image_file_id, caption=text, reply_markup=kb)
    else:
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(ShopCB.filter(F.action == "buy"))
async def buy_product(callback: CallbackQuery, callback_data: ShopCB, session: AsyncSession, lang: str) -> None:
    products = ProductRepository(session)
    product = await products.get_by_id(callback_data.product_id)
    if product is None or not product.is_visible:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return
    if product.delivery_mode.value == "inventory":
        stock = await products.available_stock(product.id)
        if stock <= 0:
            await callback.answer(t(lang, "msg_out_of_stock"), show_alert=True)
            return

    settings_repo = SettingRepository(session)
    instructions = product.payment_instructions or await settings_repo.get(
        f"payment_instructions_{lang}"
    )
    text = t(
        lang,
        "msg_payment_header",
        instructions=instructions,
        order_uuid="—",
        product_name=product_name(product, lang),
        price=fmt_price(float(product.price)),
        currency=product.currency,
    )
    await callback.message.answer(text, reply_markup=payment_kb(lang, product.id))
    await callback.answer()


@router.callback_query(ShopCB.filter(F.action == "paid"))
async def mark_paid(
    callback: CallbackQuery,
    callback_data: ShopCB,
    session: AsyncSession,
    user: User,
    lang: str,
    state: FSMContext,
) -> None:
    order_service = OrderService(session)
    try:
        order = await order_service.start_purchase(user, callback_data.product_id)
    except (ProductUnavailableError, OutOfStockError) as exc:
        await callback.answer(exc.localized(lang), show_alert=True)
        return

    await state.set_state(PurchaseStates.waiting_screenshot)
    await state.update_data(order_id=order.id)
    await callback.message.answer(t(lang, "msg_send_screenshot"), reply_markup=cancel_kb(lang))
    await callback.answer()


@router.message(PurchaseStates.waiting_screenshot, F.photo)
async def receive_screenshot(message: Message, session: AsyncSession, lang: str, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("order_id")
    if not order_id:
        await state.clear()
        return

    file_id = message.photo[-1].file_id
    order_service = OrderService(session)
    try:
        order = await order_service.submit_payment_proof(order_id, file_id, instructions_snapshot=None)
    except InvalidOrderStateError as exc:
        await message.answer(exc.localized(lang))
        await state.clear()
        return

    # re-fetch with relations for the admin notification
    full_order = await OrderRepository(session).get_by_id(order.id)
    await notify_admins_new_order(message.bot, session, full_order, file_id)

    await message.answer(t(lang, "msg_order_sent_to_admin"), reply_markup=main_menu_kb(lang))
    await state.clear()


@router.message(PurchaseStates.waiting_screenshot)
async def reject_non_photo(message: Message, lang: str) -> None:
    await message.answer(t(lang, "msg_screenshot_required"))


@router.callback_query(CryptoCB.filter(F.action == "buy"))
async def crypto_buy(
    callback: CallbackQuery, callback_data: CryptoCB, session: AsyncSession, user: User, lang: str
) -> None:
    products = ProductRepository(session)
    product = await products.get_by_id(callback_data.product_id)
    if product is None or not product.is_visible or product.price_usd is None:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return
    if product.delivery_mode.value == "inventory":
        stock = await products.available_stock(product.id)
        if stock <= 0:
            await callback.answer(t(lang, "msg_out_of_stock"), show_alert=True)
            return

    settings_repo = SettingRepository(session)
    if not await settings_repo.get_bool("crypto_payment_enabled", False):
        await callback.answer(t(lang, "msg_crypto_disabled"), show_alert=True)
        return
    provider_key = callback_data.provider
    provider = get_crypto_provider(provider_key)
    if provider is None or not getattr(provider, "token", None):
        await callback.answer(t(lang, "msg_crypto_provider_not_configured"), show_alert=True)
        return

    orders = OrderRepository(session)
    order = await orders.create(
        user_id=user.id,
        product_id=product.id,
        price=float(product.price_usd),
        currency="USD",
        payment_method=PaymentMethod.CRYPTO,
        status=OrderStatus.AWAITING_CRYPTO_PAYMENT,
        crypto_provider=provider_key,
    )

    if product.delivery_mode.value == "inventory":
        # Reserve an actual code now (not just a count check) so it can't
        # also be promised to another customer while this crypto payment is
        # still unconfirmed.
        inventory = InventoryRepository(session)
        reserved = await inventory.reserve_one(product.id, order.id)
        if reserved is None:
            await orders.set_status(order, OrderStatus.CANCELLED)
            await callback.answer(t(lang, "msg_out_of_stock"), show_alert=True)
            return

    invoice = await provider.create_invoice(
        amount_usd=float(product.price_usd),
        description=f"{product_name(product, lang)} — {order.order_uuid}",
        payload=str(order.id),
    )
    if not invoice.success or not invoice.pay_url:
        await orders.set_status(order, OrderStatus.CANCELLED)
        if product.delivery_mode.value == "inventory":
            await InventoryRepository(session).release_reservation(order.id)
        await callback.answer(
            t(lang, "msg_crypto_invoice_failed", error=invoice.error or "unknown error"),
            show_alert=True,
        )
        return

    await orders.set_crypto_invoice(order, invoice.invoice_id, invoice.pay_url)

    await callback.message.answer(
        t(
            lang,
            "msg_crypto_payment_link",
            amount=f"{float(product.price_usd):.2f}",
            order_uuid=order.order_uuid,
        ),
        reply_markup=crypto_invoice_kb(lang, invoice.pay_url, order.id),
    )
    await callback.answer()


@router.callback_query(CryptoCB.filter(F.action == "cancel"))
async def crypto_cancel(callback: CallbackQuery, callback_data: CryptoCB, session: AsyncSession, lang: str) -> None:
    order_service = OrderService(session)
    order = await OrderRepository(session).get_by_id(callback_data.order_id)
    if order is None:
        await callback.answer(t(lang, "msg_order_not_found"), show_alert=True)
        return
    cancelled = await order_service.cancel_pending(callback_data.order_id)
    if not cancelled:
        # Already paid/confirmed/cancelled in the meantime — nothing to undo.
        await callback.answer(t(lang, "msg_crypto_already_processed"), show_alert=True)
        return
    await callback.message.edit_text(t(lang, "msg_crypto_cancelled_by_user", order_uuid=order.order_uuid))
    await callback.answer()


@router.callback_query(CryptoCB.filter(F.action == "check"))
async def crypto_check(callback: CallbackQuery, callback_data: CryptoCB, session: AsyncSession, lang: str) -> None:
    orders = OrderRepository(session)
    order = await orders.get_by_id(callback_data.order_id)
    if order is None:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return
    if order.status != OrderStatus.AWAITING_CRYPTO_PAYMENT:
        await callback.answer(t(lang, "msg_crypto_already_processed"), show_alert=True)
        return

    provider = get_crypto_provider(order.crypto_provider)
    if provider is None or not order.crypto_invoice_id:
        await callback.answer(t(lang, "msg_crypto_provider_not_found"), show_alert=True)
        return

    status = await provider.check_invoice(order.crypto_invoice_id)
    if not status.success:
        await callback.answer(
            t(lang, "msg_crypto_check_failed", error=status.error or "error"), show_alert=True
        )
        return
    if not status.paid:
        await callback.answer(t(lang, "msg_crypto_not_paid_yet"), show_alert=True)
        return

    from app.services.delivery_service import DeliveryService
    from app.services.exceptions import DeliveryFailedError

    delivery = DeliveryService(session)
    try:
        result = await delivery.auto_deliver_crypto(order.id)
    except (InvalidOrderStateError, DeliveryFailedError) as exc:
        await callback.answer(exc.localized(lang), show_alert=True)
        return

    if result.delivered_now and result.payload:
        await callback.message.answer(build_delivered_message(lang, order, result.payload))
    elif result.needs_manual_message:
        from app.services.crypto_poller import _notify_admins_with_manual_button

        await callback.message.answer(t(lang, "msg_crypto_confirmed_manual_pending"))
        await _notify_admins_with_manual_button(
            callback.bot, session, order.id, order.order_uuid, order.product.name
        )
    await callback.answer(t(lang, "msg_crypto_payment_confirmed_alert"))
