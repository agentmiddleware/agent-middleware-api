"""Safety checks for the opt-in PostgreSQL crash-proof preflight."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.support.mcp_stress_preflight import (
    StressPreflightError,
    assert_empty_database_before_migration,
    assert_expected_database,
    require_explicit_isolation,
)


@pytest.fixture
def isolated_stress_environment(monkeypatch: pytest.MonkeyPatch) -> str:
    database_url = (
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/"
        "agent_middleware_stress_test"
    )
    monkeypatch.setenv("RUN_MCP_MULTIPROCESS_TESTS", "1")
    monkeypatch.setenv("MCP_STRESS_DB_ISOLATED", "1")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv(
        "MCP_STRESS_EXPECTED_DATABASE_NAME",
        "agent_middleware_stress_test",
    )
    monkeypatch.delenv("RAILWAY_PROJECT_ID", raising=False)
    monkeypatch.delenv(
        "MCP_STRESS_EXPECTED_RAILWAY_PROJECT_ID",
        raising=False,
    )
    return database_url


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    [
        ("RUN_MCP_MULTIPROCESS_TESTS", None, "set RUN_MCP"),
        ("MCP_STRESS_DB_ISOLATED", None, "MCP_STRESS_DB_ISOLATED"),
        ("DATABASE_URL", None, "DATABASE_URL is required"),
        ("DATABASE_URL", "sqlite+aiosqlite:///:memory:", "PostgreSQL"),
        ("STATE_BACKEND", "sqlite", "STATE_BACKEND=postgres"),
        ("ENVIRONMENT", "development", "exactly test or testing"),
        (
            "MCP_STRESS_EXPECTED_DATABASE_NAME",
            None,
            "MCP_STRESS_EXPECTED_DATABASE_NAME",
        ),
    ],
)
def test_preflight_requires_every_explicit_safety_signal(
    isolated_stress_environment: str,
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str | None,
    message: str,
) -> None:
    if value is None:
        monkeypatch.delenv(variable)
    else:
        monkeypatch.setenv(variable, value)

    with pytest.raises(StressPreflightError, match=message):
        require_explicit_isolation()


def test_preflight_rejects_mismatched_railway_project(
    isolated_stress_environment: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "actual-project")
    monkeypatch.setenv(
        "MCP_STRESS_EXPECTED_RAILWAY_PROJECT_ID",
        "different-project",
    )

    with pytest.raises(StressPreflightError, match="Railway"):
        require_explicit_isolation()


def test_preflight_accepts_all_explicit_safety_signals(
    isolated_stress_environment: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert require_explicit_isolation() == isolated_stress_environment
    monkeypatch.setenv("ENVIRONMENT", "testing")
    assert require_explicit_isolation() == isolated_stress_environment


@pytest.mark.asyncio
async def test_preflight_requires_exact_selected_database() -> None:
    connection = AsyncMock()
    connection.scalar.return_value = "agent_middleware_stress_test"
    await assert_expected_database(
        connection,
        "agent_middleware_stress_test",
    )

    connection.scalar.return_value = "different_database"

    with pytest.raises(StressPreflightError, match="does not match"):
        await assert_expected_database(
            connection,
            "agent_middleware_stress_test",
        )


@pytest.mark.asyncio
async def test_empty_database_preflight_is_read_only_and_rejects_data() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as connection:
            assert await assert_empty_database_before_migration(connection) == set()
            await connection.execute(
                text("CREATE TABLE application_rows (value INTEGER NOT NULL)")
            )
            await connection.execute(
                text("INSERT INTO application_rows (value) VALUES (7)")
            )
            await connection.commit()

        async with engine.connect() as connection:
            with pytest.raises(StressPreflightError, match="application_rows"):
                await assert_empty_database_before_migration(connection)
            assert (
                await connection.scalar(text("SELECT COUNT(*) FROM application_rows"))
                == 1
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_preflight_rejects_empty_prior_stress_table() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE mcp_stress_tool_executions "
                    "(execution_id INTEGER PRIMARY KEY)"
                )
            )
            await connection.commit()

        async with engine.connect() as connection:
            with pytest.raises(StressPreflightError, match="already exists"):
                await assert_empty_database_before_migration(connection)
    finally:
        await engine.dispose()
