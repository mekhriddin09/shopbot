from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Setting


class SettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str, default: str = "") -> str:
        result = await self.session.execute(select(Setting).where(Setting.key == key))
        row = result.scalar_one_or_none()
        return row.value if row else default

    async def get_bool(self, key: str, default: bool = True) -> bool:
        value = await self.get(key, "1" if default else "0")
        return value == "1"

    async def set(self, key: str, value: str) -> None:
        result = await self.session.execute(select(Setting).where(Setting.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = value
        else:
            row = Setting(key=key, value=value)
            self.session.add(row)
        await self.session.commit()

    async def all(self) -> dict[str, str]:
        result = await self.session.execute(select(Setting))
        return {row.key: row.value for row in result.scalars().all()}
