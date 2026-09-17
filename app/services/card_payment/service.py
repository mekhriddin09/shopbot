"""Automatic card payment verification: issue a unique amount per order,
then attribute incoming bank alerts back to the order that expected them.

Why unique amounts at all: a UZCARD alert says how much arrived, not who
sent it. Giving every pending order its own amount turns the amount itself
into the identifier. That only works while no two awaiting orders share an
amount, which is enforced here *and* in the database.

Safety posture throughout: when anything is uncertain — no candidate, more
than one candidate, an unreadable alert — the money is recorded and an
admin is asked. Automatic delivery only ever happens on an unambiguous,
in-window, exact match.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import CardTransaction, Order
from app.database.models.enums import CardTransactionStatus, OrderStatus
from app.repositories.card_transaction_repo import CardTransactionRepository
from app.repositories.setting_repo import SettingRepository
from app.services.card_payment.parser import CardNotification, parse_card_message
from app.utils.locks import lock_for

logger = logging.getLogger("card_payment")

# Discount band subtracted from the price to make an order's amount unique.
_MIN_DISCOUNT = 1
_MAX_DISCOUNT = 99

# Amounts are compared in whole currency units after rounding to 2dp; this
# tolerance only absorbs float representation noise, never a real
# difference (0.01 UZS apart is still a mismatch).
_EPSILON = 0.005


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes even for timezone=True columns;
    treat those as UTC so comparisons against `_now()` don't explode."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class CardPaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = SettingRepository(session)
        self.transactions = CardTransactionRepository(session)

    # ------------------------------------------------------------------
    # Issuing an amount
    # ------------------------------------------------------------------

    async def _amounts_in_use(self) -> set[float]:
        """Every amount currently spoken for by an order still awaiting
        payment. Deliberately global rather than per-product: two products
        priced 30 000 and 30 020 generate overlapping discount bands, so
        scoping this per product would allow a collision across them."""
        result = await self.session.execute(
            select(Order.expected_amount).where(
                Order.status == OrderStatus.AWAITING_CARD_PAYMENT,
                Order.expected_amount.is_not(None),
            )
        )
        return {round(float(a), 2) for a in result.scalars().all() if a is not None}

    async def generate_unique_amount(self, price: float) -> float | None:
        """price - random(1..99), avoiding every amount already in use.

        Returns None when the whole band is exhausted (i.e. ~99 orders are
        awaiting payment around this price) — the caller must then refuse
        the purchase rather than issue a duplicate amount, because a
        duplicate makes two orders indistinguishable to the matcher.
        """
        price = round(float(price), 2)
        taken = await self._amounts_in_use()

        candidates = [
            round(price - d, 2)
            for d in range(_MIN_DISCOUNT, _MAX_DISCOUNT + 1)
            if price - d > 0
        ]
        free = [c for c in candidates if c not in taken]
        if not free:
            logger.error("card_amount_band_exhausted price=%s in_use=%s", price, len(taken))
            return None
        return random.choice(free)

    async def timeout_minutes(self) -> int:
        raw = await self.settings.get("card_payment_timeout_minutes", "5")
        try:
            minutes = int(float(raw))
        except (TypeError, ValueError):
            minutes = 5
        return max(1, minutes)

    async def expires_at(self) -> datetime:
        return _now() + timedelta(minutes=await self.timeout_minutes())

    # ------------------------------------------------------------------
    # Matching an incoming alert
    # ------------------------------------------------------------------

    async def _find_candidates(self, notification: CardNotification) -> list[Order]:
        """Orders that could plausibly have produced this alert: exact
        amount, still awaiting payment, and not expired *as of now*.

        The window matters as much as the amount. Without it, an unrelated
        transfer that happens to equal a long-abandoned order's amount
        could still be credited to it."""
        now = _now()
        # Eager-load product+user: the caller immediately inspects
        # `order.product.card_manual_confirm` and `order.user.language`, and
        # a lazy load on an async session raises MissingGreenlet rather than
        # quietly fetching.
        result = await self.session.execute(
            select(Order)
            .options(selectinload(Order.product), selectinload(Order.user))
            .where(
                Order.status == OrderStatus.AWAITING_CARD_PAYMENT,
                Order.expected_amount.is_not(None),
            )
        )
        candidates = []
        for order in result.scalars().all():
            if abs(float(order.expected_amount) - notification.amount) > _EPSILON:
                continue
            expires = _as_aware(order.payment_expires_at)
            if expires is not None and expires < now:
                continue
            candidates.append(order)
        return candidates

    async def process_notification(
        self, message_key: str, text: str
    ) -> tuple[CardTransaction, Order | None]:
        """Record and attempt to attribute one card alert.

        Returns (transaction, matched_order_or_None). Every path records a
        `CardTransaction`, so nothing that arrives is ever untraceable.
        """
        async with lock_for("card_payment"):
            existing = await self.transactions.get_by_message_key(message_key)
            if existing is not None:
                # Telegram redelivered an alert we already handled. Must not
                # be reprocessed: the same money would pay a second order.
                logger.info("card_notification_duplicate key=%s", message_key)
                return existing, None

            notification = parse_card_message(text)

            if notification is None:
                tx = await self.transactions.create(
                    message_key=message_key,
                    status=CardTransactionStatus.UNPARSED,
                    raw_text=text,
                )
                logger.warning("card_notification_unparsed key=%s", message_key)
                return tx, None

            base = dict(
                message_key=message_key,
                amount=notification.amount,
                currency=notification.currency,
                direction=notification.direction,
                card_last4=notification.card_last4,
                balance_after=notification.balance,
                occurred_at=notification.occurred_at,
                raw_text=text,
            )

            if not notification.is_incoming:
                # A debit from the card — nothing to do with a customer
                # paying us. Recorded (so the ledger is complete) and skipped.
                tx = await self.transactions.create(status=CardTransactionStatus.IGNORED, **base)
                return tx, None

            candidates = await self._find_candidates(notification)

            if len(candidates) == 1:
                order = candidates[0]
                tx = await self.transactions.create(
                    status=CardTransactionStatus.MATCHED, matched_order_id=order.id, **base
                )
                logger.info(
                    "card_payment_matched order=%s amount=%s key=%s",
                    order.order_uuid, notification.amount, message_key,
                )
                return tx, order

            if not candidates:
                tx = await self.transactions.create(status=CardTransactionStatus.UNMATCHED, **base)
                logger.warning(
                    "card_payment_unmatched amount=%s key=%s", notification.amount, message_key
                )
                return tx, None

            # Should be unreachable given amount uniqueness, but if it ever
            # happens, guessing would hand a product to the wrong customer.
            tx = await self.transactions.create(status=CardTransactionStatus.AMBIGUOUS, **base)
            logger.error(
                "card_payment_ambiguous amount=%s candidates=%s key=%s",
                notification.amount, [o.order_uuid for o in candidates], message_key,
            )
            return tx, None

    # ------------------------------------------------------------------
    # Expiry
    # ------------------------------------------------------------------

    async def list_expired_orders(self) -> list[Order]:
        now = _now()
        result = await self.session.execute(
            select(Order)
            .options(selectinload(Order.product), selectinload(Order.user))
            .where(Order.status == OrderStatus.AWAITING_CARD_PAYMENT)
        )
        expired = []
        for order in result.scalars().all():
            expires = _as_aware(order.payment_expires_at)
            if expires is not None and expires < now:
                expired.append(order)
        return expired


__all__ = ["CardPaymentService"]
