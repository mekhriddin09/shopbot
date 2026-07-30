from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Review


class ReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, user_id: int, order_id: int | None, rating: int, text: str) -> Review:
        review = Review(user_id=user_id, order_id=order_id, rating=rating, text=text)
        self.session.add(review)
        await self.session.commit()
        await self.session.refresh(review)
        return review

    async def create_manual(self, admin_user_id: int, author_name: str | None, rating: int, text: str) -> Review:
        """Admin-written review — linked to the admin's own user row (so the
        `user_id` FK is satisfied) but displayed under `author_name` instead
        of the admin's own name/username."""
        review = Review(
            user_id=admin_user_id,
            rating=rating,
            text=text,
            author_name=author_name or None,
        )
        self.session.add(review)
        await self.session.commit()
        await self.session.refresh(review)
        return review

    async def list_published(self, limit: int = 10) -> list[Review]:
        result = await self.session.execute(
            select(Review)
            .options(selectinload(Review.user))
            .where(Review.is_published.is_(True))
            .order_by(Review.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_all(self, limit: int = 50) -> list[Review]:
        result = await self.session.execute(
            select(Review)
            .options(selectinload(Review.user))
            .order_by(Review.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id(self, review_id: int) -> Review | None:
        result = await self.session.execute(
            select(Review).options(selectinload(Review.user)).where(Review.id == review_id)
        )
        return result.scalar_one_or_none()

    async def delete(self, review: Review) -> None:
        await self.session.delete(review)
        await self.session.commit()
