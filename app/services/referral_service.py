"""Referral program business logic.

Design in one paragraph: every user gets a personal deep-link
(`t.me/<bot>?start=ref<user.id>`). A brand-new user who arrives via that link
gets `referred_by_id` set once, permanently. When one of that referred
user's orders is DELIVERED for a *referral-eligible* product (admin toggles
this per product), the referrer is credited — using the "first order"
reward settings if it's the referred user's first-ever delivered order,
otherwise the "recurring" reward settings, each independently enabled and
each accepting either a fixed amount ("5000") or a percentage of the order's
price ("5%"). `Order.referral_rewarded` guards against ever paying out
twice for the same order.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, User
from app.repositories.order_repo import OrderRepository
from app.repositories.setting_repo import SettingRepository
from app.utils.formatting import fmt_price
from app.utils.i18n import t

order_logger = logging.getLogger("orders")


def parse_reward_value(raw: str) -> tuple[str, float]:
    """"5000" -> ("fixed", 5000.0); "5%" -> ("percent", 5.0). Never raises —
    unparseable input is treated as a zero reward rather than crashing the
    delivery flow."""
    raw = (raw or "0").strip()
    if raw.endswith("%"):
        try:
            return "percent", float(raw[:-1].strip().replace(",", "."))
        except ValueError:
            return "percent", 0.0
    try:
        return "fixed", float(raw.replace(" ", "").replace(",", "."))
    except ValueError:
        return "fixed", 0.0


def parse_start_referral_payload(payload: str) -> int | None:
    payload = (payload or "").strip()
    if not payload.startswith("ref"):
        return None
    try:
        return int(payload[3:])
    except ValueError:
        return None


class ReferralService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.orders = OrderRepository(session)
        self.settings = SettingRepository(session)

    async def set_referrer_if_new(self, user: User, referrer_user_id: int) -> None:
        """Only ever called right after a brand-new user's first /start
        with a `ref<id>` payload. No-op if the user already has a referrer,
        the referrer id doesn't exist, or someone tries to refer themselves."""
        if user.referred_by_id is not None or referrer_user_id == user.id:
            return
        referrer = await self.session.get(User, referrer_user_id)
        if referrer is None:
            return
        user.referred_by_id = referrer.id
        await self.session.commit()
        order_logger.info("referral_linked user=%s referrer=%s", user.telegram_id, referrer.telegram_id)

    async def credit_for_delivered_order(self, order: Order, bot: Bot) -> None:
        """Call this once, right after an order is marked DELIVERED, from
        every delivery path (admin approval, crypto auto-delivery, crypto
        self-check, manual message). Safe to call unconditionally — it's a
        fast no-op unless the product is referral-eligible, the buyer was
        referred by someone, and the referral program is enabled."""
        if order.referral_rewarded:
            return
        if not order.product.referral_eligible:
            return
        if not await self.settings.get_bool("referral_enabled", False):
            return

        buyer = order.user
        if buyer is None or buyer.referred_by_id is None:
            return

        referrer = await self.session.get(User, buyer.referred_by_id)
        if referrer is None:
            return

        delivered_count = await self.orders.count_delivered_by_user(buyer.id)
        is_first = delivered_count <= 1

        if is_first:
            enabled = await self.settings.get_bool("referral_first_order_enabled", False)
            raw_value = await self.settings.get("referral_first_order_value", "0")
        else:
            enabled = await self.settings.get_bool("referral_recurring_enabled", False)
            raw_value = await self.settings.get("referral_recurring_value", "0")

        if not enabled:
            order.referral_rewarded = True
            await self.session.commit()
            return

        mode, value = parse_reward_value(raw_value)
        price = float(order.price_at_purchase)
        reward = round(price * value / 100, 2) if mode == "percent" else round(value, 2)

        order.referral_rewarded = True
        order.referral_is_first_reward = is_first
        if reward <= 0:
            await self.session.commit()
            return

        referrer.referral_balance = float(referrer.referral_balance) + reward
        await self.session.commit()

        order_logger.info(
            "referral_credited referrer=%s buyer=%s order=%s amount=%s first_order=%s",
            referrer.telegram_id, buyer.telegram_id, order.order_uuid, reward, is_first,
        )

        currency = await self.settings.get("referral_currency", "UZS")
        try:
            await bot.send_message(
                referrer.telegram_id,
                t(referrer.language, "msg_referral_reward_received", amount=fmt_price(reward), currency=currency),
            )
        except Exception:  # noqa: BLE001 - referrer may have blocked the bot
            pass
