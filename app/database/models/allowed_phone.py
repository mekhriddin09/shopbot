from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class AllowedPhoneNumber(TimestampMixin, Base):
    """Admin-managed exception list for the referral-confirmation phone
    gate: numbers here pass even though they aren't +998 (Uzbekistan).
    Stored normalized (digits only, see app/services/onboarding_service.py
    normalize_phone) so lookups are a simple exact match regardless of how
    the admin typed it in (with/without '+', spaces, dashes)."""

    __tablename__ = "allowed_phone_numbers"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AllowedPhoneNumber id={self.id} phone={self.phone_number}>"
