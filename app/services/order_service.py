from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, User
from app.database.models.enums import DeliveryMode, OrderStatus
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.product_repo import ProductRepository
from app.services.exceptions import (
    InvalidOrderStateError,
    OutOfStockError,
    ProductUnavailableError,
)

order_logger = logging.getLogger("orders")
payment_logger = logging.getLogger("payments")


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.orders = OrderRepository(session)
        self.payments = PaymentRepository(session)
        self.products = ProductRepository(session)
        self.inventory = InventoryRepository(session)

    async def start_purchase(self, user: User, product_id: int, quantity: int = 1) -> Order:
        quantity = max(1, quantity)
        product = await self.products.get_by_id(product_id)
        if product is None or not product.is_visible:
            raise ProductUnavailableError("msg_product_unavailable")

        if product.delivery_mode == DeliveryMode.INVENTORY:
            stock = await self.products.available_stock(product.id)
            if stock < quantity:
                raise OutOfStockError("msg_out_of_stock")

        order = await self.orders.create(
            user_id=user.id,
            product_id=product.id,
            price=float(product.price) * quantity,
            currency=product.currency,
            quantity=quantity,
        )

        if product.delivery_mode == DeliveryMode.INVENTORY:
            # Reserve the actual codes right now — not just a count check —
            # so they can't also be promised to another customer while this
            # order is still awaiting proof/approval. Rare race: stock
            # passed the check above but got claimed by someone else a
            # moment later; if so, cancel this order immediately instead of
            # leaving a phantom order with nothing behind it.
            reserved = await self.inventory.reserve_many(product.id, order.id, quantity)
            if reserved is None:
                await self.orders.set_status(order, OrderStatus.CANCELLED)
                raise OutOfStockError("msg_out_of_stock")

        order_logger.info(
            "order_created id=%s user=%s product=%s price=%s qty=%s",
            order.order_uuid, user.telegram_id, product.name, product.price, quantity,
        )
        return order

    _CANCELLABLE_STATUSES = (OrderStatus.AWAITING_PROOF, OrderStatus.AWAITING_CRYPTO_PAYMENT)

    async def start_preorder(self, user: User, product_id: int) -> Order:
        """Pay-now-deliver-later path for an out-of-stock product (must be
        enabled via the "preorder_enabled" setting). Unlike `start_purchase`,
        this never checks or reserves inventory — there's nothing to reserve
        yet — and always marks the order `is_preorder=True` so
        `DeliveryService` routes it to the manual-delivery path regardless
        of the product's normal delivery mode (see `_run_delivery`), since
        auto-delivery would just fail with "out of stock" the moment an
        admin approves it before restocking."""
        product = await self.products.get_by_id(product_id)
        if product is None or not product.is_visible:
            raise ProductUnavailableError("msg_product_unavailable")

        order = await self.orders.create(
            user_id=user.id,
            product_id=product.id,
            price=float(product.price),
            currency=product.currency,
            is_preorder=True,
        )
        order_logger.info(
            "preorder_created id=%s user=%s product=%s price=%s",
            order.order_uuid, user.telegram_id, product.name, product.price,
        )
        return order

    async def cancel_pending(self, order_id: int) -> bool:
        """Called when a customer backs out before completing payment — the
        "❌ Cancel" button during the screenshot-upload step (AWAITING_PROOF)
        or on a still-unpaid crypto invoice (AWAITING_CRYPTO_PAYMENT), and
        also by the crypto poller's auto-timeout for abandoned invoices.
        Releases any inventory reservation made in `start_purchase` /
        `crypto_buy` back to the available pool. No-op (returns False) if
        the order has already moved past one of those two states (e.g.
        proof was already submitted, or payment already confirmed)."""
        order = await self.orders.get_by_id(order_id)
        if order is None or order.status not in self._CANCELLABLE_STATUSES:
            return False
        await self.orders.set_status(order, OrderStatus.CANCELLED)
        await self.inventory.release_reservation(order.id)
        order_logger.info("order_cancelled id=%s", order.order_uuid)
        return True

    async def submit_payment_proof(
        self, order_id: int, screenshot_file_id: str, instructions_snapshot: str | None
    ) -> Order:
        order = await self.orders.get_by_id(order_id)
        if order is None:
            raise InvalidOrderStateError("msg_order_not_found")
        if order.status != OrderStatus.AWAITING_PROOF:
            # Prevents duplicate proof submission / re-submitting after a
            # decision has already been made.
            raise InvalidOrderStateError(
                "msg_proof_already_submitted", status=order.status.value
            )

        await self.payments.create(
            order_id=order.id,
            screenshot_file_id=screenshot_file_id,
            instructions_snapshot=instructions_snapshot,
        )
        await self.orders.set_status(order, OrderStatus.PENDING_APPROVAL)
        payment_logger.info(
            "payment_proof_submitted order=%s user_id=%s", order.order_uuid, order.user_id
        )
        return order
