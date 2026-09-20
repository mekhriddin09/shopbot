from __future__ import annotations

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.database.models.enums import DeliveryMode


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(
        String(128), nullable=False, doc="Fallback name, used if a language-specific one isn't set."
    )
    emoji: Mapped[str] = mapped_column(String(16), default="\U0001F4E6")  # 📦 — plain unicode fallback, always set
    custom_emoji_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        doc="A Telegram custom/animated (Premium) emoji's file_unique_id, if the "
        "admin picked one instead of a plain unicode emoji — see "
        "app.utils.formatting.product_emoji_html for how it's rendered.",
    )
    description: Mapped[str] = mapped_column(
        Text, default="", doc="Fallback description, used if a language-specific one isn't set."
    )
    name_uz: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name_ru: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name_en: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description_uz: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="UZS")
    price_usd: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True, doc="Crypto (USD) price. Null = crypto payment not offered for this product."
    )
    price_stars: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="Telegram Stars price (whole number, XTR has no subunits). Null = Stars payment not offered for this product."
    )
    image_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    delivery_mode: Mapped[DeliveryMode] = mapped_column(
        Enum(DeliveryMode, native_enum=False), default=DeliveryMode.INVENTORY
    )
    provider_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_product_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        doc="This product's ID in the external supplier's own catalog (e.g. "
        "'gemini'), passed to the provider on fetch(). Lets one provider "
        "(one reseller API) serve many different local products.",
    )
    manual_delivery_hint: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Shown to admin as a reminder of what to send manually"
    )
    delivery_instructions: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Fallback customer-facing text appended to the 'your product is "
        "ready' message, used if a language-specific one isn't set.",
    )
    delivery_instructions_uz: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_instructions_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_instructions_en: Mapped[str | None] = mapped_column(Text, nullable=True)

    payment_instructions: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Per-product override; falls back to global setting if empty"
    )

    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    referral_eligible: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        doc="Whether purchases of this product count toward referral rewards.",
    )

    referral_reward_value: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        doc=(
            "Per-product referral reward override, same syntax as the global "
            "settings ('5000' fixed, '2%' percent). Empty/null = inherit the "
            "global first-order/recurring split. When set, this single value "
            "replaces both — a per-product reward is a flat business rule, "
            "not something that behaves differently on repeat purchases."
        ),
    )
    referral_reward_by_qty: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        doc=(
            "Only relevant when referral_reward_value is a percentage: whether "
            "the percentage is taken of the order quantity (e.g. 2% of 100 "
            "Stars = 2) instead of the order price in UZS (the default, and "
            "the only behaviour the global settings support)."
        ),
    )

    card_auto_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        doc=(
            "Offer the automatic card payment option (unique amount verified against "
            "CardXabar alerts) for this product. Off by default so the feature can be "
            "rolled out one product at a time."
        ),
    )

    card_manual_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="1",
        doc=(
            "Offer the receipt-screenshot payment option for this product. Turn it "
            "off for goods that are only worth selling fully automatically — "
            "Stars/Premium, where a human confirming screenshots all day costs more "
            "than the margin. On by default, since that is how every existing "
            "product already behaves."
        ),
    )

    card_manual_confirm: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        doc=(
            "Automatic card payments for this product always wait for an admin tap, "
            "even when global auto-delivery is on. Meant for higher-value items where "
            "a mis-matched payment would be expensive to get wrong."
        ),
    )

    min_order_qty: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", doc="Minimum quantity a customer must buy per order."
    )
    max_order_qty: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", doc="Maximum quantity a customer may buy per order."
    )

    inventory_codes: Mapped[list["InventoryCode"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    orders: Mapped[list["Order"]] = relationship(back_populates="product")

    @property
    def available_stock(self) -> int:
        if self.delivery_mode != DeliveryMode.INVENTORY:
            return -1  # unlimited / not tracked
        return sum(1 for c in self.inventory_codes if not c.is_used and not c.is_reserved)
