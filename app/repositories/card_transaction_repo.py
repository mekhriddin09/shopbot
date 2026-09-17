from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import CardTransaction
from app.database.models.enums import CardTransactionStatus


class CardTransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_message_key(self, message_key: str) -> CardTransaction | None:
        result = await self.session.execute(
            select(CardTransaction).where(CardTransaction.message_key == message_key)
        )
        return result.scalar_one_or_none()

    async def create(self, **fields) -> CardTransaction:
        tx = CardTransaction(**fields)
        self.session.add(tx)
        await self.session.commit()
        await self.session.refresh(tx)
        return tx

    async def set_status(
        self, tx: CardTransaction, status: CardTransactionStatus, *, matched_order_id: int | None = None
    ) -> None:
        tx.status = status
        if matched_order_id is not None:
            tx.matched_order_id = matched_order_id
        await self.session.commit()

    async def list_recent(self, limit: int = 30) -> list[CardTransaction]:
        result = await self.session.execute(
            select(CardTransaction)
            .options(selectinload(CardTransaction.matched_order))
            .order_by(CardTransaction.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_needing_review(self, limit: int = 30) -> list[CardTransaction]:
        """Money that arrived but wasn't automatically attributed to an
        order — the queue an admin actually has to act on."""
        result = await self.session.execute(
            select(CardTransaction)
            .options(selectinload(CardTransaction.matched_order))
            .where(
                CardTransaction.status.in_(
                    [
                        CardTransactionStatus.UNMATCHED,
                        CardTransactionStatus.AMBIGUOUS,
                        CardTransactionStatus.UNPARSED,
                    ]
                )
            )
            .order_by(CardTransaction.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
