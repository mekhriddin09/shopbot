"""Startup bootstrap: create tables (if not managed by Alembic yet) and seed
default settings so the bot is usable immediately after first run."""
from __future__ import annotations

import logging

from sqlalchemy import select, text

from app.config.settings import settings as app_settings
from app.database.base import Base
from app.database.engine import async_session_maker, engine
from app.database.models import Setting

logger = logging.getLogger(__name__)

# Columns added to already-existing tables after the initial release.
# `create_all()` only creates missing *tables*, never adds columns to a
# table that already exists — so on an upgrade, an existing shopbot.db would
# be missing these and every query touching them would fail with
# "no such column". This list is patched in with ALTER TABLE on startup so
# upgrading is just "replace the files and restart", no manual DB surgery.
# (SQLite only — Postgres deployments should use `alembic upgrade head`.)
_NEW_COLUMNS: list[tuple[str, str, str]] = [
    # (table, column, DDL type + default)
    ("products", "price_usd", "NUMERIC(12, 2)"),
    ("orders", "payment_method", "VARCHAR(32) NOT NULL DEFAULT 'card'"),
    ("orders", "crypto_provider", "VARCHAR(32)"),
    ("orders", "crypto_invoice_id", "VARCHAR(64)"),
    ("orders", "crypto_pay_url", "TEXT"),
    ("products", "external_product_id", "VARCHAR(128)"),
    ("products", "delivery_instructions", "TEXT"),
    ("reviews", "author_name", "TEXT"),
    ("products", "name_uz", "VARCHAR(128)"),
    ("products", "name_ru", "VARCHAR(128)"),
    ("products", "name_en", "VARCHAR(128)"),
    ("products", "description_uz", "TEXT"),
    ("products", "description_ru", "TEXT"),
    ("products", "description_en", "TEXT"),
    ("products", "delivery_instructions_uz", "TEXT"),
    ("products", "delivery_instructions_ru", "TEXT"),
    ("products", "delivery_instructions_en", "TEXT"),
    ("inventory_codes", "is_reserved", "BOOLEAN NOT NULL DEFAULT 0"),
    ("inventory_codes", "reserved_by_order_id", "INTEGER"),
    ("users", "referred_by_id", "INTEGER"),
    ("users", "referral_balance", "NUMERIC(12, 2) NOT NULL DEFAULT 0"),
    ("products", "referral_eligible", "BOOLEAN NOT NULL DEFAULT 0"),
    ("products", "min_order_qty", "INTEGER NOT NULL DEFAULT 1"),
    ("products", "max_order_qty", "INTEGER NOT NULL DEFAULT 1"),
    ("orders", "referral_rewarded", "BOOLEAN NOT NULL DEFAULT 0"),
    ("orders", "referral_is_first_reward", "BOOLEAN NOT NULL DEFAULT 0"),
    ("orders", "quantity", "INTEGER NOT NULL DEFAULT 1"),
    ("orders", "is_preorder", "BOOLEAN NOT NULL DEFAULT 0"),
    ("products", "price_stars", "INTEGER"),
    ("orders", "stars_charge_id", "VARCHAR(128)"),
    ("users", "oferta_accepted", "BOOLEAN NOT NULL DEFAULT 0"),
    ("users", "phone_number", "VARCHAR(32)"),
    ("users", "referral_confirmed", "BOOLEAN NOT NULL DEFAULT 0"),
    ("users", "referral_points", "NUMERIC(12, 2) NOT NULL DEFAULT 0"),
    ("users", "referral_prompt_shown", "BOOLEAN NOT NULL DEFAULT 0"),
    ("users", "referral_confirm_rewarded", "BOOLEAN NOT NULL DEFAULT 0"),
    ("referral_rewards", "currency_type", "VARCHAR(32) NOT NULL DEFAULT 'BALANCE'"),
    ("referral_redemptions", "currency_type", "VARCHAR(32) NOT NULL DEFAULT 'BALANCE'"),
]

