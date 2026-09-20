from __future__ import annotations

from datetime import datetime
from html import escape as html_escape

from app.utils.i18n import t


_LANG_FALLBACK_ORDER = ("uz", "ru", "en")


def _localized_field(product, field_base: str, lang: str, legacy_value: str | None) -> str | None:
    """Shared fallback chain: exact language match -> the legacy
    single-field value (the admin's explicit "default for everyone") ->
    whatever other language happens to be set, as a last resort."""
    value = getattr(product, f"{field_base}_{lang}", None)
    if value:
        return value
    if legacy_value:
        return legacy_value
    for candidate in _LANG_FALLBACK_ORDER:
        value = getattr(product, f"{field_base}_{candidate}", None)
        if value:
            return value
    return legacy_value


def product_name(product, lang: str) -> str:
    """Localized product name, with fallback: requested language -> the
    legacy single `name` field (always set) -> any other set language.

    Escaped for HTML: unlike `description`, a product name is never passed
    through the rich-text conversion (`_rich_text_or_plain` in
    generic_input.py) when the admin edits it, so a literal "<", ">" or "&"
    typed into a name is stored byte-for-byte. Every caller embeds this
    inside its own HTML markup (typically `<b>{name}</b>`) and sends with
    `parse_mode=HTML`, so an unescaped stray character here breaks message
    parsing outright — this used to crash the customer product card (and
    the admin "Asosiy ma'lumot" screen, which hits the same underlying
    value) for any product whose name held one of those characters."""
    name = _localized_field(product, "name", lang, product.name) or product.name
    return html_escape(name)


def product_description(product, lang: str) -> str:
    """Same fallback chain as `product_name`, for the description field."""
    return _localized_field(product, "description", lang, product.description) or ""


def product_emoji_html(product) -> str:
    """The product's emoji, ready to drop into an HTML-parsed message or
    caption (every place this is used sends with `parse_mode=HTML`). When
    the admin picked a custom/animated (Telegram Premium) emoji instead of
    a plain unicode one, that's the only way to make it render as picked —
    a plain-text message can't embed a custom emoji any other way, unlike
    a button's dedicated `icon_custom_emoji_id` field (see
    `app.keyboards.button_helpers` / the `shop_list_kb` button-label case,
    which use that field directly instead of this HTML tag)."""
    custom_id = getattr(product, "custom_emoji_id", None)
    if custom_id:
        return f'<tg-emoji emoji-id="{custom_id}">{product.emoji}</tg-emoji>'
    return product.emoji


def product_button_emoji_prefix(product) -> str:
    """Text prefix for a button LABEL (plain text — Telegram button text
    can't carry HTML/entities). Empty when the admin set a custom/animated
    emoji, since that can only be shown via the button's own
    `icon_custom_emoji_id` field, not embedded in the label itself —
    callers should pass `icon_custom_emoji_id=getattr(product,
    "custom_emoji_id", None)` alongside this on the same button."""
    if getattr(product, "custom_emoji_id", None):
        return ""
    return f"{product.emoji} "


def fmt_price(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def fmt_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.strftime("%Y-%m-%d %H:%M")


def fmt_time(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.strftime("%H:%M")


def _localized_delivery_instructions(product, lang: str) -> str | None:
    return _localized_field(
        product, "delivery_instructions", lang, getattr(product, "delivery_instructions", None)
    )


def build_delivered_message(lang: str, order, payload: str) -> str:
    """The 'your product is ready' message, with the product's optional
    customer-facing delivery instructions appended (how to log in /
    activate / use it), in the customer's own language when set. Shared by
    every delivery path — inventory, manual, API, admin-approved, and
    crypto auto-delivered — so it only needs to be edited in one place."""
    text = t(lang, "msg_delivered_product", order_uuid=order.order_uuid, payload=payload)
    instructions = _localized_delivery_instructions(order.product, lang)
    if instructions:
        text += f"\n\n{instructions}"
    return text


# Telegram rejects any message body over 4096 characters outright, and an
# oferta or a product description written in the admin panel can easily run
# past that. 3900 leaves room for the HTML the caller may add around it.
TELEGRAM_TEXT_LIMIT = 3900


def split_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Cut a long body into sendable chunks, preferring paragraph breaks.

    Written after a live incident: an oferta longer than 4096 characters made
    `onboarding_gate` raise `message is too long` on every /start, which left
    new users stuck at the gate with no message at all — the worst possible
    failure for the one screen everybody must pass.

    Splitting is attempted on a blank line, then a newline, then a space, so
    a chunk boundary doesn't land mid-word. Only if none of those exist in
    range is the text cut bluntly.
    """
    body = (text or "").strip()
    if len(body) <= limit:
        return [body] if body else []

    chunks: list[str] = []
    while len(body) > limit:
        window = body[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 2:
            cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut < limit // 2:
            cut = limit
        chunks.append(body[:cut].strip())
        body = body[cut:].strip()
    if body:
        chunks.append(body)
    return chunks
