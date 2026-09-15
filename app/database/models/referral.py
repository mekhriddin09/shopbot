from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.database.models.enums import (
    ReferralCurrency,
    ReferralRedemptionStatus,
    ReferralWithdrawalStatus,
)


class ReferralWithdrawal(TimestampMixin, Base):
    """A user's request to cash out their accumulated referral balance.
    Admin fulfils it by hand (bank transfer, crypto, a physical gift — the
    bot doesn't move money itself) and marks it paid/rejected."""

    __tablename__ = "referral_withdrawals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[ReferralWithdrawalStatus] = mapped_column(
        Enum(ReferralWithdrawalStatus, native_enum=False), default=ReferralWithdrawalStatus.PENDING
    )
    decided_by_admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship()


class ReferralReward(TimestampMixin, Base):
    """Admin-defined item in the "referral shop" catalog — e.g. "100 ta
    Telegram Stars" or "Gemini Advanced obunasi". Customers with enough
    referral balance can redeem one instead of (or alongside) cashing out
    via `ReferralWithdrawal`. Admin decides the name/cost themselves; the
    bot never fulfils these automatically — it's always a manual hand-off
    (send the Stars, share the promo code, etc.), same philosophy as manual
    product delivery."""

    __tablename__ = "referral_rewards"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # Which of the user's two referral balances this reward is priced in.
    # Defaults to BALANCE so every reward that existed before this column
    # was introduced keeps behaving exactly as it did.
    currency_type: Mapped[ReferralCurrency] = mapped_column(
        Enum(ReferralCurrency, native_enum=False),
        default=ReferralCurrency.BALANCE,
        server_default="BALANCE",
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class ReferralRedemption(TimestampMixin, Base):
    """A customer's request to spend their referral balance on a
    `ReferralReward`. Balance is deducted the moment the request is made
    (reserved, like an inventory code) so the same balance can't be spent
    twice across several pending requests; rejecting a request refunds it.
    Snapshots the reward's name/cost at request time so the record stays
    accurate even if the admin later edits or removes that catalog item —
    mirrors how `Order.price_at_purchase` snapshots a product's price."""

    __tablename__ = "referral_redemptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reward_id: Mapped[int | None] = mapped_column(
        ForeignKey("referral_rewards.id", ondelete="RESTRICT"), nullable=True
    )
    reward_name_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    cost_snapshot: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # Snapshotted alongside name/cost: a rejection must refund to the SAME
    # balance the cost was taken from, even if the admin has since changed
    # the catalog item's currency (or deleted it entirely).
    currency_type: Mapped[ReferralCurrency] = mapped_column(
        Enum(ReferralCurrency, native_enum=False),
        default=ReferralCurrency.BALANCE,
        server_default="BALANCE",
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ReferralRedemptionStatus] = mapped_column(
        Enum(ReferralRedemptionStatus, native_enum=False), default=ReferralRedemptionStatus.PENDING
    )
    decided_by_admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship()
    reward: Mapped["ReferralReward | None"] = relationship()
