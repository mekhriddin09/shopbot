from __future__ import annotations

import logging
from html import escape as html_escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enums import DeliveryMode, OrderStatus
from app.filters.is_admin import IsAdmin
from aiogram.types import InlineKeyboardMarkup
from app.keyboards.base_buttons import InlineKeyboardButton
from app.keyboards.admin_kb import (
    admin_order_detail_kb,
    admin_orders_list_kb,
    admin_orders_menu_kb,
    admin_retry_all_kb,
    admin_write_manual_kb,
)
from app.utils.screen import answer_and_show, show
from app.keyboards.user_kb import buy_again_kb
from app.keyboards.callback_data import AdminOrderListCB, OrderCB
from app.repositories.order_repo import OrderRepository
from app.services.delivery_service import DeliveryService
from app.services.exceptions import DeliveryFailedError, InvalidOrderStateError
from app.services.referral_service import ReferralService
from app.repositories.card_transaction_repo import CardTransactionRepository
from app.states.admin_states import AdminInput
from app.utils.i18n import t
from app.utils.formatting import build_delivered_message, fmt_datetime, fmt_price, fmt_time

router = Router(name="admin_orders")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

admin_actions_logger = logging.getLogger("admin_actions")

_STATUS_MAP = {
    "pending": OrderStatus.PENDING_APPROVAL,
    "approved": OrderStatus.APPROVED,
    "delivered": OrderStatus.DELIVERED,
    "failed": OrderStatus.FAILED,
    "rejected": OrderStatus.REJECTED,
}

# A separate bucket, spanning several statuses at once: every order still
# waiting on its OWN payment confirmation to arrive (screenshot, crypto
# invoice, card_auto transfer, Stars charge) — as opposed to "pending",
# which means the payment already arrived and it's the ADMIN who's the
# bottleneck. Exists so a stuck order (payment confirmed by the provider,
# but whatever should have advanced its status never ran — see the
# successful_payment gate bug) can be found by BROWSING instead of
# requiring its exact ID, which the admin has no way to know if the usual
# "new order" notification never fired either.
_AWAITING_STATUSES = [
    OrderStatus.AWAITING_PROOF,
    OrderStatus.AWAITING_CRYPTO_PAYMENT,
    OrderStatus.AWAITING_STARS_PAYMENT,
    OrderStatus.AWAITING_CARD_PAYMENT,
]
# Statuses where the order is approved-but-not-yet-delivered — the admin may
# still need to push the product through by hand (e.g. API delivery failed,
# or it's a manual-mode product waiting for its message).
_NEEDS_MANUAL_BUTTON = {OrderStatus.APPROVED, OrderStatus.FAILED}

_STATUS_TITLES = {
    "pending": "⏳ <b>Kutilayotgan</b>",
    "approved": "✅ <b>Tasdiqlangan</b>",
    "delivered": "\U0001F4E6 <b>Yetkazilgan</b>",
    "failed": "⚠️ <b>Yetkazilmagan</b>",
    "rejected": "❌ <b>Rad etilgan</b>",
    "awaiting": "\U0001F4B3 <b>To'lov kutilmoqda</b>",
}


def _status_key(status: OrderStatus) -> str | None:
    """Reverse of _STATUS_MAP (+ the "awaiting" bucket), so a detail
    screen knows which list to go back to."""
    for key, value in _STATUS_MAP.items():
        if value == status:
            return key
    if status in _AWAITING_STATUSES:
        return "awaiting"
    return None


def _order_line(order) -> str:
    return (
        f"🔹 <b>{html_escape(order.product.name)}</b>\n"
        f"🆔 <code>{order.order_uuid}</code>\n"
        f"\U0001F464 @{order.user.username or '-'} ({order.user.telegram_id})\n"
        f"\U0001F4B0 {fmt_price(float(order.price_at_purchase))} {order.currency}\n"
        f"📅 {fmt_datetime(order.created_at)}"
    )


