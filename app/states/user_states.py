from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class PurchaseStates(StatesGroup):
    waiting_screenshot = State()


class ReviewStates(StatesGroup):
    waiting_rating = State()
    waiting_text = State()


class SupportStates(StatesGroup):
    chatting = State()


class ReferralRewardStates(StatesGroup):
    waiting_note = State()


class ReferralWithdrawStates(StatesGroup):
    waiting_card = State()
    """Collecting where to send the money (a card number, most often)
    before the withdrawal request is actually created — see
    app/handlers/user/referral.py. Unlike the reward note above, this step
    is not skippable: the admin can't pay a request out with nowhere to
    send it."""


class RecipientStates(StatesGroup):
    waiting_stars_amount = State()
    """Collecting the @username that Stars/Premium should be delivered to,
    before any payment is taken (see app/handlers/user/recipient.py)."""

    waiting_username = State()
