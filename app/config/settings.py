"""
Application configuration.

Loads all runtime configuration from environment variables (.env).
Never hardcode secrets — everything sensitive lives in .env only.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram ---
    BOT_TOKEN: str
    ADMIN_IDS: str = ""

    # --- Database ---
    DATABASE_URL: str = "sqlite+aiosqlite:///./shopbot.db"

    # --- Behaviour ---
    DEFAULT_LANGUAGE: str = "uz"
    SUPPORTED_LANGUAGES: tuple[str, ...] = ("uz", "ru", "en")
    LOG_LEVEL: str = "INFO"
    THROTTLE_RATE_SECONDS: float = 0.7

    # --- Crypto payments ---
    CRYPTOBOT_API_TOKEN: str = ""
    XROCKET_API_TOKEN: str = ""
    # xRocket invoices are priced in a crypto/token symbol, not fiat — USDT is
    # the closest 1:1 stand-in for our USD product prices. Override in .env
    # (e.g. XROCKET_CURRENCY=TONCOIN) if you'd rather charge in a different
    # token xRocket supports.
    XROCKET_CURRENCY: str = "USDT"
    CRYPTO_POLL_INTERVAL_SECONDS: float = 20.0
    # If a crypto invoice isn't paid within this many minutes, the order is
    # auto-cancelled and any reserved inventory code is released back to
    # stock — otherwise an abandoned invoice would hold a code hostage
    # forever (see crypto_poller.py).
    CRYPTO_PAYMENT_TIMEOUT_MINUTES: float = 10.0
    # Telegram Stars invoices get their own, longer timeout: unlike a crypto
    # invoice (which shows the customer a countdown/expiry), a Stars invoice
    # message never indicates it will expire, so a customer who takes their
    # time deciding can easily exceed a short window and then still tap
    # "Pay" -- if our side has already cancelled the order and released its
    # reserved stock by then, Telegram's pre-checkout step correctly
    # declines the charge, but it looks to the customer like "I paid and
    # got nothing" even though they were, in that case, not actually
    # charged. A longer window makes this far less likely to be hit in
    # normal use.
    STARS_PAYMENT_TIMEOUT_MINUTES: float = 30.0

    # --- External reseller API (Mode 3 delivery) ---
    RESELLER_API_BASE_URL: str = "http://2.26.230.116:8080"
    RESELLER_API_KEY: str = ""

    # --- Second external reseller: "Shamekh" API (Mode 3 delivery) ---
    SHAMEKH_API_BASE_URL: str = "https://worker-production-53ca.up.railway.app"
    SHAMEKH_API_KEY: str = "sb_95b764957ef1d30db00316a13798a30af5fab4c0a4d59359"

    @property
    def admin_ids(self) -> set[int]:
        ids: set[int] = set()
        for raw in self.ADMIN_IDS.split(","):
            raw = raw.strip()
            if raw.isdigit():
                ids.add(int(raw))
        return ids


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
