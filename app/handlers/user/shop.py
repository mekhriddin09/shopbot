from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Product, User
from app.database.models.enums import OrderStatus, PaymentMethod
from app.keyboards.callback_data import CryptoCB, QtyCB, RecipientCB, ShopCB, StockNotifyCB
from app.keyboards.user_kb import (
    buy_again_kb,
    cancel_kb,
    crypto_invoice_kb,
    main_menu_kb,
    payment_kb,
    product_detail_kb,
    qty_picker_kb,
    shop_list_kb,
)
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.setting_repo import SettingRepository
from app.repositories.stock_waiter_repo import StockWaiterRepository
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
from app.utils import shopscreen
from app.utils.button_filters import menu_button_filter
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


@router.message(menu_button_filter("menu_shop"))
async def open_shop(
    message: Message, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    service = ProductService(session)
    views = await service.list_shop()
    if not views:
        await message.answer(t(lang, "msg_shop_empty"))
        return
    # Opening the shop starts a fresh screen; everything after this edits it.
    sent = await message.answer(
        t(lang, "main_menu_hint"), reply_markup=shop_list_kb([v.product for v in views], lang)
    )
    await shopscreen.remember(state, sent)


@router.callback_query(StockNotifyCB.filter(F.action == "subscribe"))
async def stock_notify_subscribe(
    callback: CallbackQuery, callback_data: StockNotifyCB, session: AsyncSession, user: User, lang: str
) -> None:
    product = await ProductRepository(session).get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return
    await StockWaiterRepository(session).subscribe(user.id, product.id)
    await callback.answer(t(lang, "msg_stock_notify_subscribed"), show_alert=True)


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

    # `state.clear()` above wiped the screen coordinates, so re-anchor on
    # the message this tap came from before redrawing it.
    await shopscreen.remember(state, callback.message, is_photo=callback.message.text is None)
    await shopscreen.render(callback.bot, state, callback.message.chat.id, text, kb)
    await callback.answer()


async def build_product_card(
    session: AsyncSession,
    product_id: int,
    lang: str,
    recipient: str | None = None,
    stars_amount: int | None = None,
    recipient_name: str | None = None,
) -> tuple[str, object, str | None] | None:
    """Text + keyboard + photo for a product card.

    Split out of `open_product` so the recipient flow (Stars/Premium) can
    re-render the same card once it knows who the goods are for, instead of
    duplicating the payment-button logic.

    Returns None when the product is gone or hidden.
    """
    view = await ProductService(session).get_view(product_id)
    if view is None or not view.product.is_visible:
        return None

    settings_repo = SettingRepository(session)
    crypto_enabled = await settings_repo.get_bool("crypto_payment_enabled", False)
    crypto_providers = available_crypto_providers() if crypto_enabled and view.product.price_usd is not None else []
    show_crypto = bool(crypto_providers)
    stars_enabled = await settings_repo.get_bool("stars_payment_enabled", False)
    show_stars = stars_enabled and view.product.price_stars is not None

    card_auto_enabled = (
        view.product.card_auto_enabled
        and await settings_repo.get_bool("card_payment_enabled", False)
    )

    preorder_enabled = not view.in_stock and await settings_repo.get_bool("preorder_enabled", False)
    show_notify = not view.in_stock and not preorder_enabled

    # Custom-amount Stars: ask "how many" *before* "for whom" — verifying a
    # recipient is pointless while the order size isn't even decided yet,
    # and it puts one question on screen at a time instead of two. Once the
    # amount is known, the long description is just noise for the rest of
    # this purchase (recipient prompt, payment screen), so it's replaced by
    # a compact "size + total" line that stays through to checkout.
    from app.services.providers.fragment import is_custom_stars

    custom = is_custom_stars(view.product.external_product_id)

    if custom and not stars_amount:
        from app.keyboards.user_kb import custom_stars_kb

        unit = float(view.product.price)
        text = _product_card_text(lang, view.product, view.stock)
        if show_crypto:
            text += "\n" + t(lang, "msg_crypto_price_label", price=f"{float(view.product.price_usd):.2f}")
        if show_stars:
            text += "\n" + t(lang, "msg_stars_price_label", price=view.product.price_stars)
        text += "\n" + t(lang, "msg_custom_stars_unit", price=fmt_price(unit), currency=view.product.currency)
        text += "\n\n" + t(lang, "msg_custom_stars_prompt")
        return text, custom_stars_kb(lang, view.product.id), view.product.image_file_id

    if custom:
        total = float(view.product.price) * stars_amount
        text = t(
            lang,
            "msg_custom_stars_compact",
            emoji=view.product.emoji,
            name=product_name(view.product, lang),
            amount=stars_amount,
            total=fmt_price(total),
            currency=view.product.currency,
        )
    else:
        text = _product_card_text(lang, view.product, view.stock)
        if show_crypto:
            text += "\n" + t(lang, "msg_crypto_price_label", price=f"{float(view.product.price_usd):.2f}")
        if show_stars:
            text += "\n" + t(lang, "msg_stars_price_label", price=view.product.price_stars)

    # Goods that are delivered to a Telegram username (Stars, Premium) must
    # not reach the payment buttons until we know the recipient — see
    # handlers/user/recipient.py for why this is asked before payment.
    from app.handlers.user.recipient import product_requires_recipient

    if await product_requires_recipient(view.product) and not recipient:
        from app.keyboards.user_kb import recipient_choice_kb

        text += "\n\n" + t(lang, "msg_recipient_choose")
        return text, recipient_choice_kb(lang, view.product.id), view.product.image_file_id

    kb = product_detail_kb(
        lang,
        view.product.id,
        view.in_stock,
        show_crypto=show_crypto,
        crypto_providers=crypto_providers,
        show_stars=show_stars,
        max_order_qty=view.product.max_order_qty,
        show_notify_button=show_notify,
        show_preorder_button=preorder_enabled,
        show_card_auto=card_auto_enabled,
        fixed_qty=stars_amount if custom else None,
        show_card_manual=bool(getattr(view.product, "card_manual_enabled", True)),
    )
    if recipient:
        # The whole confirmation, inline: who Fragment resolved, not merely
        # the text that was typed. This is why the flow no longer needs a
        # separate "is this right?" screen.
        text += "\n\n" + t(lang, "msg_recipient_selected", username=recipient)
        if recipient_name:
            text += f" — <b>{recipient_name}</b>"
        text += "\n" + t(lang, "msg_recipient_warning")
        rows = list(kb.inline_keyboard)
        rows.insert(
            0,
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_recipient_change"),
                    callback_data=RecipientCB(action="change", product_id=view.product.id).pack(),
                )
            ],
        )
        kb = InlineKeyboardMarkup(inline_keyboard=rows)

    return text, kb, view.product.image_file_id


