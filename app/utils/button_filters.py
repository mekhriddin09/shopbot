"""aiogram filter builders for reply-keyboard (main menu) buttons that stay
correct even after a Button Manager text override — see the docstring on
`app.services.button_service.resolved_texts_for_key` for why a plain
`F.text.in_({...})` built once at import time isn't safe to use for these."""
from __future__ import annotations

from magic_filter import MagicFilter

from aiogram import F

from app.services.button_service import resolved_texts_for_key


def menu_button_filter(key: str) -> MagicFilter:
    """Use in place of `F.text.in_({t(l, "btn_x") for l in (...)})`.

    Example: `@router.message(menu_button_filter("menu_shop"))`.
    """
    return F.text.func(lambda text: text in resolved_texts_for_key(key))


def menu_button_key_for_text(text: str | None) -> str | None:
    """Reverse lookup used by handlers (e.g. support.py's "escape hatch")
    that need to know *which* main-menu button interrupted them, not just
    whether one did."""
    from app.services.button_registry import BUTTON_REGISTRY

    if not text:
        return None
    for button_def in BUTTON_REGISTRY.values():
        if button_def.surface == "reply" and text in resolved_texts_for_key(button_def.key):
            return button_def.key
    return None
