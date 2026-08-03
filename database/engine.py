"""
SQLAlchemy engine and session management.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.engine import make_url
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


def _safe_database_url(database_url: str) -> str:
    """Render a database URL for logs without exposing its password."""
    return make_url(database_url).render_as_string(hide_password=True)


# Import all models to register them with Base.metadata
import database.models  # noqa: E402, F401


def get_engine():
    global _engine
    if _engine is None:
        database_url = config.database.url
        # Resolve relative paths for SQLite
        if database_url.startswith("sqlite+aiosqlite:///"):
            rel_part = database_url[len("sqlite+aiosqlite:///") :]
            # Only prepend data_dir if the path is truly relative (not absolute)
            if not rel_part.startswith("/"):
                database_url = f"sqlite+aiosqlite:///{config.data_dir / rel_part}"

        logger.info("Database: %s", _safe_database_url(database_url))
        _engine = create_async_engine(
            database_url,
            echo=config.database.echo,
            pool_size=config.database.pool_size,
            max_overflow=config.database.max_overflow,
        )
        if database_url.startswith("sqlite+aiosqlite:///"):

            @event.listens_for(_engine.sync_engine, "connect")
            def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
                del connection_record
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

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
    """Create current tables and record/apply ordered deployment migrations."""
    from database.migrations import apply_migrations

    engine = get_engine()
    async with engine.connect() as conn:
        if engine.url.get_backend_name() == "sqlite":
            await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            await conn.commit()
        async with conn.begin():
            await conn.run_sync(Base.metadata.create_all)
            await apply_migrations(conn)
        if engine.url.get_backend_name() == "sqlite":
            await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            enabled = (await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar_one()
            if enabled != 1:
                raise RuntimeError("SQLite foreign-key enforcement could not be enabled")
    logger.info("All tables created/verified")


async def close_db() -> None:
    """Dispose of the engine and close all connections."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _session_factory = None
    logger.info("Database connections closed")
