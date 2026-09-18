"""Admin management of the referral-confirmation phone whitelist — specific
non-+998 numbers the admin has chosen to allow through (see
app/services/onboarding_service.py:is_phone_allowed)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters.is_admin import IsAdmin
from app.keyboards.admin_kb import admin_phone_whitelist_kb
from app.keyboards.callback_data import AdminPhoneCB
from app.repositories.allowed_phone_repo import AllowedPhoneRepository
from app.states.admin_states import AdminInput
from app.utils.screen import show

router = Router(name="admin_phone_whitelist")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def _render_list_text(entries: list) -> str:
    if not entries:
        return "☎️ Ruxsat etilgan chet el raqamlari\n\nHozircha bo'sh."
    return "☎️ Ruxsat etilgan chet el raqamlari\n\n(bosilsa o'chiriladi)"


@router.callback_query(AdminPhoneCB.filter(F.action == "list"))
async def list_allowed_phones(callback: CallbackQuery, session: AsyncSession) -> None:
    entries = await AllowedPhoneRepository(session).list_all()
    text = await _render_list_text(entries)
    await show(callback, text, reply_markup=admin_phone_whitelist_kb(entries))
    await callback.answer()


@router.callback_query(AdminPhoneCB.filter(F.action == "add"))
async def add_allowed_phone_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(panel_chat_id=callback.message.chat.id, panel_message_id=callback.message.message_id, action="add_allowed_phone")
    await show(callback, 
        "✏️ Ruxsat berilishi kerak bo'lgan raqamni yozing (masalan: +7 999 123 45 67):"
    )
    await callback.answer()


@router.callback_query(AdminPhoneCB.filter(F.action == "remove"))
async def remove_allowed_phone(callback: CallbackQuery, callback_data: AdminPhoneCB, session: AsyncSession) -> None:
    removed = await AllowedPhoneRepository(session).remove(callback_data.phone_id)
    if not removed:
        await callback.answer("Topilmadi.", show_alert=True)
        return
    entries = await AllowedPhoneRepository(session).list_all()
    text = await _render_list_text(entries)
    await callback.message.edit_text(text)
    await callback.message.edit_reply_markup(reply_markup=admin_phone_whitelist_kb(entries))
    await callback.answer("O'chirildi ✅")


__all__ = ["router"]
