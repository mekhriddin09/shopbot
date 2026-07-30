"""Live support chat: whatever the user types while in the Support section
is relayed to every admin; when an admin replies (Telegram "Reply") to that
relayed copy, the reply is forwarded back to the user. See
app/handlers/admin/support.py for the admin side of the relay."""
from __future__ import annotations

import logging

from aiogram import F, Router
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
from app.utils.i18n import t

router = Router(name="user_support")
security_logger = logging.getLogger("security")

# Every menu button label, across every language, mapped to a canonical key.
# Used so that tapping e.g. "Shop" while mid-conversation in Support exits
# the support chat and opens the shop instead of being relayed as a message.
_MENU_BUTTON_KEYS = ("btn_shop", "btn_my_orders", "btn_reviews", "btn_language", "btn_support")
_TEXT_TO_MENU_KEY = {
    t(lang, key): key for lang in ("uz", "ru", "en") for key in _MENU_BUTTON_KEYS
}


async def _all_admin_ids(session: AsyncSession) -> set[int]:
    ids = set(cfg.admin_ids)
    for admin in await AdminRepository(session).list_active():
        ids.add(admin.telegram_id)
    return ids


@router.message(F.text.in_({t(l, "btn_support") for l in ("uz", "ru", "en")}))
async def show_support(message: Message, session: AsyncSession, lang: str, state: FSMContext) -> None:
    settings_repo = SettingRepository(session)
    text = await settings_repo.get(f"support_message_{lang}") or await settings_repo.get(
        "support_message_en"
    )
    await state.set_state(SupportStates.chatting)
    await message.answer(f"{text}\n\n{t(lang, 'msg_support_type_here')}")


@router.message(SupportStates.chatting)
async def relay_to_admins(
    message: Message, session: AsyncSession, user: User, lang: str, state: FSMContext
) -> None:
    # Escape hatch: tapping any other main-menu button leaves support mode
    # and runs that section instead of being relayed as a chat message.
    if message.text in _TEXT_TO_MENU_KEY and _TEXT_TO_MENU_KEY[message.text] != "btn_support":
        await state.clear()
        await _dispatch_menu_button(_TEXT_TO_MENU_KEY[message.text], message, session, user, lang, state)
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
    if key == "btn_shop":
        from app.handlers.user.shop import open_shop

        await open_shop(message, session, lang)
    elif key == "btn_my_orders":
        from app.handlers.user.orders import my_orders

        await my_orders(message, session, user, lang)
    elif key == "btn_reviews":
        from app.handlers.user.reviews import show_reviews

        await show_reviews(message, session, lang)
    elif key == "btn_language":
        from app.handlers.user.language import choose_language

        await choose_language(message, lang)
