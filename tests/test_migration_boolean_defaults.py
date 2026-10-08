"""Boolean server defaults must be real booleans, not quoted text.

Migrations 022, 023, 038 and 039 declared Boolean columns with plain-string
server defaults (``"false"`` / ``"0"``). SQLAlchemy renders those as quoted
text literals (``DEFAULT 'false'``), which SQLite stores as text. Text
``'false'`` reads back truthy through SQLAlchemy's non-native Boolean, so
pre-existing rows (and rows inserted without the column) reported ``True``.
Postgres parses the quoted literal as boolean false, so production data is
unaffected; only fresh-database DDL changes, to the equivalent unquoted form.

Migration 042's downgrade additionally issued a raw ``BEGIN IMMEDIATE`` on
SQLite. A migration must never open its own transaction: inside a runner that
already holds one the nested BEGIN fails, and otherwise the opened
transaction is never committed by the migration itself.
"""

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Boolean, Column, MetaData, String, Table
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import Engine

REVISION_021 = "021_ledger_stripe_event_id"
REVISION_022 = "3988bd05deca"
REVISION_023 = "023_human_approval_gate"
REVISION_038 = "038_dispatch_call_slot_dup_idx"
REVISION_039 = "039_permit_allow_ident_repeats"
REVISION_041 = "041_scrub_content_owner_keys"
REVISION_042 = "042_permit_action_binding"

# (revision that introduces it, table, column). Checked right after that
# revision upgrades so later table rebuilds cannot mask the expression.
BOOLEAN_DEFAULTS = (
    (REVISION_022, "refresh_tokens", "revoked"),
    (REVISION_023, "permits", "requires_human_approval"),
    (REVISION_023, "human_approvals", "simulated"),
    (REVISION_038, "mcp_dispatch_attempts", "call_slot_reserved"),
    (REVISION_039, "permits", "allow_identical_repeats"),
)


def _assert_unquoted_boolean_default(sync_url, table, column):
    import re

    engine = create_engine(sync_url)
    try:
        with engine.connect() as connection:
            ddl = connection.execute(
                text("SELECT sql FROM sqlite_master WHERE name = :table"),
                {"table": table},
            ).scalar_one()
    finally:
        engine.dispose()
    # ADD COLUMN definitions can be appended mid-line, so search the whole
    # table DDL instead of matching one definition per line.
    pattern = re.compile(
        r'"?' + re.escape(column) + r'"?\s+\w+(?:\([^)]*\))?\s+DEFAULT\s+(\S+)'
    )
    match = pattern.search(ddl)
    assert match is not None, f"no server default found for {table}.{column} in: {ddl}"
    value = match.group(1).rstrip(",")
    assert not (len(value) >= 2 and value.startswith("'") and value.endswith("'")), (
        f"{table}.{column} has a quoted-text boolean default: {match.group(0)}"
    )


def _boolean_value(sync_url, table, key_column, key, column):
    metadata = MetaData()
    table_obj = Table(
        table,
        metadata,
        Column(key_column, String),
        Column(column, Boolean),
    )
    engine = create_engine(sync_url)
    try:
        with engine.connect() as connection:
            return connection.execute(
                select(table_obj.c[column]).where(table_obj.c[key_column] == key)
            ).scalar_one()
    finally:
        engine.dispose()


