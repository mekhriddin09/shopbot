from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import ButtonConfig, ButtonTranslation


class ButtonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str) -> ButtonConfig | None:
        result = await self.session.execute(
            select(ButtonConfig).where(ButtonConfig.key == key).options(selectinload(ButtonConfig.translations))
        )
        return result.scalar_one_or_none()

    async def all(self) -> list[ButtonConfig]:
        result = await self.session.execute(
            select(ButtonConfig).options(selectinload(ButtonConfig.translations)).order_by(ButtonConfig.sort_order, ButtonConfig.key)
        )
        return list(result.scalars().all())

    async def get_or_create(self, key: str) -> ButtonConfig:
        row = await self.get(key)
        if row:
            return row
        row = ButtonConfig(key=key)
        self.session.add(row)
        await self.session.commit()
        return await self.get(key)  # reload with translations relationship populated

    async def set_translation(self, key: str, language: str, text: str) -> None:
        row = await self.get_or_create(key)
        existing = next((tr for tr in row.translations if tr.language == language), None)
        if existing:
            existing.text = text
        else:
            self.session.add(ButtonTranslation(button_id=row.id, language=language, text=text))
        await self.session.commit()

    async def update_presentation(
        self,
        key: str,
        *,
        style: str | None | object = ...,
        custom_emoji_id: str | None | object = ...,
        unicode_emoji: str | None | object = ...,
        enabled: bool | object = ...,
        sort_order: int | object = ...,
    ) -> ButtonConfig:
        """`...` (Ellipsis) as a sentinel means "leave unchanged" so callers
        can update a single field without clobbering the rest — every field
        here is presentation-only by construction (see ButtonConfig
        docstring), so this can never be used to touch callback/action
        logic no matter what the admin panel sends it."""
        row = await self.get_or_create(key)
        if style is not ...:
            row.style = style
        if custom_emoji_id is not ...:
            row.custom_emoji_id = custom_emoji_id
        if unicode_emoji is not ...:
            row.unicode_emoji = unicode_emoji
        if enabled is not ...:
            row.enabled = enabled
        if sort_order is not ...:
            row.sort_order = sort_order
        await self.session.commit()
        return row

    async def reset_to_default(self, key: str) -> None:
        row = await self.get(key)
        if not row:
            return
        await self.session.delete(row)
        await self.session.commit()
