"""External reseller API — real Mode 3 (external supplier) provider.

Matches the "SHOP - RESELLER API" documentation the admin supplied:

- Base URL: settings.RESELLER_API_BASE_URL (default http://2.26.230.116:8080)
- Auth: header "Authorization: <api_key>" (raw key, no "Bearer " prefix)
- GET  /v1/balance             -> {"status": "success", "balance": 150.0}
- GET  /v1/products            -> {"status": "success", "products": [...]}
                                   each product has an "id" (string, e.g.
                                   "gemini") and a "stock_count" (live
                                   remaining quantity — confirmed safe to
                                   show directly to customers).
- POST /v1/buy {"product_id", "quantity"}
        -> {"status": "success", "product_id", "quantity", "total_price",
            "new_balance", "links": ["https://..."]}
        -> on out-of-stock: HTTP 409 with body
           {"error": "Out of stock", "available": 0} (no "status" key on
           this error shape — confirmed by the supplier).

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
        # These are the .env-sourced *fallback* values only — see
        # `_resolve_api_key`/`_resolve_base_url` below. The admin can
        # override either one from inside the bot itself (Admin panel ->
        # Sozlamalar -> Reseller API), stored as a DB Setting, which takes
        # priority and takes effect on the very next call — no .env edit or
        # redeploy needed. This single instance is created once at import
        # time (see registry.py), so baking the key in here permanently
        # would make bot-side key rotation impossible.
        self.base_url = (base_url or settings.RESELLER_API_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.RESELLER_API_KEY
        self.timeout = timeout

    async def _resolve_api_key(self) -> str:
        try:
            from app.database.engine import async_session_maker
            from app.repositories.setting_repo import SettingRepository

            async with async_session_maker() as session:
                db_value = await SettingRepository(session).get("reseller_api_key", "")
        except Exception:  # noqa: BLE001 - a DB hiccup must never break provider calls
            db_value = ""
        return db_value.strip() or self.api_key

    async def _resolve_base_url(self) -> str:
        try:
            from app.database.engine import async_session_maker
            from app.repositories.setting_repo import SettingRepository

            async with async_session_maker() as session:
                db_value = await SettingRepository(session).get("reseller_api_base_url", "")
        except Exception:  # noqa: BLE001
            db_value = ""
        return (db_value.strip() or self.base_url).rstrip("/")

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": await self._resolve_api_key(), "Content-Type": "application/json"}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4), reraise=True)
    async def _post(self, path: str, json_body: dict) -> httpx.Response:
        base_url = await self._resolve_base_url()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{base_url}{path}", json=json_body, headers=await self._headers())
            resp.raise_for_status()
            return resp

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4), reraise=True)
    async def _get(self, path: str) -> httpx.Response:
        base_url = await self._resolve_base_url()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{base_url}{path}", headers=await self._headers())
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

    async def get_stock_count(self, product_external_ref: str) -> int | None:
        """Live remaining quantity for one product, read from the "id" /
        "stock_count" fields of GET /v1/products. Returns None (treated by
        callers as "unknown/unlimited") on any error, missing API key, or
        if this specific product id isn't found in the supplier's list —
        never raises."""
        if not product_external_ref or not await self._resolve_api_key():
            return None
        try:
            resp = await self._get("/v1/products")
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - stock display must never break the shop
            logger.warning("reseller_api get_stock_count error for %s: %s", product_external_ref, exc)
            return None
        if data.get("status") != "success":
            return None
        for item in data.get("products") or []:
            if str(item.get("id")) == str(product_external_ref):
                try:
                    return int(item.get("stock_count"))
                except (TypeError, ValueError):
                    return None
        return None

    async def fetch(self, *, product_external_ref: str | None, order_uuid: str) -> ProviderResult:
        if not await self._resolve_api_key():
            return ProviderResult(
                success=False,
                error="Reseller API key is not configured (Admin panel -> Sozlamalar -> Reseller API, or .env RESELLER_API_KEY).",
            )
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
            # Try to surface the supplier's own error message instead of
            # just the status code. Confirmed shapes: out-of-stock is a 409
            # with {"error": "Out of stock", "available": N} (no "status"
            # key on this one) — build a clean "Out of stock (available: N)"
            # message when that shape is recognized, otherwise fall back to
            # whatever "error"/"message" field is present, then the raw body.
            body_text = exc.response.text[:500] if exc.response is not None else ""
            friendly_error = str(exc)
            try:
                body_json = exc.response.json() if exc.response is not None else {}
            except Exception:  # noqa: BLE001 - body wasn't valid JSON
                body_json = {}
            if isinstance(body_json, dict) and body_json.get("error"):
                friendly_error = str(body_json["error"])
                if "available" in body_json:
                    friendly_error += f" (available: {body_json['available']})"
            elif isinstance(body_json, dict) and body_json.get("message"):
                friendly_error = str(body_json["message"])
            logger.error("reseller_api HTTP error for order=%s: %s | body=%s", order_uuid, exc, body_text)
            return ProviderResult(
                success=False, raw_request=request_payload, raw_response=body_text, error=friendly_error
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
