"""Onboarding gate helpers: phone-number normalization/validation for the
referral-confirmation flow, and math-captcha generation. Kept as small pure
(or near-pure) functions so they're trivially unit-testable without any
Telegram/aiogram objects involved."""
from __future__ import annotations

import random

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User

_UZ_PREFIX = "998"
_UZ_LENGTH = 12  # "998" + 9 digits


def normalize_phone(raw: str) -> str:
    """'+998 90 123-45-67' -> '998901234567'. Digits only — the storage and
    comparison format used everywhere (DB column, whitelist lookups)."""
    return "".join(ch for ch in (raw or "") if ch.isdigit())


def is_uzbek_number(normalized: str) -> bool:
    return normalized.startswith(_UZ_PREFIX) and len(normalized) == _UZ_LENGTH


async def is_phone_allowed(session: AsyncSession, raw_phone: str) -> bool:
    """UZ numbers always pass; anything else must be on the admin's
    exception whitelist (app/repositories/allowed_phone_repo.py) — this is
    the specific "chet el spam qiladigan virtual nomerlar" (foreign spam /
    virtual number) protection the referral-confirmation gate exists for."""
    normalized = normalize_phone(raw_phone)
    if is_uzbek_number(normalized):
        return True
    from app.repositories.allowed_phone_repo import AllowedPhoneRepository  # local import avoids a cycle

    return await AllowedPhoneRepository(session).is_allowed(normalized)


async def user_needs_referral_confirmation(session: AsyncSession, user: User) -> bool:
    """Shown as an extra main-menu button + gates referral stats/rewards —
    only ever true for a user who (a) arrived via someone's referral link,
    (b) hasn't confirmed yet, and (c) the admin still has the feature on."""
    if not user.referred_by_id or user.referral_confirmed:
        return False
    from app.repositories.setting_repo import SettingRepository  # local import avoids a cycle

    return await SettingRepository(session).get_bool("referral_verification_enabled", True)


def generate_captcha() -> tuple[str, int, list[int]]:
    """Simple two-operand math question (e.g. "3 x 4 = ?") for a one-tap
    "prove you're a human tapping this, not a script" check. Returns
    (question_text, correct_answer, shuffled_4_options) — the caller embeds
    the correct answer directly in that option's own callback_data (see
    CaptchaCB / captcha_kb), so no server-side state needs to be remembered
    between showing the question and checking the tap."""
    a, b = random.randint(1, 9), random.randint(1, 9)
    op = random.choice(["+", "×"])  # + or ×
    correct = a + b if op == "+" else a * b
    question = f"{a} {op} {b} = ?"

    options = {correct}
    while len(options) < 4:
        candidate = correct + random.randint(-6, 6)
        if candidate >= 0:
            options.add(candidate)
    shuffled = list(options)
    random.shuffle(shuffled)
    return question, correct, shuffled
