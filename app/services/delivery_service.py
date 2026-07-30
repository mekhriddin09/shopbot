"""Order approval + delivery orchestration.

This is the most security-sensitive module in the project: it is the only
place that is allowed to (a) approve/reject an order and (b) hand out a
digital good. Every entry point re-checks the order's current status *after*
acquiring a per-order asyncio lock, so:

  - Double-tapping "Approve" (callback spam) cannot approve twice.
  - Two admins approving the same order at the same instant cannot both
    succeed.
  - A code can never be claimed/sent twice (guarded again at the DB level
    in InventoryRepository.claim_one_unused via SELECT ... FOR UPDATE).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order
from app.database.models.enums import DeliveryMode, OrderStatus
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.provider_log_repo import ProviderLogRepository
from app.repositories.setting_repo import SettingRepository
from app.services.exceptions import DeliveryFailedError, InvalidOrderStateError
from app.services.providers.registry import get_provider
from app.utils.locks import lock_for

order_logger = logging.getLogger("orders")
providers_logger = logging.getLogger("providers")


@dataclass(slots=True)
class ApprovalResult:
    order: Order
    delivery_mode: DeliveryMode
    delivered_now: bool
    payload: str | None = None          # ready-to-send text (inventory/api)
    needs_manual_message: bool = False   # admin must now type the message


class DeliveryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.orders = OrderRepository(session)
        self.inventory = InventoryRepository(session)
        self.provider_logs = ProviderLogRepository(session)
        self.settings = SettingRepository(session)

    async def approve_order(self, order_id: int, admin_id: int) -> ApprovalResult:
        async with lock_for(f"order:{order_id}"):
            order = await self.orders.get_by_id(order_id)
            if order is None:
                raise InvalidOrderStateError("msg_order_not_found")
            if order.status != OrderStatus.PENDING_APPROVAL:
                raise InvalidOrderStateError(
                    "msg_order_already_reviewed", status=order.status.value
                )

            await self.orders.set_status(order, OrderStatus.APPROVED, admin_id=admin_id)
            order_logger.info(
                "order_approved id=%s admin=%s product=%s", order.order_uuid, admin_id, order.product_id
            )
            return await self._run_delivery(order)

    async def auto_deliver_crypto(self, order_id: int) -> ApprovalResult:
        """Called by the crypto payment poller once an invoice is confirmed
        paid. Skips admin approval entirely (per product/business decision:
        crypto payments are auto-verified, so there is nothing for a human
        to check) and goes straight to delivery."""
        async with lock_for(f"order:{order_id}"):
            order = await self.orders.get_by_id(order_id)
            if order is None:
                raise InvalidOrderStateError("msg_order_not_found")
            if order.status != OrderStatus.AWAITING_CRYPTO_PAYMENT:
                raise InvalidOrderStateError(
                    "msg_not_awaiting_crypto", status=order.status.value
                )
            await self.orders.set_status(order, OrderStatus.APPROVED, admin_id=None)
            order_logger.info(
                "order_auto_approved_crypto id=%s product=%s", order.order_uuid, order.product_id
            )
            return await self._run_delivery(order)

    async def _run_delivery(self, order: Order) -> ApprovalResult:
        """Shared mode-dispatch logic for both manual admin approval and
        automatic crypto-confirmed delivery. Assumes the order is already
        in APPROVED status and the per-order lock is held by the caller."""
        mode = order.product.delivery_mode

        if mode == DeliveryMode.INVENTORY:
            if not await self.settings.get_bool("automatic_delivery_enabled", True):
                return ApprovalResult(order, mode, delivered_now=False, needs_manual_message=True)
            # Prefer finalizing the code already reserved for this order at
            # purchase time (see OrderService.start_purchase / crypto_buy);
            # fall back to claiming a fresh one for orders created before
            # reservations existed.
            code = await self.inventory.finalize_reservation(order.id)
            if code is None:
                code = await self.inventory.claim_one_unused(order.product_id, order.id)
            if code is None:
                order_logger.error("order_delivery_out_of_stock id=%s", order.order_uuid)
                await self.orders.set_status(order, OrderStatus.FAILED)
                raise DeliveryFailedError("msg_out_of_inventory")
            await self.orders.mark_delivered(order, code.code)
            order_logger.info("order_delivered id=%s mode=inventory", order.order_uuid)
            return ApprovalResult(order, mode, delivered_now=True, payload=code.code)

        if mode == DeliveryMode.API:
            if not await self.settings.get_bool("api_delivery_enabled", True):
                return ApprovalResult(order, mode, delivered_now=False, needs_manual_message=True)
            provider = get_provider(order.product.provider_key)
            if provider is None:
                providers_logger.error(
                    "provider_missing key=%s order=%s", order.product.provider_key, order.order_uuid
                )
                await self.orders.set_status(order, OrderStatus.FAILED)
                raise DeliveryFailedError("msg_provider_not_configured")

            result = await provider.fetch(
                product_external_ref=order.product.external_product_id or order.product.provider_key,
                order_uuid=order.order_uuid,
            )
            await self.provider_logs.log(
                provider_key=provider.key,
                order_id=order.id,
                request_payload=result.raw_request,
                response_payload=result.raw_response,
                success=result.success,
                error=result.error,
            )
            if not result.success or not result.payload:
                providers_logger.error(
                    "provider_delivery_failed order=%s error=%s", order.order_uuid, result.error
                )
                error_text = result.error or "unknown error"
                await self.orders.set_status(order, OrderStatus.FAILED)
                raise DeliveryFailedError("msg_provider_fetch_failed", error=error_text)
            await self.orders.mark_delivered(order, result.payload)
            order_logger.info("order_delivered id=%s mode=api", order.order_uuid)
            return ApprovalResult(order, mode, delivered_now=True, payload=result.payload)

        # MANUAL mode: admin must type the message next.
        if not await self.settings.get_bool("manual_delivery_enabled", True):
            await self.orders.set_status(order, OrderStatus.FAILED)
            raise DeliveryFailedError("msg_manual_delivery_disabled")
        return ApprovalResult(order, mode, delivered_now=False, needs_manual_message=True)

    async def deliver_manual_message(self, order_id: int, admin_id: int, message: str) -> Order:
        async with lock_for(f"order:{order_id}"):
            order = await self.orders.get_by_id(order_id)
            if order is None:
                raise InvalidOrderStateError("msg_order_not_found")
            # APPROVED = normal manual-mode flow; FAILED = recovering an
            # order whose automatic delivery (inventory/API) failed after
            # approval — same "already approved, just deliver by hand" fix.
            if order.status not in (OrderStatus.APPROVED, OrderStatus.FAILED):
                raise InvalidOrderStateError(
                    "msg_cant_send_message", status=order.status.value
                )
            if order.product.delivery_mode == DeliveryMode.INVENTORY:
                # Best-effort: if this order still had a reserved-but-not-yet
                # -used code (e.g. automatic_delivery_enabled was off), turn
                # it into "used" now so stock bookkeeping stays accurate.
                await self.inventory.finalize_reservation(order.id)
            await self.orders.mark_delivered(order, message)
            order_logger.info("order_delivered id=%s mode=manual admin=%s", order.order_uuid, admin_id)
            return order

    async def reject_order(self, order_id: int, admin_id: int, reason: str | None) -> Order:
        async with lock_for(f"order:{order_id}"):
            order = await self.orders.get_by_id(order_id)
            if order is None:
                raise InvalidOrderStateError("msg_order_not_found")
            if order.status != OrderStatus.PENDING_APPROVAL:
                raise InvalidOrderStateError(
                    "msg_order_already_reviewed", status=order.status.value
                )
            await self.orders.set_status(
                order, OrderStatus.REJECTED, admin_id=admin_id, rejection_reason=reason
            )
            # Release any inventory code reserved for this order at purchase
            # time — no-op if this order's product isn't INVENTORY mode or
            # nothing was reserved.
            await self.inventory.release_reservation(order.id)
            order_logger.info("order_rejected id=%s admin=%s reason=%s", order.order_uuid, admin_id, reason)
            return order
