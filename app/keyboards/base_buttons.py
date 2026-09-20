"""Default appearance for any button built the old way — a raw
`InlineKeyboardButton(...)` / `KeyboardButton(...)` call, not going through
`app.keyboards.button_helpers` or the Button Manager registry (that path
already resolves its own style explicitly, see `resolve_button`).

Telegram Bot API 9.4 gave buttons a `style` field (blue/green/red). A
button that never sets it renders in Telegram's flat default gray, which
next to any colored button reads as disabled/dead. The marketing
convention already used everywhere else in this bot (see
`app.services.button_registry`) is: green = positive action, red =
negative/cancel, blue for everything else — never gray. These two
subclasses apply that "blue for everything else" default to every button
built anywhere in the codebase that doesn't explicitly ask for a different
color, so admin-panel screens, payment steps, the language picker, the
quantity/recipient flow etc. all get a real color with zero per-button
edits required.

A button that DOES pass `style=...` explicitly (success/danger, or a
resolved registry override) is completely unaffected — `setdefault` only
fills the gap when `style` is left out entirely.

Any file building buttons by hand should import `InlineKeyboardButton` /
`KeyboardButton` from here instead of `aiogram.types` directly; everything
else about them (fields, behavior, `InlineKeyboardMarkup` construction)
is identical, they're real aiogram objects under the hood."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton as _InlineKeyboardButton
from aiogram.types import KeyboardButton as _KeyboardButton


class InlineKeyboardButton(_InlineKeyboardButton):
    def __init__(self, **data):
        data.setdefault("style", "primary")
        super().__init__(**data)


class KeyboardButton(_KeyboardButton):
    def __init__(self, **data):
        data.setdefault("style", "primary")
        super().__init__(**data)