DEFAULT_SETTINGS: dict[str, str] = {
    # Per-language editable content (admin can change each independently)
    "welcome_message_uz": (
        "\U0001F44B Xush kelibsiz!\n\n"
        "Bu yerda raqamli mahsulotlarni (kodlar, obunalar, akkauntlar) xarid qilishingiz mumkin.\n"
        "Quyidagi menyudan boshlang."
    ),
    "welcome_message_ru": (
        "\U0001F44B Добро пожаловать!\n\n"
        "Здесь вы можете приобрести цифровые товары (коды, подписки, аккаунты).\n"
        "Начните с меню ниже."
    ),
    "welcome_message_en": (
        "\U0001F44B Welcome!\n\n"
        "Here you can purchase digital products (codes, subscriptions, accounts).\n"
        "Start with the menu below."
    ),
    "support_message_uz": "Savollaringiz bo'lsa, admin bilan bog'laning: @your_support_username",
    "support_message_ru": "По всем вопросам обращайтесь к администратору: @your_support_username",
    "support_message_en": "For any questions, contact the admin: @your_support_username",
    "payment_instructions_uz": (
        "\U0001F4B3 To'lov uchun:\n"
        "Karta: 0000 0000 0000 0000\n"
        "Egasi: F.I.Sh\n\n"
        "To'lovni amalga oshirgach, ✅ To'ladim tugmasini bosing va chekni yuboring."
    ),
    "payment_instructions_ru": (
        "\U0001F4B3 Для оплаты:\n"
        "Карта: 0000 0000 0000 0000\n"
        "Получатель: Ф.И.О\n\n"
        "После оплаты нажмите ✅ Я оплатил и отправьте чек."
    ),
    "payment_instructions_en": (
        "\U0001F4B3 To pay:\n"
        "Card: 0000 0000 0000 0000\n"
        "Holder: Full Name\n\n"
        "After paying, press ✅ I Paid and upload the screenshot."
    ),
    # "⭐ Reviews" section content — free text the admin writes/pastes
    # directly (e.g. a summary, a few hand-picked quotes, whatever). Shown
    # as-is; empty means the "no reviews yet" placeholder is shown instead.
    "reviews_text_uz": "",
    "reviews_text_ru": "",
    "reviews_text_en": "",
    # Global toggles
    "automatic_delivery_enabled": "1",
    "manual_delivery_enabled": "1",
    "api_delivery_enabled": "1",

    # Reviews section: optional "proof" channel link (e.g. screenshots of
    # delivered orders). Empty = button hidden.
    "proof_channel_url": "",

    # Crypto payments (CryptoBot / xRocket). Off by default until the admin
    # configures an API token in .env and enables it here. NOTE: there is
    # deliberately no "which provider" setting — every provider with a token
    # in .env is offered to the customer at checkout and they pick
    # (see services/crypto/registry.py:available_crypto_providers).
    "crypto_payment_enabled": "0",

    # Referral program. Off by default until the admin sets real reward
    # values below and flips this on. Reward "value" fields accept either a
    # plain number ("5000" = fixed amount) or a percent ("5%" = 5% of the
    # order's price_at_purchase) — parsed in app/services/referral_service.py.
    "referral_enabled": "0",
    "referral_currency": "UZS",
    "referral_first_order_enabled": "1",
    "referral_first_order_value": "0",
    "referral_recurring_enabled": "0",
    "referral_recurring_value": "0",
    # Minimum balance required before a "💰 Pulni yechish" (withdraw) request
    # can be made. 0 = withdrawal requests disabled entirely.
    "referral_withdraw_min": "0",
    # Free-text referral program rules, admin-written per language. Shown
    # via a "📜 Qoidalar" button on the referral profile screen — the button
    # only appears once the admin has written something for that specific
    # language (empty = hidden for that language, checked per-request).
    "referral_rules_uz": "",
    "referral_rules_ru": "",
    "referral_rules_en": "",

    # Out-of-stock "notify me" + pre-order toggles.
    "preorder_enabled": "0",

    # Telegram Stars (native in-app payments, currency XTR). Off by default
    # until the admin sets a Stars price on at least one product and
    # enables this.
    "stars_payment_enabled": "0",

    # Reseller API (external supplier, Mode 3 delivery). Empty = fall back
    # to RESELLER_API_KEY / RESELLER_API_BASE_URL from .env. Setting these
    # from the bot (Admin panel -> Sozlamalar -> Reseller API) overrides
    # .env and takes effect immediately, no redeploy needed — lets the
    # admin rotate a leaked/expired key without touching GitHub/Railway.
    "reseller_api_key": "",
    "reseller_api_base_url": "",

    # Onboarding gate: mandatory oferta (terms) acceptance + mandatory
    # channel subscription, checked before *any* other handler runs (see
    # OnboardingGateMiddleware). Off by default — an upgrade must never
    # silently lock out existing users; the admin turns this on only after
    # writing the oferta text and setting the channel below.
    "onboarding_gate_enabled": "0",
    # Either "@channel_username" or a numeric chat id (e.g. "-1001234567890")
    # — passed straight to bot.get_chat_member(). Empty = channel check
    # skipped even if the gate above is on (oferta-only gate).
    "required_channel": "",
    # Public join link shown on the "🔗 Kanalga o'tish" button — needed
    # separately because private channels/numeric ids aren't valid t.me URLs.
    "required_channel_url": "",
    "oferta_text_uz": "",
    "oferta_text_ru": "",
    "oferta_text_en": "",

    # Card payment notifications (UZCARD/Humo alerts forwarded through a
    # Telegram Business connection — see app/handlers/business.py). Only
    # messages from this exact sender are ever read; everything else in the
    # connected account's chats is ignored. Username or numeric id.
    "card_notify_sender": "CardXabarBot",

    # Second referral currency ("Ball"): earned per referred user who
    # passes the phone+captcha confirmation, spendable only in the referral
    # shop (never withdrawable — see ReferralCurrency in models/enums.py).
    # The sales-based currency keeps its own separate name in
    # "referral_currency" above.
    "referral_points_name": "Ball",
    "referral_confirm_reward_enabled": "0",
    "referral_confirm_reward_value": "0",

    # Referral-confirmation anti-fraud gate (phone number + math captcha).
    # Only ever applies to users who arrived via a referral link — never
    # blocks organic/direct users, and never blocks the shop itself, only
    # that specific referred user's contribution to their referrer's
    # invited-count/stats/rewards. On by default per admin request.
    "referral_verification_enabled": "1",
}


