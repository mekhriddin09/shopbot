"""xRocket — Pay API integration.

Base URL, auth header and endpoint paths below are taken from xRocket's own
OFFICIAL TypeScript SDK (`xrocket-pay-api-sdk` on npm, source at
github.com/xrocket-tg/xrocket-pay-ts-sdk — published and maintained by the
xRocket team itself, not a community guess). Read directly from its compiled
`dist/client.js` on 2026-07-30:

- Base URL: https://pay.xrocket.tg/
- Auth header: Rocket-Pay-Key: <token>
- Create invoice: POST /tg-invoices
- Get invoice info: GET /tg-invoices/{id}
- Healthcheck (no auth): GET /version
- Available currencies (no auth): GET /currencies/available

Two earlier guesses both turned out wrong and failed with a hard DNS error
on the user's machine: `pay.ton-rocket.com` (dead legacy domain from a 2023
Python SDK) and `pay.api.xrocket.exchange` (from the docs.xrocket.exchange
text, which doesn't seem to actually resolve either). `pay.xrocket.tg` is
confirmed by the vendor's own current SDK, so this should be the real one.

Get your token: open @xRocket -> Settings -> Exchange settings -> API token,
then put it in .env as XROCKET_API_TOKEN.

Remaining uncertainty: the SDK's TypeScript type declarations (exact
request/response field names) weren't fetchable from here, so `amount`/
`currency`/`link`/`status` below are still best-effort, same as before. If
invoice creation succeeds but parsing fails, `raw` is logged on every call
to logs/providers.log — check it and adjust the two or three `.get(...)`
lookups below to match the real field names.
"""
from __future__ import annotations

import json
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config.settings import settings
from app.services.crypto.base import CryptoInvoice, CryptoInvoiceStatus, CryptoProvider

logger = logging.getLogger("providers")

_BASE_URL = "https://pay.xrocket.tg/"


class XRocketProvider(CryptoProvider):
    key = "xrocket"

    def __init__(self, token: str | None = None, timeout: float = 15.0) -> None:
        self.token = token or settings.XROCKET_API_TOKEN
        self.currency = settings.XROCKET_CURRENCY or "USDT"
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Rocket-Pay-Key": self.token, "Accept": "application/json"}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4), reraise=True)
    async def _post(self, path: str, json_body: dict) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{_BASE_URL}{path}", json=json_body, headers=self._headers())
            resp.raise_for_status()
            return resp

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4), reraise=True)
    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{_BASE_URL}{path}", params=params, headers=self._headers())
            resp.raise_for_status()
            return resp

    async def create_invoice(
        self, *, amount_usd: float, description: str, payload: str
    ) -> CryptoInvoice:
        if not self.token:
            return CryptoInvoice(success=False, error="XROCKET_API_TOKEN is not configured in .env")
        body = {
            "amount": round(amount_usd, 2),
            "currency": self.currency,
            "description": description[:1024],
            "numPayments": 1,
            "payload": payload[:4000],
        }
        try:
            resp = await self._post("tg-invoices", body)
            data = resp.json()
        except httpx.HTTPError as exc:
            logger.error("xrocket create_invoice HTTP error: %s", exc)
            return CryptoInvoice(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("xrocket create_invoice unexpected error")
            return CryptoInvoice(success=False, error=str(exc))

        if isinstance(data, dict) and (data.get("errors") or data.get("success") is False):
            error = (
                data["errors"][0].get("error")
                if data.get("errors")
                else data.get("message", "unknown_error")
            )
            logger.error("xrocket create_invoice failed: %s | raw=%s", error, json.dumps(data))
            return CryptoInvoice(success=False, error=str(error), raw=json.dumps(data))

        invoice = data.get("data", data) if isinstance(data, dict) else {}
        invoice_id = invoice.get("id") or invoice.get("invoiceId")
        pay_url = invoice.get("link") or invoice.get("payUrl") or invoice.get("url")
        if not invoice_id or not pay_url:
            logger.error("xrocket create_invoice: unexpected response shape: %s", data)
            return CryptoInvoice(
                success=False,
                error="Unexpected response format (raw response logged to logs/providers.log)",
                raw=json.dumps(data),
            )
        return CryptoInvoice(success=True, invoice_id=str(invoice_id), pay_url=pay_url, raw=json.dumps(data))

    async def check_invoice(self, invoice_id: str) -> CryptoInvoiceStatus:
        if not self.token:
            return CryptoInvoiceStatus(success=False, error="XROCKET_API_TOKEN is not configured in .env")
        try:
            resp = await self._get(f"tg-invoices/{invoice_id}")
            data = resp.json()
        except httpx.HTTPError as exc:
            logger.error("xrocket check_invoice HTTP error: %s", exc)
            return CryptoInvoiceStatus(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("xrocket check_invoice unexpected error")
            return CryptoInvoiceStatus(success=False, error=str(exc))

        if isinstance(data, dict) and (data.get("errors") or data.get("success") is False):
            error = (
                data["errors"][0].get("error")
                if data.get("errors")
                else data.get("message", "unknown_error")
            )
            return CryptoInvoiceStatus(success=False, error=str(error))

        invoice = data.get("data", data) if isinstance(data, dict) else {}
        status = str(invoice.get("status", "")).lower()
        payments = invoice.get("payments") or []
        paid = status in {"paid", "completed", "success"} or bool(payments) or bool(invoice.get("paid"))
        return CryptoInvoiceStatus(success=True, paid=paid, raw=json.dumps(data))
