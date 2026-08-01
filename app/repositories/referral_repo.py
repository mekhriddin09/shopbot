from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Order, ReferralWithdrawal, User
from app.database.models.enums import OrderStatus, ReferralWithdrawalStatus


class ReferralRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_stats(self, referrer_id: int) -> dict[str, int]:
        invited = await self.session.execute(
            select(func.count(User.id)).where(User.referred_by_id == referrer_id)
        )
        purchased = await self.session.execute(
            select(func.count(func.distinct(Order.user_id)))
            .join(User, User.id == Order.user_id)
            .where(User.referred_by_id == referrer_id, Order.status == OrderStatus.DELIVERED)
        )
        first_rewards = await self.session.execute(
            select(func.count(Order.id))
            .join(User, User.id == Order.user_id)
            .where(User.referred_by_id == referrer_id, Order.referral_is_first_reward.is_(True))
        )
        return {
            "invited": int(invited.scalar_one()),
            "purchased": int(purchased.scalar_one()),
            "first_rewards": int(first_rewards.scalar_one()),
        }

    async def create_withdrawal(self, user_id: int, amount: float) -> ReferralWithdrawal:
        withdrawal = ReferralWithdrawal(user_id=user_id, amount=amount, status=ReferralWithdrawalStatus.PENDING)
        self.session.add(withdrawal)
        await self.session.commit()
        await self.session.refresh(withdrawal)
        return withdrawal

    async def get_withdrawal(self, withdrawal_id: int) -> ReferralWithdrawal | None:
        result = await self.session.execute(
            select(ReferralWithdrawal)
            .options(selectinload(ReferralWithdrawal.user))
            .where(ReferralWithdrawal.id == withdrawal_id)
        )
        return result.scalar_one_or_none()

    async def mark_paid(self, withdrawal: ReferralWithdrawal, admin_id: int) -> None:
        """Deduct exactly the requested amount from the user's current
        balance (not reset to zero) — the balance may have kept growing
        after the request was made, e.g. from new referral purchases."""
        withdrawal.status = ReferralWithdrawalStatus.PAID
        withdrawal.decided_by_admin_id = admin_id
        withdrawal.decided_at = datetime.now(timezone.utc)
        user = await self.session.get(User, withdrawal.user_id)
        if user is not None:
            user.referral_balance = max(0.0, float(user.referral_balance) - float(withdrawal.amount))
        await self.session.commit()

    async def mark_rejected(self, withdrawal: ReferralWithdrawal, admin_id: int) -> None:
        withdrawal.status = ReferralWithdrawalStatus.REJECTED
        withdrawal.decided_by_admin_id = admin_id
        withdrawal.decided_at = datetime.now(timezone.utc)
        await self.session.commit()
