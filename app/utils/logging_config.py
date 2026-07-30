"""Centralized logging configuration.

Separate log files for general activity, orders/payments and errors, so the
admin can audit what happened without grepping one giant file.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.config.settings import LOGS_DIR, settings

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def _file_handler(filename: str, level: int) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        LOGS_DIR / filename, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FORMAT))
    return handler


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(stream)

    root.addHandler(_file_handler("app.log", logging.INFO))
    root.addHandler(_file_handler("errors.log", logging.ERROR))

    # Dedicated loggers used across the app (business audit trail)
    for name, filename in (
        ("orders", "orders.log"),
        ("payments", "payments.log"),
        ("admin_actions", "admin_actions.log"),
        ("providers", "providers.log"),
        ("security", "security.log"),
    ):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.addHandler(_file_handler(filename, logging.INFO))
        logger.propagate = True

    logging.getLogger("aiogram").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
