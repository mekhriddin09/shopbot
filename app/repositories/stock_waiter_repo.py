from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import StockWaiter


class StockWaiterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def subscribe(self, user_id: int, product_id: int) -> StockWaiter:
        """Create a waiter row, or reset an existing one back to
        "not yet notified" — this is what lets a customer ask to be told
        again about a *future* restock after already being notified once."""
        result = await self.session.execute(
            select(StockWaiter).where(StockWaiter.user_id == user_id, StockWaiter.product_id == product_id)
        )
        waiter = result.scalar_one_or_none()
        if waiter is None:
            waiter = StockWaiter(user_id=user_id, product_id=product_id, notified=False)
            self.session.add(waiter)
        else:
            waiter.notified = False
        await self.session.commit()
        await self.session.refresh(waiter)
        return waiter

    async def count_waiting(self, product_id: int) -> int:
        result = await self.session.execute(
            select(StockWaiter).where(StockWaiter.product_id == product_id, StockWaiter.notified.is_(False))
        )
        return len(result.scalars().all())

    async def list_waiting(self, product_id: int) -> list[StockWaiter]:
        result = await self.session.execute(
            select(StockWaiter)
            .options(selectinload(StockWaiter.user))
            .where(StockWaiter.product_id == product_id, StockWaiter.notified.is_(False))
        )
        return list(result.scalars().all())

    async def mark_all_notified(self, product_id: int) -> list[StockWaiter]:
        """Returns the list that was just notified (so the caller can fan
        out messages) and flips them all to notified=True in one go."""
        waiters = await self.list_waiting(product_id)
        for w in waiters:
            w.notified = True
        if waiters:
            await self.session.commit()
        return waiters
