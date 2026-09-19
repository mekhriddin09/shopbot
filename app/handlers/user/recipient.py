"""Collecting the @username that Stars / Premium must be delivered to.

Runs *before* payment, deliberately. These goods go straight to a Telegram
username at the supplier's end, and the supplier will simply reject an
unknown handle — discovering that after the customer has paid means a
refund and an unhappy customer, so the username is asked for and verified
up front.

The chosen recipient lives in FSM data until an order exists, then gets
copied onto the order (`attach_recipient`) so delivery, the admin card and
any later dispute all agree on who it was for.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.keyboards.callback_data import RecipientCB
from app.keyboards.user_kb import recipient_choice_kb
from app.repositories.product_repo import ProductRepository
from app.services.providers.fragment import normalize_username
from app.services.providers.registry import get_provider
from app.states.user_states import RecipientStates
from app.utils import shopscreen
from app.utils.i18n import t

router = Router(name="user_recipient")
logger = logging.getLogger("orders")

_FSM_KEY = "recipient_username"
_NAME_KEY = "recipient_name"
_AMOUNT_KEY = "stars_amount"
_AMOUNT_PRODUCT_KEY = "stars_amount_product_id"

# Telegram's own floor; Fragment rejects anything smaller.
MIN_STARS = 50


async def product_requires_recipient(product) -> bool:
    """Whether this product's supplier delivers to a username."""
    from app.database.models.enums import DeliveryMode

    if product is None or product.delivery_mode != DeliveryMode.API:
        return False
    provider = get_provider(product.provider_key)
    return bool(provider and provider.requires_recipient)


async def get_chosen_recipient(state: FSMContext) -> str | None:
    data = await state.get_data()
    return data.get(_FSM_KEY)


async def get_recipient_name(state: FSMContext) -> str | None:
    """Display name Fragment resolved for the chosen handle, shown on the
    payment screen so a typo is still caught before any money moves."""
    data = await state.get_data()
    return (data.get(_NAME_KEY) or "").strip() or None


async def get_chosen_stars_amount(state: FSMContext, product_id: int | None = None) -> int | None:
    """The custom Stars amount, but only for the product it was entered for
    — otherwise browsing to another product would inherit a stale number."""
    data = await state.get_data()
    amount = data.get(_AMOUNT_KEY)
    if not amount:
        return None
    if product_id is not None and data.get(_AMOUNT_PRODUCT_KEY) != product_id:
        return None
    return int(amount)


async def forget_recipient_choice(state: FSMContext) -> None:
    """Wipe whatever recipient/amount was picked for a previous purchase.

    Recipient and amount used to live in FSM data with no product tag, so
    buying Stars for @friend once meant every product card ever opened
    afterwards silently pre-filled @friend as the recipient — a real risk
    of paying for the wrong person by mistake if the customer is in a
    hurry. Called from a genuinely fresh product open (shop list tap, "buy
    again") so each visit starts clean; the qty-picker/payment "back"
    buttons deliberately don't call this, since those reopen the same
    product mid-purchase and must keep what was just entered.
    """
    await state.update_data(
        **{
            _FSM_KEY: None,
            _NAME_KEY: None,
            _AMOUNT_KEY: None,
            _AMOUNT_PRODUCT_KEY: None,
        }
    )


async def attach_recipient(session: AsyncSession, order, state: FSMContext) -> None:
    """Copy the verified recipient from FSM onto the order. Called by every
    payment flow right after the order row is created."""
    handle = await get_chosen_recipient(state)
    if handle and getattr(order, "recipient_username", None) != handle:
        order.recipient_username = handle
        await session.commit()


async def _screen(target, state: FSMContext, text: str, reply_markup=None) -> None:
    """Put a prompt or an error on the customer's single shop screen."""
    chat_id = target.chat.id if hasattr(target, "chat") else target.message.chat.id
    bot = target.bot if hasattr(target, "bot") else target.message.bot
    await shopscreen.render(bot, state, chat_id, text, reply_markup)


async def _verify_and_store(
    target, session: AsyncSession, state: FSMContext, lang: str, product, raw_username: str
) -> bool:
    """Normalise, ask the supplier who that handle actually is, and store it.

    There is deliberately no separate "is this right?" screen. The check it
    provided — seeing *who* Fragment resolved, not just the text typed — now
    lives on the payment screen itself, where the customer reads it anyway
    before paying. Same protection against a mistyped handle, one tap fewer:
    with a confirm step the flow ran product → who → type → confirm → amount
    → confirm → pay, and people abandoned it halfway.
    """
    handle = normalize_username(raw_username)
    if not handle:
        await _screen(target, state, t(lang, "msg_recipient_invalid"))
        return False

    display = None
    provider = get_provider(product.provider_key)
    if provider is not None:
        ok, note = await provider.search_recipient(handle)
        if not ok:
            await _screen(
                target, state, t(lang, "msg_recipient_not_found", username=handle, reason=note or "-")
            )
            return False
        display = note

    await state.update_data(**{_FSM_KEY: handle, _NAME_KEY: display or ""})
    logger.info("recipient_chosen product=%s handle=%s", product.id, handle)
    return True


