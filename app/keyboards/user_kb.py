from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.database.models import Product
from app.keyboards.callback_data import (
    CaptchaCB,
    CardAutoCB,
    CryptoCB,
    LangCB,
    MyOrderCB,
    MyOrdersPageCB,
    OnboardingCB,
    QtyCB,
    ReferralCB,
    ReferralRewardCB,
    ShopCB,
    StarsCB,
    StockNotifyCB,
)
from app.utils.formatting import fmt_price
from app.utils.i18n import t


ADMIN_PANEL_BTN = "\U0001F6E0️ Admin panel"


def main_menu_kb(lang: str, is_admin: bool = False) -> ReplyKeyboardMarkup:
    # NOTE: there is deliberately no "confirm your referral" button here.
    # Referral confirmation (phone + captcha) is enforced up-front by
    # OnboardingGateMiddleware for the users it applies to, so by the time
    # anyone sees this menu they've already passed it. An optional menu
    # button was the original design and it didn't work: users simply
    # ignored it (the shop kept working without it), so almost nobody ever
    # confirmed and referrer stats stayed empty.
    rows = [
        [KeyboardButton(text=t(lang, "btn_shop")), KeyboardButton(text=t(lang, "btn_my_orders"))],
        [KeyboardButton(text=t(lang, "btn_reviews")), KeyboardButton(text=t(lang, "btn_support"))],
        [KeyboardButton(text=t(lang, "btn_referral")), KeyboardButton(text=t(lang, "btn_language"))],
    ]
    if is_admin:
        # Only ever shown to telegram IDs that pass IsAdmin — regular users
        # never see this row, so there is nothing to hide-by-obscurity here.
        rows.append([KeyboardButton(text=ADMIN_PANEL_BTN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def card_auto_waiting_kb(lang: str, order_id: int, paid_pressed: bool = False) -> InlineKeyboardMarkup:
    """Payment screen for the automatic-card flow.

    Once the customer has pressed "I paid", a "not detected? send receipt"
    escape hatch appears immediately rather than after the countdown — a
    customer whose payment isn't being picked up should never have to sit
    out the full timer before they can reach a human.
    """
    rows = []
    if not paid_pressed:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_card_auto_paid"),
                    callback_data=CardAutoCB(action="paid", order_id=order_id).pack(),
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_card_auto_not_detected"),
                    callback_data=CardAutoCB(action="manual", order_id=order_id).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t(lang, "btn_cancel"),
                callback_data=CardAutoCB(action="cancel", order_id=order_id).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_auto_expired_kb(lang: str, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_card_auto_i_did_pay"),
                    callback_data=CardAutoCB(action="manual", order_id=order_id).pack(),
                )
            ]
        ]
    )


def oferta_accept_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_offer_accept"), callback_data=OnboardingCB(action="accept_offer").pack())]
        ]
    )


def channel_check_kb(lang: str, channel_url: str) -> InlineKeyboardMarkup:
    rows = []
    if channel_url:
        rows.append([InlineKeyboardButton(text=t(lang, "btn_channel_open"), url=channel_url)])
    rows.append(
        [InlineKeyboardButton(text=t(lang, "btn_channel_check"), callback_data=OnboardingCB(action="check_channel").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def request_contact_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "btn_share_contact"), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def captcha_kb(options: list[int], correct: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=str(value), callback_data=CaptchaCB(action="answer", correct=(value == correct)).pack())
        for value in options
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[:2], buttons[2:]])


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
    show_stars: bool = False,
    max_order_qty: int = 1,
    show_notify_button: bool = False,
    show_preorder_button: bool = False,
    show_card_auto: bool = False,
) -> InlineKeyboardMarkup:
    rows = []
    if in_stock:
        if show_card_auto:
            # Automatic card verification: the customer transfers a unique
            # amount and the bot recognises it from the bank alert. Listed
            # first because it's the fastest path for the customer.
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t(lang, "btn_pay_card_auto"),
                        callback_data=(
                            QtyCB(action="show", product_id=product_id, flow="cardauto").pack()
                            if max_order_qty > 1
                            else CardAutoCB(action="buy", product_id=product_id).pack()
                        ),
                    )
                ]
            )
        buy_label = t(lang, "btn_pay_card") if (show_crypto or show_stars) else t(lang, "btn_buy")
        if max_order_qty > 1:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=buy_label,
                        callback_data=QtyCB(action="show", product_id=product_id, flow="card").pack(),
                    )
                ]
            )
        else:
            rows.append(
                [InlineKeyboardButton(text=buy_label, callback_data=ShopCB(action="buy", product_id=product_id).pack())]
            )
        if show_crypto:
            # One button per configured crypto provider (CryptoBot / xRocket) —
            # both can be active at once, the customer just picks whichever
            # bot they already use.
            for provider_key, label in (crypto_providers or []):
                if max_order_qty > 1:
                    rows.append(
                        [
                            InlineKeyboardButton(
                                text=label,
                                callback_data=QtyCB(
                                    action="show", product_id=product_id, flow="crypto", provider=provider_key
                                ).pack(),
                            )
                        ]
                    )
                else:
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
        if show_stars:
            # Telegram's own native Stars payment — no external provider, so
            # just one button (unlike crypto, which can have several).
            if max_order_qty > 1:
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=t(lang, "btn_buy_stars"),
                            callback_data=QtyCB(action="show", product_id=product_id, flow="stars").pack(),
                        )
                    ]
                )
            else:
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=t(lang, "btn_buy_stars"),
                            callback_data=StarsCB(action="buy", product_id=product_id).pack(),
                        )
                    ]
                )
    elif show_preorder_button:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_preorder"),
                    callback_data=ShopCB(action="buy", product_id=product_id, preorder=True).pack(),
                )
            ]
        )
        if show_crypto:
            for provider_key, label in (crypto_providers or []):
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=label,
                            callback_data=CryptoCB(
                                action="buy", product_id=product_id, provider=provider_key, preorder=True
                            ).pack(),
                        )
                    ]
                )
        if show_stars:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t(lang, "btn_buy_stars"),
                        callback_data=StarsCB(action="buy", product_id=product_id, preorder=True).pack(),
                    )
                ]
            )
    elif show_notify_button:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_notify_stock"),
                    callback_data=StockNotifyCB(action="subscribe", product_id=product_id).pack(),
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=ShopCB(action="back_to_list").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def qty_picker_kb(
    lang: str, product_id: int, qty: int, min_qty: int, max_qty: int, flow: str, provider: str
) -> InlineKeyboardMarkup:
    def cb(action: str, new_qty: int = qty) -> str:
        return QtyCB(action=action, product_id=product_id, qty=new_qty, flow=flow, provider=provider).pack()

    rows = [
        [
            InlineKeyboardButton(text="➖", callback_data=cb("dec", max(min_qty, qty - 1))),
            InlineKeyboardButton(text=f"{qty}", callback_data=cb("noop")),
            InlineKeyboardButton(text="➕", callback_data=cb("inc", min(max_qty, qty + 1))),
        ]
    ]
    quick_values = sorted({v for v in (1, 5, 10) if min_qty <= v <= max_qty})
    if quick_values:
        rows.append(
            [InlineKeyboardButton(text=str(v), callback_data=cb("set", v)) for v in quick_values]
        )
    rows.append([InlineKeyboardButton(text=t(lang, "btn_confirm"), callback_data=cb("confirm"))])
    rows.append(
        [InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=ShopCB(action="open", product_id=product_id).pack())]
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
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_cancel"),
                    callback_data=CryptoCB(action="cancel", order_id=order_id).pack(),
                )
            ],
        ]
    )


