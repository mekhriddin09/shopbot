"""Central registry mapping `Product.provider_key` -> provider instance.

To add a new supplier:
  1. Create `services/providers/my_supplier.py` with a `BaseProvider` subclass.
  2. Import it below and add it to `_PROVIDERS`.
  3. Set that product's `provider_key` to the new provider's `.key` from the
     admin panel. No other code changes needed.
"""
from __future__ import annotations

from app.services.providers.base import BaseProvider
from app.services.providers.fragment import FragmentProvider
from app.services.providers.mock_provider import MockProvider
from app.services.providers.reseller_api import ResellerApiProvider
from app.services.providers.shamekh_api import ShamekhApiProvider

_PROVIDERS: dict[str, BaseProvider] = {
    MockProvider.key: MockProvider(),
    ResellerApiProvider.key: ResellerApiProvider(),
    ShamekhApiProvider.key: ShamekhApiProvider(),
    FragmentProvider.key: FragmentProvider(),
}


def get_provider(key: str | None) -> BaseProvider | None:
    if not key:
        return None
    return _PROVIDERS.get(key)


def list_provider_keys() -> list[str]:
    return list(_PROVIDERS.keys())
