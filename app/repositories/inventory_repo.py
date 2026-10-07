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

    async def count_breakdown(self, product_id: int) -> tuple[int, int, int]:
        """(free, reserved, used) for one product.

        `count_unused` lumps free and reserved together, which is exactly
        why the admin panel could say "4 unused codes" while customers saw
        the product as sold out: customers only ever see *free* stock
        (unused AND not reserved), so 4 codes sitting in reservations for
        stale/abandoned orders looked like stock to the admin and like
        nothing to everyone else."""
        result = await self.session.execute(
            select(InventoryCode.is_used, InventoryCode.is_reserved, func.count(InventoryCode.id))
            .where(InventoryCode.product_id == product_id)
            .group_by(InventoryCode.is_used, InventoryCode.is_reserved)
        )
        free = reserved = used = 0
        for is_used, is_reserved, cnt in result.all():
            if is_used:
                used += int(cnt)
            elif is_reserved:
                reserved += int(cnt)
            else:
                free += int(cnt)
        return free, reserved, used

    async def list_reserved_with_orders(self, product_id: int) -> list[tuple[InventoryCode, "Order | None"]]:
        """Every reserved-but-unused code for this product, with the order
        holding it (None if the reservation points at nothing)."""
        from app.database.models import Order

        result = await self.session.execute(
            select(InventoryCode, Order)
            .outerjoin(Order, Order.id == InventoryCode.reserved_by_order_id)
            .where(
                InventoryCode.product_id == product_id,
                InventoryCode.is_used.is_(False),
                InventoryCode.is_reserved.is_(True),
            )
            .order_by(InventoryCode.id)
        )
        return [(code, order) for code, order in result.all()]

    async def release_orphan_reservations(self) -> int:
        """Release every reservation whose holding order can never deliver
        it any more: the order is gone, or it's already in a terminal state
        (cancelled / rejected / failed / delivered). A reservation in that
        state is purely a leak — nothing will ever finalize or release it —
        so freeing it is always safe."""
        from app.database.models import Order
        from app.database.models.enums import OrderStatus

        holding = (
            OrderStatus.AWAITING_PROOF,
            OrderStatus.AWAITING_CRYPTO_PAYMENT,
            OrderStatus.AWAITING_STARS_PAYMENT,
            OrderStatus.AWAITING_CARD_PAYMENT,
            OrderStatus.PENDING_APPROVAL,
            OrderStatus.APPROVED,
        )
        result = await self.session.execute(
            select(InventoryCode)
            .outerjoin(Order, Order.id == InventoryCode.reserved_by_order_id)
            .where(
                InventoryCode.is_used.is_(False),
                InventoryCode.is_reserved.is_(True),
                (Order.id.is_(None)) | (Order.status.not_in(holding)),
            )
        )
        items = list(result.scalars().all())
        for item in items:
            item.is_reserved = False
            item.reserved_by_order_id = None
        if items:
            await self.session.commit()
        return len(items)

    async def release_stale_proof_reservations(self, older_than_minutes: float) -> list[int]:
        """Release reservations held by orders still in AWAITING_PROOF (the
        customer tapped "I'll pay by card" but never sent a receipt) for
        longer than `older_than_minutes`. Unlike crypto/Stars/card-auto,
        this state had no timeout at all, so every customer who simply
        walked away kept a code locked forever.

        The order itself is deliberately left alone (not cancelled): if the
        customer does send a receipt later, OrderService.submit_payment_proof
        re-reserves, and approval falls back to claiming any free code
        anyway. Returns the affected order ids."""
        from datetime import timedelta

        from app.database.models import Order
        from app.database.models.enums import OrderStatus

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
        result = await self.session.execute(
            select(InventoryCode, Order)
            .join(Order, Order.id == InventoryCode.reserved_by_order_id)
            .where(
                InventoryCode.is_used.is_(False),
                InventoryCode.is_reserved.is_(True),
                Order.status == OrderStatus.AWAITING_PROOF,
            )
        )
        released_orders: set[int] = set()
        for item, order in result.all():
            created = order.created_at
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created is not None and created > cutoff:
                continue
            item.is_reserved = False
            item.reserved_by_order_id = None
            released_orders.add(order.id)
        if released_orders:
            await self.session.commit()
        return sorted(released_orders)

    async def has_reservation(self, order_id: int) -> bool:
        result = await self.session.execute(
            select(func.count(InventoryCode.id)).where(
                InventoryCode.reserved_by_order_id == order_id,
                InventoryCode.is_used.is_(False),
                InventoryCode.is_reserved.is_(True),
            )
        )
        return int(result.scalar_one()) > 0

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

    async def reserve_many(self, product_id: int, order_id: int, count: int) -> list[InventoryCode] | None:
        """Reserve `count` distinct codes for one order (multi-quantity
        purchases). All-or-nothing: if fewer than `count` are available,
        whatever was reserved during this call is released again and None
        is returned, so a partially-fulfillable order never leaves a
        partial reservation behind."""
        reserved: list[InventoryCode] = []
        for _ in range(max(count, 0)):
            item = await self.reserve_one(product_id, order_id)
            if item is None:
                break
            reserved.append(item)
        if len(reserved) < count:
            for item in reserved:
                item.is_reserved = False
                item.reserved_by_order_id = None
            if reserved:
                await self.session.commit()
            return None
        return reserved

    async def release_reservation(self, order_id: int) -> int:
        """Release every code reserved for this order (there can be more
        than one, for multi-quantity purchases) back to the available pool
        — called when an order is rejected or cancelled before delivery.
        Returns how many codes were released (0 if nothing was reserved)."""
        result = await self.session.execute(
            select(InventoryCode).where(
                InventoryCode.reserved_by_order_id == order_id,
                InventoryCode.is_used.is_(False),
            )
        )
        items = list(result.scalars().all())
        if not items:
            return 0
        for item in items:
            item.is_reserved = False
            item.reserved_by_order_id = None
        await self.session.commit()
        return len(items)

    async def finalize_reservation(self, order_id: int) -> list[InventoryCode]:
        """Turn every code reserved for this order into actually-used
        (delivered) codes — called on approval. Returns an empty list if
        this order never had a reservation (e.g. it was created before
        reservations existed), so the caller can fall back to
        `claim_one_unused`."""
        result = await self.session.execute(
            select(InventoryCode).where(
                InventoryCode.reserved_by_order_id == order_id,
                InventoryCode.is_used.is_(False),
            )
        )
        items = list(result.scalars().all())
        if not items:
            return []
        now = datetime.now(timezone.utc)
        for item in items:
            item.is_used = True
            item.is_reserved = False
            item.used_by_order_id = order_id
            item.used_at = now
        await self.session.commit()
        for item in items:
            await self.session.refresh(item)
        return items
