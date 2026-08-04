from __future__ import annotations

from datetime import datetime

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
    legacy single `name` field (always set) -> any other set language."""
    return _localized_field(product, "name", lang, product.name) or product.name


def product_description(product, lang: str) -> str:
    """Same fallback chain as `product_name`, for the description field."""
    return _localized_field(product, "description", lang, product.description) or ""


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