def _delivered_confirmation_block(order) -> str:
    """Appended to the original admin notification once an order is
    actually delivered — shows exactly what was sent and when, right in
    the same message thread, so the admin never has to dig through logs
    to confirm "did this go out, and what did I send". `delivered_payload`
    is HTML-escaped since it can be an arbitrary code/link/API result that
    may contain `&`/`<`/`>` (e.g. a URL with query params) — unescaped,
    that would break Telegram's HTML parser and silently fail the edit."""
    payload = html_escape(order.delivered_payload) if order.delivered_payload else "-"
    return (
        f"\n\n✅ TASDIQLANDI VA YETKAZILDI\n"
        f"🕐 Vaqt: {fmt_time(order.delivered_at)}\n"
        f"📦 Yuborilgan:\n<code>{payload}</code>"
    )


async def _edit_order_message_with_confirmation(callback: CallbackQuery, block: str) -> None:
    """Append `block` to whatever the original admin notification was —
    almost always a photo OR a document (the payment proof — now accepted
    as either, see shop.py's receive_screenshot) with a caption, but
    sometimes a plain text message (e.g. the "needs manual delivery"
    notice from the crypto auto-confirm path). `Message.text` is `None` on
    any media message — photo *or* document — (only `.caption` is
    populated there), so blindly calling `edit_text` on one raises
    `TypeError` — which used to crash this handler right after the product
    had already been delivered to the customer, leaving the admin with no
    visible confirmation at all. Checking `.text is None` (rather than
    `.photo` specifically) covers every media type uniformly. Also guards
    against Telegram's caption length cap (1024 chars, vs 4096 for plain
    text) — a large multi-code order could exceed it — falling back to a
    fresh message instead of losing the confirmation entirely."""
    try:
        if callback.message.text is None:
            await callback.message.edit_caption(caption=(callback.message.caption or "") + block)
        else:
            await callback.message.edit_text(callback.message.text + block)
    except TelegramBadRequest:
        await callback.message.answer("✅ TASDIQLANDI VA YETKAZILDI" + block)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass


_STATUS_LABELS = {
    OrderStatus.AWAITING_PROOF: "⏳ To'lov cheki kutilmoqda",
    OrderStatus.AWAITING_CRYPTO_PAYMENT: "⏳ Kripto to'lov kutilmoqda",
    OrderStatus.AWAITING_STARS_PAYMENT: "⏳ Stars to'lovi kutilmoqda",
    OrderStatus.AWAITING_CARD_PAYMENT: "⏳ Karta to'lovi kutilmoqda",
    OrderStatus.PENDING_APPROVAL: "\U0001F50D Tekshirilmoqda (tasdiqlashingiz kerak)",
    OrderStatus.APPROVED: "✅ Tasdiqlangan (hali yetkazilmagan)",
    OrderStatus.REJECTED: "❌ Rad etilgan",
    OrderStatus.DELIVERED: "\U0001F4E6 Yetkazilgan",
    OrderStatus.CANCELLED: "\U0001F6D1 Bekor qilingan",
    OrderStatus.FAILED: "⚠️ Yetkazib bo'lmadi",
}


