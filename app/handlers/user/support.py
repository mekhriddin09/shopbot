"""Live support chat: whatever the user types while in the Support section
is relayed to every admin; when an admin replies (Telegram "Reply") to that
relayed copy, the reply is forwarded back to the user. See
app/handlers/admin/support.py for the admin side of the relay."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings as cfg
from app.database.models import User
from app.repositories.admin_repo import AdminRepository
from app.repositories.setting_repo import SettingRepository
from app.repositories.support_repo import SupportRelayRepository
from app.states.user_states import SupportStates
from app.utils.button_filters import menu_button_filter, menu_button_key_for_text
from app.utils.i18n import t

router = Router(name="user_support")
security_logger = logging.getLogger("security")


async def _all_admin_ids(session: AsyncSession) -> set[int]:
    ids = set(cfg.admin_ids)
    for admin in await AdminRepository(session).list_active():
        ids.add(admin.telegram_id)
    return ids


@router.message(menu_button_filter("menu_support"))
async def show_support(message: Message, session: AsyncSession, lang: str, state: FSMContext) -> None:
    settings_repo = SettingRepository(session)
    text = await settings_repo.get_localized("support_message", lang)
    await state.set_state(SupportStates.chatting)
    await message.answer(f"{text}\n\n{t(lang, 'msg_support_type_here')}")


@router.message(SupportStates.chatting)
async def relay_to_admins(
    message: Message, session: AsyncSession, user: User, lang: str, state: FSMContext
) -> None:
    # Escape hatch: tapping any other main-menu button leaves support mode
    # and runs that section instead of being relayed as a chat message.
    menu_key = menu_button_key_for_text(message.text)
    if menu_key and menu_key != "menu_support":
        await state.clear()
        await _dispatch_menu_button(menu_key, message, session, user, lang, state)
        return

    admin_ids = await _all_admin_ids(session)
    if not admin_ids:
        await message.answer(t(lang, "msg_error_generic"))
        return

    header = (
        f"\U0001F4AC <b>Yordam so'rovi</b>\n"
        f"\U0001F464 {user.full_name or '-'} (@{user.username or '-'})\n"
        f"\U0001F194 <code>{user.telegram_id}</code>\n\n"
    )
    relay_repo = SupportRelayRepository(session)
    for admin_id in admin_ids:
        try:
            sent = None
            if message.text:
                sent = await message.bot.send_message(admin_id, header + message.text)
            else:
                # Forward media/documents/etc. as-is, with a header first.
                await message.bot.send_message(admin_id, header.rstrip())
                sent = await message.copy_to(admin_id)
            if sent is not None:
                await relay_repo.create(user.telegram_id, admin_id, sent.message_id)
        except TelegramAPIError:
            security_logger.warning("Failed to relay support message to admin %s", admin_id)

    await message.answer(t(lang, "msg_support_sent"))


async def _dispatch_menu_button(
    key: str, message: Message, session: AsyncSession, user: User, lang: str, state: FSMContext
) -> None:
    """Re-run the handler for the menu button that interrupted support mode."""
    if key == "menu_shop":
        from app.handlers.user.shop import open_shop

        await open_shop(message, session, lang)
    elif key == "menu_my_orders":
        from app.handlers.user.orders import my_orders

        await my_orders(message, session, user, lang)
    elif key == "menu_reviews":
        from app.handlers.user.reviews import show_reviews

        await show_reviews(message, session, lang)
    elif key == "menu_language":
        from app.handlers.user.language import choose_language

        await choose_language(message, lang)
