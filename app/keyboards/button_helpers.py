"""Thin adapter between `app.services.button_service.resolve_button` and
actual aiogram keyboard button objects, so keyboard-builder functions don't
each have to repeat the "disabled -> skip, style -> field, custom emoji ->
field" wiring."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, KeyboardButton

from app.services.button_service import resolve_button


def inline_btn(key: str, lang: str, **extra) -> InlineKeyboardButton | None:
    """Builds an InlineKeyboardButton for registry `key`, applying any admin
    style/emoji/text override. `extra` is passed straight through to
    InlineKeyboardButton (callback_data=..., url=..., pay=..., etc.) — this
    function only ever touches presentation fields (text/style/
    icon_custom_emoji_id), never callback_data/url/pay, so it structurally
    cannot let a button override change what a button *does*.

    Returns None when the admin disabled this button — callers should drop
    it from the row (`if btn: row.append(btn)`)."""
    resolved = resolve_button(key, lang)
    if not resolved.enabled:
        return None
    return InlineKeyboardButton(
        text=resolved.text,
        style=resolved.style,
        icon_custom_emoji_id=resolved.custom_emoji_id,
        **extra,
    )


def reply_btn(key: str, lang: str) -> KeyboardButton | None:
    """Same idea for ReplyKeyboardMarkup buttons (main menu). KeyboardButton
    has no style/custom-emoji fields in the Bot API, so only `text` is
    used. Returns None when disabled."""
    resolved = resolve_button(key, lang)
    if not resolved.enabled:
        return None
    return KeyboardButton(text=resolved.text)
