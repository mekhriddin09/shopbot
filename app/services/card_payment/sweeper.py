"""Background task that expires unpaid automatic-card orders.

Runs alongside the bot's polling loop (see main.py), mirroring the crypto
poller's shape: its own short-lived DB session per tick, and a try/except
wide enough that one bad tick can never kill the loop — a stalled sweeper
would leave amounts reserved forever and eventually exhaust the band.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from app.database.engine import async_session_maker

logger = logging.getLogger("card_payment")

# Checked every 30s: the payment window is minutes long, so this bounds
# how late an expiry notice can be without adding meaningful load.
_INTERVAL_SECONDS = 30


async def card_expiry_loop(bot: Bot) -> None:
    from app.services.card_payment.flow import sweep_expired_card_orders

    logger.info("card expiry sweeper started")
    while True:
        try:
            async with async_session_maker() as session:
                await sweep_expired_card_orders(bot, session)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never let one bad tick kill the loop
            logger.exception("card expiry sweep failed")
        await asyncio.sleep(_INTERVAL_SECONDS)


__all__ = ["card_expiry_loop"]
