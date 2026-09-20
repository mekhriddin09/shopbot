"""Admin panel — "🎨 Tugmalar boshqaruvi" (Button Manager).

Lets an admin restyle any button in `app.services.button_registry.
BUTTON_REGISTRY` (text per language / style / emoji / enabled) without a
Python edit or redeploy. Every write here goes through
`app.repositories.button_repo.ButtonRepository`, which only ever touches
`ButtonConfig`/`ButtonTranslation` — presentation fields, never callback
data, product ids, or order logic (see the docstring on `ButtonConfig`).
After every write we call `refresh_button_cache()` so the change is live
immediately, without waiting for the next bot restart.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters.is_admin import IsAdmin
from app.keyboards.admin_kb import (
    _BUTTON_GROUP_LABELS,
    _BUTTON_STYLE_LABELS,
    admin_button_detail_kb,
    admin_button_lang_pick_kb,
    admin_button_list_kb,
    admin_button_root_kb,
    admin_button_search_results_kb,
    admin_button_style_pick_kb,
)
from app.keyboards.button_helpers import inline_btn
from app.keyboards.callback_data import AdminButtonCB, AdminSettingsCB
from app.repositories.button_repo import ButtonRepository
from app.services.button_registry import BUTTON_REGISTRY, get_button_def
from app.services.button_service import refresh_button_cache, resolve_button
from app.states.admin_states import AdminInput
from app.utils.i18n import available_languages, t
from app.utils.screen import show

logger = logging.getLogger("admin")
admin_actions_logger = logging.getLogger("admin_actions")

router = Router(name="admin_buttons")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def render_button_root(_: AsyncSession) -> tuple[str, object]:
    text = (
        "\U0001F3A8 <b>Tugmalar boshqaruvi</b>\n\n"
        "Bu yerda mijozlarga ko'rinadigan tugmalarning matni, rangi, emojisi "
        "va til bo'yicha tarjimasini o'zgartirasiz — kodga tegmasdan.\n"
        "⚠️ Bu yerda faqat ko'rinish o'zgaradi: tugma nimani bosishi (qanday "
        "amal bajarishi) hech qachon o'zgarmaydi.\n\n"
        "Bo'limni tanlang:"
    )
    return text, admin_button_root_kb()


async def render_button_group(session: AsyncSession, group: str) -> tuple[str, object]:
    repo = ButtonRepository(session)
    enabled_by_key: dict[str, bool] = {}
    for button_def in BUTTON_REGISTRY.values():
        if button_def.group != group:
            continue
        row = await repo.get(button_def.key)
        enabled_by_key[button_def.key] = row.enabled if row else True
    title = _BUTTON_GROUP_LABELS.get(group, group)
    text = f"\U0001F3A8 <b>{title}</b>\n\nTugmani tanlang:"
    return text, admin_button_list_kb(group, enabled_by_key)


async def render_button_detail(session: AsyncSession, key: str) -> tuple[str, object, str]:
    """Returns (text, keyboard, group) — group is needed by every caller to
    wire the "back" button, so it's handed back instead of re-derived."""
    button_def = get_button_def(key)
    if button_def is None:
        return f"❌ Noma'lum tugma key: <code>{key}</code>", admin_button_root_kb(), "root"

    row = await ButtonRepository(session).get(key)
    langs = available_languages()

    lines = [f"\U0001F3A8 <b>{button_def.label or key}</b>", f"Key: <code>{key}</code>", ""]
    lines.append("\U0001F310 <b>Matn:</b>")
    for lang in langs:
        tr = next((tr for tr in row.translations if tr.language == lang), None) if row else None
        if tr:
            lines.append(f"  • {lang.upper()}: {tr.text}")
        else:
            lines.append(f"  • {lang.upper()}: <i>(standart) {t(lang, button_def.i18n_key)}</i>")

    style_value = row.style if row else None
    lines.append("")
    lines.append(f"\U0001F3A8 <b>Rang:</b> {_BUTTON_STYLE_LABELS.get(style_value, style_value)}" if row and row.style else f"\U0001F3A8 <b>Rang:</b> {_BUTTON_STYLE_LABELS[None]}")

    if row and row.custom_emoji_id:
        lines.append("\U0001F600 <b>Emoji:</b> maxsus Telegram emoji o'rnatilgan")
    elif row and row.unicode_emoji:
        lines.append(f"\U0001F600 <b>Emoji:</b> {row.unicode_emoji}")
    else:
        lines.append(f"\U0001F600 <b>Emoji:</b> <i>(standart) {button_def.default_emoji or '—'}</i>")

    enabled = row.enabled if row else True
    status_text = "✅ yoqilgan" if enabled else "\U0001F6AB o'chirilgan"
    lines.append(f"\U0001F4A1 <b>Holati:</b> {status_text}")

    if button_def.surface == "reply":
        lines.append("")
        lines.append("ℹ️ Bu asosiy menyu tugmasi — Telegram reply-klaviaturada rang/maxsus emoji ko'rsatilmaydi, faqat matn ishlatiladi.")

    return "\n".join(lines), admin_button_detail_kb(key, button_def.group), button_def.group


