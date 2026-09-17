from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.database.models.enums import CardTransactionStatus


class CardTransaction(TimestampMixin, Base):
    """Every card alert the bot receives, matched or not.

    Kept as a permanent audit trail rather than only recording successes:
    when a customer says "I paid and got nothing", the answer is in here —
    either the money never arrived, or it arrived for an amount no order
    was expecting (wrong amount typed, paid after the order expired), or
    the text couldn't be parsed at all. Nothing is silently dropped.

    `message_key` is what makes replay safe. Telegram can redeliver the
    same business message after a reconnect, and a bank alert re-read twice
    must never pay for two orders — the unique constraint here is the hard
    guarantee, independent of any in-memory bookkeeping.
    """

    __tablename__ = "card_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)

    # "<business_connection_id>:<chat_id>:<message_id>" — stable per alert.
    message_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)

    amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(8), nullable=True)  # in | out
    card_last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    balance_after: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[CardTransactionStatus] = mapped_column(
        Enum(CardTransactionStatus, native_enum=False),
        default=CardTransactionStatus.UNMATCHED,
        index=True,
    )
    matched_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )

    # Verbatim alert text — the ground truth for any later dispute, and the
    # sample set for fixing the parser if the bank ever changes its format.
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    matched_order: Mapped["Order | None"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CardTransaction id={self.id} amount={self.amount} status={self.status}>"
