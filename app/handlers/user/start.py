from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.filters.is_admin import is_admin_telegram_id
from app.keyboards.user_kb import main_menu_kb
from app.repositories.setting_repo import SettingRepository

router = Router(name="user_start")


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, user: User, lang: str, state: FSMContext) -> None:
    await state.clear()
    settings_repo = SettingRepository(session)
    welcome = await settings_repo.get(f"welcome_message_{lang}") or await settings_repo.get(
        "welcome_message_en"
    )
    is_admin = await is_admin_telegram_id(user.telegram_id, session)
    await message.answer(welcome, reply_markup=main_menu_kb(lang, is_admin=is_admin))
