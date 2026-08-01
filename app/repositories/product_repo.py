from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import InventoryCode, Order, Product
from app.database.models.enums import DeliveryMode


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_visible(self) -> list[Product]:
        result = await self.session.execute(
            select(Product)
            .where(Product.is_visible.is_(True))
            .order_by(Product.sort_order, Product.id)
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[Product]:
        result = await self.session.execute(
            select(Product).order_by(Product.sort_order, Product.id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, product_id: int) -> Product | None:
        result = await self.session.execute(
            select(Product).where(Product.id == product_id)
        )
        return result.scalar_one_or_none()

    async def get_with_codes(self, product_id: int) -> Product | None:
        result = await self.session.execute(
            select(Product)
            .options(selectinload(Product.inventory_codes))
            .where(Product.id == product_id)
        )
        return result.scalar_one_or_none()

    async def available_stock(self, product_id: int) -> int:
        """Codes that are neither delivered nor already promised to another
        pending order. Reserved-but-not-yet-approved codes are excluded so
        the stock count shown to customers can't oversell while orders are
        awaiting approval/payment confirmation."""
        result = await self.session.execute(
            select(func.count(InventoryCode.id)).where(
                InventoryCode.product_id == product_id,
                InventoryCode.is_used.is_(False),
                InventoryCode.is_reserved.is_(False),
            )
        )
        return int(result.scalar_one())

    async def create(self, **fields) -> Product:
        product = Product(**fields)
        self.session.add(product)
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def update(self, product: Product, **fields) -> Product:
        for key, value in fields.items():
            setattr(product, key, value)
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def has_orders(self, product_id: int) -> bool:
        result = await self.session.execute(
            select(func.count(Order.id)).where(Order.product_id == product_id)
        )
        return int(result.scalar_one()) > 0

    async def delete(self, product: Product) -> bool:
        """Returns True if the product was actually deleted. Returns False
        (without touching the database) if this product has at least one
        Order ever placed against it — `Order.product_id` is a RESTRICT
        foreign key on purpose: deleting the product out from under
        historical orders would either orphan them or silently erase order
        history/stats. Checking first (rather than attempting the delete
        and catching the resulting IntegrityError) avoids leaving the
        session's transaction in a failed state. Callers should fall back
        to hiding the product instead."""
        if await self.has_orders(product.id):
            return False
        await self.session.delete(product)
        await self.session.commit()
        return True

    async def set_visibility(self, product: Product, visible: bool) -> None:
        product.is_visible = visible
        await self.session.commit()

    async def move(self, product: Product, new_sort_order: int) -> None:
        product.sort_order = new_sort_order
        await self.session.commit()

    async def count(self) -> int:
        result = await self.session.execute(select(func.count(Product.id)))
        return int(result.scalar_one())
