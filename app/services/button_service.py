"""Resolves one logical button (see `button_registry.BUTTON_REGISTRY`) into
concrete render fields (text/style/emoji/enabled), applying admin overrides
from the DB on top of code defaults, with a fallback at every step so a
database problem can never make the bot unusable (per the original spec:
"a database mistake should never make the bot unusable").

Fallback order for TEXT:
  1. Admin's `ButtonTranslation` for the requested language, if set.
  2. Admin's `ButtonTranslation` for the default language, if set.
  3. `app.utils.i18n.t(lang, button_def.i18n_key)` — today's existing
     locale text (emoji already baked in), byte-for-byte what renders today.
Only once an admin has actually typed a translation (step 1/2) does the
resolver switch to composing emoji + plain text separately; until then
nothing changes from current behaviour.

Fallback order for STYLE: admin override -> semantic default
(`STYLE_BY_TYPE[button_def.type]`) -> None (Telegram's own default look).

Fallback order for EMOJI (only used once a translation override exists):
custom_emoji_id (if set) -> unicode_emoji override -> registry default
Unicode emoji -> none.

Buttons for surfaces that can't carry style/custom-emoji (`surface="reply"`,
i.e. ReplyKeyboardMarkup) only ever get a resolved `text`; style/emoji
fields are still resolved but callers building KeyboardButton simply don't
use them (Telegram's KeyboardButton has no such fields at all).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.button_registry import STYLE_BY_TYPE, BUTTON_REGISTRY, ButtonDef, get_button_def
from app.utils.i18n import t

logger = logging.getLogger("buttons")


@dataclass(frozen=True)
class _CachedButton:
    style: str | None
    custom_emoji_id: str | None
    unicode_emoji: str | None
    enabled: bool
    translations: dict[str, str]  # language -> text


@dataclass(frozen=True)
class ResolvedButton:
    text: str
    style: str | None = None
    custom_emoji_id: str | None = None
    enabled: bool = True


# In-process cache, refreshed at bot startup and after any Button Manager
# edit (phase 2). Deliberately synchronous to read: every keyboard builder
# in this codebase is a plain sync function, so resolve_button() must be
# sync too — this cache is what makes that possible without threading a DB
# session through every keyboard call site.
_CACHE: dict[str, _CachedButton] = {}
_loaded = False


async def refresh_button_cache() -> None:
    """Reloads `_CACHE` from the DB. Safe to call repeatedly (bot startup,
    and after every admin edit in Button Manager). On any DB error, leaves
    the previous cache in place (or empty, pre-first-load) rather than
    raising — a broken refresh must never take the bot's buttons down."""
    global _loaded
    try:
        from app.database.engine import async_session_maker
        from app.repositories.button_repo import ButtonRepository

        async with async_session_maker() as session:
            rows = await ButtonRepository(session).all()
        new_cache: dict[str, _CachedButton] = {}
        for row in rows:
            new_cache[row.key] = _CachedButton(
                style=row.style,
                custom_emoji_id=row.custom_emoji_id,
                unicode_emoji=row.unicode_emoji,
                enabled=row.enabled,
                translations={tr.language: tr.text for tr in row.translations},
            )
        _CACHE.clear()
        _CACHE.update(new_cache)
        _loaded = True
        logger.info("Button cache refreshed: %d override(s) loaded", len(new_cache))
    except Exception:  # noqa: BLE001 - a cache refresh must never crash the bot
        logger.exception("Button cache refresh failed; keeping previous cache")


def resolve_button(key: str, lang: str, default_language: str = "uz") -> ResolvedButton:
    button_def: ButtonDef | None = get_button_def(key)
    if button_def is None:
        # Unknown key (typo, or a key retired from the registry): render
        # something visible instead of crashing a keyboard build.
        logger.warning("resolve_button: unknown button key %r", key)
        return ResolvedButton(text=key)

    cached = _CACHE.get(key)
    if cached is None:
        # No admin override at all -> identical to current hardcoded
        # behaviour (i18n text as-is, semantic default style, no custom
        # emoji).
        return ResolvedButton(
            text=t(lang, button_def.i18n_key),
            style=STYLE_BY_TYPE.get(button_def.type),
            custom_emoji_id=None,
            enabled=True,
        )

    text = (
        cached.translations.get(lang)
        or cached.translations.get(default_language)
        or t(lang, button_def.i18n_key)
    )
    # Only compose a separate emoji prefix once the admin actually typed a
    # plain-text translation override — otherwise `text` already came
    # straight from i18n with its emoji baked in, and prefixing again would
    # double it up.
    has_translation_override = bool(cached.translations.get(lang) or cached.translations.get(default_language))
    if has_translation_override:
        emoji = cached.unicode_emoji or button_def.default_emoji
        if emoji and not cached.custom_emoji_id:
            text = f"{emoji} {text}"

    style = cached.style if cached.style is not None else STYLE_BY_TYPE.get(button_def.type)
    return ResolvedButton(
        text=text,
        style=style,
        custom_emoji_id=cached.custom_emoji_id,
        enabled=cached.enabled,
    )


def is_loaded() -> bool:
    return _loaded


def resolved_texts_for_key(key: str) -> set[str]:
    """Every text string that should currently be recognized as "the X
    button was tapped", across all 3 languages, both the code default AND
    any admin override.

    Several main-menu handlers match incoming message text against a fixed
    set of strings (a `ReplyKeyboardMarkup` has no callback_data — Telegram
    just echoes back whatever text was on the button). If Button Manager
    (phase 2) lets an admin rename that text, a *static* set built once at
    import time would go stale and the button would silently stop working
    the moment it's renamed. Handlers must call this function (via
    `app.utils.button_filters.menu_button_filter`) instead of hardcoding
    `{t(l, "btn_x") for l in (...)}`, so a rename always keeps working."""
    from app.utils.i18n import available_languages

    button_def = get_button_def(key)
    if button_def is None:
        return set()

    texts = {t(lang, button_def.i18n_key) for lang in available_languages()}
    cached = _CACHE.get(key)
    if cached:
        for lang, override_text in cached.translations.items():
            texts.add(override_text)
            emoji = cached.unicode_emoji or button_def.default_emoji
            if emoji and not cached.custom_emoji_id:
                texts.add(f"{emoji} {override_text}")
    return texts