async def render_order_detail(session: AsyncSession, order) -> str:
    """Everything an admin needs to answer "what happened with this order?"
    in one message: whether it was delivered, exactly what was sent, who
    bought it, and how they paid."""
    delivered_block = ""
    if order.delivered_payload:
        payload = html_escape(order.delivered_payload)
        delivered_block = (
            f"\n\n\U0001F4E4 <b>Yuborilgan:</b>\n<code>{payload}</code>"
            f"\n\U0001F550 Yetkazilgan: {fmt_datetime(order.delivered_at)}"
        )

    expected_block = ""
    if order.expected_amount is not None:
        expected_block = f"\n\U0001F3AF Kutilgan summa: <b>{fmt_price(float(order.expected_amount))}</b>"
        matched = await CardTransactionRepository(session).get_matched_for_order(order.id)
        if matched is not None:
            expected_block += (
                f"\n\U0001F4B3 Kelgan to'lov: {fmt_price(float(matched.amount or 0))} "
                f"(karta ***{matched.card_last4 or '-'}, {fmt_datetime(matched.created_at)})"
            )

    reason_block = f"\n\U0001F4DD Sabab: {html_escape(order.rejection_reason)}" if order.rejection_reason else ""
    qty_block = f" × {order.quantity}" if order.quantity and order.quantity > 1 else ""
    preorder_block = "\n⏳ <b>Oldindan buyurtma</b>" if order.is_preorder else ""

    return (
        f"\U0001F9FE <b>Buyurtma</b> <code>{order.order_uuid}</code>\n\n"
        f"\U0001F4CC Holat: <b>{_STATUS_LABELS.get(order.status, order.status.value)}</b>\n"
        f"\U0001F4E6 Mahsulot: {html_escape(order.product.name) if order.product else '-'}{qty_block}\n"
        f"\U0001F4B0 Narxi: {fmt_price(float(order.price_at_purchase))} {order.currency}\n"
        f"\U0001F4B3 To'lov usuli: {order.payment_method.value}"
        f"{expected_block}{preorder_block}\n\n"
        f"\U0001F464 Mijoz: {order.user.full_name if order.user else '-'} "
        f"(@{order.user.username if order.user and order.user.username else '-'})\n"
        f"\U0001F194 <code>{order.user.telegram_id if order.user else '-'}</code>\n"
        f"\U0001F4C5 Yaratilgan: {fmt_datetime(order.created_at)}"
        f"{reason_block}{delivered_block}"
    )


async def show_order_detail(
    event, session: AsyncSession, order, src: str | None = None, page: int = 0
) -> None:
    """Render the order screen in place (or as a new screen when the admin
    arrived by typing an ID, where there is no panel message to reuse)."""
    await show(
        event,
        await render_order_detail(session, order),
        reply_markup=admin_order_detail_kb(order, src=src, page=page),
    )


@router.callback_query(AdminOrderListCB.filter(F.action == "menu"))
async def orders_menu(callback: CallbackQuery) -> None:
    await answer_and_show(callback, "\U0001F4E5 Buyurtmalar bo'limi:", admin_orders_menu_kb())


@router.callback_query(AdminOrderListCB.filter(F.action == "noop"))
async def orders_noop(callback: CallbackQuery) -> None:
    """The page counter in the middle of the pager is a label, not a
    button — but Telegram still needs the callback answered or the client
    spins on it."""
    await callback.answer()


@router.callback_query(AdminOrderListCB.filter(F.action == "search"))
async def order_search_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(
        action="order_search",
        panel_chat_id=callback.message.chat.id,
        panel_message_id=callback.message.message_id,
    )
    await answer_and_show(
        callback,
        "\U0001F50D Buyurtma ID'sini yuboring.\n\n"
        "Masalan: <code>46C94A7FC616</code>\n"
        "(mijozga ko'rsatiladigan ID yoki ichki raqam ham bo'ladi)",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="‹ Orqaga", callback_data=AdminOrderListCB(action="menu").pack()
                    )
                ]
            ]
        ),
    )


@router.callback_query(AdminOrderListCB.filter(F.action == "open"))
async def open_order_from_list(
    callback: CallbackQuery, callback_data: AdminOrderListCB, session: AsyncSession
) -> None:
    order = await OrderRepository(session).get_by_id(callback_data.order_id)
    if order is None:
        await callback.answer("Buyurtma topilmadi.", show_alert=True)
        return
    src = _status_key(order.status)
    await callback.answer()
    await show_order_detail(callback, session, order, src=src, page=callback_data.page)


ORDERS_PER_PAGE = 8


