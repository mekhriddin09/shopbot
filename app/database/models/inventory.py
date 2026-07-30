from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class InventoryCode(TimestampMixin, Base):
    """A single redeemable code/credential belonging to a product.

    Delivery is guaranteed to happen at most once per code: `is_used` is
    flipped inside the same DB transaction that creates the delivery record,
    using a row-level lock (SELECT ... FOR UPDATE equivalent via
    `with_for_update`) so two concurrent approvals can never hand out the
    same code twice.
    """

    __tablename__ = "inventory_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(Text, nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", index=True)
    used_by_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # A code is "reserved" the moment a customer starts a purchase (before
    # admin approval / before a crypto payment is confirmed) so the same
    # code can't be promised to multiple customers while one order is still
    # pending. Approval finalizes the reservation into `is_used`; a
    # rejection/cancellation releases it back to the available pool.
    is_reserved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", index=True)
    reserved_by_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )

    product: Mapped["Product"] = relationship(back_populates="inventory_codes")
