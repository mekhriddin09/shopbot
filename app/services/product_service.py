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
        # Deliberately does NOT do a live API stock lookup here (see
        # `live_stock`) — this renders every visible product at once, and
        # a slow/unreachable supplier would multiply into a slow/broken
        # shop list for every customer. The live check happens once the
        # customer opens a *specific* product (`get_view`), which is also
        # the point where it actually matters for their purchase decision.
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
        stock = await self.live_stock(product)
        return ProductView(product=product, stock=stock)

    async def live_stock(self, product: Product) -> int:
        """Real-time stock, used both for display (`get_view`) and for
        pre-purchase gating in the buy/crypto/stars handlers — mirrors the
        check already done for INVENTORY-mode products so a customer can't
        pay for something the external supplier doesn't actually have.

        INVENTORY: exact count from locally-held codes.
        API: live `provider.get_stock_count()` call against the supplier;
             falls back to -1 ("unknown, don't block the purchase") if the
             provider doesn't support this, the product has no external ID
             configured, or the supplier call fails for any reason — same
             behavior as before this existed, so a flaky supplier API can
             never itself block a sale.
        MANUAL: always -1 (no stock concept — admin fulfils by hand).
        """
        if product.delivery_mode == DeliveryMode.INVENTORY:
            return await self.products.available_stock(product.id)
        if product.delivery_mode == DeliveryMode.API and product.provider_key and product.external_product_id:
            from app.services.providers.registry import get_provider  # local import avoids a cycle

            provider = get_provider(product.provider_key)
            if provider is not None:
                count = await provider.get_stock_count(product.external_product_id)
                if count is not None:
                    return count
        return -1

    async def stock_shortfall(self, product: Product, qty: int = 1) -> bool:
        """True only if this product genuinely doesn't have `qty` units
        available right now (used by the buy/crypto/stars pre-purchase
        checks). MANUAL delivery, or API delivery where the supplier can't
        be reached / doesn't expose a count (`live_stock` returning -1),
        never counts as a shortfall — same fail-open behavior this bot has
        always used, so a flaky supplier API can never itself block a
        sale."""
        if product.delivery_mode not in (DeliveryMode.INVENTORY, DeliveryMode.API):
            return False
        stock = await self.live_stock(product)
        if stock < 0:
            return False
        return stock < qty
