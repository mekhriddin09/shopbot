"""Reference implementation of an external supplier provider (Mode 3).

This is a working example that generates a fake license key locally instead
of calling a real HTTP endpoint, so the project runs end-to-end out of the
box without any third-party account. Swap the body of `fetch()` for a real
`httpx` call to your actual supplier when you have one — the retry/timeout
scaffolding below is already production-shaped.
"""
from __future__ import annotations

import json
import logging
import secrets

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.services.providers.base import BaseProvider, ProviderResult

logger = logging.getLogger("providers")


class MockProvider(BaseProvider):
    key = "mock_provider"

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4))
    async def _call_supplier(self, order_uuid: str) -> str:
        # --- Replace this block with a real call, e.g.: ---
        # async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
        #     resp = await client.post(
        #         "https://supplier.example.com/api/issue",
        #         json={"order": order_uuid},
        #         headers={"Authorization": f"Bearer {settings.MOCK_PROVIDER_API_KEY}"},
        #     )
        #     resp.raise_for_status()
        #     return resp.json()["license_key"]
        return f"MOCK-{secrets.token_hex(6).upper()}"

    async def fetch(self, *, product_external_ref: str | None, order_uuid: str) -> ProviderResult:
        request_payload = json.dumps({"order_uuid": order_uuid, "ref": product_external_ref})
        try:
            license_key = await self._call_supplier(order_uuid)
            logger.info("mock_provider issued key for order=%s", order_uuid)
            return ProviderResult(
                success=True,
                payload=license_key,
                raw_request=request_payload,
                raw_response=json.dumps({"license_key": license_key}),
            )
        except httpx.HTTPError as exc:
            logger.error("mock_provider HTTP error for order=%s: %s", order_uuid, exc)
            return ProviderResult(
                success=False, raw_request=request_payload, error=f"HTTP error: {exc}"
            )
        except Exception as exc:  # noqa: BLE001 - provider must never raise
            logger.exception("mock_provider unexpected error for order=%s", order_uuid)
            return ProviderResult(success=False, raw_request=request_payload, error=str(exc))
