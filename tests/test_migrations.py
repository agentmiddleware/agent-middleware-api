"""Migration coverage for production schema drift."""

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_alembic_upgrade_creates_auth_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "migration.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", async_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")
    asyncio.set_event_loop(asyncio.new_event_loop())

    engine = create_engine(sync_url)
    inspector = inspect(engine)

    tables = set(inspector.get_table_names())
    assert {
        "api_keys",
        "key_rotation_logs",
        "kyc_verifications",
        "service_registry",
        "signing_keys",
        "permits",
        "receipts",
        "idempotency_records",
        "mcp_dispatch_attempts",
        "human_approvals",
    } <= tables

    permit_columns = {col["name"] for col in inspector.get_columns("permits")}
    assert "requires_human_approval" in permit_columns
    receipt_columns = {col["name"] for col in inspector.get_columns("receipts")}
    assert "approval_id" in receipt_columns
    assert {"idempotency_record_id", "dispatch_attempt_id"} <= receipt_columns

    ledger_columns = {col["name"] for col in inspector.get_columns("ledger_entries")}
    assert "operation_key" in ledger_columns

    idempotency_columns = {
        col["name"] for col in inspector.get_columns("idempotency_records")
    }
    assert "operation_kind" in idempotency_columns

    dispatch_columns = {
        col["name"] for col in inspector.get_columns("mcp_dispatch_attempts")
    }
    assert {
        "idempotency_record_id",
        "approval_id",
        "ledger_entry_id",
        "state",
        "dispatch_claim_hash",
        "result_json",
        "result_size_bytes",
        "response_hash",
    } <= dispatch_columns
    dispatch_foreign_keys = inspector.get_foreign_keys("mcp_dispatch_attempts")
    assert any(
        foreign_key["constrained_columns"] == ["approval_id"]
        and foreign_key["referred_table"] == "human_approvals"
        for foreign_key in dispatch_foreign_keys
    )
    dispatch_indexes = inspector.get_indexes("mcp_dispatch_attempts")
    assert any(
        index["name"] == "ix_mcp_dispatch_attempts_approval_id"
        and index["column_names"] == ["approval_id"]
        for index in dispatch_indexes
    )

    wallet_columns = {col["name"] for col in inspector.get_columns("wallets")}
    assert {
        "child_agent_id",
        "max_spend",
        "task_description",
        "ttl_seconds",
        "kyc_status",
        "kyc_verified_at",
    } <= wallet_columns
    # Revision 025 scrubs these compatibility columns but retains their shape
    # for one rolling release so the previous worker can drain safely.
    assert "owner_key" in wallet_columns

    service_columns = {col["name"] for col in inspector.get_columns("service_registry")}
    assert "owner_key" in service_columns

    audit_columns = {
        col["name"] for col in inspector.get_columns("control_plane_audit_events")
    }
    assert {
        "payload_hash",
        "previous_hash",
        "chain_hash",
        "signature",
        "signature_key_id",
    } <= audit_columns

    engine.dispose()
    os.remove(db_path)


