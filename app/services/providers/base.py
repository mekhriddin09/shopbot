"""Base contract every external supplier provider must implement.

Adding a new supplier means: subclass BaseProvider, implement `fetch()`,
register it in `registry.py`. Nothing else in the codebase needs to change
(handlers/services only ever talk to `BaseProvider`).
"""
from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(slots=True)
class ProviderResult:
    success: bool
    payload: str | None = None          # what gets sent to the customer
    raw_request: str | None = None       # for provider_logs
    raw_response: str | None = None      # for provider_logs
    error: str | None = None


class BaseProvider(abc.ABC):
    #: unique key stored on Product.provider_key
    key: str = "base"

    @abc.abstractmethod
    async def fetch(self, *, product_external_ref: str | None, order_uuid: str) -> ProviderResult:
        """Request one unit of digital goods from the supplier.

        Implementations should apply their own timeout/retry (see
        `mock_provider.py` for the recommended `httpx` + `tenacity` pattern)
        and must never raise — always return a `ProviderResult`, converting
        exceptions into `ProviderResult(success=False, error=...)`.
        """
        raise NotImplementedError

    async def get_stock_count(self, product_external_ref: str) -> int | None:
        """Optional: live remaining-stock count from the supplier, used to
        show real numbers on the product card and to block purchases the
        supplier can't actually fulfil (mirrors the check already done for
        INVENTORY-mode products). Default: unsupported — the caller treats
        `None` the same as before this existed (shown as "unlimited",
        no pre-purchase stock check). Override in providers whose API
        actually exposes this (see `ResellerApiProvider`). Must never
        raise — return `None` on any error."""
        return None
