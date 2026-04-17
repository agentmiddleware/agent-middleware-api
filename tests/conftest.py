"""
Shared test configuration.
Sets up pytest-asyncio, database, and common fixtures.
"""

import os
import asyncio
import pytest
import pytest_asyncio
from sqlalchemy import text

# Set up SQLite for testing before any imports
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
# Configure auth so tests don't hit the fail-safe 503 in verify_api_key.
# Tests authenticate with X-API-Key: test-key (see RateLimitMiddleware, which
# also special-cases this value to bypass rate limiting).
os.environ.setdefault("VALID_API_KEYS", "test-key")


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    """Set up database tables before any tests run."""
    from app.db.database import init_db, close_db, get_engine

    # Close any existing connection
    await close_db()

    # Start from a clean SQLite file so stale rows from prior runs
    # (e.g., unique constraints on seeded session IDs) don't leak
    # into the next run.
    if os.path.exists("test.db"):
        os.remove("test.db")

    # Initialize tables
    await init_db()

    yield

    # Cleanup
    await close_db()


@pytest_asyncio.fixture(scope="function")
async def clean_database():
    """Clean database tables between tests."""
    from app.db.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        # Clean up tables
        await session.execute(text("DELETE FROM ledger_entries"))
        await session.execute(text("DELETE FROM billing_alerts"))
        await session.execute(text("DELETE FROM wallets"))
        await session.execute(text("DELETE FROM daily_balance_snapshots"))
        await session.execute(text("DELETE FROM kyc_verifications"))
        await session.execute(text("DELETE FROM api_keys"))
        await session.execute(text("DELETE FROM key_rotation_logs"))
        await session.execute(text("DELETE FROM service_registry"))
        await session.commit()

    yield