def test_governed_persistence_migration_backfills_only_unambiguous_receipts(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "governed-persistence-migration.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", async_url)
    config = Config("alembic.ini")
    command.upgrade(config, "025_remove_plaintext_owner_keys")

    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO wallets (
                    wallet_id, wallet_type, balance, lifetime_credits,
                    lifetime_debits, daily_spent, auto_refill, status
                ) VALUES ('agt-migration', 'agent', 100, 100, 0, 0, 0, 'active')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO signing_keys (
                    key_id, alg, public_key_b64, status
                ) VALUES ('sig-migration', 'Ed25519', 'public', 'active')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO permits (
                    permit_id, issuer_wallet_id, subject_wallet_id,
                    scopes_json, allowed_tools_json, max_credits,
                    spent_credits, expires_at, nonce, status, signature, key_id
                ) VALUES (
                    'permit-migration', 'agt-migration', 'agt-migration',
                    '[]', '[]', 10, 0, '2030-01-01 00:00:00',
                    'nonce-migration', 'active', 'signature', 'sig-migration'
                )
                """
            )
        )
        for receipt_id in (
            "receipt-unambiguous",
            "receipt-ambiguous",
            "receipt-mismatched",
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO receipts (
                        receipt_id, permit_id, wallet_id, tool, request_hash,
                        credits_authorized, credits_charged, outcome,
                        signature, signature_key_id
                    ) VALUES (
                        :receipt_id, 'permit-migration', 'agt-migration',
                        'partner-tool', :request_hash, 1, 0, 'denied',
                        'signature', 'sig-migration'
                    )
                    """
                ),
                {"receipt_id": receipt_id, "request_hash": "a" * 64},
            )
        for record_id, idem_key, receipt_id in (
            ("idem-unambiguous", "key-one", "receipt-unambiguous"),
            ("idem-ambiguous-a", "key-two", "receipt-ambiguous"),
            ("idem-ambiguous-b", "key-three", "receipt-ambiguous"),
            ("idem-mismatched", "key-four", "receipt-mismatched"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO idempotency_records (
                        record_id, wallet_id, endpoint, idempotency_key,
                        request_hash, response_reference, status_code
                    ) VALUES (
                        :record_id, 'agt-migration', '/mcp/messages', :idem_key,
                        :request_hash, :receipt_id, 200
                    )
                    """
                ),
                {
                    "record_id": record_id,
                    "idem_key": idem_key,
                    "request_hash": (
                        "b" * 64 if record_id == "idem-mismatched" else "a" * 64
                    ),
                    "receipt_id": receipt_id,
                },
            )
    engine.dispose()

    command.upgrade(config, "head")
    asyncio.set_event_loop(asyncio.new_event_loop())

    engine = create_engine(sync_url)
    with engine.connect() as connection:
        rows = dict(
            connection.execute(
                text(
                    """
                    SELECT receipt_id, idempotency_record_id
                    FROM receipts
                    ORDER BY receipt_id
                    """
                )
            ).all()
        )
    assert rows["receipt-unambiguous"] == "idem-unambiguous"
    assert rows["receipt-ambiguous"] is None
    assert rows["receipt-mismatched"] is None
    engine.dispose()
    os.remove(db_path)


def test_governed_mcp_identity_migration_enforces_cross_endpoint_uniqueness(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "governed-mcp-identity-migration.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", async_url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    asyncio.set_event_loop(asyncio.new_event_loop())

    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO wallets (
                    wallet_id, wallet_type, balance, lifetime_credits,
                    lifetime_debits, daily_spent, auto_refill, status
                ) VALUES (
                    'agt-identity-migration', 'agent', 100, 100, 0, 0, 0, 'active'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO idempotency_records (
                    record_id, wallet_id, endpoint, idempotency_key,
                    request_hash, status_code
                ) VALUES (
                    'idm-identity-legacy', 'agt-identity-migration',
                    '/mcp/messages', 'shared-identity-key', :request_hash, 200
                )
                """
            ),
            {"request_hash": "a" * 64},
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO idempotency_records (
                        record_id, wallet_id, endpoint, idempotency_key,
                        request_hash, status_code
                    ) VALUES (
                        'idm-identity-canonical', 'agt-identity-migration',
                        '/mcp/invoke', 'shared-identity-key', :request_hash, 200
                    )
                    """
                ),
                {"request_hash": "b" * 64},
            )
    engine.dispose()
    os.remove(db_path)


def test_governed_mcp_identity_migration_refuses_ambiguous_history(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "governed-mcp-identity-conflict.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", async_url)
    config = Config("alembic.ini")
    command.upgrade(config, "026_governed_mcp_persistence")

    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO wallets (
                    wallet_id, wallet_type, balance, lifetime_credits,
                    lifetime_debits, daily_spent, auto_refill, status
                ) VALUES (
                    'agt-identity-conflict', 'agent', 100, 100, 0, 0, 0, 'active'
                )
                """
            )
        )
        for record_id, endpoint in (
            ("idm-identity-conflict-legacy", "/mcp/messages"),
            ("idm-identity-conflict-current", "/mcp/invoke"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO idempotency_records (
                        record_id, wallet_id, endpoint, idempotency_key,
                        request_hash, status_code
                    ) VALUES (
                        :record_id, 'agt-identity-conflict', :endpoint,
                        'ambiguous-history-key', :request_hash, 200
                    )
                    """
                ),
                {
                    "record_id": record_id,
                    "endpoint": endpoint,
                    "request_hash": "a" * 64,
                },
            )
    engine.dispose()

    with pytest.raises(
        RuntimeError,
        match=r"1 ambiguous wallet/key group\(s\)",
    ) as exc_info:
        command.upgrade(config, "head")
    assert "agt-identity-conflict" not in str(exc_info.value)
    assert "ambiguous-history-key" not in str(exc_info.value)
    asyncio.set_event_loop(asyncio.new_event_loop())

    engine = create_engine(sync_url)
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        installed_index = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM sqlite_master
                WHERE type = 'index'
                  AND name = 'uq_idempotency_governed_mcp_identity'
                """
            )
        ).scalar_one()
    assert revision == "026_governed_mcp_persistence"
    assert installed_index == 0
    engine.dispose()
    os.remove(db_path)


