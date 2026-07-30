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
