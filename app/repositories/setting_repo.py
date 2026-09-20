from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Setting


class SettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str, default: str = "") -> str:
        result = await self.session.execute(select(Setting).where(Setting.key == key))
        row = result.scalar_one_or_none()
        return row.value if row else default

    async def get_bool(self, key: str, default: bool = True) -> bool:
        value = await self.get(key, "1" if default else "0")
        return value == "1"

    async def set(self, key: str, value: str) -> None:
        result = await self.session.execute(select(Setting).where(Setting.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = value
        else:
            row = Setting(key=key, value=value)
            self.session.add(row)
        await self.session.commit()

    async def all(self) -> dict[str, str]:
        result = await self.session.execute(select(Setting))
        return {row.key: row.value for row in result.scalars().all()}

    async def get_localized(self, base_key: str, lang: str, langs: tuple[str, ...] = ("uz", "ru", "en")) -> str:
        """`{base_key}_{lang}` if the admin filled it in, otherwise
        whichever other language they DID fill in, in `langs` order.

        Several call sites used to hardcode a single fixed fallback
        language instead of this (e.g. `get(f"oferta_text_{lang}") or
        get("oferta_text_uz")`) — harmless for a user whose language
        already IS that fallback, but for everyone else it meant "admin
        only wrote the Russian oferta text" left every Uzbek-language user
        with an empty string and no oferta screen at all (silently skipped
        — see onboarding_gate.py), instead of falling back to whatever the
        admin actually wrote. This is the one fallback chain every
        "lang"-kind setting (oferta_text, welcome_message, reviews_text,
        support_message, referral_rules, payment_instructions,
        card_auto_note, ...) should use instead."""
        value = await self.get(f"{base_key}_{lang}")
        if (value or "").strip():
            return value
        for candidate in langs:
            if candidate == lang:
                continue
            value = await self.get(f"{base_key}_{candidate}")
            if (value or "").strip():
                return value
        return ""