async def render_orders_list(session: AsyncSession, status_key: str, page: int):
    """(text, keyboard) for one page of a status list."""
    repo = OrderRepository(session)
    page = max(0, page)
    if status_key == "awaiting":
        total = await repo.count_by_statuses(_AWAITING_STATUSES)
        orders = await repo.page_by_statuses(
            _AWAITING_STATUSES, offset=page * ORDERS_PER_PAGE, limit=ORDERS_PER_PAGE
        )
    else:
        status = _STATUS_MAP[status_key]
        total = await repo.count_by_status(status)
        orders = await repo.page_by_status(status, offset=page * ORDERS_PER_PAGE, limit=ORDERS_PER_PAGE)

    title = _STATUS_TITLES.get(status_key, status_key)
    if not orders:
        text = f"{title}\n\nBu bo'limda buyurtma yo'q."
    else:
        lines = [f"{title} — jami {total} ta", ""]
        for order in orders:
            lines.append(_order_line(order))
            if status_key == "awaiting":
                # Which payment this order is stuck waiting on isn't
                # obvious from the generic order line alone — spell it out,
                # since this list exists specifically to hunt down stuck
                # orders.
                lines.append(f"   {_STATUS_LABELS.get(order.status, order.status.value)}")
            lines.append("")
        text = "\n".join(lines).strip()
        if status_key == "failed":
            text += (
                "\n\n\U0001F4A1 Sababini (masalan hamyon balansi) bartaraf etgan bo'lsangiz, "
                "hammasini bitta tugma bilan qayta urinib ko'ring."
            )
        elif status_key == "awaiting":
            text += (
                "\n\n\U0001F4A1 To'lov haqiqatda o'tgan bo'lsa-yu, buyurtma shu yerda \"osilib\" "
                "qolgan bo'lsa (masalan Stars/kripto), buyurtmani ochib \"✅ Tasdiqlash va "
                "yetkazish\" tugmasini bosing — mahsulot qo'lda yetkaziladi."
            )
    return text, admin_orders_list_kb(orders, status_key, page, total, ORDERS_PER_PAGE)


@router.callback_query(AdminOrderListCB.filter())
async def list_orders(
    callback: CallbackQuery, callback_data: AdminOrderListCB, session: AsyncSession
) -> None:
    if callback_data.action not in _STATUS_MAP and callback_data.action != "awaiting":
        await callback.answer()
        return
    text, kb = await render_orders_list(session, callback_data.action, callback_data.page)
    await answer_and_show(callback, text, kb)


async def _retry_one(bot, session: AsyncSession, order_id: int) -> tuple[bool, str]:
    """Re-run automatic delivery for one order. (ok, short report line).

    Never raises: a bulk retry over a dozen stranded orders must report on
    every one of them, not stop at the first that still fails.
    """
    from app.services.notify import notify_delivery_failure

    delivery = DeliveryService(session)
    try:
        result = await delivery.retry_delivery(order_id)
    except InvalidOrderStateError as exc:
        return False, f"#{order_id}: {exc}"
    except DeliveryFailedError as exc:
        fresh = await OrderRepository(session).get_by_id(order_id)
        if fresh is not None:
            await notify_delivery_failure(bot, session, fresh, str(exc), tell_customer=False)
        return False, f"#{order_id}: {exc}"

    order = result.order
    lang = order.user.language
    if result.delivered_now and result.payload:
        try:
            await bot.send_message(
                order.user.telegram_id,
                build_delivered_message(lang, order, result.payload),
                reply_markup=buy_again_kb(lang, order.product_id),
            )
        except Exception:  # noqa: BLE001 - customer may have blocked the bot
            pass
        await ReferralService(session).credit_for_delivered_order(order, bot)
        return True, f"#{order_id}: ✅ yetkazildi"
    return False, f"#{order_id}: qo'lda yuborish kerak"


