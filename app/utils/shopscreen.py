"""The customer's side of the shop is also one message.

Same idea as `app/utils/screen.py`, but the shop has a complication the admin
panel doesn't: product cards may be photos. Telegram cannot turn a text
message into a photo message or back, so "just edit it" is not always
available. This module hides that: when the media type matches it edits,
and when it doesn't it deletes the old screen and sends the new one, which
looks identical to the customer — the screen changes, the chat doesn't grow.

It also keeps the screen's coordinates in FSM data, because the steps that
ask the customer to type (a username, a number of Stars) arrive as separate
messages and no longer carry the screen with them. Those handlers delete
what the customer typed and update the remembered screen, so a purchase that
takes four steps still leaves exactly one message in the chat.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, Message

logger = logging.getLogger("shop")

_CHAT_KEY = "shop_screen_chat_id"
_MSG_KEY = "shop_screen_message_id"
_PHOTO_KEY = "shop_screen_is_photo"


async def remember(state: FSMContext, message: Message | None, is_photo: bool = False) -> None:
    """Record which message is currently the shop screen."""
    if message is None:
        return
    await state.update_data(
        **{
            _CHAT_KEY: message.chat.id,
            _MSG_KEY: message.message_id,
            _PHOTO_KEY: is_photo,
        }
    )


async def forget(state: FSMContext) -> None:
    """Stop treating any message as the screen (after checkout, say)."""
    await state.update_data(**{_CHAT_KEY: None, _MSG_KEY: None, _PHOTO_KEY: False})


async def delete_input(message: Message) -> None:
    """Remove what the customer typed, so only the screen remains.

    Telegram allows a bot to delete incoming messages in a private chat, but
    not unconditionally (age limits, chat restrictions), and this is purely
    cosmetic — it must never interfere with a purchase.
    """
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass


async def render(
    bot,
    state: FSMContext,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    photo_id: str | None = None,
    **kwargs: Any,
) -> Message | None:
    """Draw the shop screen, reusing the remembered message where possible.

    Falls back to sending a new message whenever the old one can't be
    reused — which is also what happens on the very first render.
    """
    data = await state.get_data()
    known_chat = data.get(_CHAT_KEY)
    message_id = data.get(_MSG_KEY)
    was_photo = bool(data.get(_PHOTO_KEY))
    now_photo = photo_id is not None

    if known_chat == chat_id and message_id and was_photo == now_photo:
        try:
            if now_photo:
                await bot.edit_message_caption(
                    chat_id=chat_id, message_id=message_id, caption=text,
                    reply_markup=reply_markup, **kwargs
                )
            else:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text,
                    reply_markup=reply_markup, **kwargs
                )
            return None  # edited in place; coordinates unchanged
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return None
            logger.info("shop_screen_edit_failed: %s", exc)

    # Either there is no screen yet, or the media type changed (a photo card
    # becoming a text payment screen). Replace it: delete the old one first
    # so the customer is never looking at two live screens.
    if known_chat == chat_id and message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:  # noqa: BLE001 - already gone, or too old
            pass

    if now_photo:
        sent = await bot.send_photo(
            chat_id=chat_id, photo=photo_id, caption=text, reply_markup=reply_markup, **kwargs
        )
    else:
        sent = await bot.send_message(
            chat_id=chat_id, text=text, reply_markup=reply_markup, **kwargs
        )
    await remember(state, sent, is_photo=now_photo)
    return sent


__all__ = ["render", "remember", "forget", "delete_input"]
