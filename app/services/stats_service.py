from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enums import OrderStatus
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.user_repo import UserRepository


@dataclass(slots=True)
class Statistics:
    total_users: int
    total_products: int
    total_orders: int
    pending_orders: int
    approved_orders: int
    rejected_orders: int
    delivered_orders: int
    total_sales: float
    most_sold: list[tuple[str, int]]


class StatsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.orders = OrderRepository(session)
        self.products = ProductRepository(session)
        self.users = UserRepository(session)

    async def collect(self) -> Statistics:
        return Statistics(
            total_users=await self.users.count_all(),
            total_products=await self.products.count(),
            total_orders=await self.orders.count_all(),
            pending_orders=await self.orders.count_by_status(OrderStatus.PENDING_APPROVAL),
            approved_orders=await self.orders.count_by_status(OrderStatus.APPROVED),
            rejected_orders=await self.orders.count_by_status(OrderStatus.REJECTED),
            delivered_orders=await self.orders.count_by_status(OrderStatus.DELIVERED),
            total_sales=await self.orders.total_sales(),
            most_sold=await self.orders.most_sold_products(),
        )
