"""Shared enums used across ORM models and business logic."""
from __future__ import annotations

import enum


class DeliveryMode(str, enum.Enum):
    INVENTORY = "inventory"   # Mode 1: internal code inventory
    MANUAL = "manual"         # Mode 2: admin writes a custom message
    API = "api"                # Mode 3: external supplier API


class OrderStatus(str, enum.Enum):
    AWAITING_PROOF = "awaiting_proof"        # user pressed "I paid", waiting for screenshot
    AWAITING_CRYPTO_PAYMENT = "awaiting_crypto_payment"  # crypto invoice created, waiting for on-chain confirmation
    AWAITING_STARS_PAYMENT = "awaiting_stars_payment"    # Telegram Stars invoice sent, waiting for successful_payment
    PENDING_APPROVAL = "pending_approval"    # screenshot forwarded to admin
    APPROVED = "approved"
    REJECTED = "rejected"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    FAILED = "failed"                         # approved but delivery failed (e.g. API error)


class AdminRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"   # from .env, cannot be removed via bot
    ADMIN = "admin"                # added from within the bot


class PaymentMethod(str, enum.Enum):
    CARD = "card"      # manual card/wallet transfer + screenshot proof
    CRYPTO = "crypto"  # CryptoBot / xRocket invoice, auto-confirmed
    STARS = "stars"    # Telegram Stars (native Telegram payments), auto-confirmed


class ReferralWithdrawalStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    REJECTED = "rejected"


class ReferralRedemptionStatus(str, enum.Enum):
    PENDING = "pending"
    FULFILLED = "fulfilled"
    REJECTED = "rejected"


class ReferralCurrency(str, enum.Enum):
    """The two independent referral currencies a user can accumulate.

    BALANCE — earned from *sales*: a referred user's first and recurring
    purchases (see ReferralService.credit_for_delivered_order). Real
    money-like value, so it's the only one that can be cashed out via a
    `ReferralWithdrawal`. Its display name is admin-configurable via the
    "referral_currency" setting (UZS / USD / Stars / whatever).

    POINTS — earned from *invites*: each referred user who passes the
    phone+captcha confirmation (see ReferralService.credit_for_confirmation).
    Deliberately NOT withdrawable — it can only be spent in the referral
    shop, so farming invites with throwaway accounts can never turn into
    a cash-out. Display name configurable via "referral_points_name".
    """

    BALANCE = "balance"
    POINTS = "points"
