"""Downgrade roundtrip coverage for the governed-loop migrations (026-039).

The upgrade direction is covered by test_migrations.py and the focused
026/027/037/038/040/041/042 tests. What was untested is the way back down:
every migration in the money, auth and integrity path must remove exactly
what it added while leaving the rows it did not own untouched, and a
re-upgrade must succeed. Each test below upgrades to N-1 on a throwaway
SQLite database, seeds representative rows, upgrades to N, downgrades to
N-1, then upgrades to N again.
"""

import asyncio

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def _fresh_loop():
    asyncio.set_event_loop(asyncio.new_event_loop())


def _config(db_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    return Config("alembic.ini")


def _engine(db_path):
    return create_engine(f"sqlite:///{db_path}")


def _columns(db_path, table):
    engine = _engine(db_path)
    try:
        return {col["name"]: col for col in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _tables(db_path):
    engine = _engine(db_path)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _indexes(db_path, table):
    engine = _engine(db_path)
    try:
        return {idx["name"]: idx for idx in inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def _exec(db_path, statement, params=None):
    engine = _engine(db_path)
    try:
        with engine.begin() as connection:
            connection.execute(text(statement), params or {})
    finally:
        engine.dispose()


def _query(db_path, statement, params=None):
    engine = _engine(db_path)
    try:
        with engine.connect() as connection:
            return connection.execute(text(statement), params or {}).all()
    finally:
        engine.dispose()


def _seed_wallet(db_path, wallet_id="agt-downgrade"):
    _exec(
        db_path,
        """
        INSERT INTO wallets (
            wallet_id, wallet_type, balance, lifetime_credits,
            lifetime_debits, daily_spent, auto_refill, status
        ) VALUES (:wallet_id, 'agent', 100, 100, 0, 0, 0, 'active')
        """,
        {"wallet_id": wallet_id},
    )
    # Several tests seed two wallets; the shared signing key must not fail
    # the second insert.
    _exec(
        db_path,
        """
        INSERT OR IGNORE INTO signing_keys (key_id, alg, public_key_b64, status)
        VALUES ('sig-downgrade', 'Ed25519', 'public', 'active')
        """,
    )


def _seed_permit(db_path, permit_id="permit-downgrade"):
    _exec(
        db_path,
        """
        INSERT INTO permits (
            permit_id, issuer_wallet_id, subject_wallet_id,
            scopes_json, allowed_tools_json, max_credits,
            spent_credits, expires_at, nonce, status, signature, key_id,
            issued_at
        ) VALUES (
            :permit_id, 'agt-downgrade', 'agt-downgrade',
            '[]', '[]', 10, 0, '2030-01-01 00:00:00',
            :nonce, 'active', 'signature', 'sig-downgrade',
            '2026-01-01 00:00:00'
        )
        """,
        {"permit_id": permit_id, "nonce": f"nonce-{permit_id}"},
    )


def test_alembic_history_is_a_single_linear_chain():
    """Every revision must sit on one line from base to the 042 head.

    A branch or a second head would leave production boot (which refuses to
    start off-head in either direction) with no unique target, so the chain
    shape itself is a money-safety property.
    """
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    revisions = list(script.walk_revisions())
    # 001-024, two 025s (key binding, then owner-key scrub), 026-042.
    assert len(revisions) == 43
    assert list(script.get_heads()) == ["042_permit_action_binding"]
    assert script.get_base() is not None
    by_revision = {rev.revision: rev for rev in revisions}
    assert len(by_revision) == len(revisions)
    for rev in revisions:
        assert not rev.is_branch_point
        assert not rev.is_merge_point
    # Walk down_revisions from head and confirm every revision is visited once.
    # (Script.down_revision is a plain string on this linear chain; merges
    # would surface as a tuple and fail the merge-point assertion above.)
    seen = set()
    current = "042_permit_action_binding"
    while current is not None:
        assert current not in seen
        seen.add(current)
        downs = by_revision[current].down_revision
        if downs is None:
            current = None
        elif isinstance(downs, str):
            current = downs
        else:
            (current,) = downs
    assert seen == set(by_revision)


def test_026_persistence_downgrade_keeps_base_rows_and_backfill_is_unique(
    tmp_path, monkeypatch
):
    """026 adds the governed persistence tables; its downgrade removes them all.

    Also pins that two ledger rows may not share one (wallet, operation_key):
    without that constraint a retried charge could debit twice.
    """
    db_path = tmp_path / "m026.db"
    config = _config(db_path, monkeypatch)
    command.upgrade(config, "025_remove_plaintext_owner_keys")
    _fresh_loop()
    _seed_wallet(db_path)
    _seed_permit(db_path)
    _exec(
        db_path,
        """
        INSERT INTO receipts (
            receipt_id, permit_id, wallet_id, tool, request_hash,
            credits_authorized, credits_charged, outcome,
            signature, signature_key_id
        ) VALUES (
            'receipt-026', 'permit-downgrade', 'agt-downgrade',
            'partner-tool', :request_hash, 1, 0, 'denied',
            'signature', 'sig-downgrade'
        )
        """,
        {"request_hash": "a" * 64},
    )
    _exec(
        db_path,
        """
        INSERT INTO idempotency_records (
            record_id, wallet_id, endpoint, idempotency_key,
            request_hash, response_reference, status_code
        ) VALUES (
            'idem-026', 'agt-downgrade', '/mcp/invoke', 'key-026',
            :request_hash, 'receipt-026', 200
        )
        """,
        {"request_hash": "a" * 64},
    )

    command.upgrade(config, "026_governed_mcp_persistence")
    _fresh_loop()
    assert "mcp_dispatch_attempts" in _tables(db_path)
    assert "operation_key" in _columns(db_path, "ledger_entries")
    assert "idempotency_record_id" in _columns(db_path, "receipts")
    assert "dispatch_attempt_id" in _columns(db_path, "receipts")
    linked = _query(
        db_path,
        "SELECT idempotency_record_id FROM receipts WHERE receipt_id = 'receipt-026'",
    )
    assert linked == [("idem-026",)]
    engine = _engine(db_path)
    try:
        uniques = inspect(engine).get_unique_constraints("ledger_entries")
    finally:
        engine.dispose()
    assert any(
        set(u["column_names"]) == {"wallet_id", "operation_key"} for u in uniques
    )

    command.downgrade(config, "025_remove_plaintext_owner_keys")
    _fresh_loop()
    assert "mcp_dispatch_attempts" not in _tables(db_path)
    assert "operation_key" not in _columns(db_path, "ledger_entries")
    assert "operation_kind" not in _columns(db_path, "idempotency_records")
    assert "idempotency_record_id" not in _columns(db_path, "receipts")
    assert "dispatch_attempt_id" not in _columns(db_path, "receipts")
    assert _query(db_path, "SELECT receipt_id FROM receipts") == [("receipt-026",)]
    assert _query(db_path, "SELECT record_id FROM idempotency_records") == [
        ("idem-026",)
    ]

    command.upgrade(config, "026_governed_mcp_persistence")
    _fresh_loop()
    assert "mcp_dispatch_attempts" in _tables(db_path)


def _has_sqlite_index(db_path, name):
    # The 027 identity index is an expression index; sqlite_master is the
    # exact source instead of the inspector's column decoding.
    return _query(
        db_path,
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = :name",
        {"name": name},
    ) == [(1,)]


def test_027_identity_downgrade_drops_index_and_keeps_canonical_rows(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "m027.db"
    config = _config(db_path, monkeypatch)
    command.upgrade(config, "027_governed_mcp_identity")
    _fresh_loop()
    assert _has_sqlite_index(db_path, "uq_idempotency_governed_mcp_identity")
    _seed_wallet(db_path)
    _exec(
        db_path,
        """
        INSERT INTO idempotency_records (
            record_id, wallet_id, endpoint, idempotency_key,
            request_hash, status_code
        ) VALUES (
            'idm-027', 'agt-downgrade', '/mcp/invoke', 'key-027', :request_hash, 200
        )
        """,
        {"request_hash": "a" * 64},
    )

    command.downgrade(config, "026_governed_mcp_persistence")
    _fresh_loop()
    assert not _has_sqlite_index(db_path, "uq_idempotency_governed_mcp_identity")
    assert _query(db_path, "SELECT record_id FROM idempotency_records") == [
        ("idm-027",)
    ]

    command.upgrade(config, "027_governed_mcp_identity")
    _fresh_loop()
    assert _has_sqlite_index(db_path, "uq_idempotency_governed_mcp_identity")


def test_028_revocation_survives_its_noop_downgrade(tmp_path, monkeypatch):
    """028's downgrade is deliberately a no-op: revoked stays revoked.

    A downgrade that resurrected historical unbound refresh tokens would hand
    derived authority back to tokens no live key can vouch for.
    """
    db_path = tmp_path / "m028.db"
    config = _config(db_path, monkeypatch)
    command.upgrade(config, "027_governed_mcp_identity")
    _fresh_loop()
    _seed_wallet(db_path)
    _exec(
        db_path,
        """
        INSERT INTO refresh_tokens (
            jti, wallet_id, key_id, revoked, created_at, expires_at
        ) VALUES (
            'legacy-028', 'agt-downgrade', NULL, 0,
            '2026-08-01 00:00:00', '2026-08-08 00:00:00'
        ), (
            'bound-028', 'agt-downgrade', 'key-live', 0,
            '2026-08-01 00:00:00', '2026-08-08 00:00:00'
        )
        """,
    )

    command.upgrade(config, "028_revoke_unbound_refresh")
    _fresh_loop()
    command.downgrade(config, "027_governed_mcp_identity")
    _fresh_loop()
    rows = _query(db_path, "SELECT jti, revoked FROM refresh_tokens ORDER BY jti")
    assert rows == [("bound-028", 0), ("legacy-028", 1)]

    command.upgrade(config, "028_revoke_unbound_refresh")
    _fresh_loop()
    assert _query(
        db_path, "SELECT revoked FROM refresh_tokens WHERE jti = 'legacy-028'"
    ) == [(1,)]


def test_029_v2_constraints_roundtrip_preserves_permit_and_receipt(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "m029.db"
    config = _config(db_path, monkeypatch)
    command.upgrade(config, "028_revoke_unbound_refresh")
    _fresh_loop()
    _seed_wallet(db_path)
    _seed_permit(db_path)
    _exec(
        db_path,
        """
        INSERT INTO receipts (
            receipt_id, permit_id, wallet_id, tool, request_hash,
            credits_authorized, credits_charged, outcome,
            signature, signature_key_id
        ) VALUES (
            'receipt-029', 'permit-downgrade', 'agt-downgrade',
            'partner-tool', :request_hash, 1, 1, 'success',
            'signature', 'sig-downgrade'
        )
        """,
        {"request_hash": "a" * 64},
    )

    command.upgrade(config, "029_add_permit_v2_constraints")
    _fresh_loop()
    permit_cols = _columns(db_path, "permits")
    assert {
        "max_calls_per_tool_json",
        "aggregate_value_cap",
        "forbidden_fields_json",
        "recipient_domain",
    } <= set(permit_cols)
    assert "constraints_evaluated_json" in _columns(db_path, "receipts")
    _exec(
        db_path,
        "UPDATE permits SET recipient_domain = 'example.com' "
        "WHERE permit_id = 'permit-downgrade'",
    )

    command.downgrade(config, "028_revoke_unbound_refresh")
    _fresh_loop()
    assert "recipient_domain" not in _columns(db_path, "permits")
    assert "constraints_evaluated_json" not in _columns(db_path, "receipts")
    assert _query(
        db_path, "SELECT max_credits FROM permits WHERE permit_id = 'permit-downgrade'"
    ) == [(10,)]
    assert _query(db_path, "SELECT receipt_id FROM receipts") == [("receipt-029",)]

    command.upgrade(config, "029_add_permit_v2_constraints")
    _fresh_loop()
    assert _query(
        db_path,
        "SELECT recipient_domain FROM permits WHERE permit_id = 'permit-downgrade'",
    ) == [(None,)]


def test_030_permit_requests_idempotency_unique_and_downgrade(tmp_path, monkeypatch):
    """A retried permit request must collide on one row, not mint two permits."""
    db_path = tmp_path / "m030.db"
    config = _config(db_path, monkeypatch)
    command.upgrade(config, "030_permit_requests")
    _fresh_loop()
    _seed_wallet(db_path, "spn-030")
    _seed_wallet(db_path, "agt-030")
    row = (
        "'req-030', 'spn-030', 'agt-030', 'mint-key-030', '[]', '[]', 10,"
        " '2030-01-01 00:00:00', 'need tool access', :request_hash,"
        " 'reserved-030', '2026-08-01 00:00:00', '2026-08-02 00:00:00'"
    )
    _exec(
        db_path,
        f"""
        INSERT INTO permit_requests (
            request_id, issuer_wallet_id, subject_wallet_id, idempotency_key,
            scopes_json, allowed_tools_json, max_credits, permit_expires_at,
            justification, request_hash, reserved_permit_id, requested_at,
            expires_at
        ) VALUES ({row})
        """,
        {"request_hash": "a" * 64},
    )
    with pytest.raises(IntegrityError):
        _exec(
            db_path,
            """
            INSERT INTO permit_requests (
                request_id, issuer_wallet_id, subject_wallet_id, idempotency_key,
                scopes_json, allowed_tools_json, max_credits, permit_expires_at,
                justification, request_hash, reserved_permit_id, requested_at,
                expires_at
            ) VALUES ('req-030-retry', 'spn-030', 'agt-030', 'mint-key-030',
                      '[]', '[]', 10, '2030-01-01 00:00:00', 'need tool access',
                      :request_hash, 'reserved-030-retry',
                      '2026-08-01 00:00:00', '2026-08-02 00:00:00')
            """,
            {"request_hash": "a" * 64},
        )

    command.downgrade(config, "029_add_permit_v2_constraints")
    _fresh_loop()
    assert "permit_requests" not in _tables(db_path)
    assert _query(db_path, "SELECT wallet_id FROM wallets ORDER BY wallet_id") == [
        ("agt-030",),
        ("spn-030",),
    ]

    command.upgrade(config, "030_permit_requests")
    _fresh_loop()
    assert "permit_requests" in _tables(db_path)


def test_031_quotes_roundtrip(tmp_path, monkeypatch):
    db_path = tmp_path / "m031.db"
    config = _config(db_path, monkeypatch)
    command.upgrade(config, "031_quotes")
    _fresh_loop()
    _seed_wallet(db_path)
    _exec(
        db_path,
        """
        INSERT INTO quotes (
            quote_id, wallet_id, tool, quoted_credits, category,
            issued_at, expires_at, signature, key_id
        ) VALUES (
            'quote-031', 'agt-downgrade', 'partner-tool', 5, 'agent_comms',
            '2026-08-01 00:00:00', '2026-08-02 00:00:00', 'sig', 'sig-downgrade'
        )
        """,
    )
    assert _query(
        db_path, "SELECT status FROM quotes WHERE quote_id = 'quote-031'"
    ) == [("active",)]
    assert {
        "ix_quotes_wallet_id",
        "ix_quotes_tool",
        "ix_quotes_status",
        "ix_quotes_expires_at",
        "ix_quotes_key_id",
    } <= set(_indexes(db_path, "quotes"))

    command.downgrade(config, "030_permit_requests")
    _fresh_loop()
    assert "quotes" not in _tables(db_path)

    command.upgrade(config, "031_quotes")
    _fresh_loop()
    assert "quotes" in _tables(db_path)
    assert _query(db_path, "SELECT quote_id FROM quotes") == []


def test_032_reason_code_roundtrip_preserves_receipt(tmp_path, monkeypatch):
    db_path = tmp_path / "m032.db"
    config = _config(db_path, monkeypatch)
    command.upgrade(config, "031_quotes")
    _fresh_loop()
    _seed_wallet(db_path)
    _seed_permit(db_path)
    _exec(
        db_path,
        """
        INSERT INTO receipts (
            receipt_id, permit_id, wallet_id, tool, request_hash,
            credits_authorized, credits_charged, outcome,
            signature, signature_key_id
        ) VALUES (
            'receipt-032', 'permit-downgrade', 'agt-downgrade',
            'partner-tool', :request_hash, 1, 0, 'denied',
            'signature', 'sig-downgrade'
        )
        """,
        {"request_hash": "a" * 64},
    )

    command.upgrade(config, "032_receipt_reason_code")
    _fresh_loop()
    assert "reason_code" in _columns(db_path, "receipts")
    _exec(
        db_path,
        "UPDATE receipts SET reason_code = 'INSUFFICIENT_BALANCE' "
        "WHERE receipt_id = 'receipt-032'",
    )

    command.downgrade(config, "031_quotes")
    _fresh_loop()
    assert "reason_code" not in _columns(db_path, "receipts")
    assert _query(
        db_path,
        "SELECT outcome, signature FROM receipts WHERE receipt_id = 'receipt-032'",
    ) == [("denied", "signature")]

    command.upgrade(config, "032_receipt_reason_code")
    _fresh_loop()
    assert _query(
        db_path,
        "SELECT reason_code FROM receipts WHERE receipt_id = 'receipt-032'",
    ) == [(None,)]


def test_033_telemetry_drop_and_recreate_matches_013(tmp_path, monkeypatch):
    """033 removes an unwritten table; its downgrade must rebuild the 013 shape."""
    db_path = tmp_path / "m033.db"
    config = _config(db_path, monkeypatch)
    command.upgrade(config, "032_receipt_reason_code")
    _fresh_loop()
    assert "optimizer_telemetry" in _tables(db_path)
    shape_before = _columns(db_path, "optimizer_telemetry")
    indexes_before = _indexes(db_path, "optimizer_telemetry")
    assert {
        "ix_optimizer_telemetry_ts",
        "ix_optimizer_telemetry_wallet_id",
        "ix_optimizer_telemetry_agent_id",
    } <= set(indexes_before)
    _exec(
        db_path,
        "INSERT INTO optimizer_telemetry (wallet_id, agent_id, endpoint)"
        " VALUES ('w-033', 'a-033', '/v1/invoke')",
    )

    command.upgrade(config, "033_drop_optimizer_telemetry")
    _fresh_loop()
    assert "optimizer_telemetry" not in _tables(db_path)

    command.downgrade(config, "032_receipt_reason_code")
    _fresh_loop()
    shape_after = _columns(db_path, "optimizer_telemetry")
    assert set(shape_after) == set(shape_before)
    for name, col in shape_before.items():
        assert shape_after[name]["nullable"] == col["nullable"]
    assert {
        "ix_optimizer_telemetry_ts",
        "ix_optimizer_telemetry_wallet_id",
        "ix_optimizer_telemetry_agent_id",
    } <= set(_indexes(db_path, "optimizer_telemetry"))

    command.upgrade(config, "033_drop_optimizer_telemetry")
    _fresh_loop()
    assert "optimizer_telemetry" not in _tables(db_path)


def test_034_tool_call_counts_roundtrip(tmp_path, monkeypatch):
    db_path = tmp_path / "m034.db"
    config = _config(db_path, monkeypatch)
    command.upgrade(config, "033_drop_optimizer_telemetry")
    _fresh_loop()
    _seed_wallet(db_path)
    _seed_permit(db_path)

    command.upgrade(config, "034_add_permit_tool_call_counts")
    _fresh_loop()
    assert "tool_call_counts_json" in _columns(db_path, "permits")
    assert _query(
        db_path,
        "SELECT tool_call_counts_json FROM permits "
        "WHERE permit_id = 'permit-downgrade'",
    ) == [(None,)]
    _exec(
        db_path,
        "UPDATE permits SET tool_call_counts_json = '{\"partner.tool\": 2}' "
        "WHERE permit_id = 'permit-downgrade'",
    )

    command.downgrade(config, "033_drop_optimizer_telemetry")
    _fresh_loop()
    assert "tool_call_counts_json" not in _columns(db_path, "permits")
    assert _query(db_path, "SELECT permit_id FROM permits") == [("permit-downgrade",)]

    command.upgrade(config, "034_add_permit_tool_call_counts")
    _fresh_loop()
    assert "tool_call_counts_json" in _columns(db_path, "permits")


def test_035_api_key_caps_default_to_unlimited_and_roundtrip(tmp_path, monkeypatch):
    """Existing keys stay unlimited (NULL cap); the downgrade drops the cap."""
    db_path = tmp_path / "m035.db"
    config = _config(db_path, monkeypatch)
    command.upgrade(config, "034_add_permit_tool_call_counts")
    _fresh_loop()
    _seed_wallet(db_path)
    _exec(
        db_path,
        "INSERT INTO api_keys (key_id, wallet_id, key_hash, key_prefix)"
        " VALUES ('key-035', 'agt-downgrade', :key_hash, 'b2a_live')",
        {"key_hash": "h" * 64},
    )

    command.upgrade(config, "035_api_key_max_uses")
    _fresh_loop()
    cols = _columns(db_path, "api_keys")
    assert "max_uses" in cols and cols["max_uses"]["nullable"] is True
    assert "use_count" in cols and cols["use_count"]["nullable"] is False
    assert _query(
        db_path, "SELECT max_uses, use_count FROM api_keys WHERE key_id = 'key-035'"
    ) == [(None, 0)]
    _exec(
        db_path,
        "UPDATE api_keys SET max_uses = 3, use_count = 1 WHERE key_id = 'key-035'",
    )

    command.downgrade(config, "034_add_permit_tool_call_counts")
    _fresh_loop()
    remaining = _columns(db_path, "api_keys")
    assert "max_uses" not in remaining
    assert "use_count" not in remaining
    assert _query(db_path, "SELECT key_id FROM api_keys") == [("key-035",)]

    command.upgrade(config, "035_api_key_max_uses")
    _fresh_loop()
    assert _query(
        db_path, "SELECT max_uses, use_count FROM api_keys WHERE key_id = 'key-035'"
    ) == [(None, 0)]


def test_036_request_hash_anchor_backfills_and_downgrade(tmp_path, monkeypatch):
    """036 freezes the reviewed hash; rows minted before it inherit request_hash."""
    db_path = tmp_path / "m036.db"
    config = _config(db_path, monkeypatch)
    command.upgrade(config, "035_api_key_max_uses")
    _fresh_loop()
    _seed_wallet(db_path, "spn-036")
    _seed_wallet(db_path, "agt-036")
    _exec(
        db_path,
        """
        INSERT INTO permit_requests (
            request_id, issuer_wallet_id, subject_wallet_id, idempotency_key,
            scopes_json, allowed_tools_json, max_credits, permit_expires_at,
            justification, request_hash, reserved_permit_id, requested_at,
            expires_at
        ) VALUES (
            'req-036', 'spn-036', 'agt-036', 'mint-key-036', '[]', '[]', 10,
            '2030-01-01 00:00:00', 'need tool access', :request_hash,
            'reserved-036', '2026-08-01 00:00:00', '2026-08-02 00:00:00'
        )
        """,
        {"request_hash": "a" * 64},
    )

    command.upgrade(config, "036_permit_request_hash_anchor")
    _fresh_loop()
    assert _query(
        db_path,
        "SELECT request_hash, original_request_hash FROM permit_requests "
        "WHERE request_id = 'req-036'",
    ) == [("a" * 64, "a" * 64)]

    command.downgrade(config, "035_api_key_max_uses")
    _fresh_loop()
    assert "original_request_hash" not in _columns(db_path, "permit_requests")
    assert _query(
        db_path,
        "SELECT request_hash FROM permit_requests WHERE request_id = 'req-036'",
    ) == [("a" * 64,)]

    command.upgrade(config, "036_permit_request_hash_anchor")
    _fresh_loop()
    assert _query(
        db_path,
        "SELECT original_request_hash FROM permit_requests "
        "WHERE request_id = 'req-036'",
    ) == [("a" * 64,)]


def test_038_call_slot_and_dup_index_downgrade(tmp_path, monkeypatch):
    db_path = tmp_path / "m038.db"
    config = _config(db_path, monkeypatch)
    command.upgrade(config, "037_mcp_dispatch_claim_hash")
    _fresh_loop()
    _exec(
        db_path,
        """
        INSERT INTO mcp_dispatch_attempts (
            attempt_id, idempotency_record_id, wallet_id, permit_id,
            public_tool_id, upstream_tool_name, upstream_origin,
            request_hash, credits_authorized, credits_charged, state
        ) VALUES (
            'dsp-038', 'idm-038', 'agt-038', 'permit-038',
            'partner.legacy', 'partner_legacy', 'https://partner.example',
            :request_hash, 1, 0, 'prepared'
        )
        """,
        {"request_hash": "a" * 64},
    )

    command.upgrade(config, "038_dispatch_call_slot_dup_idx")
    _fresh_loop()
    cols = _columns(db_path, "mcp_dispatch_attempts")
    assert "call_slot_reserved" in cols
    assert cols["call_slot_reserved"]["nullable"] is False
    assert "ix_mcp_dispatch_attempts_duplicate_detection" in _indexes(
        db_path, "mcp_dispatch_attempts"
    )
    assert _query(
        db_path,
        "SELECT call_slot_reserved FROM mcp_dispatch_attempts "
        "WHERE attempt_id = 'dsp-038'",
    ) == [(0,)]

    command.downgrade(config, "037_mcp_dispatch_claim_hash")
    _fresh_loop()
    assert "call_slot_reserved" not in _columns(db_path, "mcp_dispatch_attempts")
    assert "ix_mcp_dispatch_attempts_duplicate_detection" not in _indexes(
        db_path, "mcp_dispatch_attempts"
    )
    assert _query(
        db_path,
        "SELECT state FROM mcp_dispatch_attempts WHERE attempt_id = 'dsp-038'",
    ) == [("prepared",)]

    command.upgrade(config, "038_dispatch_call_slot_dup_idx")
    _fresh_loop()
    assert "call_slot_reserved" in _columns(db_path, "mcp_dispatch_attempts")


def test_039_identical_repeats_defaults_off_and_downgrade(tmp_path, monkeypatch):
    """Duplicate detection stays on unless a permit explicitly opts out."""
    db_path = tmp_path / "m039.db"
    config = _config(db_path, monkeypatch)
    command.upgrade(config, "038_dispatch_call_slot_dup_idx")
    _fresh_loop()
    _seed_wallet(db_path)
    _seed_permit(db_path)

    command.upgrade(config, "039_permit_allow_ident_repeats")
    _fresh_loop()
    cols = _columns(db_path, "permits")
    assert "allow_identical_repeats" in cols
    assert cols["allow_identical_repeats"]["nullable"] is False
    assert _query(
        db_path,
        "SELECT allow_identical_repeats FROM permits "
        "WHERE permit_id = 'permit-downgrade'",
    ) == [(0,)]
    _exec(
        db_path,
        "UPDATE permits SET allow_identical_repeats = 1 "
        "WHERE permit_id = 'permit-downgrade'",
    )

    command.downgrade(config, "038_dispatch_call_slot_dup_idx")
    _fresh_loop()
    assert "allow_identical_repeats" not in _columns(db_path, "permits")
    assert _query(db_path, "SELECT permit_id FROM permits") == [("permit-downgrade",)]

    command.upgrade(config, "039_permit_allow_ident_repeats")
    _fresh_loop()
    assert _query(
        db_path,
        "SELECT allow_identical_repeats FROM permits "
        "WHERE permit_id = 'permit-downgrade'",
    ) == [(0,)]
