"""Second external reseller — "Shamekh" API. A different supplier from
`reseller_api.py`, with its own base URL, auth scheme and response shapes,
so it lives as its own provider rather than being squeezed into the other
one. Both run side by side: each Product's `provider_key` picks which
supplier fulfils it.

Matches the "SHOP - RESELLER API DOCUMENTATION" the admin supplied:

- Base URL: settings.SHAMEKH_API_BASE_URL (default
  https://worker-production-53ca.up.railway.app)
- Auth: header "X-API-Key: <key>" (note: different header name from
  reseller_api.py, which uses a bare "Authorization" header)
- GET  /api/health              -> {"ok": true, "status": "healthy"}
- GET  /api/me                  -> {"ok": true, "user": {"user_id",
                                    "username", "first_name", "balance",
                                    "language"}}
- GET  /api/products             -> {"ok": true, "products": [{"id" (int,
                                    e.g. 1), "name_en", "price",
                                    "stock_count"}]}
- POST /api/buy {"product_id", "quantity"}
        -> {"ok": true, "transaction_id", "product_id", "quantity",
            "total_price", "new_balance", "items": ["item_content", ...]}
        -> error shape not documented explicitly; treated generically as
           any response with "ok": false (or a non-2xx status), reading
           whatever "error"/"message" field is present.

Each local Product using this provider needs `external_product_id` set to
the matching numeric `id` from GET /api/products (e.g. "1") — edit it from
Admin panel -> product -> "Tashqi ID". `provider_key` itself just needs to
be set to this provider's key, "shamekh_api".
"""
from __future__ import annotations

import json
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config.settings import settings
from app.services.providers.base import BaseProvider, ProviderResult, SupplierProduct

logger = logging.getLogger("providers")


class ShamekhApiProvider(BaseProvider):
    key = "shamekh_api"

    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 15.0) -> None:
        # .env-sourced fallback values only — see `_resolve_api_key`/
        # `_resolve_base_url`. The admin can override either from Admin
        # panel -> Sozlamalar -> Shamekh API, stored as a DB Setting, which
        # takes priority and applies on the very next call.
        self.base_url = (base_url or settings.SHAMEKH_API_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.SHAMEKH_API_KEY
        self.timeout = timeout

    async def _resolve_api_key(self) -> str:
        try:
            from app.database.engine import async_session_maker
            from app.repositories.setting_repo import SettingRepository

            async with async_session_maker() as session:
                db_value = await SettingRepository(session).get("shamekh_api_key", "")
        except Exception:  # noqa: BLE001 - a DB hiccup must never break provider calls
            db_value = ""
        return db_value.strip() or self.api_key

    async def _resolve_base_url(self) -> str:
        try:
            from app.database.engine import async_session_maker
            from app.repositories.setting_repo import SettingRepository

            async with async_session_maker() as session:
                db_value = await SettingRepository(session).get("shamekh_api_base_url", "")
        except Exception:  # noqa: BLE001
            db_value = ""
        return (db_value.strip() or self.base_url).rstrip("/")

    async def _headers(self) -> dict[str, str]:
        return {"X-API-Key": await self._resolve_api_key(), "Content-Type": "application/json"}

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
        admin/stats side can call to show remaining reseller balance.
        Reads it off GET /api/me (this supplier has no separate /balance
        endpoint)."""
        try:
            resp = await self._get("/api/me")
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.error("shamekh_api get_balance error: %s", exc)
            return False, None, str(exc)
        if not data.get("ok"):
            return False, None, data.get("error") or data.get("message", "unknown_error")
        user = data.get("user") or {}
        return True, user.get("balance"), None

    async def get_stock_count(self, product_external_ref: str) -> int | None:
        """Live remaining quantity for one product, read from GET
        /api/products. Returns None (treated by callers as "unknown/
        unlimited") on any error, missing API key, or if this specific
        product id isn't found — never raises."""
        if not product_external_ref or not await self._resolve_api_key():
            return None
        try:
            resp = await self._get("/api/products")
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - stock display must never break the shop
            logger.warning("shamekh_api get_stock_count error for %s: %s", product_external_ref, exc)
            return None
        if not data.get("ok"):
            return None
        for item in data.get("products") or []:
            if str(item.get("id")) == str(product_external_ref):
                try:
                    return int(item.get("stock_count"))
                except (TypeError, ValueError):
                    return None
        return None

    async def list_products(self) -> list[SupplierProduct] | None:
        """Lets the admin panel offer a pick-from-list instead of typing the
        id from memory. This supplier's /api/products exposes a proper
        name ("name_en") and price alongside stock_count."""
        if not await self._resolve_api_key():
            return None
        try:
            resp = await self._get("/api/products")
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - listing must never break the admin panel
            logger.warning("shamekh_api list_products error: %s", exc)
            return None
        if not data.get("ok"):
            return None
        out: list[SupplierProduct] = []
        for item in data.get("products") or []:
            raw_id = item.get("id")
            if raw_id is None:
                continue
            try:
                stock = int(item.get("stock_count"))
            except (TypeError, ValueError):
                stock = None
            name = item.get("name_en") or item.get("name") or None
            out.append(SupplierProduct(id=str(raw_id), name=name, stock=stock))
        return out

    async def fetch(self, *, product_external_ref: str | None, order_uuid: str, recipient: str | None = None) -> ProviderResult:
        if not await self._resolve_api_key():
            return ProviderResult(
                success=False,
                error="Shamekh API key is not configured (Admin panel -> Sozlamalar -> Shamekh API, or .env SHAMEKH_API_KEY).",
            )
        if not product_external_ref:
            return ProviderResult(
                success=False,
                error="This product has no 'External ID' set (admin panel -> product -> External ID).",
            )

        request_payload = json.dumps({"product_id": product_external_ref, "quantity": 1})
        try:
            resp = await self._post("/api/buy", {"product_id": product_external_ref, "quantity": 1})
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            # Error shape isn't documented — surface whatever "error"/
            # "message" field is present, falling back to the raw body.
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
            logger.error("shamekh_api HTTP error for order=%s: %s | body=%s", order_uuid, exc, body_text)
            return ProviderResult(
                success=False, raw_request=request_payload, raw_response=body_text, error=friendly_error
            )
        except httpx.HTTPError as exc:
            logger.error("shamekh_api HTTP error for order=%s: %s", order_uuid, exc)
            return ProviderResult(success=False, raw_request=request_payload, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - provider must never raise
            logger.exception("shamekh_api unexpected error for order=%s", order_uuid)
            return ProviderResult(success=False, raw_request=request_payload, error=str(exc))

        raw_response = json.dumps(data)
        if not data.get("ok"):
            error = data.get("error") or data.get("message") or "unknown_error"
            logger.error("shamekh_api buy failed for order=%s: %s", order_uuid, error)
            return ProviderResult(
                success=False, raw_request=request_payload, raw_response=raw_response, error=str(error)
            )

        items = data.get("items") or []
        if not items:
            logger.error("shamekh_api buy: no items in response for order=%s: %s", order_uuid, raw_response)
            return ProviderResult(
                success=False,
                raw_request=request_payload,
                raw_response=raw_response,
                error="Delivered, but no code/item was found in the response (raw response was logged).",
            )

        payload = "\n".join(str(i) for i in items) if len(items) > 1 else str(items[0])
        logger.info(
            "shamekh_api issued %s item(s) for order=%s product=%s", len(items), order_uuid, product_external_ref
        )
        return ProviderResult(success=True, payload=payload, raw_request=request_payload, raw_response=raw_response)
