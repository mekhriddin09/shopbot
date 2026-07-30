from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class Payment(TimestampMixin, Base):
    """Payment proof submitted by the customer for a given order."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), unique=True
    )
    method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    screenshot_file_id: Mapped[str] = mapped_column(Text, nullable=False)
    instructions_snapshot: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Payment instructions shown to the user at purchase time"
    )

    order: Mapped["Order"] = relationship(back_populates="payment")
