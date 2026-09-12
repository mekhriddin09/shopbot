from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Order, ReferralRedemption, ReferralReward, ReferralWithdrawal, User
from app.database.models.enums import OrderStatus, ReferralRedemptionStatus, ReferralWithdrawalStatus


class ReferralRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_stats(self, referrer_id: int) -> dict[str, int]:
        # When the referral-confirmation anti-fraud gate is on (default),
        # both counts are scoped to `referral_confirmed=True` — a referred
        # user who hasn't passed the phone+captcha check yet (see
        # app/services/onboarding_service.py) doesn't count toward their
        # referrer's stats, so fake/bot-farmed accounts can't inflate them
        # just by clicking the link. If the admin turns that feature off,
        # fall back to counting every linked user like before (so numbers
        # don't mysteriously drop to zero when they disable it).
        from app.repositories.setting_repo import SettingRepository  # local import avoids a cycle

        verification_enabled = await SettingRepository(self.session).get_bool("referral_verification_enabled", True)
        confirmed_clause = [User.referral_confirmed.is_(True)] if verification_enabled else []

        invited = await self.session.execute(
            select(func.count(User.id)).where(User.referred_by_id == referrer_id, *confirmed_clause)
        )
        purchased = await self.session.execute(
            select(func.count(func.distinct(Order.user_id)))
            .join(User, User.id == Order.user_id)
            .where(
                User.referred_by_id == referrer_id,
                Order.status == OrderStatus.DELIVERED,
                *confirmed_clause,
            )
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

    # ------------------------------------------------------------------
    # Referral "shop" — admin-defined catalog items redeemable with balance
    # ------------------------------------------------------------------

    async def list_active_rewards(self) -> list[ReferralReward]:
        result = await self.session.execute(
            select(ReferralReward)
            .where(ReferralReward.is_active.is_(True))
            .order_by(ReferralReward.sort_order, ReferralReward.id)
        )
        return list(result.scalars().all())

    async def list_all_rewards(self) -> list[ReferralReward]:
        result = await self.session.execute(
            select(ReferralReward).order_by(ReferralReward.sort_order, ReferralReward.id)
        )
        return list(result.scalars().all())

    async def get_reward(self, reward_id: int) -> ReferralReward | None:
        return await self.session.get(ReferralReward, reward_id)

    async def create_reward(self, **fields) -> ReferralReward:
        reward = ReferralReward(**fields)
        self.session.add(reward)
        await self.session.commit()
        await self.session.refresh(reward)
        return reward

    async def update_reward(self, reward: ReferralReward, **fields) -> ReferralReward:
        for key, value in fields.items():
            setattr(reward, key, value)
        await self.session.commit()
        await self.session.refresh(reward)
        return reward

    async def has_redemptions(self, reward_id: int) -> bool:
        result = await self.session.execute(
            select(func.count(ReferralRedemption.id)).where(ReferralRedemption.reward_id == reward_id)
        )
        return int(result.scalar_one()) > 0

    async def delete_reward(self, reward: ReferralReward) -> bool:
        """Mirrors `ProductRepository.delete`: refuse to hard-delete a
        reward that already has redemption history (would violate the
        RESTRICT FK and, more importantly, would corrupt that history) —
        the caller should fall back to hiding it (`is_active=False`)."""
        if await self.has_redemptions(reward.id):
            return False
        await self.session.delete(reward)
        await self.session.commit()
        return True

    async def create_redemption(
        self, user_id: int, reward: ReferralReward, note: str | None
    ) -> ReferralRedemption:
        redemption = ReferralRedemption(
            user_id=user_id,
            reward_id=reward.id,
            reward_name_snapshot=reward.name,
            cost_snapshot=reward.cost,
            note=note,
            status=ReferralRedemptionStatus.PENDING,
        )
        self.session.add(redemption)
        await self.session.commit()
        await self.session.refresh(redemption)
        return redemption

    async def get_redemption(self, redemption_id: int) -> ReferralRedemption | None:
        result = await self.session.execute(
            select(ReferralRedemption)
            .options(selectinload(ReferralRedemption.user))
            .where(ReferralRedemption.id == redemption_id)
        )
        return result.scalar_one_or_none()

    async def mark_redemption_fulfilled(self, redemption: ReferralRedemption, admin_id: int) -> None:
        redemption.status = ReferralRedemptionStatus.FULFILLED
        redemption.decided_by_admin_id = admin_id
        redemption.decided_at = datetime.now(timezone.utc)
        await self.session.commit()

    async def mark_redemption_rejected(self, redemption: ReferralRedemption, admin_id: int) -> None:
        """Refund the reserved balance back to the user — the request never
        went through, so the spend shouldn't stick."""
        redemption.status = ReferralRedemptionStatus.REJECTED
        redemption.decided_by_admin_id = admin_id
        redemption.decided_at = datetime.now(timezone.utc)
        user = await self.session.get(User, redemption.user_id)
        if user is not None:
            user.referral_balance = float(user.referral_balance) + float(redemption.cost_snapshot)
        await self.session.commit()
