"""Migration coverage for production schema drift."""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_crash_proof_preflights_database_before_running_migrations():
    recipe = (
        Path("Makefile")
        .read_text(encoding="utf-8")
        .split("prove-crash-recovery:", 1)[1]
        .split("\ndemo-trust-plane:", 1)[0]
    )

    preflight = "python -m tests.support.mcp_stress_preflight"
    assert preflight in recipe
    assert recipe.index(preflight) < recipe.index("alembic upgrade head")
    assert "MCP_STRESS_DB_ISOLATED=1" not in recipe
    assert "MCP_STRESS_EXPECTED_DATABASE_NAME=" not in recipe
    assert "STATE_BACKEND=postgres" not in recipe
    assert "ENVIRONMENT=test" not in recipe

    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    ci_recipe = workflow.split("  postgres_permit_concurrency:", 1)[1].split(
        "\n  secret_scan:",
        1,
    )[0]
    uv_install = "pip install pytest pytest-asyncio uv"
    crash_proof = "run: make prove-crash-recovery"
    concurrency_proof = "pytest tests/test_permit_postgres_concurrency.py"
    assert ci_recipe.index(uv_install) < ci_recipe.index(crash_proof)
    assert ci_recipe.index(crash_proof) < ci_recipe.index(concurrency_proof)
    assert "MCP_STRESS_EXPECTED_DATABASE_NAME: agent_middleware_permit_test" in (
        ci_recipe
    )
    assert "alembic upgrade head" not in ci_recipe


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
        "permit_call_reservations",
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

    reservation_columns = {
        col["name"] for col in inspector.get_columns("permit_call_reservations")
    }
    assert {
        "idempotency_record_id",
        "wallet_id",
        "permit_id",
        "tool",
        "request_hash",
        "credits_authorized",
        "state",
        "created_at",
        "updated_at",
        "execution_started_at",
        "released_at",
    } == reservation_columns
    reservation_primary_key = inspector.get_pk_constraint("permit_call_reservations")
    assert reservation_primary_key["constrained_columns"] == ["idempotency_record_id"]
    reservation_foreign_keys = inspector.get_foreign_keys("permit_call_reservations")
    assert {
        (tuple(foreign_key["constrained_columns"]), foreign_key["referred_table"])
        for foreign_key in reservation_foreign_keys
    } == {
        (("idempotency_record_id",), "idempotency_records"),
        (("wallet_id",), "wallets"),
        (("permit_id",), "permits"),
    }
    reservation_indexes = inspector.get_indexes("permit_call_reservations")
    assert any(
        index["name"] == "ix_permit_call_reservations_permit_tool_state"
        and index["column_names"] == ["permit_id", "tool", "state"]
        and not index["unique"]
        for index in reservation_indexes
    )
    reservation_checks = inspector.get_check_constraints("permit_call_reservations")
    state_check = next(
        check
        for check in reservation_checks
        if check["name"] == "ck_permit_call_reservations_state"
    )
    assert all(
        state in state_check["sqltext"]
        for state in ("reserved", "consumed", "released")
    )
    lifecycle_check = next(
        check
        for check in reservation_checks
        if check["name"] == "ck_permit_call_reservations_lifecycle"
    )
    assert "execution_started_at IS NOT NULL" in lifecycle_check["sqltext"]
    assert "released_at IS NOT NULL" in lifecycle_check["sqltext"]
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO permit_call_reservations (
                        idempotency_record_id,
                        wallet_id,
                        permit_id,
                        tool,
                        request_hash,
                        credits_authorized,
                        state
                    ) VALUES (
                        'idm-invalid-reservation-state',
                        'wallet-invalid-reservation-state',
                        'permit-invalid-reservation-state',
                        'invalid-reservation-tool',
                        :request_hash,
                        1,
                        'unknown'
                    )
                    """
                ),
                {"request_hash": "a" * 64},
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


def test_dispatch_claim_fence_preserves_legacy_rows_and_downgrades(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "dispatch-claim-fence.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", async_url)
    config = Config("alembic.ini")
    command.upgrade(config, "032_receipt_reason_code")
    asyncio.set_event_loop(asyncio.new_event_loop())

    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO mcp_dispatch_attempts (
                    attempt_id, idempotency_record_id, wallet_id, permit_id,
                    public_tool_id, upstream_tool_name, upstream_origin,
                    request_hash, ledger_entry_id, credits_authorized,
                    credits_charged, state, dispatched_at
                ) VALUES (
                    'dsp-legacy-claim', 'idm-legacy-claim', 'agt-legacy-claim',
                    'permit-legacy-claim', 'partner.legacy', 'partner_legacy',
                    'https://partner.example', :request_hash,
                    'led-legacy-claim', 1, 1, 'dispatched', CURRENT_TIMESTAMP
                )
                """
            ),
            {"request_hash": "a" * 64},
        )
        connection.execute(
            text(
                """
                INSERT INTO human_approvals (
                    approval_id, wallet_id, permit_id, tool, idempotency_key,
                    status, simulated, requested_at, expires_at, decided_at,
                    request_hash, reason
                ) VALUES (
                    'appr-expired-before-033', 'agt-expired-before-033',
                    'permit-expired-before-033', 'partner.expired',
                    'invoke-expired-before-033', 'approved', 0,
                    '1999-01-01 00:00:00', '2000-01-01 00:00:00',
                    '1999-01-02 00:00:00', :request_hash, 'old-approved'
                ), (
                    'appr-live-before-033', 'agt-live-before-033',
                    'permit-live-before-033', 'partner.live',
                    'invoke-live-before-033', 'approved', 0,
                    CURRENT_TIMESTAMP, '2999-01-01 00:00:00',
                    CURRENT_TIMESTAMP, :request_hash, 'old-approved'
                ), (
                    'appr-pending-before-033', 'agt-pending-before-033',
                    'permit-pending-before-033', 'partner.pending',
                    'invoke-pending-before-033', 'pending', 0,
                    CURRENT_TIMESTAMP, '2999-01-01 00:00:00',
                    NULL, :request_hash, 'pending_reason'
                ), (
                    'appr-rejected-before-033', 'agt-rejected-before-033',
                    'permit-rejected-before-033', 'partner.rejected',
                    'invoke-rejected-before-033', 'rejected', 0,
                    '1999-01-01 00:00:00', '2000-01-01 00:00:00',
                    '1999-01-02 00:00:00', :request_hash, 'rejected_reason'
                ), (
                    'appr-consumed-before-033', 'agt-consumed-before-033',
                    'permit-consumed-before-033', 'partner.consumed',
                    'invoke-consumed-before-033', 'consumed', 0,
                    '1999-01-01 00:00:00', '2000-01-01 00:00:00',
                    '1999-01-02 00:00:00', :request_hash, 'consumed_reason'
                )
                """
            ),
            {"request_hash": "c" * 64},
        )
    engine.dispose()

    command.upgrade(config, "033_mcp_dispatch_claim_fence")
    engine = create_engine(sync_url)
    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("mcp_dispatch_attempts")
    }
    assert columns["dispatch_claim_hash"]["nullable"] is True
    with engine.begin() as connection:
        # A pre-fence worker can still write its old column shape after the
        # migration. Semantic overlap is fenced by the new ``dispatch_claimed``
        # state, not by making this additive column mandatory.
        connection.execute(
            text(
                """
                INSERT INTO mcp_dispatch_attempts (
                    attempt_id, idempotency_record_id, wallet_id, permit_id,
                    public_tool_id, upstream_tool_name, upstream_origin,
                    request_hash, credits_authorized, credits_charged, state
                ) VALUES (
                    'dsp-old-worker', 'idm-old-worker', 'agt-old-worker',
                    'permit-old-worker', 'partner.old', 'partner_old',
                    'https://partner.example', :request_hash,
                    1, 0, 'prepared'
                )
                """
            ),
            {"request_hash": "b" * 64},
        )
        legacy_hash = connection.execute(
            text(
                """
                SELECT dispatch_claim_hash
                FROM mcp_dispatch_attempts
                WHERE attempt_id = 'dsp-legacy-claim'
                """
            )
        ).scalar_one()
        old_worker_hash = connection.execute(
            text(
                """
                SELECT dispatch_claim_hash
                FROM mcp_dispatch_attempts
                WHERE attempt_id = 'dsp-old-worker'
                """
            )
        ).scalar_one()
        approval_statuses = connection.execute(
            text(
                """
                SELECT approval_id, status, reason
                FROM human_approvals
                WHERE approval_id LIKE 'appr-%-before-033'
                ORDER BY approval_id
                """
            )
        ).all()
    assert legacy_hash is None
    assert old_worker_hash is None
    assert approval_statuses == [
        (
            "appr-consumed-before-033",
            "consumed",
            "consumed_reason",
        ),
        (
            "appr-expired-before-033",
            "expired",
            "approval_protocol_upgrade",
        ),
        (
            "appr-live-before-033",
            "expired",
            "approval_protocol_upgrade",
        ),
        (
            "appr-pending-before-033",
            "expired",
            "approval_protocol_upgrade",
        ),
        (
            "appr-rejected-before-033",
            "rejected",
            "rejected_reason",
        ),
    ]
    engine.dispose()

    command.downgrade(config, "032_receipt_reason_code")
    engine = create_engine(sync_url)
    assert "dispatch_claim_hash" not in {
        column["name"]
        for column in inspect(engine).get_columns("mcp_dispatch_attempts")
    }
    with engine.begin() as connection:
        downgraded_approval_statuses = connection.execute(
            text(
                """
                SELECT approval_id, status, reason
                FROM human_approvals
                WHERE approval_id LIKE 'appr-%-before-033'
                ORDER BY approval_id
                """
            )
        ).all()
    assert downgraded_approval_statuses == approval_statuses
    engine.dispose()


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
