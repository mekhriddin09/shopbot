from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, User
from app.keyboards.callback_data import MyOrdersPageCB
from app.keyboards.user_kb import my_orders_page_kb
from app.repositories.order_repo import OrderRepository
from app.utils.formatting import fmt_datetime, fmt_price, product_name
from app.utils.i18n import t

router = Router(name="user_orders")

_PAGE_SIZE = 5


def _order_text(lang: str, order: Order) -> str:
    return t(
        lang,
        "msg_order_item",
        product_name=product_name(order.product, lang),
        order_uuid=order.order_uuid,
        status=t(lang, f"status_{order.status.value}"),
        price=fmt_price(float(order.price_at_purchase)),
        currency=order.currency,
        created_at=fmt_datetime(order.created_at),
    )


def _page_text(lang: str, orders: list[Order], page: int, total_pages: int) -> str:
    start = (page - 1) * _PAGE_SIZE
    page_orders = orders[start : start + _PAGE_SIZE]
    body = "\n\n➖➖➖➖➖\n\n".join(_order_text(lang, order) for order in page_orders)
    if total_pages > 1:
        body += f"\n\n📄 {page}/{total_pages}"
    return body


@router.message(F.text.in_({t(l, "btn_my_orders") for l in ("uz", "ru", "en")}))
async def my_orders(message: Message, session: AsyncSession, user: User, lang: str) -> None:
    orders = await OrderRepository(session).list_by_user(user.id, limit=200)
    if not orders:
        await message.answer(t(lang, "msg_my_orders_empty"))
        return

    total_pages = (len(orders) + _PAGE_SIZE - 1) // _PAGE_SIZE
    text = _page_text(lang, orders, 1, total_pages)
    await message.answer(text, reply_markup=my_orders_page_kb(1, total_pages))


@router.callback_query(MyOrdersPageCB.filter(F.action == "page"))
async def my_orders_page(
    callback: CallbackQuery, callback_data: MyOrdersPageCB, session: AsyncSession, user: User, lang: str
) -> None:
    orders = await OrderRepository(session).list_by_user(user.id, limit=200)
    if not orders:
        await callback.answer(t(lang, "msg_my_orders_empty"), show_alert=True)
        return

    total_pages = (len(orders) + _PAGE_SIZE - 1) // _PAGE_SIZE
    page = max(1, min(callback_data.page, total_pages))
    text = _page_text(lang, orders, page, total_pages)
    try:
        await callback.message.edit_text(text, reply_markup=my_orders_page_kb(page, total_pages))
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
    await callback.answer()
