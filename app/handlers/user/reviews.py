"""Customer-facing "⭐ Reviews" section.

The content here is plain free text the admin writes/pastes directly per
language (Admin panel → Sozlamalar → "⭐ Sharhlar matni"), shown as-is,
plus the optional proof-channel link. There is no per-review rating/list —
just whatever the admin wants shown (a summary, hand-picked quotes, etc).
"""
from __future__ import annotations

from aiogram import Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.user_kb import proof_channel_kb
from app.repositories.setting_repo import SettingRepository
from app.utils.button_filters import menu_button_filter
from app.utils.i18n import t

router = Router(name="user_reviews")


@router.message(menu_button_filter("menu_reviews"))
async def show_reviews(message: Message, session: AsyncSession, lang: str) -> None:
    settings_repo = SettingRepository(session)
    reviews_text = await settings_repo.get_localized("reviews_text", lang)
    await message.answer(reviews_text or t(lang, "msg_reviews_empty"))

    proof_url = await settings_repo.get("proof_channel_url")
    if proof_url:
        await message.answer(
            t(lang, "msg_proof_channel_prompt"),
            reply_markup=proof_channel_kb(lang, proof_url),
        )
