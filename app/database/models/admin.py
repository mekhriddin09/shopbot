from __future__ import annotations

from sqlalchemy import BigInteger, Enum
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin
from app.database.models.enums import AdminRole


class AdminUser(TimestampMixin, Base):
    """Persisted admins (in addition to the bootstrap ADMIN_IDS in .env).

    The .env ADMIN_IDS are always treated as super admins, regardless of
    whether a row exists here. This table lets super admins grant/revoke
    admin access to other people from inside the bot itself.
    """

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    role: Mapped[AdminRole] = mapped_column(
        Enum(AdminRole, native_enum=False), default=AdminRole.ADMIN
    )
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1")
