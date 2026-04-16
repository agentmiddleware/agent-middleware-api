"""
Database engine and session management for Agent Middleware API.
Provides async PostgreSQL connection via SQLModel/SQLAlchemy.

Supports SQLite fallback for testing when DATABASE_URL is not configured.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlmodel import SQLModel

from ..core.config import get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_database_url() -> str | None:
    """Get database URL from settings or environment."""
    settings = get_settings()
    if settings.DATABASE_URL:
        return settings.DATABASE_URL

    import os
    return os.environ.get("DATABASE_URL")


def get_engine() -> AsyncEngine | None:
    """Get or create the async database engine.

    Returns None if DATABASE_URL is not configured.
    """
    global _engine

    if _engine is None:
        db_url = _get_database_url()

        if not db_url:
            logger.warning("DATABASE_URL not configured. Database features disabled.")
            return None

        _engine = create_async_engine(
            db_url,
            echo=get_settings().DEBUG,
            pool_size=get_settings().DB_POOL_SIZE,
            max_overflow=get_settings().DB_MAX_OVERFLOW,
            pool_pre_ping=True,
        )

        logger.info(
            f"Database engine created: pool_size={get_settings().DB_POOL_SIZE}, "
            f"max_overflow={get_settings().DB_MAX_OVERFLOW}"
        )

    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory.

    Raises RuntimeError if database is not configured.
    """
    global _session_factory

    if _session_factory is None:
        engine = get_engine()
        if engine is None:
            raise RuntimeError(
                "DATABASE_URL not configured. "
                "Set STATE_BACKEND=postgres and provide DATABASE_URL."
            )

        _session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

    return _session_factory


def is_database_configured() -> bool:
    """Check if database is configured."""
    return get_engine() is not None


async def init_db() -> None:
    """
    Initialize the database.

    Creates all tables defined in SQLModel metadata.
    For production, use Alembic migrations instead.
    """
    engine = get_engine()
    if engine is None:
        logger.warning("Database not configured, skipping initialization")
        return

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    logger.info("Database tables initialized")


async def close_db() -> None:
    """Close the database engine and cleanup connections."""
    global _engine, _session_factory

    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine closed")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions.

    Usage:
        async with get_session() as session:
            result = await session.execute(select(Model))

    Raises RuntimeError if database is not configured.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class DatabaseManager:
    """
    Database manager for dependency injection.

    Usage in FastAPI:
        @app.get("/example")
        async def example(db: DatabaseManager):
            async with db.session() as session:
                ...
    """

    def __init__(self):
        self._factory = get_session_factory()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a new database session."""
        async with self._factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def execute(self, query) -> any:
        """Execute a query and return results."""
        async with self.session() as session:
            result = await session.execute(query)
            return result
