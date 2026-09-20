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

from app.database.models import Order, ReferralRedemption, User
from app.database.models.enums import ReferralCurrency
from app.repositories.order_repo import OrderRepository
from app.repositories.referral_repo import ReferralRepository
from app.repositories.setting_repo import SettingRepository
from app.services.exceptions import InsufficientBalanceError, RewardUnavailableError
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
        self.referrals = ReferralRepository(session)

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

        # Anti-fraud gate: a referred user who hasn't confirmed via
        # phone+captcha yet (see app/services/onboarding_service.py) never
        # triggers a reward for their referrer — otherwise a script could
        # farm fake accounts through the referral link and cash in the
        # moment any one of them makes a purchase. Deliberately NOT marking
        # `order.referral_rewarded = True` here: if this same buyer confirms
        # later, a *subsequent* delivered order can still reward the
        # referrer normally (this specific unconfirmed order just never
        # counts — no retroactive credit for it once confirmed).
        if not buyer.referral_confirmed and await self.settings.get_bool("referral_verification_enabled", True):
            return

        referrer = await self.session.get(User, buyer.referred_by_id)
        if referrer is None:
            return

        delivered_count = await self.orders.count_delivered_by_user(buyer.id)
        is_first = delivered_count <= 1
        price = float(order.price_at_purchase)

        product_override = (getattr(order.product, "referral_reward_value", "") or "").strip()
        if product_override:
            # An admin-set per-product rule takes over entirely for this
            # product: same reward whether it's the buyer's first order or
            # their fifth, and it applies regardless of whether the global
            # first-order/recurring toggles are even on — setting a reward
            # here is a deliberate, explicit choice.
            mode, value = parse_reward_value(product_override)
            if mode == "percent":
                by_qty = bool(getattr(order.product, "referral_reward_by_qty", False))
                base = float(order.quantity or 1) if by_qty else price
                reward = round(base * value / 100, 2)
            else:
                reward = round(value, 2)
        else:
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

    async def credit_for_confirmation(self, user: User, bot: Bot) -> None:
        """Credit the *referrer* with invite points ("Ball") the moment one
        of their referred users passes the phone+captcha confirmation. This
        is the second, independent referral currency — see ReferralCurrency
        in models/enums.py for why it's kept apart from the sales-based
        balance (short version: points come from invites, are shop-only,
        and can never be cashed out, so invite-farming has no cash exit).

        Safe to call unconditionally — a fast no-op unless the reward is
        enabled, the user was actually referred, and they haven't already
        been paid for."""
        if user.referral_confirm_rewarded or user.referred_by_id is None:
            return
        if not await self.settings.get_bool("referral_enabled", False):
            return
        if not await self.settings.get_bool("referral_confirm_reward_enabled", False):
            return

        referrer = await self.session.get(User, user.referred_by_id)
        if referrer is None:
            return

        # Points are a flat per-invite amount — a percentage would be
        # meaningless here since no purchase is involved.
        _, value = parse_reward_value(await self.settings.get("referral_confirm_reward_value", "0"))
        reward = round(value, 2)

        user.referral_confirm_rewarded = True
        if reward <= 0:
            await self.session.commit()
            return

        referrer.referral_points = float(referrer.referral_points) + reward
        await self.session.commit()

        order_logger.info(
            "referral_points_credited referrer=%s invited=%s amount=%s",
            referrer.telegram_id, user.telegram_id, reward,
        )

        points_name = await self.settings.get("referral_points_name", "Ball")
        try:
            await bot.send_message(
                referrer.telegram_id,
                t(
                    referrer.language,
                    "msg_referral_points_received",
                    amount=fmt_price(reward),
                    currency=points_name,
                ),
            )
        except Exception:  # noqa: BLE001 - referrer may have blocked the bot
            pass

    async def describe_referral_rewards(self, lang: str) -> list[str]:
        """Auto-generated, always-current "what do I actually get" lines for
        the referral profile screen — built live from the real settings/
        product configuration instead of the admin having to type it out by
        hand in the free-text rules field (which drifts the moment a
        product's reward changes, since nothing keeps it in sync). Returns
        display-ready lines (possibly empty, if nothing is configured
        anywhere yet); the caller decides whether/how to show them."""
        from app.repositories.product_repo import ProductRepository
        from app.utils.formatting import fmt_price, product_emoji_html, product_name

        lines: list[str] = []
        currency = await self.settings.get("referral_currency", "UZS")
        points_name = await self.settings.get("referral_points_name", "Ball")

        if await self.settings.get_bool("referral_confirm_reward_enabled", False):
            _, points_value = parse_reward_value(await self.settings.get("referral_confirm_reward_value", "0"))
            if points_value > 0:
                lines.append(
                    t(lang, "msg_referral_info_invite", amount=fmt_price(points_value), points_name=points_name)
                )

        first_enabled = await self.settings.get_bool("referral_first_order_enabled", False)
        first_raw = await self.settings.get("referral_first_order_value", "0")

        products = await ProductRepository(self.session).list_visible()
        for product in products:
            if not product.referral_eligible:
                continue
            reward_text = self._describe_product_reward(product, first_enabled, first_raw, currency)
            if reward_text:
                lines.append(
                    t(
                        lang,
                        "msg_referral_info_product",
                        emoji=product_emoji_html(product),
                        name=product_name(product, lang),
                        reward=reward_text,
                    )
                )
        return lines

    def _describe_product_reward(
        self, product, first_order_enabled: bool, first_order_raw: str, currency: str
    ) -> str | None:
        """One reward, in whichever form the admin actually configured it —
        an explicit per-product override always wins (see
        `credit_for_delivered_order` above, same precedence); with no
        override, falls back to describing the global first-order reward,
        since a brand-new referred customer's *first* purchase is the
        scenario a referral link exists for. Returns None when there's
        genuinely nothing to advertise for this product (nothing enabled,
        or the configured amount is zero)."""
        override = (getattr(product, "referral_reward_value", "") or "").strip()
        if override:
            mode, value = parse_reward_value(override)
            if value <= 0:
                return None
            if mode == "percent":
                by_qty = bool(getattr(product, "referral_reward_by_qty", False))
                basis = "sotilgan sondan" if by_qty else "narxdan"
                return f"{value:g}% ({basis})"
            return f"{fmt_price(value)} {currency}"

        if not first_order_enabled:
            return None
        mode, value = parse_reward_value(first_order_raw)
        if value <= 0:
            return None
        if mode == "percent":
            return f"{value:g}% (narxdan)"
        return f"{fmt_price(value)} {currency}"

    async def redeem_reward(self, user: User, reward_id: int, note: str | None) -> ReferralRedemption:
        """Spend the customer's referral balance on a catalog reward — the
        "referral shop" checkout. Each reward is priced in exactly one of
        the two currencies (`reward.currency_type`), and is paid for from
        that matching balance only. The amount is deducted immediately
        (treated as reserved the same way an inventory code is reserved at
        purchase time) so a customer can't fire off several requests
        against the same balance before an admin gets to the first one; a
        rejected request refunds it to the same currency it came from (see
        `ReferralRepository.mark_redemption_rejected`)."""
        reward = await self.referrals.get_reward(reward_id)
        if reward is None or not reward.is_active:
            raise RewardUnavailableError("msg_referral_reward_unavailable")

        uses_points = reward.currency_type == ReferralCurrency.POINTS
        balance = float(user.referral_points if uses_points else user.referral_balance)
        cost = float(reward.cost)
        if balance < cost:
            raise InsufficientBalanceError("msg_referral_reward_insufficient_balance")

        if uses_points:
            user.referral_points = balance - cost
        else:
            user.referral_balance = balance - cost
        await self.session.commit()

        redemption = await self.referrals.create_redemption(user.id, reward, note)
        order_logger.info(
            "referral_reward_redeemed user=%s reward=%s cost=%s currency=%s redemption=%s",
            user.telegram_id, reward.name, cost, reward.currency_type.value, redemption.id,
        )
        return redemption
