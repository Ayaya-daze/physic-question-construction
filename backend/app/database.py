"""Database engine, session factory, and initialization utilities."""

import asyncio
from collections.abc import AsyncGenerator

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# ── Engine creation ──────────────────────────────────────────────────
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

# Shared engine kwargs
_engine_kw: dict = {"echo": settings.DEBUG}

# Async engine
if _is_sqlite:
    async_engine = create_async_engine(settings.DATABASE_URL, **_engine_kw)
else:
    async_engine = create_async_engine(settings.DATABASE_URL, pool_size=20, max_overflow=10, **_engine_kw)

# Sync engine (for DDL)
if _is_sqlite:
    sync_engine = create_engine(settings.DATABASE_URL_SYNC, connect_args={"check_same_thread": False}, **_engine_kw)
else:
    sync_engine = create_engine(settings.DATABASE_URL_SYNC, **_engine_kw)

# Enable WAL mode + foreign keys on SQLite (must happen on every connection)
if _is_sqlite:
    @event.listens_for(sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# Async session factory
async_session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables using the sync engine (wrapped in a thread for async safety)."""
    # Import all models so they register on Base.metadata
    import app.models  # noqa: F401

    def _create_tables():
        Base.metadata.create_all(bind=sync_engine)

    await asyncio.to_thread(_create_tables)
