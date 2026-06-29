"""
SQLAlchemy engine and session management.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import config

logger = logging.getLogger("bark.database")

_engine = None
_session_factory = None


class Base(DeclarativeBase):
    pass


# Import all models to register them with Base.metadata
import database.models  # noqa: F401


def get_engine():
    global _engine
    if _engine is None:
        database_url = config.database.url
        # Resolve relative paths for SQLite
        if database_url.startswith("sqlite+aiosqlite:///"):
            rel_part = database_url[len("sqlite+aiosqlite:///"):]
            # Only prepend data_dir if the path is truly relative (not absolute)
            if not rel_part.startswith("/"):
                database_url = f"sqlite+aiosqlite:///{config.data_dir / rel_part}"

        logger.info("Database: %s", database_url)
        _engine = create_async_engine(
            database_url,
            echo=config.database.echo,
            pool_size=config.database.pool_size,
            max_overflow=config.database.max_overflow,
        )
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields an async DB session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Context manager for manual DB sessions outside FastAPI."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables if they don't exist."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("All tables created/verified")


async def close_db() -> None:
    """Dispose of the engine."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("Database engine disposed")
