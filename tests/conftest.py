"""
Shared test configuration.
Sets up pytest-asyncio, database, and common fixtures.
"""

import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import DateTime, event, inspect as sa_inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

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
        "test_awi_governed_mcp",
        "test_awi_http_governance",
        "test_awi_phase9",
        "test_behavioral_sandbox",
        "test_broadcast",
        "test_comms",
        "test_agent_comms_durable",
        "test_content_factory_generation_durable",
        "test_content_store",
        "test_discover_phase9",
        "test_discovery",
        "test_discovery_consistency",
        "test_discovery_drift",
        "test_discovery_honesty",
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
# Durable state stays in memory for the suite. State this explicitly: the tests
# always ran on memory state, but only as an accident of auto-resolution
# choosing postgres and asyncpg then failing on the SQLite DSN above. Once a
# SQLite DATABASE_URL resolves to the SQLite backend, "auto" opens a real
# aiosqlite connection whose worker thread is not a daemon, and an unclosed one
# blocks interpreter shutdown. See the teardown in setup_database.
os.environ.setdefault("STATE_BACKEND", "memory")
# Ephemeral SQLite create_all even when a job sets ENVIRONMENT=production
# (production_trust CI). Never applies to Postgres — see allows_metadata_create_all.
os.environ.setdefault("ALLOW_METADATA_CREATE_ALL", "true")
# Match the application default. Proof-marked tests opt in through the fixture
# below, so importing the app in an ordinary test never silently mounts demos.
os.environ.setdefault("ENABLE_PROOF_SURFACES", "false")
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
# Stop the suite from self-throttling. RateLimitMiddleware exempts only the
# literal "test-key"; unauthenticated requests all share the "anonymous"
# bucket and provisioned agent keys each get their own, so a fast full-suite
# run can cross the 120/min default and return 429 where a test expects
# 401/403 (observed as a flaky `assert 429 == 401` in
# test_tenant_isolation_hardening). Raising the limit for tests removes the
# cross-test coupling without changing production behavior; the one test that
# exercises limiting (test_runtime_degradation) builds its own middleware with
# an explicit per-instance limit and is unaffected.
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "1000000")


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def enable_proof_surfaces_for_marked_tests(request):
    """Explicitly opt proof-marked tests into the frozen route collection."""
    if request.node.get_closest_marker("proof") is None:
        yield
        return

    from app.core.config import get_settings
    from app.main import PROOF_SURFACE_ROUTERS, app
    from app.services.mcp_phase9_tools import sync_proof_surface_mcp_registration

    cfg = get_settings()
    previous = cfg.ENABLE_PROOF_SURFACES
    cfg.ENABLE_PROOF_SURFACES = True
    if not getattr(app.state, "proof_test_routes_mounted", False):
        for router_module in PROOF_SURFACE_ROUTERS:
            app.include_router(router_module.router)
        app.state.proof_test_routes_mounted = True
    sync_proof_surface_mcp_registration()
    try:
        yield
    finally:
        cfg.ENABLE_PROOF_SURFACES = previous
        sync_proof_surface_mcp_registration()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    """Set up database tables before any tests run."""
    from app.core.durable_state import close_durable_state
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
    # Release any durable-state backend a test opted into. aiosqlite runs each
    # connection on a non-daemon worker thread, so an unclosed one keeps the
    # interpreter alive after the run finishes — the suite passes and pytest
    # never exits. STATE_BACKEND=memory above means this is normally a no-op;
    # it exists so a test that deliberately selects a real backend cannot wedge
    # the process.
    await close_durable_state()


@pytest_asyncio.fixture(scope="function")
async def clean_database():
    """Clean database tables between tests."""
    from app.db.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        # Child tables that FK to wallets must go before wallets. Self-FK on
        # wallets.parent_wallet_id is cleared so a bulk DELETE succeeds with
        # PRAGMA foreign_keys=ON (Postgres-parity for SQLite tests).
        await session.execute(text("DELETE FROM receipts"))
        await session.execute(text("DELETE FROM mcp_dispatch_attempts"))
        await session.execute(text("DELETE FROM human_approvals"))
        await session.execute(text("DELETE FROM permit_requests"))
        await session.execute(text("DELETE FROM quotes"))
        await session.execute(text("DELETE FROM idempotency_records"))
        await session.execute(text("DELETE FROM permits"))
        await session.execute(text("DELETE FROM agent_comms_messages"))
        await session.execute(text("DELETE FROM content_factory_generations"))
        await session.execute(text("DELETE FROM ledger_entries"))
        await session.execute(text("DELETE FROM billing_alerts"))
        await session.execute(text("DELETE FROM policy_bundles"))
        await session.execute(text("DELETE FROM daily_balance_snapshots"))
        await session.execute(text("DELETE FROM kyc_verifications"))
        await session.execute(text("DELETE FROM refresh_tokens"))
        await session.execute(text("DELETE FROM api_keys"))
        await session.execute(text("DELETE FROM key_rotation_logs"))
        await session.execute(text("DELETE FROM service_registry"))
        await session.execute(text("DELETE FROM control_plane_audit_events"))
        await session.execute(text("DELETE FROM audit_chain_heads"))
        await session.execute(text("DELETE FROM signing_keys"))
        await session.execute(text("DELETE FROM optimizer_telemetry"))
        await session.execute(text("UPDATE wallets SET parent_wallet_id = NULL"))
        await session.execute(text("DELETE FROM wallets"))
        await session.commit()

    yield


@pytest.fixture
def enforce_naive_utc_datetime_columns():
    """Fail before SQLite hides an aware value bound to the naive-UTC schema.

    PostgreSQL's asyncpg driver rejects this mismatch, while SQLite silently
    serializes the value and lets the same test pass. Inspect both ORM flushes
    and Core/SQL query parameters. Keep this opt-in so focused production-parity
    tests can guard trust-critical paths without expanding unrelated scope.
    """

    def iter_parameter_values(value):
        if isinstance(value, Mapping):
            for nested in value.values():
                yield from iter_parameter_values(nested)
        elif isinstance(value, (list, tuple, set)):
            for nested in value:
                yield from iter_parameter_values(nested)
        else:
            yield value

    def assert_naive_datetime_values(session, _flush_context, _instances):
        for instance in [*session.new, *session.dirty]:
            mapper = sa_inspect(instance).mapper
            for attribute in mapper.column_attrs:
                if not any(
                    isinstance(column.type, DateTime) and not column.type.timezone
                    for column in attribute.columns
                ):
                    continue
                value = getattr(instance, attribute.key, None)
                if isinstance(value, datetime) and value.utcoffset() is not None:
                    raise AssertionError(
                        f"{type(instance).__name__}.{attribute.key} must be naive UTC"
                    )

    def assert_naive_statement_parameters(
        connection,
        clauseelement,
        multiparams,
        params,
        _execution_options,
    ):
        compiled_params = clauseelement.compile(dialect=connection.dialect).params
        for value in iter_parameter_values((multiparams, params, compiled_params)):
            if isinstance(value, datetime) and value.utcoffset() is not None:
                raise AssertionError("SQL datetime parameters must be naive UTC")

    event.listen(Session, "before_flush", assert_naive_datetime_values)
    event.listen(Engine, "before_execute", assert_naive_statement_parameters)
    try:
        yield
    finally:
        event.remove(Session, "before_flush", assert_naive_datetime_values)
        event.remove(Engine, "before_execute", assert_naive_statement_parameters)
