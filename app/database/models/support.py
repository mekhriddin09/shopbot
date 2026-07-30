from __future__ import annotations

from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class SupportRelay(TimestampMixin, Base):
    """Maps a copy of a user's support message forwarded to a specific admin
    back to that user, so that when the admin *replies* to it in Telegram,
    the bot knows exactly who to relay the reply to.

    One row per (admin, forwarded message) pair — the same user message is
    forwarded to every admin, each getting their own `admin_message_id`.
    Stores the user's Telegram ID directly (denormalized) so relaying a
    reply never needs an extra join.
    """

    __tablename__ = "support_relays"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    admin_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    admin_message_id: Mapped[int] = mapped_column(BigInteger, index=True)
