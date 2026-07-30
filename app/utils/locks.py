"""In-process async lock registry.

SQLite's transaction isolation protects data integrity, but it can still
raise "database is locked" under contention, and callback spam (a user or
admin double-tapping a button) can trigger two handlers for the same
resource before the first one's transaction lands. This registry gives call
sites a cheap per-key `async with` mutex to serialize such racy operations
at the application level, on top of the DB-level guarantees.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict


class _KeyedLockRegistry:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def get(self, key: str) -> asyncio.Lock:
        return self._locks[key]


_registry = _KeyedLockRegistry()


def lock_for(key: str) -> asyncio.Lock:
    """Return a process-wide asyncio.Lock scoped to `key`.

    Usage: `async with lock_for(f"order:{order_id}"): ...`
    """
    return _registry.get(key)
