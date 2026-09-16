"""Crypto provider registry.

Every provider whose API token is configured in .env is offered to the
customer at checkout and *they* pick which one to pay with — there is no
single admin-selected "active provider" (an early design that was replaced;
the leftover `crypto_provider` setting has been removed).
"""
from __future__ import annotations

from app.services.crypto.base import CryptoProvider
from app.services.crypto.cryptobot import CryptoBotProvider
from app.services.crypto.xrocket import XRocketProvider

_PROVIDERS: dict[str, CryptoProvider] = {
    CryptoBotProvider.key: CryptoBotProvider(),
    XRocketProvider.key: XRocketProvider(),
}

_LABELS: dict[str, str] = {
    "cryptobot": "\U0001FA99 CryptoBot (avto)",
    "xrocket": "\U0001FA99 xRocket (avto)",
}


def get_crypto_provider(key: str | None) -> CryptoProvider | None:
    if not key:
        return None
    return _PROVIDERS.get(key)


def list_crypto_provider_keys() -> list[str]:
    return list(_PROVIDERS.keys())


def available_crypto_providers() -> list[tuple[str, str]]:
    """(key, button_label) for every provider that has an API token configured
    in .env. Both CryptoBot and xRocket can be active at the same time — the
    customer picks which one to pay with, instead of the admin having to
    choose a single "active" provider."""
    return [
        (key, _LABELS.get(key, key))
        for key, provider in _PROVIDERS.items()
        if getattr(provider, "token", None)
    ]
