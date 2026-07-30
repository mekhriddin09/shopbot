"""CryptoBot (@CryptoBot / @CryptoTestnetBot) — Crypto Pay API integration.

Docs: https://help.send.tg/en/articles/10279948-crypto-pay-api

Get your API token: open @CryptoBot -> Crypto Pay -> Create App -> API Token,
then put it in .env as CRYPTOBOT_API_TOKEN.

We create invoices priced in USD (currency_type=fiat, fiat=USD) so the
customer can pay with whichever crypto CryptoBot supports (USDT, TON, BTC,
etc.) — CryptoBot handles the conversion. Payment status is checked via
`getInvoices` (polling); no webhook server is required.
"""
from __future__ import annotations

import json
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config.settings import settings
from app.services.crypto.base import CryptoInvoice, CryptoInvoiceStatus, CryptoProvider

logger = logging.getLogger("providers")

_MAINNET_BASE = "https://pay.crypt.bot/api/"
_TESTNET_BASE = "https://testnet-pay.crypt.bot/api/"


class CryptoBotProvider(CryptoProvider):
    key = "cryptobot"

    def __init__(self, token: str | None = None, testnet: bool = False, timeout: float = 15.0) -> None:
        self.token = token or settings.CRYPTOBOT_API_TOKEN
        self.base_url = _TESTNET_BASE if testnet else _MAINNET_BASE
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Crypto-Pay-API-Token": self.token}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4), reraise=True)
    async def _call(self, method: str, params: dict) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}{method}", data=params, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def create_invoice(
        self, *, amount_usd: float, description: str, payload: str
    ) -> CryptoInvoice:
        if not self.token:
            return CryptoInvoice(success=False, error="CRYPTOBOT_API_TOKEN is not configured in .env")
        params = {
            "currency_type": "fiat",
            "fiat": "USD",
            "amount": f"{amount_usd:.2f}",
            "description": description[:1024],
            "payload": payload[:4000],
            "allow_comments": "false",
            "allow_anonymous": "true",
        }
        try:
            data = await self._call("createInvoice", params)
        except httpx.HTTPError as exc:
            logger.error("cryptobot create_invoice HTTP error: %s", exc)
            return CryptoInvoice(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("cryptobot create_invoice unexpected error")
            return CryptoInvoice(success=False, error=str(exc))

        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            logger.error("cryptobot create_invoice failed: %s", error)
            return CryptoInvoice(success=False, error=str(error), raw=json.dumps(data))

        invoice = data["result"]
        pay_url = invoice.get("bot_invoice_url") or invoice.get("pay_url")
        return CryptoInvoice(
            success=True,
            invoice_id=str(invoice["invoice_id"]),
            pay_url=pay_url,
            raw=json.dumps(invoice),
        )

    async def check_invoice(self, invoice_id: str) -> CryptoInvoiceStatus:
        if not self.token:
            return CryptoInvoiceStatus(success=False, error="CRYPTOBOT_API_TOKEN is not configured in .env")
        try:
            data = await self._call("getInvoices", {"invoice_ids": invoice_id})
        except httpx.HTTPError as exc:
            logger.error("cryptobot check_invoice HTTP error: %s", exc)
            return CryptoInvoiceStatus(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("cryptobot check_invoice unexpected error")
            return CryptoInvoiceStatus(success=False, error=str(exc))

        if not data.get("ok"):
            return CryptoInvoiceStatus(success=False, error=str(data.get("error", "unknown_error")))

        items = data["result"].get("items", [])
        if not items:
            return CryptoInvoiceStatus(success=False, error="invoice_not_found")

        invoice = items[0]
        paid = invoice.get("status") == "paid"
        return CryptoInvoiceStatus(success=True, paid=paid, raw=json.dumps(invoice))
