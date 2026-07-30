from __future__ import annotations

import logging

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.repositories.admin_repo import AdminRepository

security_logger = logging.getLogger("security")


async def is_admin_telegram_id(telegram_id: int, session: AsyncSession) -> bool:
    """Plain-function version of the admin check, reusable outside of
    filters — e.g. to decide whether to show the "Admin panel" menu button."""
    if telegram_id in settings.admin_ids:
        return True
    record = await AdminRepository(session).get(telegram_id)
    return bool(record and record.is_active)


class IsAdmin(BaseFilter):
    """True if the sender is a super admin (from .env ADMIN_IDS) or an
    active admin added later from inside the bot.

    Every admin-only handler must declare this filter explicitly — there is
    no "implicit" admin access anywhere in the codebase.
    """

    async def __call__(self, event: TelegramObject, session: AsyncSession, **kwargs) -> bool:
        tg_user = kwargs.get("event_from_user")
        if tg_user is None:
            return False

        is_admin = await is_admin_telegram_id(tg_user.id, session)
        if not is_admin:
            security_logger.warning("unauthorized_admin_attempt telegram_id=%s", tg_user.id)
        return is_admin
