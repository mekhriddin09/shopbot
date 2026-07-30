from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ProviderLog


class ProviderLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(
        self,
        provider_key: str,
        order_id: int | None,
        request_payload: str | None,
        response_payload: str | None,
        success: bool,
        error: str | None = None,
    ) -> ProviderLog:
        entry = ProviderLog(
            provider_key=provider_key,
            order_id=order_id,
            request_payload=request_payload,
            response_payload=response_payload,
            success=success,
            error=error,
        )
        self.session.add(entry)
        await self.session.commit()
        return entry
