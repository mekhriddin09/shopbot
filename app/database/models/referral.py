from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.database.models.enums import ReferralWithdrawalStatus


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