def test_sqlite_boolean_defaults_are_real_false(tmp_path, monkeypatch):
    db_path = tmp_path / "boolean-defaults.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", async_url)
    config = Config("alembic.ini")

    command.upgrade(config, REVISION_021)
    asyncio.set_event_loop(asyncio.new_event_loop())

    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO wallets (
                    wallet_id, wallet_type, owner_key, balance,
                    lifetime_credits, lifetime_debits, daily_spent,
                    auto_refill, status
                ) VALUES (
                    'w-bool', 'agent', '', 100, 100, 0, 0, 0, 'active'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO signing_keys (
                    key_id, public_key_b64, status
                ) VALUES ('k-bool', 'public', 'active')
                """
            )
        )
        # Legacy permit from before the boolean columns existed.
        connection.execute(
            text(
                """
                INSERT INTO permits (
                    permit_id, issuer_wallet_id, subject_wallet_id,
                    scopes_json, allowed_tools_json, max_credits,
                    expires_at, nonce, status, signature, key_id
                ) VALUES (
                    'p-bool', 'w-bool', 'w-bool', '[]', '[]', 10,
                    '2030-01-01 00:00:00', 'n-bool', 'active',
                    'signature', 'k-bool'
                )
                """
            )
        )
    engine.dispose()

    # 022: refresh_tokens.revoked. Rows inserted without the column must
    # read False, and the stored DDL default must not be quoted text.
    command.upgrade(config, REVISION_022)
    asyncio.set_event_loop(asyncio.new_event_loop())
    _assert_unquoted_boolean_default(sync_url, "refresh_tokens", "revoked")
    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO refresh_tokens (
                    jti, wallet_id, created_at, expires_at
                ) VALUES (
                    'jti-bool', 'w-bool',
                    '2026-01-01 00:00:00', '2030-01-01 00:00:00'
                )
                """
            )
        )
    engine.dispose()
    assert (
        _boolean_value(sync_url, "refresh_tokens", "jti", "jti-bool", "revoked")
        is False
    )

    # 023: backfilled legacy permits and omitted simulated flags read False.
    command.upgrade(config, REVISION_023)
    asyncio.set_event_loop(asyncio.new_event_loop())
    _assert_unquoted_boolean_default(sync_url, "permits", "requires_human_approval")
    _assert_unquoted_boolean_default(sync_url, "human_approvals", "simulated")
    assert (
        _boolean_value(
            sync_url,
            "permits",
            "permit_id",
            "p-bool",
            "requires_human_approval",
        )
        is False
    )
    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO human_approvals (
                    approval_id, wallet_id, permit_id, tool,
                    idempotency_key, requested_at, expires_at
                ) VALUES (
                    'a-bool', 'w-bool', 'p-bool', 'tool',
                    'key-bool', '2026-01-01 00:00:00',
                    '2030-01-01 00:00:00'
                )
                """
            )
        )
    engine.dispose()
    assert (
        _boolean_value(
            sync_url, "human_approvals", "approval_id", "a-bool", "simulated"
        )
        is False
    )

    # 038 and 039: SQLite type affinity happens to store '0' as integer 0,
    # so only the DDL expression can pin the fix (no quoted text default).
    command.upgrade(config, REVISION_038)
    asyncio.set_event_loop(asyncio.new_event_loop())
    _assert_unquoted_boolean_default(
        sync_url, "mcp_dispatch_attempts", "call_slot_reserved"
    )
    command.upgrade(config, REVISION_039)
    asyncio.set_event_loop(asyncio.new_event_loop())
    _assert_unquoted_boolean_default(sync_url, "permits", "allow_identical_repeats")


def test_042_downgrade_issues_no_begin_on_sqlite(tmp_path, monkeypatch):
    db_path = tmp_path / "action-downgrade.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", async_url)
    config = Config("alembic.ini")

    command.upgrade(config, REVISION_042)
    asyncio.set_event_loop(asyncio.new_event_loop())

    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        command.downgrade(config, REVISION_041)
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    asyncio.set_event_loop(asyncio.new_event_loop())

    begins = [
        statement
        for statement in statements
        if statement.strip().upper() in ("BEGIN", "BEGIN IMMEDIATE")
    ]
    assert begins == [], f"downgrade opened its own transaction: {begins}"

    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        for table in ("permits", "receipts"):
            columns = {col["name"] for col in inspector.get_columns(table)}
            assert not any(name.startswith("action_") for name in columns), (
                f"{table} kept action columns after downgrade"
            )
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                == REVISION_041
            )
    finally:
        engine.dispose()


async def _postgres_maintenance(statement):
    import asyncpg

    connection = await asyncpg.connect("postgresql://sellers@localhost/postgres")
    try:
        await connection.execute(statement)
    finally:
        await connection.close()


def _postgres_available():
    try:
        asyncio.run(_postgres_maintenance("SELECT 1"))
    except Exception:
        return False
    return True


def _assert_pg_fragment_unquoted(statements, table, column):
    import re

    candidates = [statement for statement in statements if column in statement]
    assert candidates, f"no emitted DDL mentions {table}.{column}"
    pattern = re.compile(
        r'"?' + re.escape(column) + r'"?\s+\w+(?:\([^)]*\))?\s+DEFAULT\s+(\S+)'
    )
    checked = 0
    for statement in candidates:
        match = pattern.search(statement)
        if match is None:
            continue
        checked += 1
        value = match.group(1).rstrip(",")
        assert not (
            len(value) >= 2 and value.startswith("'") and value.endswith("'")
        ), f"{table}.{column} emitted as quoted text: {match.group(0)}"
    assert checked > 0, (
        f"could not parse a DEFAULT for {table}.{column} from: {candidates}"
    )


def test_postgres_boolean_defaults_and_042_roundtrip(monkeypatch):
    if not _postgres_available():
        pytest.skip("requires local throwaway PostgreSQL")
    db_name = "fleet_migration_bools"
    url = f"postgresql://sellers@localhost/{db_name}"
    asyncio.run(_postgres_maintenance(f'DROP DATABASE IF EXISTS "{db_name}"'))
    asyncio.run(_postgres_maintenance(f'CREATE DATABASE "{db_name}"'))
    try:
        monkeypatch.setenv("DATABASE_URL", url)
        config = Config("alembic.ini")
        command.upgrade(config, REVISION_021)
        asyncio.set_event_loop(asyncio.new_event_loop())

        # Capture the real emitted DDL per revision. Postgres parses the
        # old quoted literals as boolean false, so information_schema alone
        # cannot tell them apart; the emitted statement can.
        statements = []

        def record(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(Engine, "before_cursor_execute", record)
        try:
            command.upgrade(config, REVISION_022)
            _assert_pg_fragment_unquoted(statements, "refresh_tokens", "revoked")
            del statements[:]
            command.upgrade(config, REVISION_023)
            _assert_pg_fragment_unquoted(
                statements, "permits", "requires_human_approval"
            )
            _assert_pg_fragment_unquoted(statements, "human_approvals", "simulated")
            del statements[:]
            command.upgrade(config, REVISION_038)
            _assert_pg_fragment_unquoted(
                statements, "mcp_dispatch_attempts", "call_slot_reserved"
            )
            del statements[:]
            command.upgrade(config, REVISION_039)
            _assert_pg_fragment_unquoted(
                statements, "permits", "allow_identical_repeats"
            )
        finally:
            event.remove(Engine, "before_cursor_execute", record)
        asyncio.set_event_loop(asyncio.new_event_loop())

        command.upgrade(config, "head")
        asyncio.set_event_loop(asyncio.new_event_loop())

        import asyncpg

        async def fetch_defaults():
            connection = await asyncpg.connect(
                f"postgresql://sellers@localhost/{db_name}"
            )
            try:
                return await connection.fetch(
                    """
                    SELECT table_name, column_name, column_default
                    FROM information_schema.columns
                    WHERE (table_name, column_name) IN (
                        ('refresh_tokens', 'revoked'),
                        ('permits', 'requires_human_approval'),
                        ('human_approvals', 'simulated'),
                        ('mcp_dispatch_attempts', 'call_slot_reserved'),
                        ('permits', 'allow_identical_repeats')
                    )
                    """
                )
            finally:
                await connection.close()

        # Stored defaults are plain boolean false, identical to production.
        rows = asyncio.run(fetch_defaults())
        assert len(rows) == 5, f"boolean columns missing: {rows}"
        for row in rows:
            assert row["column_default"] == "false", (
                f"{row['table_name']}.{row['column_name']} default "
                f"is {row['column_default']!r}, expected boolean false"
            )

        command.downgrade(config, REVISION_041)
        asyncio.set_event_loop(asyncio.new_event_loop())

        async def fetch_after_downgrade():
            connection = await asyncpg.connect(
                f"postgresql://sellers@localhost/{db_name}"
            )
            try:
                action_columns = await connection.fetch(
                    """
                    SELECT table_name, column_name
                    FROM information_schema.columns
                    WHERE table_name IN ('permits', 'receipts')
                      AND column_name LIKE 'action\\_%'
                    """
                )
                version = await connection.fetchval(
                    "SELECT version_num FROM alembic_version"
                )
                return action_columns, version
            finally:
                await connection.close()

        action_columns, version = asyncio.run(fetch_after_downgrade())
        assert action_columns == []
        assert version == REVISION_041
        command.upgrade(config, "head")
        asyncio.set_event_loop(asyncio.new_event_loop())
    finally:
        asyncio.run(
            _postgres_maintenance(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        )