async def _show_payment_options(
    target, session: AsyncSession, product_id: int, lang: str, state: FSMContext
) -> None:
    """Re-render the product card now that the recipient (and, for
    custom-amount products, the quantity) is known.

    Passing them through is what makes the card move on: `build_product_card`
    re-applies the same gate it used to show the "who is it for?" buttons, so
    omitting the recipient here just redraws that question forever.
    """
    from app.handlers.user.shop import render_product_card

    await render_product_card(
        target,
        session,
        product_id,
        lang,
        await get_chosen_recipient(state),
        await get_chosen_stars_amount(state, product_id),
        await get_recipient_name(state),
        state=state,
    )


@router.callback_query(RecipientCB.filter(F.action == "myself"))
async def recipient_myself(
    callback: CallbackQuery,
    callback_data: RecipientCB,
    session: AsyncSession,
    user: User,
    lang: str,
    state: FSMContext,
) -> None:
    product = await ProductRepository(session).get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return

    if not user.username:
        # Telegram accounts without a public username can't receive these
        # goods at all — say so instead of failing later at the supplier.
        await _screen(callback.message, state, t(lang, "msg_recipient_no_username"))
        await state.set_state(None)
        await callback.answer()
        return

    if await _verify_and_store(callback.message, session, state, lang, product, user.username):
        await _show_payment_options(callback.message, session, product.id, lang, state)
    await callback.answer()


@router.callback_query(RecipientCB.filter(F.action == "other"))
async def recipient_other(
    callback: CallbackQuery, callback_data: RecipientCB, lang: str, state: FSMContext
) -> None:
    await state.set_state(RecipientStates.waiting_username)
    await state.update_data(recipient_product_id=callback_data.product_id)
    await _screen(callback.message, state, t(lang, "msg_recipient_ask"))
    await callback.answer()


@router.callback_query(RecipientCB.filter(F.action == "amount"))
async def custom_stars_amount_prompt(
    callback: CallbackQuery,
    callback_data: RecipientCB,
    session: AsyncSession,
    lang: str,
    state: FSMContext,
) -> None:
    product = await ProductRepository(session).get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return
    minimum = max(MIN_STARS, product.min_order_qty or 0)
    maximum = product.max_order_qty if (product.max_order_qty or 0) > minimum else 1_000_000
    await state.set_state(RecipientStates.waiting_stars_amount)
    await state.update_data(**{_AMOUNT_PRODUCT_KEY: product.id})
    await _screen(
        callback.message, state, t(lang, "msg_custom_stars_ask", minimum=minimum, maximum=maximum)
    )
    await callback.answer()


@router.message(RecipientStates.waiting_stars_amount, F.text)
async def custom_stars_amount_received(
    message: Message, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    data = await state.get_data()
    product = await ProductRepository(session).get_by_id(data.get(_AMOUNT_PRODUCT_KEY) or 0)
    if product is None:
        await state.set_state(None)
        await shopscreen.delete_input(message)
        await _screen(message, state, t(lang, "msg_product_not_found"))
        return

    raw = (message.text or "").strip().replace(" ", "").replace(",", "")
    if not raw.isdigit():
        await shopscreen.delete_input(message)
        await _screen(message, state, t(lang, "msg_custom_stars_invalid"))
        return
    amount = int(raw)
    minimum = max(MIN_STARS, product.min_order_qty or 0)
    maximum = product.max_order_qty if (product.max_order_qty or 0) > minimum else 1_000_000
    if not (minimum <= amount <= maximum):
        await shopscreen.delete_input(message)
        await _screen(message, state, t(lang, "msg_custom_stars_range", minimum=minimum, maximum=maximum))
        return

    await state.update_data(**{_AMOUNT_KEY: amount, _AMOUNT_PRODUCT_KEY: product.id})
    await state.set_state(None)
    logger.info("custom_stars_amount product=%s amount=%s", product.id, amount)
    await shopscreen.delete_input(message)
    await _show_payment_options(message, session, product.id, lang, state)


@router.callback_query(RecipientCB.filter(F.action == "change"))
async def recipient_change(
    callback: CallbackQuery, callback_data: RecipientCB, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    await state.update_data(**{_FSM_KEY: None, _NAME_KEY: None})
    product = await ProductRepository(session).get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer(t(lang, "msg_product_not_found"), show_alert=True)
        return
    await _screen(
        callback.message, state, t(lang, "msg_recipient_choose"), recipient_choice_kb(lang, product.id)
    )
    await callback.answer()


@router.message(RecipientStates.waiting_username, F.text)
async def recipient_username_received(
    message: Message, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    """Only active while RecipientStates.waiting_username is set — the
    state filter is applied at registration time below."""
    data = await state.get_data()
    product_id = data.get("recipient_product_id")
    product = await ProductRepository(session).get_by_id(product_id) if product_id else None
    if product is None:
        await state.set_state(None)
        await shopscreen.delete_input(message)
        await _screen(message, state, t(lang, "msg_product_not_found"))
        return

    if await _verify_and_store(message, session, state, lang, product, message.text):
        await state.set_state(None)
        await shopscreen.delete_input(message)
        await _show_payment_options(message, session, product.id, lang, state)


__all__ = [
    "router",
    "attach_recipient",
    "forget_recipient_choice",
    "get_chosen_recipient",
    "get_chosen_stars_amount",
    "get_recipient_name",
    "product_requires_recipient",
]
