from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Product
from app.database.models.enums import DeliveryMode
from app.repositories.product_repo import ProductRepository


@dataclass(slots=True)
class ProductView:
    product: Product
    stock: int  # -1 means unlimited/not tracked

    @property
    def in_stock(self) -> bool:
        return self.stock != 0


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.products = ProductRepository(session)

    async def list_shop(self) -> list[ProductView]:
        items = await self.products.list_visible()
        views: list[ProductView] = []
        for product in items:
            stock = (
                await self.products.available_stock(product.id)
                if product.delivery_mode == DeliveryMode.INVENTORY
                else -1
            )
            views.append(ProductView(product=product, stock=stock))
        return views

    async def get_view(self, product_id: int) -> ProductView | None:
        product = await self.products.get_by_id(product_id)
        if product is None:
            return None
        stock = (
            await self.products.available_stock(product.id)
            if product.delivery_mode == DeliveryMode.INVENTORY
            else -1
        )
        return ProductView(product=product, stock=stock)