def stars_invoice_kb(lang: str, order_id: int) -> InlineKeyboardMarkup:
    """Telegram requires the very first button of an invoice message's first
    row to have `pay=True` (no callback_data/url) for it to render as the
    native "Pay" button. We add a Cancel row below it so the customer can
    still back out and release any reserved stock — Stars payments are
    push-based, so there's no separate "check payment" button like crypto."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_pay_stars"), pay=True)],
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_cancel"),
                    callback_data=StarsCB(action="cancel", order_id=order_id).pack(),
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


def referral_profile_kb(
    lang: str,
    can_withdraw: bool,
    has_rewards: bool = False,
    has_rules: bool = False,
    needs_confirmation: bool = False,
) -> InlineKeyboardMarkup | None:
    rows = []
    if needs_confirmation:
        # Shown to a referred-but-unconfirmed user so they can complete (or
        # retry) the phone+captcha check whenever they want — e.g. they
        # declined the one-time prompt at entry, or their first attempt was
        # rejected because they only had a foreign number at the time.
        rows.append(
            [InlineKeyboardButton(text=t(lang, "btn_referral_confirm"), callback_data=ReferralCB(action="confirm").pack())]
        )
    if has_rewards:
        rows.append(
            [InlineKeyboardButton(text=t(lang, "btn_referral_shop"), callback_data=ReferralRewardCB(action="list").pack())]
        )
    if can_withdraw:
        rows.append(
            [InlineKeyboardButton(text=t(lang, "btn_referral_withdraw"), callback_data=ReferralCB(action="withdraw").pack())]
        )
    if has_rules:
        rows.append(
            [InlineKeyboardButton(text=t(lang, "btn_referral_rules"), callback_data=ReferralCB(action="rules").pack())]
        )
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def referral_reward_list_kb(
    lang: str, rewards: list, currency_name: str = "", points_name: str = ""
) -> InlineKeyboardMarkup:
    """Each button spells out which of the two currencies the item costs,
    so the customer can tell at a glance what they can actually afford
    without opening every single one."""
    from app.database.models.enums import ReferralCurrency  # local import avoids a cycle

    rows = []
    for r in rewards:
        unit = points_name if r.currency_type == ReferralCurrency.POINTS else currency_name
        label = f"{r.name} — {fmt_price(float(r.cost))}"
        if unit:
            label += f" {unit}"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=ReferralRewardCB(action="open", reward_id=r.id).pack())]
        )
    rows.append(
        [InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=ReferralCB(action="profile_back").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def referral_reward_detail_kb(lang: str, reward_id: int, can_afford: bool) -> InlineKeyboardMarkup:
    rows = []
    if can_afford:
        rows.append(
            [InlineKeyboardButton(text=t(lang, "btn_referral_reward_buy"), callback_data=ReferralRewardCB(action="buy", reward_id=reward_id).pack())]
        )
    rows.append(
        [InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=ReferralRewardCB(action="list").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def referral_reward_skip_note_kb(lang: str, reward_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_skip"),
                    callback_data=ReferralRewardCB(action="skip_note", reward_id=reward_id).pack(),
                )
            ]
        ]
    )


def payment_kb(lang: str, product_id: int, qty: int = 1, preorder: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "btn_paid"),
                    callback_data=ShopCB(action="paid", product_id=product_id, qty=qty, preorder=preorder).pack(),
                )
            ],
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


