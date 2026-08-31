"""Read-only safety preflight for the destructive PostgreSQL crash harness."""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection


class StressPreflightError(RuntimeError):
    """The selected database is not safe for destructive fault injection."""


class StressPreflightDisabled(StressPreflightError):
    """The caller did not explicitly opt into the crash harness."""


def require_explicit_isolation() -> str:
    if os.environ.get("RUN_MCP_MULTIPROCESS_TESTS") != "1":
        raise StressPreflightDisabled(
            "set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated "
            "PostgreSQL multiprocess harness"
        )
    if os.environ.get("MCP_STRESS_DB_ISOLATED") != "1":
        raise StressPreflightError(
            "MCP_STRESS_DB_ISOLATED=1 is required; refusing to inspect or "
            "mutate an unacknowledged database"
        )

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise StressPreflightError("DATABASE_URL is required for the opt-in harness")
    if not database_url.startswith(
        ("postgres://", "postgresql://", "postgresql+asyncpg://")
    ):
        raise StressPreflightError(
            "the opt-in harness requires a PostgreSQL DATABASE_URL"
        )
    if os.environ.get("STATE_BACKEND", "").strip().lower() != "postgres":
        raise StressPreflightError(
            "STATE_BACKEND=postgres is required for the opt-in harness"
        )
    if os.environ.get("ENVIRONMENT", "").strip().lower() not in {
        "test",
        "testing",
    }:
        raise StressPreflightError(
            "ENVIRONMENT must be exactly test or testing for the multiprocess harness"
        )

    if not os.environ.get("MCP_STRESS_EXPECTED_DATABASE_NAME", "").strip():
        raise StressPreflightError(
            "MCP_STRESS_EXPECTED_DATABASE_NAME must name the disposable "
            "PostgreSQL database exactly"
        )

    railway_project_id = os.environ.get("RAILWAY_PROJECT_ID", "").strip()
    expected_project_id = os.environ.get(
        "MCP_STRESS_EXPECTED_RAILWAY_PROJECT_ID", ""
    ).strip()
    if railway_project_id or expected_project_id:
        if not railway_project_id or railway_project_id != expected_project_id:
            raise StressPreflightError(
                "Railway runs must set MCP_STRESS_EXPECTED_RAILWAY_PROJECT_ID "
                "to the disposable project's exact RAILWAY_PROJECT_ID"
            )
    return database_url


async def assert_expected_database(
    connection: AsyncConnection,
    expected_database_name: str,
) -> None:
    selected_database = await connection.scalar(text("SELECT current_database()"))
    if selected_database != expected_database_name:
        raise StressPreflightError(
            "the selected PostgreSQL database does not match "
            "MCP_STRESS_EXPECTED_DATABASE_NAME"
        )


async def assert_empty_database_before_migration(
    connection: AsyncConnection,
) -> set[str]:
    table_names = set(
        await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    )
    stress_table = "mcp_stress_tool_executions"
    if stress_table in table_names:
        raise StressPreflightError(
            f"{stress_table} already exists; refusing to reuse a prior stress run"
        )

    populated: list[str] = []
    identifier_preparer = connection.dialect.identifier_preparer
    for table_name in sorted(table_names - {"alembic_version"}):
        # table_name comes only from SQLAlchemy's database inspector.
        quoted_table_name = identifier_preparer.quote(table_name)
        count = await connection.scalar(
            text(f"SELECT COUNT(*) FROM {quoted_table_name}")
        )
        if int(count or 0):
            populated.append(table_name)
    if populated:
        raise StressPreflightError(
            "isolated PostgreSQL database contains application data in: "
            + ", ".join(populated)
            + "; refusing to run destructive fault injection"
        )
    return table_names


async def run_preflight() -> None:
    require_explicit_isolation()
    expected_database_name = os.environ["MCP_STRESS_EXPECTED_DATABASE_NAME"].strip()

    from app.db.database import close_db, get_engine

    engine = get_engine()
    if engine is None or engine.dialect.name != "postgresql":
        raise StressPreflightError("configured database engine is not PostgreSQL")
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            await assert_expected_database(connection, expected_database_name)
            await assert_empty_database_before_migration(connection)
    finally:
        await close_db()


def main() -> int:
    try:
        asyncio.run(run_preflight())
    except StressPreflightError as exc:
        print(f"crash-proof preflight refused: {exc}", file=sys.stderr)
        return 2
    print("crash-proof preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
