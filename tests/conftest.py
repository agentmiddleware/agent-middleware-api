"""
Shared test configuration.
Sets up pytest-asyncio, database, and common fixtures.
"""

import os
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

# --- Proof-surface test classification -------------------------------------
# The product is the trust plane (app/trust + the core trust routers). Everything
# else is a "proof surface" — example workloads that exercise the spine but are
# NOT the product (see README "Core platform vs. example workloads"). Tests for
# these are auto-marked `proof` so the inner dev loop can skip them:
#     make test       -> fast, core only  (pytest -m "not proof")
#     make test-all   -> full suite       (what CI runs)
# Conservative by design: when a test's surface is ambiguous, leave it OUT of
# this set so it stays in the fast (core) loop and is never silently skipped.
PROOF_SURFACE_TEST_MODULES = frozenset(
    {
        "test_awi",
        "test_awi_adoption",
        "test_awi_dom_bridge_integration",
        "test_awi_phase9",
        "test_behavioral_sandbox",
        "test_broadcast",
        "test_comms",
        "test_agent_comms_durable",
        "test_content_factory_generation_durable",
        "test_content_store",
        "test_factory",
        "test_iot",
        "test_iot_registry",
        "test_media",
        "test_oracle",
        "test_oracle_durable_crawl",
        "test_oracle_store",
        "test_protocol",
        "test_red_team",
        "test_rtaas",
        "test_sandbox",
        "test_sandbox_integration",
        "test_telemetry",
        "test_telemetry_scope",
        "test_telemetry_store",
    }
)


def pytest_collection_modifyitems(config, items):
    """Auto-apply the `proof` marker to proof-surface test modules."""
    proof = pytest.mark.proof
    for item in items:
        stem = Path(item.nodeid.split("::", 1)[0]).stem
        if stem in PROOF_SURFACE_TEST_MODULES:
            item.add_marker(proof)


def iter_routes(routes):
    """Yield every leaf route from an app/router route list.

    Newer FastAPI versions wrap `app.include_router()` results in an
    `_IncludedRouter` that has no `.path` of its own. Walk into its
    `original_router.routes` so callers see the real `APIRoute` instances.
    """
    for route in routes:
        if hasattr(route, "path"):
            yield route
            continue
        original = getattr(route, "original_router", None)
        if original is not None and hasattr(original, "routes"):
            yield from iter_routes(original.routes)


# Set up SQLite for testing before any imports
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
# Configure auth so tests don't hit the fail-safe 503 in verify_api_key.
# Tests authenticate with X-API-Key: test-key (see RateLimitMiddleware, which
# also special-cases this value to bypass rate limiting).
os.environ.setdefault("VALID_API_KEYS", "test-key")
# Production now defaults to strict trust mode (TRUST_MODE_ENABLED=true,
# ALLOW_LEGACY_UNPERMITTED_MCP=false). Many tests predate that flip and
# exercise MCP paths without supplying permits; opt the test suite back into
# legacy/permissive behavior unless an individual test explicitly monkeypatches
# strict mode (see test_mcp_trust_mode.py and test_trust_negative_security.py
# for examples that flip back to strict at the test boundary).
os.environ.setdefault("TRUST_MODE_ENABLED", "false")
os.environ.setdefault("ALLOW_LEGACY_UNPERMITTED_MCP", "true")


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    """Set up database tables before any tests run."""
    from app.db.database import init_db, close_db

    # Close any existing connection
    await close_db()

    # Start from a clean SQLite file so stale rows from prior runs
    # (e.g., unique constraints on seeded session IDs) don't leak
    # into the next run.
    for db_file in ("test.db", "test.db-shm", "test.db-wal"):
        if os.path.exists(db_file):
            os.remove(db_file)

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
        await session.execute(text("DELETE FROM idempotency_records"))
        await session.execute(text("DELETE FROM receipts"))
        await session.execute(text("DELETE FROM permits"))
        await session.execute(text("DELETE FROM agent_comms_messages"))
        await session.execute(text("DELETE FROM content_factory_generations"))
        await session.execute(text("DELETE FROM ledger_entries"))
        await session.execute(text("DELETE FROM billing_alerts"))
        await session.execute(text("DELETE FROM policy_bundles"))
        await session.execute(text("DELETE FROM wallets"))
        await session.execute(text("DELETE FROM daily_balance_snapshots"))
        await session.execute(text("DELETE FROM kyc_verifications"))
        await session.execute(text("DELETE FROM api_keys"))
        await session.execute(text("DELETE FROM key_rotation_logs"))
        await session.execute(text("DELETE FROM service_registry"))
        await session.execute(text("DELETE FROM control_plane_audit_events"))
        await session.execute(text("DELETE FROM audit_chain_heads"))
        await session.execute(text("DELETE FROM signing_keys"))
        await session.execute(text("DELETE FROM optimizer_telemetry"))
        await session.commit()

    yield
