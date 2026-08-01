from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class StockWaiter(TimestampMixin, Base):
    """A user's subscription to be notified when a specific out-of-stock
    product gets new inventory. One row per (user, product) pair;
    `notified` flips to True the moment we ping them, so a restock never
    pings the same waiter twice — they must tap "notify me" again if they
    want to be told about a *future* restock too."""

    __tablename__ = "stock_waiters"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_stock_waiter_user_product"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    notified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    user: Mapped["User"] = relationship()
    product: Mapped["Product"] = relationship()
