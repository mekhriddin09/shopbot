from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Payment


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, order_id: int, screenshot_file_id: str, instructions_snapshot: str | None, method: str | None = None
    ) -> Payment:
        payment = Payment(
            order_id=order_id,
            screenshot_file_id=screenshot_file_id,
            instructions_snapshot=instructions_snapshot,
            method=method,
        )
        self.session.add(payment)
        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def get_by_order(self, order_id: int) -> Payment | None:
        result = await self.session.execute(
            select(Payment).where(Payment.order_id == order_id)
        )
        return result.scalar_one_or_none()
