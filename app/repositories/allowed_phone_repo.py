from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AllowedPhoneNumber


class AllowedPhoneRepository:
    """Admin-managed exception list letting specific non-+998 numbers pass
    the referral-confirmation phone gate (see app/services/onboarding_service.py)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[AllowedPhoneNumber]:
        result = await self.session.execute(
            select(AllowedPhoneNumber).order_by(AllowedPhoneNumber.id.desc())
        )
        return list(result.scalars().all())

    async def is_allowed(self, normalized_phone: str) -> bool:
        result = await self.session.execute(
            select(AllowedPhoneNumber).where(AllowedPhoneNumber.phone_number == normalized_phone)
        )
        return result.scalar_one_or_none() is not None

    async def add(self, normalized_phone: str, note: str | None = None) -> AllowedPhoneNumber:
        entry = AllowedPhoneNumber(phone_number=normalized_phone, note=note)
        self.session.add(entry)
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def remove(self, entry_id: int) -> bool:
        entry = await self.session.get(AllowedPhoneNumber, entry_id)
        if entry is None:
            return False
        await self.session.delete(entry)
        await self.session.commit()
        return True