@router.callback_query(AdminButtonCB.filter(F.action == "root"))
async def button_root(callback: CallbackQuery, session: AsyncSession) -> None:
    text, kb = await render_button_root(session)
    await show(callback, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(AdminButtonCB.filter(F.action == "group"))
async def button_group(callback: CallbackQuery, callback_data: AdminButtonCB, session: AsyncSession) -> None:
    text, kb = await render_button_group(session, callback_data.group or "main_menu")
    await show(callback, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(AdminButtonCB.filter(F.action == "open"))
async def button_open(callback: CallbackQuery, callback_data: AdminButtonCB, session: AsyncSession) -> None:
    if not callback_data.key:
        await callback.answer()
        return
    text, kb, _group = await render_button_detail(session, callback_data.key)
    await show(callback, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(AdminButtonCB.filter(F.action == "pick_lang_text"))
async def button_pick_lang_text(callback: CallbackQuery, callback_data: AdminButtonCB) -> None:
    if not callback_data.key:
        await callback.answer()
        return
    try:
        await callback.message.edit_reply_markup(
            reply_markup=admin_button_lang_pick_kb(callback_data.key, callback_data.group or "main_menu")
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
    await callback.answer()


@router.callback_query(AdminButtonCB.filter(F.action == "edit_text"))
async def button_edit_text_start(
    callback: CallbackQuery, callback_data: AdminButtonCB, session: AsyncSession, state: FSMContext
) -> None:
    key, lang = callback_data.key, callback_data.lang
    if not key or not lang:
        await callback.answer()
        return
    button_def = get_button_def(key)
    row = await ButtonRepository(session).get(key)
    current_override = None
    if row:
        tr = next((tr for tr in row.translations if tr.language == lang), None)
        current_override = tr.text if tr else None
    current_default = t(lang, button_def.i18n_key) if button_def else ""

    await state.set_state(AdminInput.waiting_text)
    await state.update_data(
        panel_chat_id=callback.message.chat.id,
        panel_message_id=callback.message.message_id,
        action="button_edit_text",
        key=key,
        lang=lang,
        group=callback_data.group or "main_menu",
    )
    shown = current_override or f"(standart) {current_default}"
    await show(
        callback,
        f"Joriy matn ({lang.upper()}):\n\n{shown}\n\n"
        f"👇 Yangi matnni yozing (standartga qaytarish uchun '-' yuboring):",
    )
    await callback.answer()


@router.callback_query(AdminButtonCB.filter(F.action == "style_menu"))
async def button_style_menu(callback: CallbackQuery, callback_data: AdminButtonCB) -> None:
    if not callback_data.key:
        await callback.answer()
        return
    try:
        await callback.message.edit_reply_markup(
            reply_markup=admin_button_style_pick_kb(callback_data.key, callback_data.group or "main_menu")
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
    await callback.answer()


@router.callback_query(AdminButtonCB.filter(F.action == "set_style"))
async def button_set_style(callback: CallbackQuery, callback_data: AdminButtonCB, session: AsyncSession) -> None:
    key = callback_data.key
    if not key:
        await callback.answer()
        return
    # "_default" sentinel avoids the aiogram CallbackData empty-string/None
    # round-trip bug (see QtyCB.provider's docstring for the same issue).
    style = None if callback_data.style in (None, "_default") else callback_data.style
    await ButtonRepository(session).update_presentation(key, style=style)
    await refresh_button_cache()
    admin_actions_logger.info("button_style_changed key=%s style=%s admin=%s", key, style, callback.from_user.id)
    text, kb, _group = await render_button_detail(session, key)
    await show(callback, text, reply_markup=kb)
    await callback.answer("Rang o'zgartirildi ✅")


@router.callback_query(AdminButtonCB.filter(F.action == "toggle_enabled"))
async def button_toggle_enabled(callback: CallbackQuery, callback_data: AdminButtonCB, session: AsyncSession) -> None:
    key = callback_data.key
    if not key:
        await callback.answer()
        return
    repo = ButtonRepository(session)
    row = await repo.get(key)
    new_state = not (row.enabled if row else True)
    await repo.update_presentation(key, enabled=new_state)
    await refresh_button_cache()
    admin_actions_logger.info("button_enabled_changed key=%s enabled=%s admin=%s", key, new_state, callback.from_user.id)
    text, kb, _group = await render_button_detail(session, key)
    await show(callback, text, reply_markup=kb)
    await callback.answer("Yoqildi ✅" if new_state else "O'chirildi \U0001F6AB")


@router.callback_query(AdminButtonCB.filter(F.action == "emoji_prompt"))
async def button_emoji_prompt(
    callback: CallbackQuery, callback_data: AdminButtonCB, state: FSMContext
) -> None:
    key = callback_data.key
    if not key:
        await callback.answer()
        return
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(
        panel_chat_id=callback.message.chat.id,
        panel_message_id=callback.message.message_id,
        action="button_edit_emoji",
        key=key,
        group=callback_data.group or "main_menu",
    )
    await show(
        callback,
        "\U0001F600 Yangi emoji yuboring:\n\n"
        "• Oddiy Unicode emoji (masalan 🔥) — shunchaki yuboring.\n"
        "• Maxsus Telegram emoji (Premium) — o'sha emojini o'z ichiga olgan "
        "xabar sifatida yuboring, bot uni avtomatik taniydi.\n\n"
        "Standart emojiga qaytarish uchun '-' yuboring.",
    )
    await callback.answer()


@router.callback_query(AdminButtonCB.filter(F.action == "reset"))
async def button_reset(callback: CallbackQuery, callback_data: AdminButtonCB, session: AsyncSession) -> None:
    key = callback_data.key
    if not key:
        await callback.answer()
        return
    await ButtonRepository(session).reset_to_default(key)
    await refresh_button_cache()
    admin_actions_logger.info("button_reset key=%s admin=%s", key, callback.from_user.id)
    text, kb, _group = await render_button_detail(session, key)
    await show(callback, "♻️ Standart qiymatlarga qaytarildi.\n\n" + text, reply_markup=kb)
    await callback.answer()


@router.callback_query(AdminButtonCB.filter(F.action == "preview"))
async def button_preview(callback: CallbackQuery, callback_data: AdminButtonCB) -> None:
    key = callback_data.key
    button_def = get_button_def(key) if key else None
    if not key or button_def is None:
        await callback.answer()
        return
    await callback.answer()
    for lang in available_languages():
        if button_def.surface == "reply":
            resolved = resolve_button(key, lang)
            await callback.message.answer(f"{lang.upper()}: {resolved.text}")
            continue
        from aiogram.types import InlineKeyboardMarkup

        btn = inline_btn(key, lang, callback_data=AdminButtonCB(action="root").pack())
        if btn is None:
            await callback.message.answer(f"{lang.upper()}: (tugma o'chirilgan — ko'rinmaydi)")
            continue
        await callback.message.answer(
            f"{lang.upper()} preview:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn]])
        )


@router.callback_query(AdminButtonCB.filter(F.action == "search_prompt"))
async def button_search_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(
        panel_chat_id=callback.message.chat.id,
        panel_message_id=callback.message.message_id,
        action="button_search",
    )
    await show(callback, "\U0001F50D Qidiruv so'zini yozing (masalan: \"sotib olish\" yoki \"buy\"):")
    await callback.answer()
