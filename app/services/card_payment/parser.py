"""Parser for CardXabar (UZCARD/Humo) notification messages.

Real sample captured from @CardXabarBot:

    🟢 Perevod na kartu
    ➕ 1 000.00 UZS
    💳 ***5902
    📍 TOSHKENT SH. MIKROKREDITBANK ATB BOSH, UZ
    🕐 17.09.26 17:56
    💰 1 323 384.95 UZS

THE TRAP: the message contains **two** currency amounts — the transaction
(1 000.00) and the resulting account balance (1 323 384.95). Picking the
wrong one silently breaks every payment match, so amount extraction is
deliberately driven by the direction marker (➕/➖) rather than by "first
number in the text", and the balance line is identified and excluded.

Design stance: this parser refuses to guess. Anything it isn't confident
about returns `None`, which routes the notification to manual review
instead of risking an automatic delivery against a misread amount. A
missed auto-match costs a few minutes of admin time; a wrong one gives a
product away for free.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

# Space characters banks like to put inside numbers: regular, non-breaking
# (U+00A0), narrow no-break (U+202F), thin (U+2009).
_SPACES = "    "
_SPACE_RE = re.compile(f"[{_SPACES}]")

# "1 000.00 UZS" / "1 323 384,95 UZS" / "29973 UZS"
_AMOUNT_RE = re.compile(
    rf"(?P<num>\d[\d{_SPACES}]*(?:[.,]\d{{1,2}})?)\s*(?P<cur>[A-Z]{{3}})\b"
)

_LAST4_RE = re.compile(r"\*+\s*(\d{4})\b")

# "17.09.26 17:56" — DD.MM.YY HH:MM
_DATETIME_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})\b")

# Direction markers. Emoji vary between bank bots and Telegram clients, so
# plain ASCII +/- are accepted too.
_IN_MARKERS = ("➕", "🟢", "+")
_OUT_MARKERS = ("➖", "🔴", "−", "-")

# Markers that identify the *balance* line, which must never be read as
# the transaction amount.
_BALANCE_MARKERS = ("💰", "💵", "💴", "💶", "💷", "🤑", "balans", "баланс", "balance")


@dataclass(slots=True)
class CardNotification:
    amount: float
    currency: str
    direction: str              # "in" | "out"
    card_last4: str | None
    occurred_at: datetime | None
    balance: float | None
    raw_text: str

    @property
    def is_incoming(self) -> bool:
        return self.direction == "in"


def _to_float(raw: str) -> float | None:
    cleaned = _SPACE_RE.sub("", raw).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _looks_like_balance(line: str) -> bool:
    low = line.lower()
    return any(m.lower() in low for m in _BALANCE_MARKERS)


def _direction_of(line: str) -> str | None:
    # Check outgoing first: "➖"/"−" are unambiguous, whereas a bare "-"
    # could also appear inside a date. We only consult markers at the very
    # start of the line for the ASCII variants, to avoid such false hits.
    stripped = line.strip()
    for m in ("➖", "🔴", "−"):
        if m in stripped:
            return "out"
    for m in ("➕", "🟢"):
        if m in stripped:
            return "in"
    if stripped.startswith("-"):
        return "out"
    if stripped.startswith("+"):
        return "in"
    return None


def parse_card_message(text: str) -> CardNotification | None:
    """Return a parsed notification, or None when the text isn't a
    recognisable transaction alert (error replies, menus, promos, or
    anything whose amount/direction can't be established confidently)."""
    if not text or not text.strip():
        return None

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None

    amount: float | None = None
    currency: str | None = None
    direction: str | None = None
    balance: float | None = None

    # Pass 1: the amount line is one that carries BOTH a direction marker
    # and a currency amount, and is not the balance line.
    for line in lines:
        match = _AMOUNT_RE.search(line)
        if not match:
            continue
        if _looks_like_balance(line):
            if balance is None:
                balance = _to_float(match.group("num"))
            continue
        line_direction = _direction_of(line)
        if line_direction and amount is None:
            value = _to_float(match.group("num"))
            if value is not None:
                amount, currency, direction = value, match.group("cur"), line_direction

    # Pass 2: no direction marker anywhere. Rather than assume the first
    # number is the payment, give up — an unsigned alert might equally be
    # a debit, and guessing wrong hands out a product for free.
    if amount is None or direction is None:
        return None

    last4_match = _LAST4_RE.search(text)
    dt_match = _DATETIME_RE.search(text)
    occurred_at = None
    if dt_match:
        day, month, year, hour, minute = (int(g) for g in dt_match.groups())
        try:
            occurred_at = datetime(2000 + year, month, day, hour, minute)
        except ValueError:
            occurred_at = None

    return CardNotification(
        amount=amount,
        currency=currency or "UZS",
        direction=direction,
        card_last4=last4_match.group(1) if last4_match else None,
        occurred_at=occurred_at,
        balance=balance,
        raw_text=text,
    )


__all__ = ["CardNotification", "parse_card_message"]
