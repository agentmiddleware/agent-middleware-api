"""Row-level security on wallet-scoped tables (migration 048_tenant_rls).

The unit tests run everywhere. The PostgreSQL tests need a superuser URL in
``TEST_RLS_POSTGRES_ADMIN_URL``: they create a scratch database plus an owner
role and a NOSUPERUSER NOBYPASSRLS non-owner runtime role (the posture
docs/tenant-rls.md prescribes), migrate as the owner, and exercise the
policies as the runtime role. ``REQUIRE_TENANT_RLS_POSTGRES_TESTS=1`` turns
the skip into a failure for CI.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import String, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

from app.core import auth as auth_module
from app.core.config import Settings, get_settings
from app.core.db_urls import as_asyncpg_url
from app.core.time import utc_now
from app.db import tenant_rls
from app.db.models import LedgerEntryModel, PermitModel, SigningKeyModel, WalletModel
from app.db.tenant_rls import (
    RLS_TABLES,
    RlsScope,
    TenantRlsPostureError,
    TenantScopedSession,
    bind_wallet_scope,
    check_tenant_rls_posture,
    current_rls_scope,
    enable_rls_statements,
    rls_admin_scope,
    rls_wallet_scope,
    scope_settings,
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "048_tenant_rls.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_048", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# Unit tests (no PostgreSQL)
# --------------------------------------------------------------------------


def test_migration_table_list_matches_runtime_list():
    assert _load_migration().RLS_TABLES == RLS_TABLES


def test_wallet_columns_are_varchar_so_policies_compare_text():
    # The policy compares the column to current_setting(...) (text) with no
    # cast. That is only correct while every owner column is a string column;
    # a uuid column would need ::uuid and a different empty-string guard.
    for table, columns in RLS_TABLES.items():
        sa_table = SQLModel.metadata.tables[table]
        for column in columns:
            column_type = sa_table.c[column].type
            # sqlmodel's AutoString is a TypeDecorator over String.
            impl = getattr(column_type, "impl", column_type)
            assert isinstance(impl, String), (table, column)


def test_policy_predicate_fails_closed_on_unset_or_empty_wallet():
    predicate = _load_migration().policy_predicate(
        ("issuer_wallet_id", "subject_wallet_id")
    )
    assert predicate == (
        "(issuer_wallet_id = NULLIF(current_setting('app.current_wallet_id', true), '')"
        " OR subject_wallet_id = "
        "NULLIF(current_setting('app.current_wallet_id', true), ''))"
        " OR current_setting('app.rls_bypass', true) = 'on'"
    )


def test_scope_settings():
    assert scope_settings(None) == {"wallet": "", "bypass": "off"}
    assert scope_settings(RlsScope(wallet_id="w1")) == {"wallet": "w1", "bypass": "off"}
    assert scope_settings(RlsScope(admin_reason="ops")) == {
        "wallet": "",
        "bypass": "on",
    }


async def _in_fresh_context(coro):
    # A task runs in a copy of the context, so bindings never leak out.
    return await asyncio.create_task(coro)


@pytest.mark.anyio
async def test_scopes_nest_and_reset():
    async def body():
        assert current_rls_scope() is None
        with rls_admin_scope("maintenance"):
            assert current_rls_scope() == RlsScope(admin_reason="maintenance")
            with rls_wallet_scope("w1"):
                assert current_rls_scope() == RlsScope(wallet_id="w1")
            assert current_rls_scope().bypass
        assert current_rls_scope() is None
        bind_wallet_scope("w2")
        assert current_rls_scope() == RlsScope(wallet_id="w2")
        bind_wallet_scope(None)
        assert current_rls_scope() is None

    await _in_fresh_context(body())
    with pytest.raises(ValueError, match="requires a reason"):
        with rls_admin_scope(""):
            pass
    with pytest.raises(ValueError, match="requires a wallet_id"):
        with rls_wallet_scope(""):
            pass


def test_enable_rls_statements_cover_every_table():
    statements = enable_rls_statements()
    assert len(statements) == 2 * len(RLS_TABLES)
    for table in RLS_TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in statements
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in statements


def test_off_mode_hook_sets_nothing_by_default(monkeypatch):
    class _Conn:
        class dialect:
            name = "postgresql"

        def __init__(self):
            self.executed = []

        def execute(self, statement, params=None):
            self.executed.append(params)

    monkeypatch.setattr(get_settings(), "TENANT_RLS_MODE", "off")
    assert tenant_rls._off_mode_bypass_required is False
    conn = _Conn()
    tenant_rls._apply_rls_scope(None, None, conn)
    assert conn.executed == []
    monkeypatch.setattr(tenant_rls, "_off_mode_bypass_required", True)
    tenant_rls._apply_rls_scope(None, None, conn)
    assert conn.executed == [{"wallet": "", "bypass": "on"}]
    monkeypatch.setattr(get_settings(), "TENANT_RLS_MODE", "enforce")
    with rls_wallet_scope("w1"):
        tenant_rls._apply_rls_scope(None, None, conn)
    assert conn.executed[-1] == {"wallet": "w1", "bypass": "off"}


def test_tenant_rls_mode_setting_rejects_typos():
    assert Settings().TENANT_RLS_MODE == "off"
    assert Settings(TENANT_RLS_MODE=" Enforce ").TENANT_RLS_MODE == "enforce"
    with pytest.raises(ValueError, match="TENANT_RLS_MODE must be"):
        Settings(TENANT_RLS_MODE="enforced")


@pytest.mark.anyio
async def test_auth_resolves_under_admin_scope_then_binds_caller_wallet(monkeypatch):
    seen: list[RlsScope | None] = []

    async def fake_resolve(api_key, authorization):
        seen.append(current_rls_scope())
        if api_key == "admin-key":
            return auth_module.AuthContext(
                source="env", raw_key=api_key, is_bootstrap_admin=True
            )
        if api_key == "bad-key":
            raise HTTPException(status_code=403, detail="invalid_api_key")
        return auth_module.AuthContext(
            source="db", raw_key=api_key, key_id="k1", wallet_id="wallet-a"
        )

    monkeypatch.setattr(auth_module, "_resolve_auth_context", fake_resolve)

    async def call(key):
        await auth_module.get_auth_context(api_key=key, authorization=None)
        return current_rls_scope()

    assert await _in_fresh_context(call("wallet-key")) == RlsScope(wallet_id="wallet-a")
    assert await _in_fresh_context(call("admin-key")) == RlsScope(
        admin_reason="bootstrap_admin"
    )

    async def rejected():
        with pytest.raises(HTTPException):
            await auth_module.get_auth_context(api_key="bad-key", authorization=None)
        # A refused credential leaves no scope behind (fail closed).
        return current_rls_scope()

    assert await _in_fresh_context(rejected()) is None
    assert seen == [RlsScope(admin_reason="credential_resolution")] * 3


@pytest.mark.anyio
async def test_posture_check_is_inert_on_sqlite():
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        report = await check_tenant_rls_posture(engine)
    finally:
        await engine.dispose()
    assert report["effective"] is False
    assert report["dialect"] == "sqlite"
    assert tenant_rls._off_mode_bypass_required is False


# --------------------------------------------------------------------------
# PostgreSQL tests
# --------------------------------------------------------------------------

ADMIN_URL = os.environ.get("TEST_RLS_POSTGRES_ADMIN_URL", "").strip()


def _require_postgres():
    if ADMIN_URL:
        return
    if os.environ.get("REQUIRE_TENANT_RLS_POSTGRES_TESTS") == "1":
        pytest.fail("REQUIRE_TENANT_RLS_POSTGRES_TESTS=1 but no admin URL is set")
    pytest.skip("TEST_RLS_POSTGRES_ADMIN_URL not set")


def _with_credentials(url: str, user: str, password: str, database: str) -> str:
    from sqlalchemy.engine import make_url

    parsed = make_url(url).set(
        drivername="postgresql+asyncpg",
        username=user,
        password=password,
        database=database,
    )
    return parsed.render_as_string(hide_password=False)


async def _admin_execute(statements: list[str], database: str | None = None) -> None:
    import asyncpg

    from sqlalchemy.engine import make_url

    url = make_url(ADMIN_URL)
    if database:
        url = url.set(database=database)
    conn = await asyncpg.connect(
        as_asyncpg_url(url.render_as_string(hide_password=False))
    )
    try:
        for statement in statements:
            await conn.execute(statement)
    finally:
        await conn.close()


def _alembic(url: str, action: str, revision: str, mode: str = "enforce") -> None:
    from alembic import command
    from alembic.config import Config

    settings = get_settings()
    previous = os.environ.get("DATABASE_URL")
    previous_mode = settings.TENANT_RLS_MODE
    os.environ["DATABASE_URL"] = url
    # 048_tenant_rls enables RLS only when migrated under enforce.
    settings.TENANT_RLS_MODE = mode
    try:
        getattr(command, action)(Config("alembic.ini"), revision)
    finally:
        settings.TENANT_RLS_MODE = previous_mode
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        asyncio.set_event_loop(asyncio.new_event_loop())


@pytest.fixture(scope="module")
def rls_db():
    _require_postgres()
    suffix = uuid.uuid4().hex[:8]
    database = f"amw_rls_{suffix}"
    owner, app_role = f"amw_rls_owner_{suffix}", f"amw_rls_app_{suffix}"
    asyncio.run(
        _admin_execute(
            [
                f"CREATE ROLE {owner} LOGIN PASSWORD 'owner' NOSUPERUSER NOBYPASSRLS",
                f"CREATE ROLE {app_role} LOGIN PASSWORD 'app' "
                "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE",
                f"CREATE DATABASE {database} OWNER {owner}",
            ]
        )
    )
    # Same grants docs/tenant-rls.md prescribes for the runtime role.
    asyncio.run(
        _admin_execute(
            [
                f"GRANT ALL ON SCHEMA public TO {owner}",
                f"GRANT USAGE ON SCHEMA public TO {app_role}",
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app_role}",
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public "
                f"GRANT USAGE, SELECT ON SEQUENCES TO {app_role}",
            ],
            database=database,
        )
    )
    owner_url = _with_credentials(ADMIN_URL, owner, "owner", database)
    app_url = _with_credentials(ADMIN_URL, app_role, "app", database)
    _alembic(owner_url, "upgrade", "head")
    try:
        yield {
            "owner_url": owner_url,
            "app_url": app_url,
            "app_role": app_role,
            "owner": owner,
            "database": database,
        }
    finally:
        asyncio.run(
            _admin_execute(
                [
                    f"DROP DATABASE IF EXISTS {database} WITH (FORCE)",
                    f"DROP ROLE IF EXISTS {app_role}",
                    f"DROP ROLE IF EXISTS {owner}",
                ]
            )
        )


WALLET_A, WALLET_B, WALLET_C = "rls-wallet-a", "rls-wallet-b", "rls-wallet-c"


def _engine(url: str, **kwargs):
    return create_async_engine(url, poolclass=NullPool, **kwargs)


@pytest.fixture
async def seeded(rls_db):
    """Two wallets' rows, written by the owner under the explicit bypass."""
    engine = _engine(rls_db["owner_url"])
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.rls_bypass', 'on', true)"))
            for table in ("receipts", "permits", "ledger_entries"):
                await conn.execute(text(f"DELETE FROM {table}"))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                text("SELECT set_config('app.rls_bypass', 'on', true)")
            )
            for wallet in (WALLET_A, WALLET_B, WALLET_C):
                if await session.get(WalletModel, wallet) is None:
                    session.add(WalletModel(wallet_id=wallet, wallet_type="agent"))
            if await session.get(SigningKeyModel, "rls-kid") is None:
                session.add(SigningKeyModel(key_id="rls-kid", public_key_b64="x"))
            await session.flush()
            for wallet in (WALLET_A, WALLET_A, WALLET_B):
                session.add(
                    LedgerEntryModel(
                        entry_id=f"le-{uuid.uuid4().hex[:12]}",
                        wallet_id=wallet,
                        action="debit",
                        amount=Decimal("-1"),
                        balance_after=Decimal("0"),
                    )
                )
            session.add(
                PermitModel(
                    permit_id="rls-permit-ab",
                    issuer_wallet_id=WALLET_A,
                    subject_wallet_id=WALLET_B,
                    scopes_json="[]",
                    allowed_tools_json="[]",
                    max_credits=Decimal("1"),
                    expires_at=utc_now() + timedelta(hours=1),
                    nonce="n1",
                    signature="sig",
                    key_id="rls-kid",
                )
            )
            await session.commit()
    finally:
        await engine.dispose()
    return rls_db