async def render_product_card(
    target: Message,
    session: AsyncSession,
    product_id: int,
    lang: str,
    recipient: str | None = None,
    stars_amount: int | None = None,
    recipient_name: str | None = None,
    state: FSMContext | None = None,
) -> None:
    """Draw the product card on the customer's single shop screen."""
    built = await build_product_card(
        session, product_id, lang, recipient, stars_amount, recipient_name
    )
    if built is None:
        await target.answer(t(lang, "msg_product_not_found"))
        return
    text, kb, image_file_id = built
    if state is not None:
        await shopscreen.render(
            target.bot, state, target.chat.id, text, kb, photo_id=image_file_id
        )
        return
    if image_file_id:
        await target.answer_photo(image_file_id, caption=text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(ShopCB.filter(F.action == "open"))
async def open_product(
    callback: CallbackQuery,
    callback_data: ShopCB,
    session: AsyncSession,
    lang: str,
    state: FSMContext,
) -> None:
    from app.handlers.user.recipient import (
        forget_recipient_choice,
        get_chosen_recipient,
        get_chosen_stars_amount,
        get_recipient_name,
    )

    if callback_data.fresh:
        # A genuinely fresh look at the product (shop list, "buy again") —
        # not the qty-picker/payment "back" buttons, which reopen the same
        # product mid-purchase via this same handler with fresh=False and
        # must keep whatever was just entered.
        await forget_recipient_choice(state)

    built = await build_product_card(
        session,
        callback_data.product_id,
        lang,
        await get_chosen_recipient(state),
        await get_chosen_stars_amount(state, callback_data.product_id),
        await get_recipient_name(state),
    )
    if built is None:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return
    text, kb, image_file_id = built
    # The message the tap came from IS the screen — remember it, then let
    # the renderer decide between editing and replacing (a photo card and a
    # text card cannot be edited into one another).
    await shopscreen.remember(state, callback.message, is_photo=callback.message.text is None)
    await shopscreen.render(
        callback.bot, state, callback.message.chat.id, text, kb, photo_id=image_file_id
    )
    await callback.answer()


async def _show_card_payment_instructions(
    callback: CallbackQuery,
    session: AsyncSession,
    product: Product,
    lang: str,
    qty: int,
    preorder: bool = False,
    state: FSMContext | None = None,
) -> None:
    settings_repo = SettingRepository(session)
    instructions = product.payment_instructions or await settings_repo.get(
        f"payment_instructions_{lang}"
    )
    total_price = float(product.price) * qty
    name = product_name(product, lang) + (f" × {qty}" if qty > 1 else "")
    key = "msg_preorder_payment_header" if preorder else "msg_payment_header"
    text = t(
        lang,
        key,
        instructions=instructions,
        order_uuid="—",
        product_name=name,
        price=fmt_price(total_price),
        currency=product.currency,
    )
    kb = payment_kb(lang, product.id, qty=qty, preorder=preorder)
    if state is not None:
        await shopscreen.render(callback.bot, state, callback.message.chat.id, text, kb)
    else:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(ShopCB.filter(F.action == "buy"))
async def buy_product(
    callback: CallbackQuery,
    callback_data: ShopCB,
    session: AsyncSession,
    lang: str,
    state: FSMContext,
) -> None:
    products = ProductRepository(session)
    product = await products.get_by_id(callback_data.product_id)
    if product is None or not product.is_visible:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return
    if not callback_data.preorder and await ProductService(session).stock_shortfall(product):
        await callback.answer(t(lang, "msg_out_of_stock"), show_alert=True)
        return
    await _show_card_payment_instructions(
        callback, session, product, lang, qty=1, preorder=callback_data.preorder, state=state
    )


@router.callback_query(QtyCB.filter(F.action == "show"))
async def qty_show(callback: CallbackQuery, callback_data: QtyCB, session: AsyncSession, lang: str) -> None:
    product = await ProductRepository(session).get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return
    await callback.message.edit_reply_markup(
        reply_markup=qty_picker_kb(
            lang, product.id, product.min_order_qty, product.min_order_qty, product.max_order_qty,
            callback_data.flow, callback_data.provider or "",
        )
    )
    await callback.answer()


@router.callback_query(QtyCB.filter(F.action.in_({"inc", "dec", "set"})))
async def qty_change(callback: CallbackQuery, callback_data: QtyCB, session: AsyncSession, lang: str) -> None:
    product = await ProductRepository(session).get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return
    qty = max(product.min_order_qty, min(product.max_order_qty, callback_data.qty))
    try:
        await callback.message.edit_reply_markup(
            reply_markup=qty_picker_kb(
                lang, product.id, qty, product.min_order_qty, product.max_order_qty,
                callback_data.flow, callback_data.provider or "",
            )
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
    await callback.answer()


@router.callback_query(QtyCB.filter(F.action == "noop"))
async def qty_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(QtyCB.filter(F.action == "confirm"))
async def qty_confirm(
    callback: CallbackQuery,
    callback_data: QtyCB,
    session: AsyncSession,
    user: User,
    lang: str,
    state: FSMContext,
) -> None:
    products = ProductRepository(session)
    product = await products.get_by_id(callback_data.product_id)
    if product is None or not product.is_visible:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return
    qty = max(product.min_order_qty, min(product.max_order_qty, callback_data.qty))
    if await ProductService(session).stock_shortfall(product, qty):
        await callback.answer(t(lang, "msg_out_of_stock"), show_alert=True)
        return

    if callback_data.flow == "crypto":
        await _start_crypto_purchase(
            callback, session, user, lang, product, callback_data.provider or "", qty, state=state
        )
    elif callback_data.flow == "stars":
        from app.handlers.user.stars import start_stars_purchase

        await start_stars_purchase(callback, session, user, lang, product, qty, state=state)
    elif callback_data.flow == "cardauto":
        from app.handlers.user.card_auto import start_card_auto_purchase

        await start_card_auto_purchase(callback, session, user, lang, product.id, qty, state=state)
    else:
        await _show_card_payment_instructions(callback, session, product, lang, qty, state=state)


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
        if callback_data.preorder:
            order = await order_service.start_preorder(user, callback_data.product_id)
        else:
            order = await order_service.start_purchase(user, callback_data.product_id, quantity=callback_data.qty)
    except (ProductUnavailableError, OutOfStockError) as exc:
        await callback.answer(exc.localized(lang), show_alert=True)
        return

    from app.handlers.user.recipient import attach_recipient

    await attach_recipient(session, order, state)

    await state.set_state(PurchaseStates.waiting_screenshot)
    await state.update_data(order_id=order.id)
    await shopscreen.render(
        callback.bot, state, callback.message.chat.id, t(lang, "msg_send_screenshot"), cancel_kb(lang)
    )
    await callback.answer()


@router.message(PurchaseStates.waiting_screenshot, F.photo | F.document)
async def receive_screenshot(message: Message, session: AsyncSession, lang: str, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("order_id")
    if not order_id:
        await state.clear()
        return

    # Accept a native Telegram photo OR any uploaded file (png/jpg sent as
    # a "file" instead of compressed photo, pdf, docx, ...) — some bank
    # apps export receipts as PDF/DOCX rather than a screenshot, and some
    # users deliberately send images as files to avoid Telegram's photo
    # compression. Whichever it is, the exact same file_id gets stored and
    # forwarded on to the admin (see notify_admins_new_order's is_document).
    is_document = message.document is not None
    file_id = message.document.file_id if is_document else message.photo[-1].file_id

    order_service = OrderService(session)
    try:
        order = await order_service.submit_payment_proof(order_id, file_id, instructions_snapshot=None)
    except InvalidOrderStateError as exc:
        await message.answer(exc.localized(lang))
        await state.clear()
        return

    # re-fetch with relations for the admin notification
    full_order = await OrderRepository(session).get_by_id(order.id)
    await notify_admins_new_order(message.bot, session, full_order, file_id, is_document=is_document)

    await message.answer(t(lang, "msg_order_sent_to_admin"), reply_markup=main_menu_kb(lang))
    await state.clear()


@router.message(PurchaseStates.waiting_screenshot)
async def reject_non_photo(message: Message, lang: str) -> None:
    await message.answer(t(lang, "msg_screenshot_required"))


async def _start_crypto_purchase(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    lang: str,
    product: Product,
    provider_key: str,
    qty: int,
    preorder: bool = False,
    state: FSMContext | None = None,
) -> None:
    settings_repo = SettingRepository(session)
    if not await settings_repo.get_bool("crypto_payment_enabled", False):
        await callback.answer(t(lang, "msg_crypto_disabled"), show_alert=True)
        return
    provider = get_crypto_provider(provider_key)
    if provider is None or not getattr(provider, "token", None):
        await callback.answer(t(lang, "msg_crypto_provider_not_configured"), show_alert=True)
        return

    total_usd = float(product.price_usd) * qty
    orders = OrderRepository(session)
    order = await orders.create(
        user_id=user.id,
        product_id=product.id,
        price=total_usd,
        currency="USD",
        payment_method=PaymentMethod.CRYPTO,
        status=OrderStatus.AWAITING_CRYPTO_PAYMENT,
        crypto_provider=provider_key,
        quantity=qty,
        is_preorder=preorder,
    )

    if state is not None:
        from app.handlers.user.recipient import attach_recipient

        await attach_recipient(session, order, state)

    if not preorder and product.delivery_mode.value == "inventory":
        # Reserve the actual code(s) now (not just a count check) so they
        # can't also be promised to another customer while this crypto
        # payment is still unconfirmed. Skipped entirely for pre-orders —
        # there's no stock to reserve yet.
        inventory = InventoryRepository(session)
        reserved = await inventory.reserve_many(product.id, order.id, qty)
        if reserved is None:
            await orders.set_status(order, OrderStatus.CANCELLED)
            await callback.answer(t(lang, "msg_out_of_stock"), show_alert=True)
            return

    description = (
        product_name(product, lang)
        + (f" × {qty}" if qty > 1 else "")
        + (" (pre-order)" if preorder else "")
        + f" — {order.order_uuid}"
    )
    invoice = await provider.create_invoice(
        amount_usd=total_usd,
        description=description,
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
        t(lang, "msg_crypto_payment_link", amount=f"{total_usd:.2f}", order_uuid=order.order_uuid),
        reply_markup=crypto_invoice_kb(lang, invoice.pay_url, order.id),
    )
    await callback.answer()


@router.callback_query(CryptoCB.filter(F.action == "buy"))
async def crypto_buy(
    callback: CallbackQuery,
    callback_data: CryptoCB,
    session: AsyncSession,
    user: User,
    lang: str,
    state: FSMContext,
) -> None:
    products = ProductRepository(session)
    product = await products.get_by_id(callback_data.product_id)
    if product is None or not product.is_visible or product.price_usd is None:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return
    if not callback_data.preorder and await ProductService(session).stock_shortfall(product):
        await callback.answer(t(lang, "msg_out_of_stock"), show_alert=True)
        return
    await _start_crypto_purchase(
        callback,
        session,
        user,
        lang,
        product,
        callback_data.provider or "",
        qty=1,
        preorder=callback_data.preorder,
        state=state,
    )


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
        await callback.message.answer(
            build_delivered_message(lang, order, result.payload),
            reply_markup=buy_again_kb(lang, order.product_id),
        )
        from app.services.referral_service import ReferralService

        await ReferralService(session).credit_for_delivered_order(order, callback.bot)
    elif result.needs_manual_message:
        from app.services.crypto_poller import _notify_admins_with_manual_button

        await callback.message.answer(t(lang, "msg_crypto_confirmed_manual_pending"))
        await _notify_admins_with_manual_button(
            callback.bot, session, order.id, order.order_uuid, order.product.name
        )
    await callback.answer(t(lang, "msg_crypto_payment_confirmed_alert"))