def test_owner_key_migration_scrubs_values_but_retains_rolling_compatible_columns(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "owner-key-migration.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"
    sentinel = "b2a_live_secret_that_must_not_survive"

    monkeypatch.setenv("DATABASE_URL", async_url)
    config = Config("alembic.ini")
    command.upgrade(config, "021_ledger_stripe_event_id")

    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO wallets (
                    wallet_id,
                    wallet_type,
                    owner_key,
                    balance,
                    lifetime_credits,
                    lifetime_debits,
                    daily_spent,
                    auto_refill,
                    status
                ) VALUES (
                    :wallet_id,
                    'sponsor',
                    :owner_key,
                    0,
                    0,
                    0,
                    0,
                    0,
                    'active'
                )
                """
            ),
            {"wallet_id": "spn-owner-key-migration", "owner_key": sentinel},
        )
        connection.execute(
            text(
                """
                INSERT INTO service_registry (
                    service_id,
                    name,
                    owner_wallet_id,
                    owner_key,
                    category,
                    credits_per_unit
                ) VALUES (
                    'svc-owner-key-migration',
                    'Legacy service',
                    :wallet_id,
                    :owner_key,
                    'agent_comms',
                    1
                )
                """
            ),
            {"wallet_id": "spn-owner-key-migration", "owner_key": sentinel},
        )
    engine.dispose()

    command.upgrade(config, "head")
    asyncio.set_event_loop(asyncio.new_event_loop())

    engine = create_engine(sync_url)
    inspector = inspect(engine)
    assert "owner_key" in {
        column["name"] for column in inspector.get_columns("wallets")
    }
    assert "owner_key" in {
        column["name"] for column in inspector.get_columns("service_registry")
    }
    with engine.connect() as connection:
        wallet = connection.execute(
            text(
                """
                SELECT wallet_id, owner_key
                FROM wallets
                WHERE wallet_id = :wallet_id
                """
            ),
            {"wallet_id": "spn-owner-key-migration"},
        ).one()
        service = connection.execute(
            text(
                """
                SELECT owner_wallet_id, owner_key
                FROM service_registry
                WHERE service_id = 'svc-owner-key-migration'
                """
            )
        ).one()
        assert wallet == (
            "spn-owner-key-migration",
            "",
        )
        assert service == (
            "spn-owner-key-migration",
            "",
        )
        assert sentinel not in repr((wallet, service))
    engine.dispose()


def test_refresh_token_binding_migration_revokes_unbound_rows(tmp_path, monkeypatch):
    """Historical refresh tokens cannot be safely assigned to a live API key."""
    db_path = tmp_path / "refresh-token-binding-migration.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", async_url)
    config = Config("alembic.ini")
    # Reproduce the real upgrade path: revision 025 is already published, so
    # the data fix must live in a later migration.
    command.upgrade(config, "025_refresh_token_key_binding")

    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO wallets (
                    wallet_id, wallet_type, owner_key, balance, lifetime_credits,
                    lifetime_debits, daily_spent, auto_refill, status
                ) VALUES (
                    'agt-legacy-refresh', 'agent', '', 0, 0, 0, 0, 0, 'active'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO refresh_tokens (
                    jti, wallet_id, key_id, revoked, created_at, expires_at
                ) VALUES (
                    'legacy-refresh-jti', 'agt-legacy-refresh', NULL, 0,
                    '2026-08-01 00:00:00', '2026-08-08 00:00:00'
                ), (
                    'bound-refresh-jti', 'agt-legacy-refresh', 'key-live', 0,
                    '2026-08-01 00:00:00', '2026-08-08 00:00:00'
                )
                """
            )
        )
    engine.dispose()

    command.upgrade(config, "head")
    asyncio.set_event_loop(asyncio.new_event_loop())

    engine = create_engine(sync_url)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT jti, key_id, revoked
                FROM refresh_tokens
                ORDER BY jti
                """
            )
        ).all()
    assert rows == [
        ("bound-refresh-jti", "key-live", 0),
        ("legacy-refresh-jti", None, 1),
    ]
    engine.dispose()


def test_024_repairs_sqlite_boolean_backfill(tmp_path, monkeypatch):
    """Verify 024 repairs 023's SQLite text-boolean backfill."""
    from sqlalchemy import Boolean, Column, MetaData, String, Table, select

    db_path = tmp_path / "repair.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", async_url)
    config = Config("alembic.ini")

    command.upgrade(config, "023_human_approval_gate")
    asyncio.set_event_loop(asyncio.new_event_loop())
    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO permits (permit_id, issuer_wallet_id, "
                "subject_wallet_id, scopes_json, allowed_tools_json, max_credits, "
                "expires_at, nonce, status, requires_human_approval, signature, "
                "key_id, issued_at) VALUES ('p-legacy', 'w', 'w', '[]', '[]', 10, "
                "'2999-01-01 00:00:00', 'n', 'active', 'false', 'sig', 'k', "
                "'2026-01-01 00:00:00')"
            )
        )

    metadata = MetaData()
    permits = Table(
        "permits",
        metadata,
        Column("permit_id", String, primary_key=True),
        Column("requires_human_approval", Boolean),
    )
    with engine.connect() as connection:
        buggy = connection.execute(
            select(permits.c.requires_human_approval).where(
                permits.c.permit_id == "p-legacy"
            )
        ).scalar_one()
    assert buggy is True, "precondition: 023 leaves a truthy text value on SQLite"

    command.upgrade(config, "024_human_approval_hardening")
    with engine.connect() as connection:
        fixed = connection.execute(
            select(permits.c.requires_human_approval).where(
                permits.c.permit_id == "p-legacy"
            )
        ).scalar_one()
    assert fixed is False, "024 must normalize the backfilled text 'false' to False"

    approval_columns = {
        column["name"] for column in inspect(engine).get_columns("human_approvals")
    }
    assert "request_hash" in approval_columns
    engine.dispose()