@router.callback_query(OrderCB.filter(F.action == "retry_auto"))
async def retry_order_delivery(
    callback: CallbackQuery, callback_data: OrderCB, session: AsyncSession
) -> None:
    await callback.answer("Qayta urinilmoqda…")
    ok, line = await _retry_one(callback.bot, session, callback_data.order_id)
    admin_actions_logger.info(
        "order_retry order=%s admin=%s ok=%s", callback_data.order_id, callback.from_user.id, ok
    )

    # Redraw THIS screen with the new outcome. Sending the result as a new
    # message was the actual complaint: the old card still said "DELIVERY
    # FAILED" while the reply somewhere below said it had succeeded, and
    # the admin had to scroll to find out which was current.
    order = await OrderRepository(session).get_by_id(callback_data.order_id)
    if order is None:
        return
    header = (
        "✅ <b>YETKAZILDI</b> (qayta urinishdan keyin)\n\n"
        if ok
        else f"❌ <b>Hali ham bo'lmadi</b>\n{line}\n\n"
    )
    await show(
        callback,
        header + await render_order_detail(session, order),
        reply_markup=admin_order_detail_kb(order, src=callback_data.src, page=callback_data.page),
    )


@router.callback_query(AdminOrderListCB.filter(F.action == "retry_all"))
async def retry_all_failed(callback: CallbackQuery, session: AsyncSession) -> None:
    """One tap for the whole backlog: the usual cause (empty wallet, stale
    cookies) strands every order that arrived while it lasted."""
    from app.database.models.enums import OrderStatus

    failed = await OrderRepository(session).list_by_status(OrderStatus.FAILED)
    if not failed:
        await callback.answer("Muvaffaqiyatsiz buyurtma yo'q.", show_alert=True)
        return

    await callback.answer(f"{len(failed)} ta buyurtma qayta urinilmoqda…")
    lines, done = [], 0
    for order in failed:
        ok, line = await _retry_one(callback.bot, session, order.id)
        done += int(ok)
        lines.append(line)
    admin_actions_logger.info(
        "orders_retry_all admin=%s total=%s ok=%s", callback.from_user.id, len(failed), done
    )
    # Back to the (now shorter) failed list, with the summary on top of it.
    text, kb = await render_orders_list(session, "failed", 0)
    await show(
        callback,
        f"\U0001F501 <b>Qayta urinish natijasi</b>\n\n"
        f"Jami: {len(failed)} ta · Yetkazildi: {done} ta · Qoldi: {len(failed) - done} ta\n\n"
        + "\n".join(lines[:15])
        + "\n\n"
        + text,
        reply_markup=kb,
    )


