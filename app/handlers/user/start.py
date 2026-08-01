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
from app.services.referral_service import ReferralService, parse_start_referral_payload

router = Router(name="user_start")


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    session: AsyncSession,
    user: User,
    lang: str,
    state: FSMContext,
    user_created: bool = False,
) -> None:
    await state.clear()

    # Referral deep-link: only ever linked on this user's very first /start
    # (see ReferralService.set_referrer_if_new — also guards against
    # self-referral and non-existent referrer ids).
    if user_created:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            referrer_id = parse_start_referral_payload(parts[1])
            if referrer_id is not None:
                await ReferralService(session).set_referrer_if_new(user, referrer_id)

    settings_repo = SettingRepository(session)
    welcome = await settings_repo.get(f"welcome_message_{lang}") or await settings_repo.get(
        "welcome_message_en"
    )
    is_admin = await is_admin_telegram_id(user.telegram_id, session)
    await message.answer(welcome, reply_markup=main_menu_kb(lang, is_admin=is_admin))
