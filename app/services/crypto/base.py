"""Common contract for crypto payment providers (CryptoBot, xRocket, ...).

Adding a new provider: subclass `CryptoProvider`, implement `create_invoice`
and `check_invoice`, register it in `registry.py`. The rest of the bot
(shop handlers, the background poller) only ever talks to this interface.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(slots=True)
class CryptoInvoice:
    success: bool
    invoice_id: str | None = None
    pay_url: str | None = None
    raw: str | None = None
    error: str | None = None


@dataclass(slots=True)
class CryptoInvoiceStatus:
    success: bool
    paid: bool = False
    raw: str | None = None
    error: str | None = None


class CryptoProvider(abc.ABC):
    key: str = "base"

    @abc.abstractmethod
    async def create_invoice(
        self, *, amount_usd: float, description: str, payload: str
    ) -> CryptoInvoice:
        """Create a payable invoice for `amount_usd` USD.

        Must never raise — convert exceptions into
        `CryptoInvoice(success=False, error=...)`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def check_invoice(self, invoice_id: str) -> CryptoInvoiceStatus:
        """Check whether the given invoice has been paid."""
        raise NotImplementedError
