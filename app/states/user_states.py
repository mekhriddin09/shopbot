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