async def _count(conn, table: str) -> int:
    return int((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar())


async def _set_scope(conn, wallet: str = "", bypass: str = "off") -> None:
    await conn.execute(
        text(
            "SELECT set_config('app.current_wallet_id', :w, true), "
            "set_config('app.rls_bypass', :b, true)"
        ),
        {"w": wallet, "b": bypass},
    )


@pytest.mark.anyio
async def test_unset_and_empty_scope_see_and_write_nothing(seeded):
    engine = _engine(seeded["app_url"])
    try:
        async with engine.connect() as conn:
            # Nothing set at all: current_setting(..., true) is NULL.
            assert await _count(conn, "ledger_entries") == 0
            assert await _count(conn, "permits") == 0
            await conn.rollback()
            await _set_scope(conn, wallet="")
            assert await _count(conn, "ledger_entries") == 0
            await conn.rollback()
            with pytest.raises(Exception, match="row-level security"):
                await conn.execute(
                    text(
                        "INSERT INTO ledger_entries (entry_id, wallet_id, action, "
                        "amount, balance_after, description) VALUES "
                        f"('le-x', '{WALLET_A}', 'debit', -1, 0, '')"
                    )
                )
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_wallet_scope_sees_and_writes_only_its_rows(seeded):
    engine = _engine(seeded["app_url"])
    try:
        async with engine.connect() as conn:
            await _set_scope(conn, wallet=WALLET_A)
            assert await _count(conn, "ledger_entries") == 2
            # UPDATE/DELETE cannot reach another wallet's rows.
            result = await conn.execute(
                text(
                    "UPDATE ledger_entries SET description = 'x' WHERE wallet_id = :w"
                ),
                {"w": WALLET_B},
            )
            assert result.rowcount == 0
            # WITH CHECK: cannot move a visible row to another wallet...
            with pytest.raises(Exception, match="row-level security"):
                await conn.execute(
                    text(
                        "UPDATE ledger_entries SET wallet_id = :b WHERE wallet_id = :a"
                    ),
                    {"a": WALLET_A, "b": WALLET_B},
                )
            await conn.rollback()
            # ...or insert one for it.
            await _set_scope(conn, wallet=WALLET_A)
            with pytest.raises(Exception, match="row-level security"):
                await conn.execute(
                    text(
                        "INSERT INTO ledger_entries (entry_id, wallet_id, action, "
                        "amount, balance_after, description) VALUES "
                        f"('le-y', '{WALLET_B}', 'debit', -1, 0, '')"
                    )
                )
            await conn.rollback()
            await _set_scope(conn, wallet=WALLET_B)
            assert await _count(conn, "ledger_entries") == 1
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_permits_visible_to_issuer_and_subject_only(seeded):
    engine = _engine(seeded["app_url"])
    try:
        async with engine.connect() as conn:
            for wallet, expected in ((WALLET_A, 1), (WALLET_B, 1), (WALLET_C, 0)):
                await _set_scope(conn, wallet=wallet)
                assert await _count(conn, "permits") == expected, wallet
                await conn.rollback()
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_permit_issuer_reads_subject_receipt_and_its_ledger_only(seeded):
    """Mirrors authorize_receipt_access's delegated-issuer branch, read-only.

    Permit rls-permit-ab: issuer A, subject B. A receipt filed under B for
    that permit (and the ledger entry it names) is readable by A, never
    writable by A, and invisible to C.
    """
    owner = _engine(seeded["owner_url"])
    try:
        async with owner.begin() as conn:
            await _set_scope(conn, bypass="on")
            ledger_id = (
                await conn.execute(
                    text("SELECT entry_id FROM ledger_entries WHERE wallet_id = :b"),
                    {"b": WALLET_B},
                )
            ).scalar_one()
            await conn.execute(text("DELETE FROM receipts"))
            await conn.execute(
                text(
                    "INSERT INTO receipts (receipt_id, permit_id, wallet_id, tool, "
                    "request_hash, credits_authorized, outcome, signature, "
                    "signature_key_id, ledger_entry_id) VALUES "
                    "('rcpt-b', 'rls-permit-ab', :b, 't', 'h', 1, 'success', 's', "
                    "'rls-kid', :ledger)"
                ),
                {"b": WALLET_B, "ledger": ledger_id},
            )
    finally:
        await owner.dispose()

    engine = _engine(seeded["app_url"])
    try:
        async with engine.connect() as conn:
            await _set_scope(conn, wallet=WALLET_A)
            assert await _count(conn, "receipts") == 1
            # A's own two entries plus the one B-entry the receipt names.
            assert await _count(conn, "ledger_entries") == 3
            # Read-only: the delegated branch never admits a write.
            result = await conn.execute(
                text("UPDATE receipts SET outcome = 'x' WHERE receipt_id = 'rcpt-b'")
            )
            assert result.rowcount == 0
            result = await conn.execute(
                text("DELETE FROM ledger_entries WHERE entry_id = :e"),
                {"e": ledger_id},
            )
            assert result.rowcount == 0
            await conn.rollback()
            await _set_scope(conn, wallet=WALLET_C)
            assert await _count(conn, "receipts") == 0
            assert await _count(conn, "ledger_entries") == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_explicit_bypass_sees_every_wallet(seeded):
    engine = _engine(seeded["app_url"])
    try:
        async with engine.connect() as conn:
            await _set_scope(conn, bypass="on")
            assert await _count(conn, "ledger_entries") == 3
            await conn.rollback()
            # Any value other than exactly 'on' is not a bypass.
            await _set_scope(conn, bypass="true")
            assert await _count(conn, "ledger_entries") == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_set_local_scope_does_not_survive_commit(seeded):
    """A pooled connection must not carry the last request's wallet."""
    engine = _engine(seeded["app_url"])
    try:
        async with engine.connect() as conn:
            await _set_scope(conn, wallet=WALLET_A)
            assert await _count(conn, "ledger_entries") == 2
            await conn.commit()
            # Same physical connection, next transaction, nothing set.
            assert await _count(conn, "ledger_entries") == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_live_wallet_columns_are_character_varying(rls_db):
    engine = _engine(rls_db["owner_url"])
    try:
        async with engine.connect() as conn:
            for table, columns in RLS_TABLES.items():
                for column in columns:
                    data_type = (
                        await conn.execute(
                            text(
                                "SELECT data_type FROM information_schema.columns "
                                "WHERE table_name = :t AND column_name = :c"
                            ),
                            {"t": table, "c": column},
                        )
                    ).scalar()
                    assert data_type == "character varying", (table, column)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_owner_is_bound_by_force(seeded):
    engine = _engine(seeded["owner_url"])
    try:
        async with engine.connect() as conn:
            assert await _count(conn, "ledger_entries") == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_app_session_hook_applies_scope_per_transaction(seeded, monkeypatch):
    monkeypatch.setattr(get_settings(), "TENANT_RLS_MODE", "enforce")
    engine = _engine(seeded["app_url"])
    factory = async_sessionmaker(
        engine, sync_session_class=TenantScopedSession, expire_on_commit=False
    )
    count = select(func.count()).select_from(LedgerEntryModel)

    async def body():
        async with factory() as session:
            assert (await session.execute(count)).scalar() == 0
        with rls_wallet_scope(WALLET_A):
            async with factory() as session:
                assert (await session.execute(count)).scalar() == 2
                await session.commit()
                # A new transaction re-applies the (still bound) scope.
                assert (await session.execute(count)).scalar() == 2
        with rls_admin_scope("test"):
            async with factory() as session:
                assert (await session.execute(count)).scalar() == 3
        bind_wallet_scope(WALLET_B)
        async with factory() as session:
            assert (await session.execute(count)).scalar() == 1

    try:
        await _in_fresh_context(body())
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_off_mode_after_enforce_bypasses_once_posture_sees_rls(
    seeded, monkeypatch
):
    # RLS left enabled by an earlier enforce rollout, mode switched back off:
    # the boot posture check turns on the per-transaction bypass.
    monkeypatch.setattr(get_settings(), "TENANT_RLS_MODE", "off")
    monkeypatch.setattr(tenant_rls, "_off_mode_bypass_required", False)
    engine = _engine(seeded["app_url"])
    factory = async_sessionmaker(
        engine, sync_session_class=TenantScopedSession, expire_on_commit=False
    )
    count = select(func.count()).select_from(LedgerEntryModel)
    try:
        async with factory() as session:
            assert (await session.execute(count)).scalar() == 0
        report = await check_tenant_rls_posture(engine)
        assert report["tables_with_rls_enabled"] == sorted(RLS_TABLES)
        assert tenant_rls._off_mode_bypass_required is True
        async with factory() as session:
            assert (await session.execute(count)).scalar() == 3
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_posture_accepts_runtime_role_and_refuses_superuser(seeded, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "TENANT_RLS_MODE", "enforce")
    engine = _engine(seeded["app_url"])
    try:
        report = await check_tenant_rls_posture(engine)
    finally:
        await engine.dispose()
    assert report["effective"] is True
    assert report["superuser"] is False and report["bypassrls"] is False
    assert report["owns_rls_tables"] == []
    assert report["tables_without_forced_rls"] == []

    engine = _engine(seeded["owner_url"])
    try:
        report = await check_tenant_rls_posture(engine)
    finally:
        await engine.dispose()
    # The owner is still bound (FORCE), so not refused, but reported.
    assert report["effective"] is True
    assert sorted(report["owns_rls_tables"]) == sorted(RLS_TABLES)

    from sqlalchemy.engine import make_url

    superuser_url = (
        make_url(ADMIN_URL)
        .set(drivername="postgresql+asyncpg", database=seeded["database"])
        .render_as_string(hide_password=False)
    )
    engine = _engine(superuser_url)
    try:
        with pytest.raises(TenantRlsPostureError, match="SUPERUSER"):
            await check_tenant_rls_posture(engine)
        monkeypatch.setattr(settings, "TENANT_RLS_MODE", "off")
        report = await check_tenant_rls_posture(engine)
        assert report["superuser"] is True and report["effective"] is False
    finally:
        await engine.dispose()


def test_downgrade_removes_policies_and_upgrade_restores(rls_db):
    async def forced_tables(url: str) -> set[str]:
        engine = _engine(url)
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    text(
                        "SELECT relname FROM pg_class WHERE relrowsecurity "
                        "AND relforcerowsecurity AND relname = ANY(:t)"
                    ),
                    {"t": list(RLS_TABLES)},
                )
                return {row[0] for row in rows}
        finally:
            await engine.dispose()

    async def policy_tables(url: str) -> set[str]:
        engine = _engine(url)
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    text("SELECT tablename FROM pg_policies WHERE policyname = :p"),
                    {"p": tenant_rls.POLICY_NAME},
                )
                return {row[0] for row in rows}
        finally:
            await engine.dispose()

    owner_url = rls_db["owner_url"]
    _alembic(owner_url, "downgrade", "046_demo_tenant_key_allowlist")
    assert asyncio.run(forced_tables(owner_url)) == set()
    assert asyncio.run(policy_tables(owner_url)) == set()
    # Default off: policies exist, RLS stays disabled for every client.
    _alembic(owner_url, "upgrade", "head", mode="off")
    assert asyncio.run(forced_tables(owner_url)) == set()
    assert asyncio.run(policy_tables(owner_url)) == set(RLS_TABLES)
    _alembic(owner_url, "downgrade", "046_demo_tenant_key_allowlist")
    _alembic(owner_url, "upgrade", "head")
    assert asyncio.run(forced_tables(owner_url)) == set(RLS_TABLES)


