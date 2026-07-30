from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import InventoryCode


class InventoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_code(self, product_id: int, code: str) -> InventoryCode:
        item = InventoryCode(product_id=product_id, code=code.strip())
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def bulk_import(self, product_id: int, codes: list[str]) -> int:
        clean = [c.strip() for c in codes if c.strip()]
        if not clean:
            return 0
        self.session.add_all(InventoryCode(product_id=product_id, code=c) for c in clean)
        await self.session.commit()
        return len(clean)

    async def delete_code(self, code_id: int) -> bool:
        item = await self.session.get(InventoryCode, code_id)
        if item is None:
            return False
        await self.session.delete(item)
        await self.session.commit()
        return True

    async def delete_codes(self, code_ids: list[int]) -> int:
        """Bulk-delete a specific set of codes (used by the multi-select
        picker). Never deletes a code that's already been used/delivered —
        only unused codes should ever be selectable in that UI, but this is
        a defensive second guard against deleting a code a customer already
        received."""
        if not code_ids:
            return 0
        result = await self.session.execute(
            delete(InventoryCode).where(
                InventoryCode.id.in_(code_ids), InventoryCode.is_used.is_(False)
            )
        )
        await self.session.commit()
        return result.rowcount or 0

    async def delete_all_unused(self, product_id: int) -> int:
        result = await self.session.execute(
            delete(InventoryCode).where(
                InventoryCode.product_id == product_id, InventoryCode.is_used.is_(False)
            )
        )
        await self.session.commit()
        return result.rowcount or 0

    async def list_codes(self, product_id: int, only_unused: bool = False) -> list[InventoryCode]:
        stmt = select(InventoryCode).where(InventoryCode.product_id == product_id)
        if only_unused:
            stmt = stmt.where(InventoryCode.is_used.is_(False))
        stmt = stmt.order_by(InventoryCode.id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_unused(self, product_id: int) -> int:
        result = await self.session.execute(
            select(func.count(InventoryCode.id)).where(
                InventoryCode.product_id == product_id,
                InventoryCode.is_used.is_(False),
            )
        )
        return int(result.scalar_one())

    async def claim_one_unused(self, product_id: int, order_id: int) -> InventoryCode | None:
        """Atomically claim and mark-used one code for the given product.

        Uses SELECT ... FOR UPDATE (row lock) so that two concurrent
        approvals for the same product can never claim the same code.
        Must be called within a transaction (the caller commits).
        """
        stmt = (
            select(InventoryCode)
            .where(
                InventoryCode.product_id == product_id,
                InventoryCode.is_used.is_(False),
                InventoryCode.is_reserved.is_(False),
            )
            .order_by(InventoryCode.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        item = result.scalar_one_or_none()
        if item is None:
            return None
        item.is_used = True
        item.used_by_order_id = order_id
        item.used_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def reserve_one(self, product_id: int, order_id: int) -> InventoryCode | None:
        """Atomically reserve (but not yet mark used) one unused, unreserved
        code for the given product — called the moment a customer starts a
        purchase, so the same code can never be promised to more than one
        pending order at once. Same row-lock pattern as `claim_one_unused`."""
        stmt = (
            select(InventoryCode)
            .where(
                InventoryCode.product_id == product_id,
                InventoryCode.is_used.is_(False),
                InventoryCode.is_reserved.is_(False),
            )
            .order_by(InventoryCode.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        item = result.scalar_one_or_none()
        if item is None:
            return None
        item.is_reserved = True
        item.reserved_by_order_id = order_id
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def release_reservation(self, order_id: int) -> bool:
        """Release the code reserved for this order (if any) back to the
        available pool — called when an order is rejected or cancelled
        before delivery. No-op (returns False) if nothing was reserved."""
        result = await self.session.execute(
            select(InventoryCode).where(
                InventoryCode.reserved_by_order_id == order_id,
                InventoryCode.is_used.is_(False),
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            return False
        item.is_reserved = False
        item.reserved_by_order_id = None
        await self.session.commit()
        return True

    async def finalize_reservation(self, order_id: int) -> InventoryCode | None:
        """Turn this order's existing reservation into an actually-used
        (delivered) code — called on approval. Returns None if this order
        never had a reservation (e.g. it was created before reservations
        existed), so the caller can fall back to `claim_one_unused`."""
        result = await self.session.execute(
            select(InventoryCode).where(
                InventoryCode.reserved_by_order_id == order_id,
                InventoryCode.is_used.is_(False),
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            return None
        item.is_used = True
        item.is_reserved = False
        item.used_by_order_id = order_id
        item.used_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item
