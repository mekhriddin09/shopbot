"""Code-side source of truth for every button the Button Manager can style.

This is the ONLY place that decides what a button *does* semantically
(its `ButtonType`) and what it looks like out of the box (default Unicode
emoji, default i18n key). `app.database.models.button.ButtonConfig` /
`ButtonTranslation` only ever override the *presentation* fields below —
never add a key here that isn't already wired through a real
callback/handler; the registry describes existing buttons, it doesn't
create new ones.

Centralizing the semantic-type -> Telegram style mapping here means no
handler or keyboard-builder file ever has to decide "should this be
green?" — they just declare *what kind* of action the button is
(BUY = positive, CANCEL = negative, BACK = navigation, ...) and this
module decides the color, so future policy changes (e.g. Telegram adding
a 4th style) only ever touch one place.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ButtonType(str, Enum):
    """Semantic category of a button's action — NOT a Telegram concept.
    Maps to a Telegram Bot API 9.4+ `style` via `STYLE_BY_TYPE` below."""

    PRIMARY = "primary"        # the main/expected next action (Shop, Buy w/ card)
    POSITIVE = "positive"      # pay/confirm/buy-with-Stars — "this completes something good"
    NEGATIVE = "negative"      # cancel/delete/remove
    WARNING = "warning"        # "I already paid but it's not detected" etc.
    NEUTRAL = "neutral"        # default look, no strong signal
    NAVIGATION = "navigation"  # back/menu/pagination
    INFO = "info"              # informational, non-actionable-ish (channel link, proof)


# Telegram Bot API 9.4 InlineKeyboardButton.style only accepts these three
# values (or omitted entirely for Telegram's own default gray look). Every
# ButtonType maps down to one of them, following the ordinary marketing
# convention the admin asked for: green = positive/"go" action (buy, pay,
# confirm), red = negative/"stop" action (cancel), blue for everything else
# — never Telegram's flat default gray, which reads as "disabled".
STYLE_BY_TYPE: dict[ButtonType, str | None] = {
    ButtonType.PRIMARY: "primary",
    ButtonType.POSITIVE: "success",
    ButtonType.NEGATIVE: "danger",
    ButtonType.WARNING: "danger",
    ButtonType.NEUTRAL: "primary",
    ButtonType.NAVIGATION: "primary",
    ButtonType.INFO: "primary",
}


@dataclass(frozen=True)
class ButtonDef:
    key: str
    type: ButtonType
    i18n_key: str  # existing app/locales/*.json key — current text+emoji baked in, used verbatim as the code default
    default_emoji: str | None = None  # used only once an admin sets a plain-text translation override (see button_service)
    group: str = "general"
    label: str = ""  # short admin-facing name, e.g. for the Button Manager list (phase 2)
    surface: str = "inline"  # "inline" (InlineKeyboardButton) or "reply" (KeyboardButton) — both support style/custom emoji since Bot API 9.4; this only decides which button_helpers builder function to call


# Phase 1 scope, per the confirmed plan: main menu (reply keyboard) +
# product/payment buttons (inline). Admin-only buttons are deliberately
# NOT included here (see the user's own spec instruction: don't blindly
# migrate admin-only buttons).
BUTTON_REGISTRY: dict[str, ButtonDef] = {
    # --- Main menu (ReplyKeyboardMarkup — text only, no style/custom emoji) ---
    "menu_shop": ButtonDef("menu_shop", ButtonType.PRIMARY, "btn_shop", "🛍️", "main_menu", "Do'kon", "reply"),
    "menu_my_orders": ButtonDef("menu_my_orders", ButtonType.NEUTRAL, "btn_my_orders", "📦", "main_menu", "Buyurtmalarim", "reply"),
    "menu_reviews": ButtonDef("menu_reviews", ButtonType.NEUTRAL, "btn_reviews", "⭐", "main_menu", "Sharhlar", "reply"),
    "menu_support": ButtonDef("menu_support", ButtonType.NEUTRAL, "btn_support", "💬", "main_menu", "Yordam", "reply"),
    "menu_referral": ButtonDef("menu_referral", ButtonType.NEUTRAL, "btn_referral", "🤝", "main_menu", "Referral", "reply"),
    "menu_language": ButtonDef("menu_language", ButtonType.NEUTRAL, "btn_language", "🌐", "main_menu", "Til", "reply"),
    # --- Product / payment (InlineKeyboardMarkup — style + custom emoji supported) ---
    # Every "buy this / pay this way" button is POSITIVE (green) — it's the
    # action that makes the sale happen, so it gets the "go" color, not the
    # neutral blue a generic primary action would get.
    "buy": ButtonDef("buy", ButtonType.POSITIVE, "btn_buy", "💳", "product", "Sotib olish"),
    "pay_card": ButtonDef("pay_card", ButtonType.POSITIVE, "btn_pay_card", "💳", "product", "Karta orqali"),
    "pay_card_auto": ButtonDef("pay_card_auto", ButtonType.POSITIVE, "btn_pay_card_auto", "⚡️", "product", "Karta (avtomatik)"),
    "buy_stars": ButtonDef("buy_stars", ButtonType.POSITIVE, "btn_buy_stars", "⭐", "product", "Stars orqali"),
    "pay_balance": ButtonDef("pay_balance", ButtonType.POSITIVE, "btn_pay_balance", "💰", "product", "Referal balansidan"),
    "paid": ButtonDef("paid", ButtonType.POSITIVE, "btn_paid", "✅", "product", "To'ladim"),
    "confirm": ButtonDef("confirm", ButtonType.POSITIVE, "btn_confirm", "✅", "product", "Tasdiqlash"),
    "cancel": ButtonDef("cancel", ButtonType.NEGATIVE, "btn_cancel", "❌", "product", "Bekor qilish"),
    "back": ButtonDef("back", ButtonType.NAVIGATION, "btn_back", "🔙", "product", "Orqaga"),
    "buy_again": ButtonDef("buy_again", ButtonType.POSITIVE, "btn_buy_again", "🔁", "product", "Yana sotib olish"),
    # Only ever shown INSTEAD of "buy" (see product_detail_kb: in_stock is
    # False for both) — so stock status colors itself automatically: in
    # stock -> green "buy", out of stock -> red "preorder"/"notify me",
    # with no per-product admin toggle needed for the color to make sense.
    "preorder": ButtonDef("preorder", ButtonType.NEGATIVE, "btn_preorder", "📦", "product", "Oldindan buyurtma (stock yo'q)"),
    "notify_stock": ButtonDef("notify_stock", ButtonType.NEGATIVE, "btn_notify_stock", "🔔", "product", "Kelganda ogohlantir (stock yo'q)"),
}


# Reverse index: i18n key ("btn_shop") -> registry key ("menu_shop"). Several
# handler files match incoming message text against the *default* i18n
# strings for reply-keyboard buttons (see app/utils/button_filters.py) —
# this lets that matching stay keyed by the stable registry key even though
# the handler code only knows the i18n key.
I18N_KEY_TO_BUTTON_KEY: dict[str, str] = {d.i18n_key: d.key for d in BUTTON_REGISTRY.values()}


def get_button_def(key: str) -> ButtonDef | None:
    return BUTTON_REGISTRY.get(key)


def list_groups() -> dict[str, list[ButtonDef]]:
    groups: dict[str, list[ButtonDef]] = {}
    for item in BUTTON_REGISTRY.values():
        groups.setdefault(item.group, []).append(item)
    return groups