def test_tenant_rls_module_exposes_documented_settings():
    assert tenant_rls.WALLET_SETTING == "app.current_wallet_id"
    assert tenant_rls.BYPASS_SETTING == "app.rls_bypass"


@pytest.mark.anyio
async def test_admin_route_dependency_binds_scope_for_the_endpoint():
    from fastapi import Depends, FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.db.tenant_rls import rls_admin_route

    mini = FastAPI()

    @mini.post("/x", dependencies=[Depends(rls_admin_route("unit"))])
    async def endpoint():
        scope = current_rls_scope()
        return {"reason": scope.admin_reason if scope else None}

    @mini.post("/y")
    async def unscoped():
        return {"scope": current_rls_scope() is not None}

    async def post(path):
        async with AsyncClient(
            transport=ASGITransport(app=mini), base_url="http://t"
        ) as c:
            return (await c.post(path)).json()

    # ASGI servers run each request in its own task, as here; the binding
    # lives in that task's context and cannot reach the next request.
    assert await _in_fresh_context(post("/x")) == {"reason": "unit"}
    assert await _in_fresh_context(post("/y")) == {"scope": False}
    with pytest.raises(ValueError, match="requires a reason"):
        rls_admin_route("")


def test_unauthenticated_writers_carry_explicit_admin_scope():
    from app.routers import auth as auth_router
    from app.routers import demo_keys, dev_keys, webhooks

    expected = [
        (dev_keys.router, "/v1/dev-keys/self-provision"),
        (demo_keys.router, "/v1/demo/keys"),
        (webhooks.router, "/v1/webhooks/stripe"),
        (webhooks.router, "/v1/webhooks/stripe/identity"),
        (auth_router.router, "/v1/auth/token"),
        (auth_router.router, "/v1/auth/refresh"),
        (auth_router.router, "/v1/auth/revoke"),
    ]
    for router, path in expected:
        route = next(r for r in router.routes if getattr(r, "path", None) == path)
        names = {d.dependency.__name__ for d in route.dependencies}
        assert "bind_rls_admin_scope" in names, path
