from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.database.models.enums import OrderStatus, PaymentMethod


def _new_order_uuid() -> str:
    return uuid.uuid4().hex[:12].upper()


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_uuid: Mapped[str] = mapped_column(
        String(16), unique=True, index=True, default=_new_order_uuid
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))

    price_at_purchase: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="UZS")
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, native_enum=False),
        default=OrderStatus.AWAITING_PROOF,
        index=True,
    )

    payment_method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, native_enum=False), default=PaymentMethod.CARD
    )
    crypto_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    crypto_invoice_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    crypto_pay_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    stars_charge_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, doc="telegram_payment_charge_id from successful_payment, needed for refundStarPayment"
    )

    decided_by_admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    delivered_payload: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="What was actually sent to the customer (code / message / API result)"
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Referral program bookkeeping — guards against ever crediting the same
    # order's reward twice, and records whether the credited reward (if any)
    # was the "first order" reward or a "recurring" one, for stats.
    referral_rewarded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    referral_is_first_reward: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    is_preorder: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0",
        doc="Paid while the product was out of stock; admin delivers by hand once restocked.",
    )

    user: Mapped["User"] = relationship(back_populates="orders")
    product: Mapped["Product"] = relationship(back_populates="orders")
    payment: Mapped["Payment"] = relationship(
        back_populates="order", uselist=False, cascade="all, delete-orphan"
    )
