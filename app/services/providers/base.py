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


@dataclass(slots=True)
class SupplierProduct:
    """One entry from a supplier's own catalog — used to let the admin
    *pick* a product's `external_product_id` from a live list instead of
    typing it from memory (see `admin -> product -> Tashqi ID -> Ta'minotchi
    mahsulotlarini ko'rish`). `name` and `stock` are best-effort: a supplier
    whose API doesn't expose them (see ResellerApiProvider) just leaves them
    None, and the admin panel shows the id alone in that case."""

    id: str
    name: str | None = None
    stock: int | None = None


class BaseProvider(abc.ABC):
    #: unique key stored on Product.provider_key
    key: str = "base"

    #: True when the supplier delivers straight to a Telegram @username
    #: rather than returning a code, so the bot must collect (and verify)
    #: that username *before* taking payment. Callers check this flag
    #: instead of hardcoding provider names.
    requires_recipient: bool = False

    @abc.abstractmethod
    async def fetch(
        self,
        *,
        product_external_ref: str | None,
        order_uuid: str,
        recipient: str | None = None,
    ) -> ProviderResult:
        """Request one unit of digital goods from the supplier.

        `recipient` is the Telegram @username the goods must be delivered
        to, for suppliers that send straight to a third party rather than
        returning a code (Telegram Stars / Premium — see
        `FragmentProvider`). Optional and ignored by suppliers that hand
        back a code for the bot to forward, so existing providers need no
        changes.

        Implementations should apply their own timeout/retry (see
        `mock_provider.py` for the recommended `httpx` + `tenacity` pattern)
        and must never raise — always return a `ProviderResult`, converting
        exceptions into `ProviderResult(success=False, error=...)`.
        """
        raise NotImplementedError

    async def search_recipient(self, username: str) -> tuple[bool, str | None]:
        """Optional: check the supplier can actually deliver to this
        username *before* the customer pays. Returns (ok, display_name or
        error message). Default: unsupported, treated as "can't tell, let
        it through" by callers. Must never raise."""
        return True, None

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

    async def list_products(self) -> list[SupplierProduct] | None:
        """Optional: the supplier's full catalog, so the admin panel can
        offer "pick from a list" instead of "type the id from memory" when
        setting a product's Tashqi ID. Default: unsupported (`None`) —
        the admin panel falls back to manual text entry in that case, same
        as before this existed. Override in providers whose API exposes a
        product list (see `ResellerApiProvider`, `ShamekhApiProvider`).
        Must never raise — return `None` on any error, including a missing
        API key."""
        return None
