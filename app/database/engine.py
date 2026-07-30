"""Async SQLAlchemy engine & session factory."""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config.settings import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
)


if _is_sqlite:
    # SQLite has no real row-level locking. Set a busy_timeout so concurrent
    # writers (e.g. two order approvals at once) retry instead of
    # immediately raising "database is locked", and enforce foreign keys
    # (SQLite disables them by default). WAL mode is attempted opportunistically
    # for better read/write concurrency, but some filesystems (network drives,
    # certain container overlays) don't support the shared-memory file it
    # needs, so we fall back silently to the default journal mode there.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except Exception:  # noqa: BLE001 - WAL unsupported on this filesystem
            pass
        cursor.close()


async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)
