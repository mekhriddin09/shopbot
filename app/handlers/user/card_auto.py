"""Customer side of the automatic card payment flow.

The customer is shown a unique amount to transfer; the bot recognises the
bank alert for that exact amount and completes the order. See
app/services/card_payment/ for the matching engine and
app/handlers/business.py for where the alerts arrive.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.models.enums import OrderStatus, PaymentMethod
from app.keyboards.callback_data import CardAutoCB
from app.keyboards.user_kb import card_auto_waiting_kb
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.setting_repo import SettingRepository
from app.services.card_payment.service import CardPaymentService
from app.services.exceptions import OutOfStockError, ProductUnavailableError
from app.services.order_service import OrderService
from app.states.user_states import PurchaseStates
from app.utils.formatting import fmt_price, product_name
from app.utils.i18n import t

router = Router(name="user_card_auto")
logger = logging.getLogger("card_payment")


def _fmt_deadline(order) -> str:
    return order.payment_expires_at.strftime("%H:%M") if order.payment_expires_at else "-"


async def _payment_text(session: AsyncSession, order, lang: str) -> str:
    """The whole payment guide is generated, not hand-written: the card
    number, holder, exact amount and deadline are pulled from live data, so
    they can never go stale the way a manually-typed instruction block
    does. The admin only supplies the card details (Settings -> Payments)
    and, optionally, one extra sentence per language."""
    settings_repo = SettingRepository(session)

    card_number = (await settings_repo.get("card_auto_number", "")).strip()
    card_holder = (await settings_repo.get("card_auto_holder", "")).strip()
    if card_number:
        card_block = t(
            lang,
            "msg_card_auto_card_block",
            card_number=card_number,
            card_holder=card_holder or "-",
        )
    else:
        # No card configured yet — fall back to whatever free-text payment
        # details the shop already uses, so the flow still works.
        card_block = (
            order.product.payment_instructions
            or await settings_repo.get(f"payment_instructions_{lang}")
            or await settings_repo.get("payment_instructions_en")
            or ""
        ) + "\n"

    note = (await settings_repo.get(f"card_auto_note_{lang}", "")).strip()
    note_block = f"\n\n{note}" if note else ""

    minutes = await CardPaymentService(session).timeout_minutes()
    return t(
        lang,
        "msg_card_auto_payment",
        card_block=card_block,
        note_block=note_block,
        amount=fmt_price(float(order.expected_amount)),
        currency=order.currency,
        product_name=product_name(order.product, lang),
        order_uuid=order.order_uuid,
        deadline=_fmt_deadline(order),
        minutes=minutes,
    )


async def start_card_auto_purchase(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    lang: str,
    product_id: int,
    quantity: int = 1,
    state: FSMContext | None = None,
) -> None:
    """Create the order and issue its unique amount. Shared by the plain
    buy button and the quantity-selector flow."""
    product = await ProductRepository(session).get_by_id(product_id)
    if product is None or not product.is_visible or not product.card_auto_enabled:
        await callback.answer(t(lang, "msg_product_unavailable"), show_alert=True)
        return
    if not await SettingRepository(session).get_bool("card_payment_enabled", False):
        await callback.answer(t(lang, "msg_card_auto_disabled"), show_alert=True)
        return

    card_service = CardPaymentService(session)
    total_price = float(product.price) * max(1, quantity)
    amount = await card_service.generate_unique_amount(total_price)
    if amount is None:
        # Every amount in the discount band is currently spoken for. Issuing
        # a duplicate would make two orders indistinguishable to the
        # matcher, so refuse rather than risk delivering to the wrong buyer.
        logger.error("card_auto_band_exhausted product=%s price=%s", product_id, total_price)
        await callback.answer(t(lang, "msg_card_auto_busy"), show_alert=True)
        return

    try:
        order = await OrderService(session).start_purchase(
            user, product_id, quantity=quantity, status=OrderStatus.AWAITING_CARD_PAYMENT
        )
    except (ProductUnavailableError, OutOfStockError) as exc:
        await callback.answer(exc.localized(lang), show_alert=True)
        return

    if state is not None:
        # Stars/Premium: remember who the goods are for while the order is
        # still unpaid, so delivery and the admin card agree later.
        from app.handlers.user.recipient import attach_recipient

        await attach_recipient(session, order, state)

    order.payment_method = PaymentMethod.CARD_AUTO
    order.expected_amount = amount
    order.payment_expires_at = await card_service.expires_at()
    await session.commit()

    full_order = await OrderRepository(session).get_by_id(order.id)
    await callback.message.answer(
        await _payment_text(session, full_order, lang),
        reply_markup=card_auto_waiting_kb(lang, order.id),
    )
    await callback.answer()


@router.callback_query(CardAutoCB.filter(F.action == "buy"))
async def card_auto_buy(
    callback: CallbackQuery,
    callback_data: CardAutoCB,
    session: AsyncSession,
    user: User,
    lang: str,
    state: FSMContext,
) -> None:
    await start_card_auto_purchase(
        callback, session, user, lang, callback_data.product_id, quantity=1, state=state
    )


@router.callback_query(CardAutoCB.filter(F.action == "paid"))
async def card_auto_paid(
    callback: CallbackQuery, callback_data: CardAutoCB, session: AsyncSession, user: User, lang: str
) -> None:
    """Purely an acknowledgement — matching happens automatically whether
    or not this is pressed. Its real value is revealing the "not detected?"
    escape hatch straight away."""
    order = await OrderRepository(session).get_by_id(callback_data.order_id)
    if order is None or order.user_id != user.id:
        await callback.answer(t(lang, "msg_order_not_found"), show_alert=True)
        return
    if order.status != OrderStatus.AWAITING_CARD_PAYMENT:
        await callback.answer(t(lang, "msg_order_already_processed"), show_alert=True)
        return

    try:
        await callback.message.edit_text(
            t(lang, "msg_card_auto_waiting", amount=fmt_price(float(order.expected_amount)), currency=order.currency),
            reply_markup=card_auto_waiting_kb(lang, order.id, paid_pressed=True),
        )
    except Exception:  # noqa: BLE001 - best effort
        pass
    await callback.answer()


@router.callback_query(CardAutoCB.filter(F.action == "cancel"))
async def card_auto_cancel(
    callback: CallbackQuery, callback_data: CardAutoCB, session: AsyncSession, user: User, lang: str
) -> None:
    order = await OrderRepository(session).get_by_id(callback_data.order_id)
    if order is None or order.user_id != user.id:
        await callback.answer(t(lang, "msg_order_not_found"), show_alert=True)
        return
    if order.status != OrderStatus.AWAITING_CARD_PAYMENT:
        await callback.answer(t(lang, "msg_order_already_processed"), show_alert=True)
        return

    await OrderService(session).cancel_pending(order.id)
    try:
        await callback.message.edit_text(
            t(lang, "msg_card_auto_cancelled", order_uuid=order.order_uuid), reply_markup=None
        )
    except Exception:  # noqa: BLE001 - best effort
        pass
    await callback.answer()


@router.callback_query(CardAutoCB.filter(F.action == "manual"))
async def card_auto_switch_to_manual(
    callback: CallbackQuery,
    callback_data: CardAutoCB,
    session: AsyncSession,
    user: User,
    lang: str,
    state: FSMContext,
) -> None:
    """"I did pay / it wasn't detected" — hand the order over to the existing
    receipt-review flow instead of leaving the customer stuck."""
    order = await OrderRepository(session).get_by_id(callback_data.order_id)
    if order is None or order.user_id != user.id:
        await callback.answer(t(lang, "msg_order_not_found"), show_alert=True)
        return
    if order.status not in (OrderStatus.AWAITING_CARD_PAYMENT, OrderStatus.CANCELLED):
        await callback.answer(t(lang, "msg_order_already_processed"), show_alert=True)
        return

    # Free the reserved amount so it can be reissued to someone else, but
    # keep the order alive under the manual (proof) flow.
    await OrderRepository(session).set_status(order, OrderStatus.AWAITING_PROOF)
    order.expected_amount = None
    order.payment_expires_at = None
    order.payment_method = PaymentMethod.CARD
    await session.commit()

    await state.set_state(PurchaseStates.waiting_screenshot)
    await state.update_data(order_id=order.id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001 - best effort
        pass
    await callback.message.answer(t(lang, "msg_card_auto_send_receipt"))
    await callback.answer()


__all__ = ["router", "start_card_auto_purchase"]
