from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Order, Product, User
from app.database.models.enums import OrderStatus, PaymentMethod


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        user_id: int,
        product_id: int,
        price: float,
        currency: str,
        *,
        payment_method: PaymentMethod = PaymentMethod.CARD,
        status: OrderStatus = OrderStatus.AWAITING_PROOF,
        crypto_provider: str | None = None,
        crypto_invoice_id: str | None = None,
        crypto_pay_url: str | None = None,
        quantity: int = 1,
        is_preorder: bool = False,
    ) -> Order:
        order = Order(
            user_id=user_id,
            product_id=product_id,
            price_at_purchase=price,
            currency=currency,
            status=status,
            payment_method=payment_method,
            crypto_provider=crypto_provider,
            crypto_invoice_id=crypto_invoice_id,
            crypto_pay_url=crypto_pay_url,
            quantity=quantity,
            is_preorder=is_preorder,
        )
        self.session.add(order)
        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def list_awaiting_crypto_payment(self) -> list[Order]:
        result = await self.session.execute(
            select(Order)
            .options(selectinload(Order.product), selectinload(Order.user))
            .where(Order.status == OrderStatus.AWAITING_CRYPTO_PAYMENT)
        )
        return list(result.scalars().all())

    async def list_awaiting_stars_payment(self) -> list[Order]:
        result = await self.session.execute(
            select(Order)
            .options(selectinload(Order.product), selectinload(Order.user))
            .where(Order.status == OrderStatus.AWAITING_STARS_PAYMENT)
        )
        return list(result.scalars().all())

    async def get_by_id(self, order_id: int, *, for_update: bool = False) -> Order | None:
        stmt = (
            select(Order)
            .options(selectinload(Order.product), selectinload(Order.user))
            .where(Order.id == order_id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_uuid(self, order_uuid: str) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .options(selectinload(Order.product), selectinload(Order.user))
            .where(Order.order_uuid == order_uuid)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int, limit: int = 20) -> list[Order]:
        result = await self.session.execute(
            select(Order)
            .options(selectinload(Order.product))
            .where(Order.user_id == user_id)
            .order_by(Order.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_status(self, status: OrderStatus, limit: int = 50) -> list[Order]:
        result = await self.session.execute(
            select(Order)
            .options(selectinload(Order.product), selectinload(Order.user))
            .where(Order.status == status)
            .order_by(Order.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def search_by_product_name(self, name_query: str, limit: int = 50) -> list[Order]:
        result = await self.session.execute(
            select(Order)
            .join(Product)
            .options(selectinload(Order.product), selectinload(Order.user))
            .where(Product.name.ilike(f"%{name_query}%"))
            .order_by(Order.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def search_by_user(self, telegram_id_or_username: str, limit: int = 50) -> list[Order]:
        query = telegram_id_or_username.lstrip("@")
        stmt = (
            select(Order)
            .join(User)
            .options(selectinload(Order.product), selectinload(Order.user))
            .order_by(Order.id.desc())
            .limit(limit)
        )
        if query.isdigit():
            stmt = stmt.where(User.telegram_id == int(query))
        else:
            stmt = stmt.where(User.username.ilike(f"%{query}%"))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def set_status(
        self,
        order: Order,
        status: OrderStatus,
        *,
        admin_id: int | None = None,
        rejection_reason: str | None = None,
    ) -> None:
        order.status = status
        if admin_id is not None:
            order.decided_by_admin_id = admin_id
            order.decided_at = datetime.now(timezone.utc)
        if rejection_reason is not None:
            order.rejection_reason = rejection_reason
        await self.session.commit()

    async def set_crypto_invoice(self, order: Order, invoice_id: str, pay_url: str) -> None:
        order.crypto_invoice_id = invoice_id
        order.crypto_pay_url = pay_url
        await self.session.commit()

    async def mark_delivered(self, order: Order, payload: str) -> None:
        order.status = OrderStatus.DELIVERED
        order.delivered_payload = payload
        order.delivered_at = datetime.now(timezone.utc)
        await self.session.commit()

    async def count_by_status(self, status: OrderStatus) -> int:
        result = await self.session.execute(
            select(func.count(Order.id)).where(Order.status == status)
        )
        return int(result.scalar_one())

    async def count_all(self) -> int:
        result = await self.session.execute(select(func.count(Order.id)))
        return int(result.scalar_one())

    async def total_sales(self) -> float:
        result = await self.session.execute(
            select(func.coalesce(func.sum(Order.price_at_purchase), 0)).where(
                Order.status == OrderStatus.DELIVERED
            )
        )
        return float(result.scalar_one())

    async def count_delivered_by_user(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count(Order.id)).where(Order.user_id == user_id, Order.status == OrderStatus.DELIVERED)
        )
        return int(result.scalar_one())

    async def list_buyer_user_ids(self, product_id: int | None = None) -> set[int]:
        """Distinct `user_id`s that have at least one successfully DELIVERED
        order — the definition of "a customer" used by the broadcast
        audience filter (task: xarid qilgan/qilmagan). Optionally scoped to
        a single product for the "by product" filter."""
        stmt = select(Order.user_id).where(Order.status == OrderStatus.DELIVERED).distinct()
        if product_id is not None:
            stmt = stmt.where(Order.product_id == product_id)
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def most_sold_products(self, limit: int = 5) -> list[tuple[str, int]]:
        result = await self.session.execute(
            select(Product.name, func.count(Order.id).label("cnt"))
            .join(Order, Order.product_id == Product.id)
            .where(Order.status == OrderStatus.DELIVERED)
            .group_by(Product.id)
            .order_by(func.count(Order.id).desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]
