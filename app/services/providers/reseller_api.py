"""External reseller API — real Mode 3 (external supplier) provider.

Matches the "SHOP - RESELLER API" documentation the admin supplied:

- Base URL: settings.RESELLER_API_BASE_URL (default http://2.26.230.116:8080)
- Auth: header "Authorization: <api_key>" (raw key, no "Bearer " prefix)
- GET  /v1/balance             -> {"status": "success", "balance": 150.0}
- GET  /v1/products            -> {"status": "success", "products": [...]}
- POST /v1/buy {"product_id", "quantity"}
        -> {"status": "success", "product_id", "quantity", "total_price",
            "new_balance", "links": ["https://..."]}

Each local Product using this provider needs `external_product_id` set to
the matching `id` from the supplier's /v1/products list (e.g. "gemini") —
edit it from Admin panel -> product -> "🆔 Tashqi ID". `provider_key` itself
just needs to be set to this provider's key, "reseller_api".
"""
from __future__ import annotations

import json
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config.settings import settings
from app.services.providers.base import BaseProvider, ProviderResult

logger = logging.getLogger("providers")


class ResellerApiProvider(BaseProvider):
    key = "reseller_api"

    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 15.0) -> None:
        self.base_url = (base_url or settings.RESELLER_API_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.RESELLER_API_KEY
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self.api_key, "Content-Type": "application/json"}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4), reraise=True)
    async def _post(self, path: str, json_body: dict) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}{path}", json=json_body, headers=self._headers())
            resp.raise_for_status()
            return resp

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4), reraise=True)
    async def _get(self, path: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}{path}", headers=self._headers())
            resp.raise_for_status()
            return resp

    async def get_balance(self) -> tuple[bool, float | None, str | None]:
        """Not part of the BaseProvider contract — a small extra helper the
        admin/stats side can call to show remaining reseller balance."""
        try:
            resp = await self._get("/v1/balance")
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.error("reseller_api get_balance error: %s", exc)
            return False, None, str(exc)
        if data.get("status") != "success":
            return False, None, data.get("message", "unknown_error")
        return True, data.get("balance"), None

    async def fetch(self, *, product_external_ref: str | None, order_uuid: str) -> ProviderResult:
        if not self.api_key:
            return ProviderResult(success=False, error="RESELLER_API_KEY is not configured in .env")
        if not product_external_ref:
            return ProviderResult(
                success=False,
                error="This product has no 'External ID' set (admin panel -> product -> External ID).",
            )

        request_payload = json.dumps({"product_id": product_external_ref, "quantity": 1})
        try:
            resp = await self._post("/v1/buy", {"product_id": product_external_ref, "quantity": 1})
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            # Try to surface the supplier's own error message (e.g. "out of
            # stock" / "insufficient balance") instead of just the status code.
            body_text = exc.response.text[:500] if exc.response is not None else ""
            logger.error("reseller_api HTTP error for order=%s: %s | body=%s", order_uuid, exc, body_text)
            return ProviderResult(
                success=False, raw_request=request_payload, raw_response=body_text, error=str(exc)
            )
        except httpx.HTTPError as exc:
            logger.error("reseller_api HTTP error for order=%s: %s", order_uuid, exc)
            return ProviderResult(success=False, raw_request=request_payload, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - provider must never raise
            logger.exception("reseller_api unexpected error for order=%s", order_uuid)
            return ProviderResult(success=False, raw_request=request_payload, error=str(exc))

        raw_response = json.dumps(data)
        if data.get("status") != "success":
            error = data.get("message") or data.get("error") or "unknown_error"
            logger.error("reseller_api buy failed for order=%s: %s", order_uuid, error)
            return ProviderResult(
                success=False, raw_request=request_payload, raw_response=raw_response, error=str(error)
            )

        links = data.get("links") or []
        if not links:
            logger.error("reseller_api buy: no links in response for order=%s: %s", order_uuid, raw_response)
            return ProviderResult(
                success=False,
                raw_request=request_payload,
                raw_response=raw_response,
                error="Delivered, but no code/link was found in the response (raw response was logged).",
            )

        payload = "\n".join(links) if len(links) > 1 else links[0]
        logger.info(
            "reseller_api issued %s link(s) for order=%s product=%s", len(links), order_uuid, product_external_ref
        )
        return ProviderResult(success=True, payload=payload, raw_request=request_payload, raw_response=raw_response)