@router.callback_query(OrderCB.filter(F.action == "approve"))
async def approve_order(callback: CallbackQuery, callback_data: OrderCB, session: AsyncSession, state: FSMContext) -> None:
    admin_id = callback.from_user.id
    delivery = DeliveryService(session)
    try:
        result = await delivery.approve_order(callback_data.order_id, admin_id)
    except InvalidOrderStateError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except DeliveryFailedError as exc:
        # Order was already marked APPROVED before delivery was attempted
        # (see DeliveryService.approve_order), so it's now stuck: re-tapping
        # "Approve" will just hit the "already reviewed" guard above. Give
        # the admin a way out — write the delivery message by hand instead
        # of leaving the order paid-for-but-undelivered with no recovery
        # path in the UI.
        await callback.answer(str(exc), show_alert=True)
        # Keep the customer in the loop too: they've paid and been told
        # "approved", so silence here reads as a scam.
        failed_order = await OrderRepository(session).get_by_id(callback_data.order_id)
        if failed_order is not None and failed_order.user is not None:
            try:
                await callback.bot.send_message(
                    failed_order.user.telegram_id,
                    t(
                        failed_order.user.language,
                        "msg_delivery_manual_fallback",
                        order_uuid=failed_order.order_uuid,
                    ),
                )
            except Exception:  # noqa: BLE001 - customer may have blocked the bot
                pass
        # Redraw this same screen: approved, delivery failed, here are the
        # ways out (retry / send by hand) — rather than leaving the old
        # "pending" card above a separate error message.
        if failed_order is not None:
            await show(
                callback,
                f"⚠️ <b>Tasdiqlandi, lekin avtomatik yetkazilmadi</b>\n{exc}\n\n"
                + await render_order_detail(session, failed_order),
                reply_markup=admin_order_detail_kb(
                    failed_order, src=callback_data.src, page=callback_data.page
                ),
            )
        return

    admin_actions_logger.info("order_approved order=%s admin=%s", callback_data.order_id, admin_id)

    order = result.order
    lang = order.user.language

    if result.delivered_now and result.payload:
        await callback.bot.send_message(
            order.user.telegram_id,
            build_delivered_message(lang, order, result.payload),
            reply_markup=buy_again_kb(lang, order.product_id),
        )
        await ReferralService(session).credit_for_delivered_order(order, callback.bot)
        await _edit_order_message_with_confirmation(callback, _delivered_confirmation_block(order))
    elif result.needs_manual_message:
        await state.set_state(AdminInput.waiting_text)
        await state.update_data(
            action="manual_deliver",
            order_id=order.id,
            panel_chat_id=callback.message.chat.id,
            panel_message_id=callback.message.message_id,
            src=callback_data.src,
            page=callback_data.page,
            # Threaded through so generic_input.py's manual_deliver handler
            # can edit *this* original notification (screenshot or text)
            # once the admin actually types the delivery message, instead
            # of leaving it as a stale, button-less card with no outcome
            # ever shown on it.
            admin_chat_id=callback.message.chat.id,
            admin_message_id=callback.message.message_id,
            # True for any media message (photo OR document) — both use
            # `.caption` instead of `.text`, see _edit_order_message_with_confirmation.
            admin_msg_is_photo=callback.message.text is None,
            admin_original_body=callback.message.caption if callback.message.text is None else callback.message.text,
        )
        preorder_note = "\n⏳ Bu — oldindan buyurtma edi. Mahsulot stokga kelgach yuboring." if order.is_preorder else ""
        await show(
            callback,
            f"✏️ Buyurtma <code>{order.order_uuid}</code> uchun mijozga yuboriladigan "
            f"xabarni yozing:{preorder_note}",
        )

    await callback.answer("Tasdiqlandi ✅")


@router.callback_query(OrderCB.filter(F.action == "reject"))
async def reject_order_start(callback: CallbackQuery, callback_data: OrderCB, state: FSMContext) -> None:
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(
        action="reject_reason",
        order_id=callback_data.order_id,
        # Remembered so the typed-reason handler can put this same screen
        # back where it was instead of trailing another message.
        panel_chat_id=callback.message.chat.id,
        panel_message_id=callback.message.message_id,
        src=callback_data.src,
        page=callback_data.page,
    )
    await answer_and_show(
        callback,
        "❌ <b>Rad etish</b>\n\nSababini yozib yuboring (yoki '-' yuboring — sababsiz rad etiladi).",
    )


@router.callback_query(OrderCB.filter(F.action == "write_manual"))
async def write_manual_start(callback: CallbackQuery, callback_data: OrderCB, state: FSMContext) -> None:
    """Entry point used after a crypto payment is auto-confirmed for a
    manually-delivered product (see services/crypto_poller.py) — the order
    is already APPROVED, the admin just needs to type the message."""
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(
        action="manual_deliver",
        order_id=callback_data.order_id,
        panel_chat_id=callback.message.chat.id,
        panel_message_id=callback.message.message_id,
        src=callback_data.src,
        page=callback_data.page,
        admin_chat_id=callback.message.chat.id,
        admin_message_id=callback.message.message_id,
        admin_msg_is_photo=callback.message.text is None,
        admin_original_body=callback.message.caption if callback.message.text is None else callback.message.text,
    )
    await answer_and_show(
        callback,
        "✍️ <b>Qo'lda yetkazish</b>\n\nMijozga yuboriladigan xabarni (yoki faylni) yuboring.",
    )
