from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SupportRelay


class SupportRelayRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, user_telegram_id: int, admin_telegram_id: int, admin_message_id: int) -> SupportRelay:
        relay = SupportRelay(
            user_telegram_id=user_telegram_id,
            admin_telegram_id=admin_telegram_id,
            admin_message_id=admin_message_id,
        )
        self.session.add(relay)
        await self.session.commit()
        return relay

    async def find_user_telegram_id(self, admin_telegram_id: int, admin_message_id: int) -> int | None:
        result = await self.session.execute(
            select(SupportRelay.user_telegram_id).where(
                SupportRelay.admin_telegram_id == admin_telegram_id,
                SupportRelay.admin_message_id == admin_message_id,
            )
        )
        return result.scalar_one_or_none()
