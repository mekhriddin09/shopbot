from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self, telegram_id: int, username: str | None, full_name: str | None, language: str
    ) -> tuple[User, bool]:
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            changed = False
            if user.username != username:
                user.username = username
                changed = True
            if user.full_name != full_name:
                user.full_name = full_name
                changed = True
            if changed:
                await self.session.commit()
            return user, False

        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
            language=language,
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user, True

    async def set_language(self, user: User, language: str) -> None:
        user.language = language
        await self.session.commit()

    async def set_blocked(self, user: User, blocked: bool) -> None:
        user.is_blocked = blocked
        await self.session.commit()

    async def count_all(self) -> int:
        result = await self.session.execute(select(func.count(User.id)))
        return int(result.scalar_one())

    async def list_all(self) -> list[User]:
        """Every non-blocked user — the base pool for broadcast messages.
        Users blocked by an admin (`is_blocked`) are excluded; users who
        blocked the *bot* itself aren't tracked here and are instead skipped
        one-by-one at send time (Telegram raises when we try to message
        them)."""
        result = await self.session.execute(
            select(User).where(User.is_blocked.is_(False))
        )
        return list(result.scalars().all())
