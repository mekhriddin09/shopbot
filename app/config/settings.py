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

    # --- External reseller API (Mode 3 delivery) ---
    RESELLER_API_BASE_URL: str = "http://2.26.230.116:8080"
    RESELLER_API_KEY: str = ""

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
