from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.database.models import Product
from app.keyboards.callback_data import CryptoCB, LangCB, MyOrderCB, MyOrdersPageCB, ShopCB
from app.utils.i18n import t


ADMIN_PANEL_BTN = "\U0001F6E0️ Admin panel"


def main_menu_kb(lang: str, is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=t(lang, "btn_shop")), KeyboardButton(text=t(lang, "btn_my_orders"))],
        [KeyboardButton(text=t(lang, "btn_reviews")), KeyboardButton(text=t(lang, "btn_support"))],
        [KeyboardButton(text=t(lang, "btn_language"))],
    ]
    if is_admin:
        # Only ever shown to telegram IDs that pass IsAdmin — regular users
        # never see this row, so there is nothing to hide-by-obscurity here.
        rows.append([KeyboardButton(text=ADMIN_PANEL_BTN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def shop_list_kb(products: list[Product], lang: str) -> InlineKeyboardMarkup:
    from app.utils.formatting import product_name  # local import avoids a cycle

    rows = [
        [
            InlineKeyboardButton(
                text=f"{p.emoji} {product_name(p, lang)}",
                callback_data=ShopCB(action="open", product_id=p.id).pack(),
            )
        ]
        for p in products
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_detail_kb(
    lang: str,
    product_id: int,
    in_stock: bool,
    show_crypto: bool = False,
    crypto_providers: list[tuple[str, str]] | None = None,
) -> InlineKeyboardMarkup:
    rows = []
    if in_stock:
        buy_label = t(lang, "btn_pay_card") if show_crypto else t(lang, "btn_buy")
        rows.append(
            [InlineKeyboardButton(text=buy_label, callback_data=ShopCB(action="buy", product_id=product_id).pack())]
        )
        if show_crypto:
            # One button per configured crypto provider (CryptoBot / xRocket) —
            # both can be active at once, the customer just picks whichever
            # bot they already use.
            for provider_key, label in (crypto_providers or []):
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=label,
                            callback_data=CryptoCB(
                                action="buy", product_id=product_id, provider=provider_key
                            ).pack(),
                        )
                    ]
                )
    rows.append(
        [InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=ShopCB(action="back_to_list").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def crypto_invoice_kb(lang: str, pay_url: str, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_pay"), url=pay_url)],
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_check_payment"),
                    callback_data=CryptoCB(action="check", order_id=order_id).pack(),
                )
            ],
        ]
    )


def proof_channel_kb(lang: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "btn_proof_channel"), url=url)]]
    )


def my_orders_page_kb(current_page: int, total_pages: int) -> InlineKeyboardMarkup | None:
    """Page-number row (1, 2, 3, ...) for the "My Orders" single-message
    view. Returns None when there's nothing to page through."""
    if total_pages <= 1:
        return None
    rows, row = [], []
    for page in range(1, total_pages + 1):
        label = f"· {page} ·" if page == current_page else str(page)
        row.append(InlineKeyboardButton(text=label, callback_data=MyOrdersPageCB(action="page", page=page).pack()))
        if len(row) == 8:  # keep rows from getting unreasonably wide
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_kb(lang: str, product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_paid"), callback_data=ShopCB(action="paid", product_id=product_id).pack())],
            [InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=ShopCB(action="open", product_id=product_id).pack())],
        ]
    )


def cancel_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "btn_cancel"), callback_data=ShopCB(action="back_to_list").pack())]]
    )


def language_kb() -> InlineKeyboardMarkup:
    labels = {"uz": "🇺🇿 O'zbekcha", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}
    rows = [
        [InlineKeyboardButton(text=label, callback_data=LangCB(code=code).pack())]
        for code, label in labels.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


