from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AdminUser
from app.database.models.enums import AdminRole


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(self) -> list[AdminUser]:
        result = await self.session.execute(
            select(AdminUser).where(AdminUser.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def get(self, telegram_id: int) -> AdminUser | None:
        result = await self.session.execute(
            select(AdminUser).where(AdminUser.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def add(self, telegram_id: int, added_by: int) -> AdminUser:
        existing = await self.get(telegram_id)
        if existing:
            existing.is_active = True
            await self.session.commit()
            return existing
        admin = AdminUser(telegram_id=telegram_id, added_by=added_by, role=AdminRole.ADMIN)
        self.session.add(admin)
        await self.session.commit()
        await self.session.refresh(admin)
        return admin

    async def deactivate(self, telegram_id: int) -> bool:
        admin = await self.get(telegram_id)
        if not admin:
            return False
        admin.is_active = False
        await self.session.commit()
        return True