async def init_models() -> None:
    """Create all tables if they do not exist yet.

    For iterative schema changes in production, prefer `alembic upgrade
    head`. This call is a safety net so the bot also works out-of-the-box
    on a brand-new database.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured (create_all).")
    await _patch_missing_columns()
    await _normalize_payment_method_values()


async def _patch_missing_columns() -> None:
    if not app_settings.DATABASE_URL.startswith("sqlite"):
        return  # Postgres etc: use `alembic upgrade head` instead

    async with engine.begin() as conn:
        for table, column, ddl in _NEW_COLUMNS:
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            existing_columns = {row[1] for row in result.fetchall()}
            if column not in existing_columns:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                logger.info("Patched missing column: %s.%s", table, column)


async def _normalize_payment_method_values() -> None:
    """Fix a data inconsistency from the `orders.payment_method` migration.

    `_patch_missing_columns` above adds the column via raw
    `ALTER TABLE ... DEFAULT 'card'` (lowercase), which back-fills every
    pre-existing row with the literal string 'card'. But the ORM's
    `Enum(PaymentMethod)` column (no `values_callable`) serializes new rows
    using the enum *member name* ('CARD'/'CRYPTO'), not `.value`. That
    mismatch made SQLAlchemy raise `LookupError: 'card' is not among the
    defined enum values` for any pre-migration order the moment it was
    loaded — which is exactly what broke "My Orders" for existing users.
    Normalizing everything to the member-name casing fixes it without
    touching the column type (keeps behavior identical to every other
    Enum column in this project, e.g. DeliveryMode).
    """
    if not app_settings.DATABASE_URL.startswith("sqlite"):
        return  # Postgres etc: fix data via a real migration instead

    async with engine.begin() as conn:
        for table, column, values in (
            ("orders", "payment_method", {"card": "CARD", "crypto": "CRYPTO"}),
        ):
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            if column not in {row[1] for row in result.fetchall()}:
                continue  # table/column doesn't exist yet on a brand-new DB
            for old, new in values.items():
                await conn.execute(
                    text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old"),
                    {"new": new, "old": old},
                )


async def seed_defaults() -> None:
    async with async_session_maker() as session:
        existing = (await session.execute(select(Setting.key))).scalars().all()
        existing_keys = set(existing)
        created = False
        for key, value in DEFAULT_SETTINGS.items():
            if key not in existing_keys:
                session.add(Setting(key=key, value=value))
                created = True
        if created:
            await session.commit()
            logger.info("Default settings seeded.")


async def bootstrap_database() -> None:
    await init_models()
    await seed_defaults()
