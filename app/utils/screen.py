"""One admin panel = one Telegram message.

The admin panel used to answer every tap with a brand-new message. After a
few taps the chat was a wall of half-dead screens: old menus with live
buttons, an order card saying "DELIVERY FAILED" sitting above the message
that said it had since succeeded, and the screen you actually wanted pushed
off the top. Worse, the stale buttons still worked, so it was possible to
act on an order from a card describing a state it had left minutes ago.

So the rule here is: an admin tap **edits the message it was sent from**.
The panel behaves like a screen that changes, not a chat that grows.

`show()` is the single entry point. It takes the callback (or message) and
the new screen, and does the right thing in every case Telegram makes
awkward:

- text message  -> edit_text
- photo/caption -> edit_caption (edit_text raises on media messages)
- unchanged     -> Telegram's "message is not modified" is swallowed, since
                   re-rendering an identical screen is a no-op, not an error
- uneditable    -> too old, deleted, or sent by someone else: falls back to
                   a fresh message so the admin is never left with a dead
                   button and no feedback

Flows that must collect typed input (a price, a broadcast body) can't stay
inside one message — Telegram has no way to type into a message. Those
prompt separately and then call `show()` again on the original screen, so
the panel snaps back to where the admin was instead of leaving a trail.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

logger = logging.getLogger("admin")


def _is_media(message: Message) -> bool:
    """A message whose body lives in `caption`, not `text`.

    `.text is None` is the reliable signal: it covers photos, documents,
    videos and albums alike, whereas checking `.photo` alone misses receipts
    sent as documents — a real bug this project has already hit once.
    """
    return message.text is None


async def show(
    event: CallbackQuery | Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    *,
    force_new: bool = False,
    **kwargs: Any,
) -> Message | None:
    """Render a screen, reusing the current message wherever possible.

    Pass a CallbackQuery (a button tap) to edit in place; pass a Message
    (a command, or text the admin just typed) to start a fresh screen,
    since there is no previous panel message to reuse in that case.
    """
    # Duck-typed rather than isinstance: a CallbackQuery is "the thing that
    # carries the message it came from". Checking the attribute keeps this
    # usable from tests and from any wrapper object, and there is nothing
    # else it could reasonably be.
    message = getattr(event, "message", None)
    if message is None:
        # A plain Message (a command, or text the admin typed): there is no
        # previous panel screen to reuse, so start one.
        return await event.answer(text, reply_markup=reply_markup, **kwargs)

    if force_new:
        return await message.answer(text, reply_markup=reply_markup, **kwargs)

    try:
        if _is_media(message):
            return await message.edit_caption(caption=text, reply_markup=reply_markup, **kwargs)
        return await message.edit_text(text, reply_markup=reply_markup, **kwargs)
    except TelegramBadRequest as exc:
        detail = str(exc)
        if "message is not modified" in detail:
            # Same screen re-rendered (e.g. a toggle that landed back on its
            # original value). Nothing to do, and certainly nothing to
            # report to the admin.
            return message
        logger.info("screen_edit_failed, sending new message: %s", detail)
        try:
            return await message.answer(text, reply_markup=reply_markup, **kwargs)
        except TelegramBadRequest as exc2:
            # The text itself is what Telegram is rejecting (most commonly
            # "can't parse entities" — some stored value has become invalid
            # HTML, e.g. mismatched tags from a manual DB edit or an old
            # save path). Retrying identically would just fail the same way
            # again, and leaving this exception uncaught means the admin's
            # tap never gets a `callback.answer()` — which is exactly what
            # makes flows like "type the oferta text" look like they
            # silently swallow the admin's input: Telegram's own client
            # shows a timeout/error toast on the stuck button, with no clue
            # what actually went wrong. Show it as escaped plain text
            # instead — worse formatting, but the admin sees their data and
            # a real explanation rather than nothing at all.
            logger.warning("screen_send_failed, falling back to plain text: %s", exc2)
            from html import escape as html_escape

            plain_kwargs = dict(kwargs)
            plain_kwargs["parse_mode"] = None
            fallback_text = (
                "⚠️ Formatlab ko'rsatib bo'lmadi (matnda noto'g'ri HTML belgilari bo'lishi mumkin), "
                "lekin quyidagi qiymat saqlangan/joriy holatda:\n\n" + html_escape(text)
            )
            try:
                return await message.answer(fallback_text, reply_markup=reply_markup, **plain_kwargs)
            except TelegramBadRequest:
                logger.error("screen_send_failed_completely: %s", exc2)
                return None


async def answer_and_show(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    *,
    toast: str | None = None,
    alert: bool = False,
    **kwargs: Any,
) -> Message | None:
    """`show()` plus the callback acknowledgement Telegram requires.

    Without answering the callback the client shows a spinner on the button
    for several seconds, which reads as "the bot is stuck" even when the
    screen underneath has already updated.
    """
    await callback.answer(toast or "", show_alert=alert)
    return await show(callback, text, reply_markup, **kwargs)


async def edit_panel(
    bot,
    chat_id: int | None,
    message_id: int | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    **kwargs: Any,
) -> bool:
    """Update the panel screen from a *message* handler.

    Typed input (a price, a rejection reason) necessarily arrives as its own
    message, so the handler no longer holds the callback that owns the
    screen. Flows therefore stash the panel's chat_id/message_id in FSM data
    and call this when they're done, which puts the admin back on the screen
    they started from instead of ending the flow with another loose message.

    Returns False when there was nothing to edit, letting the caller decide
    whether to send something instead.
    """
    if not chat_id or not message_id:
        return False
    try:
        await bot.edit_message_text(
            text=text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup, **kwargs
        )
        return True
    except TelegramBadRequest as exc:
        detail = str(exc)
        if "message is not modified" in detail:
            return True
        if "there is no text in the message" in detail:
            # The panel is a photo/document card (an order with a receipt):
            # its body lives in the caption.
            try:
                await bot.edit_message_caption(
                    caption=text, chat_id=chat_id, message_id=message_id,
                    reply_markup=reply_markup, **kwargs
                )
                return True
            except TelegramBadRequest:
                return False
        logger.info("panel_edit_failed: %s", detail)
        return False


__all__ = ["show", "answer_and_show", "edit_panel"]
