from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.filters.is_admin import is_admin_telegram_id
from app.keyboards.callback_data import LangCB
from app.keyboards.user_kb import language_kb, main_menu_kb
from app.repositories.user_repo import UserRepository
from app.utils.button_filters import menu_button_filter
from app.utils.i18n import available_languages, t

router = Router(name="user_language")


@router.message(menu_button_filter("menu_language"))
async def choose_language(message: Message, lang: str) -> None:
    await message.answer(t(lang, "msg_choose_language"), reply_markup=language_kb())


@router.callback_query(LangCB.filter())
async def set_language(
    callback: CallbackQuery, callback_data: LangCB, session: AsyncSession, user: User
) -> None:
    code = callback_data.code
    if code not in available_languages():
        await callback.answer()
        return
    users = UserRepository(session)
    await users.set_language(user, code)
    is_admin = await is_admin_telegram_id(user.telegram_id, session)
    await callback.message.edit_text(t(code, "msg_language_set"))
    await callback.message.answer(t(code, "main_menu_hint"), reply_markup=main_menu_kb(code, is_admin=is_admin))
    await callback.answer()
