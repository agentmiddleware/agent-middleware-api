"""Additive authority migration must never downgrade accepted bindings away."""

import os
import sqlite3
import subprocess
import sys

import pytest

FIELDS = (
    "action_contract_version",
    "action_payload_hash",
    "action_schema_id",
    "action_schema_version",
    "action_public_tool_id",
    "action_upstream_binding_hash",
)


def migrate(url, revision, direction="upgrade"):
    return subprocess.run(
        [sys.executable, "-m", "alembic", direction, revision],
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("authority", [None, "permits", "receipts", "partial", "owner"])
def test_action_migration_retains_legacy_and_blocks_authority_loss(tmp_path, authority):
    path = tmp_path / "migration.sqlite"
    url = f"sqlite+aiosqlite:///{path}"
    result = migrate(url, "040_permit_repeat_window")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO wallets (wallet_id, wallet_type, balance, lifetime_credits, lifetime_debits, daily_spent, auto_refill, status) VALUES ('w','agent',100,100,0,0,0,'active')"
        )
        db.execute(
            "INSERT INTO signing_keys (key_id,alg,public_key_b64,status) VALUES ('k','Ed25519','public','active')"
        )
        db.execute(
            "INSERT INTO permits (permit_id,issuer_wallet_id,subject_wallet_id,scopes_json,allowed_tools_json,max_credits,spent_credits,expires_at,nonce,status,signature,key_id,issued_at) VALUES ('p','w','w','[]','[]',10,0,'2030-01-01','n','active','literal-old-signature','k','2026-01-01')"
        )
        db.execute(
            "INSERT INTO receipts (receipt_id,permit_id,wallet_id,tool,request_hash,credits_authorized,credits_charged,outcome,created_at,signature,signature_key_id) VALUES ('legacy','p','w','tool','hash',0,0,'success','2026-01-01','literal-old-receipt','k')"
        )
        receipt_before = db.execute("SELECT * FROM receipts").fetchone()
        before = db.execute("SELECT * FROM permits").fetchone()
    result = migrate(url, "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM permits").fetchone() == (
            *before,
            *([None] * 6),
        )
        assert db.execute(
            "SELECT * FROM receipts WHERE receipt_id='legacy'"
        ).fetchone() == (*receipt_before, *([None] * 6))
        for table in ("permits", "receipts"):
            cols = {r[1]: r for r in db.execute(f"PRAGMA table_info({table})")}
            assert all(name in cols and cols[name][3] == 0 for name in FIELDS)
        if authority in ("permits", "partial"):
            # Even partial/unknown-version data cannot be silently erased.
            column = (
                "action_contract_version"
                if authority == "permits"
                else "action_payload_hash"
            )
            db.execute(
                f"UPDATE permits SET {column} = ?",
                (99 if authority == "permits" else "digest",),
            )
        elif authority == "receipts":
            db.execute(
                "INSERT INTO receipts (receipt_id,permit_id,wallet_id,tool,request_hash,credits_authorized,credits_charged,outcome,created_at,signature,signature_key_id,action_contract_version) VALUES ('r','p','w','tool','hash',0,0,'success','2026-01-01','literal-receipt','k',1)"
            )
        elif authority == "owner":
            db.execute(
                "INSERT INTO idempotency_records (record_id,wallet_id,endpoint,idempotency_key,request_hash,created_at) VALUES ('o','w','/mcp/action/v1','act1-key','hash','2026-01-01')"
            )
    result = migrate(url, "040_permit_repeat_window", "downgrade")
    if authority is None:
        assert result.returncode == 0, result.stderr
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT * FROM permits").fetchone() == before
            assert db.execute("SELECT * FROM receipts").fetchone() == receipt_before
    else:
        assert result.returncode != 0, "downgrade discarded durable action authority"
        assert "action_authority_retained" in result.stderr
        with sqlite3.connect(path) as db:
            assert (
                db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                == "041_permit_action_binding"
            )
            assert all(
                name in {r[1] for r in db.execute("PRAGMA table_info(receipts)")}
                for name in FIELDS
            )


@pytest.mark.skipif(
    not os.environ.get("ACTION_MIGRATION_DATABASE_URL"),
    reason="requires fresh disposable local action migration DB",
)
def test_postgres_legacy_roundtrip_and_fail_closed_downgrade():
    import asyncio
    import asyncpg

    url = os.environ["ACTION_MIGRATION_DATABASE_URL"]
    assert url.startswith("postgresql+asyncpg://sellers@127.0.0.1:55439/amw_action_")
    assert os.environ.get("ENVIRONMENT") == "test"

    async def query(sql):
        connection = await asyncpg.connect(
            url.replace("postgresql+asyncpg", "postgresql")
        )
        try:
            return [dict(r) for r in await connection.fetch(sql)]
        finally:
            await connection.close()

    def sql(statement):
        return asyncio.run(query(statement))

    assert sql("SELECT tablename FROM pg_tables WHERE schemaname='public'") == [], (
        "refuse reused migration DB"
    )
    result = migrate(url, "040_permit_repeat_window")
    assert result.returncode == 0, result.stderr
    sql(
        "INSERT INTO wallets (wallet_id,wallet_type,balance,lifetime_credits,lifetime_debits,daily_spent,auto_refill,status) VALUES ('w','agent',100,100,0,0,false,'active') RETURNING wallet_id"
    )
    sql(
        "INSERT INTO signing_keys (key_id,alg,public_key_b64,status) VALUES ('k','Ed25519','public','active') RETURNING key_id"
    )
    sql(
        "INSERT INTO permits (permit_id,issuer_wallet_id,subject_wallet_id,scopes_json,allowed_tools_json,max_credits,spent_credits,expires_at,nonce,status,signature,key_id,issued_at) VALUES ('p','w','w','[]','[]',10,0,'2030-01-01','n','active','literal-old-signature','k','2026-01-01') RETURNING permit_id"
    )
    sql(
        "INSERT INTO receipts (receipt_id,permit_id,wallet_id,tool,request_hash,credits_authorized,credits_charged,outcome,created_at,signature,signature_key_id) VALUES ('r','p','w','tool','hash',0,0,'success','2026-01-01','literal-old-receipt','k') RETURNING receipt_id"
    )
    before = {t: sql(f"SELECT * FROM {t}")[0] for t in ("permits", "receipts")}
    result = migrate(url, "head")
    assert result.returncode == 0, result.stderr
    for table, old in before.items():
        assert sql(f"SELECT * FROM {table}")[0] == {**old, **dict.fromkeys(FIELDS)}
    result = migrate(url, "040_permit_repeat_window", "downgrade")
    assert result.returncode == 0, result.stderr
    assert {t: sql(f"SELECT * FROM {t}")[0] for t in before} == before
    result = migrate(url, "head")
    assert result.returncode == 0, result.stderr
    sql("UPDATE permits SET action_contract_version=1 RETURNING permit_id")
    result = migrate(url, "040_permit_repeat_window", "downgrade")
    assert result.returncode != 0 and "action_authority_retained" in result.stderr
    assert (
        sql("SELECT version_num FROM alembic_version")[0]["version_num"]
        == "041_permit_action_binding"
    )
    assert (
        sql("SELECT action_contract_version FROM permits")[0]["action_contract_version"]
        == 1
    )
    print(
        "PostgreSQL: legacy permit/receipt bytes retained through roundtrip; accepted authority downgrade blocked"
    )
