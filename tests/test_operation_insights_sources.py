"""Scoped evidence reads against synthetic rows only."""

from __future__ import annotations

import sys
import os
import uuid
import itertools
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import ModuleType, SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    delete,
    insert,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.db.models import (
    ControlPlaneAuditEventModel,
    HumanApprovalModel,
    IdempotencyRecordModel,
    LedgerEntryModel,
    McpDispatchAttemptModel,
    PermitModel,
    PermitRequestModel,
    ReceiptModel,
    WalletModel,
)
from app.services.operation_insights.contracts import (
    AuthorizedOwnershipEpoch,
    Limits,
    Scope,
    Window,
)


def utc(day: int) -> datetime:
    return datetime(2026, 10, day, tzinfo=timezone.utc)


@pytest.fixture
async def scoped_session(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            SQLModel.metadata.create_all,
            tables=[
                WalletModel.__table__,
                IdempotencyRecordModel.__table__,
                LedgerEntryModel.__table__,
                PermitModel.__table__,
                McpDispatchAttemptModel.__table__,
                ReceiptModel.__table__,
                ControlPlaneAuditEventModel.__table__,
                HumanApprovalModel.__table__,
                PermitRequestModel.__table__,
            ],
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        scope = Scope(
            wallet_ids=frozenset({"wallet-A"}),
            authorized_ownership_epochs=(
                AuthorizedOwnershipEpoch("wallet-A", "epoch-A", utc(1), utc(20)),
            ),
        )
        auth = ModuleType("app.services.operation_insights.auth")

        def assert_scope_bound(presented: Scope, current: AsyncSession) -> None:
            if presented is not scope or current is not session:
                raise PermissionError("scope_unbound")

        auth.assert_scope_bound = assert_scope_bound  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, auth.__name__, auth)
        yield session, scope
    await engine.dispose()


@pytest.mark.asyncio
async def test_unbound_scope_rejected_before_source_query(scoped_session) -> None:
    from app.services.operation_insights.sources import read_evidence

    session, scope = scoped_session
    seen: list[str] = []

    def watch(_connection, _cursor, statement, _parameters, _context, _executemany):
        seen.append(statement)

    event.listen(session.bind.sync_engine, "before_cursor_execute", watch)
    copied = Scope(
        wallet_ids=scope.wallet_ids,
        authorized_ownership_epochs=scope.authorized_ownership_epochs,
    )
    with pytest.raises(PermissionError, match="scope_unbound"):
        await read_evidence(
            copied, Window(utc(2), utc(3), "first_observed_evidence"), Limits(), session
        )

    assert seen == []


@pytest.mark.asyncio
async def test_equal_time_keyset_deduplicates_and_filters_wallet(
    scoped_session,
) -> None:
    from app.services.operation_insights.sources import read_evidence

    session, scope = scoped_session
    session.add_all(
        [
            WalletModel(wallet_id="wallet-A", wallet_type="agent"),
            WalletModel(wallet_id="wallet-B", wallet_type="agent"),
        ]
    )
    session.add_all(
        [
            IdempotencyRecordModel(
                record_id=f"idm-{index:04d}",
                wallet_id="wallet-A",
                endpoint="/mcp/invoke",
                idempotency_key=f"private-{index}",
                request_hash="0" * 64,
                operation_kind="upstream_mcp",
                created_at=utc(2),
            )
            for index in range(1201)
        ]
    )
    session.add(
        IdempotencyRecordModel(
            record_id="foreign-idm",
            wallet_id="wallet-B",
            endpoint="/mcp/invoke",
            idempotency_key="foreign-secret",
            request_hash="0" * 64,
            operation_kind="upstream_mcp",
            created_at=utc(2),
        )
    )
    await session.flush()

    batch = await read_evidence(
        scope,
        Window(utc(2), utc(3), "first_observed_evidence"),
        Limits(page_size=500),
        session,
    )

    assert len(batch.rows) == 1201
    assert len({(row.source, row.source_id) for row in batch.rows}) == 1201
    assert {row.wallet_id for row in batch.rows} == {"wallet-A"}
    assert {row.ownership_epoch_id for row in batch.rows} == {"epoch-A"}
    assert all("private-" not in repr(row) for row in batch.rows)
    assert batch.coverage.truncated is False
    for source_name in ("idempotency", "dispatch", "ledger"):
        coverage = next(
            source for source in batch.coverage.sources if source.source == source_name
        )
        assert coverage.enumeration_complete is False
        assert "surviving_roots_only" in coverage.gaps
        assert "retention_unverified" in coverage.gaps


@pytest.mark.asyncio
async def test_reader_time_limit_preserves_enumerated_rows_as_partial(
    scoped_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.operation_insights import sources

    session, scope = scoped_session
    session.add(WalletModel(wallet_id="wallet-A", wallet_type="agent"))
    session.add_all(
        IdempotencyRecordModel(
            record_id=f"budget-root-{index}",
            wallet_id="wallet-A",
            endpoint="/mcp/invoke",
            idempotency_key=f"synthetic-budget-{index}",
            request_hash="0" * 64,
            operation_kind="upstream_mcp",
            created_at=utc(2),
        )
        for index in range(3)
    )
    await session.flush()
    ticks = itertools.chain((0.0, 0.0), itertools.repeat(301.0))
    monkeypatch.setattr(sources, "time", SimpleNamespace(monotonic=lambda: next(ticks)))

    batch = await sources.read_evidence(
        scope,
        Window(utc(2), utc(3), "first_observed_evidence"),
        Limits(page_size=1),
        session,
    )

    assert {(row.source, row.source_id) for row in batch.rows} == {
        ("idempotency", "budget-root-0")
    }
    assert batch.coverage.truncated is True
    assert batch.coverage.enumeration_complete is False
    assert "execution_budget_reached" in batch.coverage.gaps


@pytest.mark.asyncio
async def test_empty_epoch_scope_reads_no_wallet_rows(scoped_session) -> None:
    from app.services.operation_insights.sources import read_evidence

    session, bound_scope = scoped_session
    session.add(WalletModel(wallet_id="wallet-A", wallet_type="agent"))
    session.add(
        IdempotencyRecordModel(
            record_id="idm-A",
            wallet_id="wallet-A",
            endpoint="/mcp/invoke",
            idempotency_key="private-A",
            request_hash="0" * 64,
            created_at=utc(2),
        )
    )
    await session.flush()
    empty = Scope(wallet_ids=bound_scope.wallet_ids)
    auth = sys.modules["app.services.operation_insights.auth"]
    auth.assert_scope_bound = lambda _scope, _session: None  # type: ignore[attr-defined]

    batch = await read_evidence(
        empty, Window(utc(2), utc(3), "first_observed_evidence"), Limits(), session
    )

    assert batch.rows == ()


@pytest.mark.asyncio
async def test_window_ingress_is_independent_of_historical_roots(
    scoped_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.operation_insights import sources

    read_evidence = sources.read_evidence

    session, scope = scoped_session
    event_table = Table(
        "operation_insight_events",
        MetaData(),
        Column("event_id", String, primary_key=True),
        Column("kind", String, nullable=False),
        Column("request_id", String),
        Column("attempt_id", String),
        Column("logical_operation_id", String),
        Column("wallet_id", String),
        Column("ownership_epoch_id", String),
        Column("original_operation_anchor_id", String),
        Column("request_disposition", String),
        Column("tool", String),
        Column("reason_code", String),
        Column("gateway_outcome", String),
        Column("effect_state", String),
        Column("http_status_code", String),
        Column("occurred_at", DateTime),
        Column("ingested_at", DateTime),
        Column("duplicate_conflict_at", DateTime),
        Column("environment", String),
        Column("server_release", String),
        Column("deployment", String),
        Column("client_version", String),
    )
    async with session.bind.begin() as connection:
        await connection.run_sync(event_table.create)
    for record in [
        {
            "event_id": "ingress-A",
            "kind": "ingress",
            "request_id": "req-A",
            "wallet_id": "wallet-A",
            "original_operation_anchor_id": "ingress-A",
            "request_disposition": "execution_intent",
            "environment": "staging",
            "server_release": "commit-abc",
            "deployment": "deploy-abc",
            "client_version": "sdk-py-1.2",
            "occurred_at": utc(2).replace(tzinfo=None),
            "ingested_at": utc(2).replace(tzinfo=None),
        },
        {
            "event_id": "terminal-A",
            "kind": "terminal",
            "request_id": "req-A",
            "wallet_id": "wallet-A",
            "original_operation_anchor_id": "ingress-A",
            "gateway_outcome": "denied",
            "occurred_at": utc(4).replace(tzinfo=None),
            "ingested_at": utc(4).replace(tzinfo=None),
        },
        {
            "event_id": "replay-A",
            "kind": "ingress",
            "request_id": "req-A-replay",
            "wallet_id": "wallet-A",
            "original_operation_anchor_id": "ingress-A",
            "request_disposition": "same_key_replay",
            "occurred_at": utc(2).replace(tzinfo=None),
            "ingested_at": utc(2).replace(tzinfo=None),
        },
        {
            "event_id": "ingress-B",
            "kind": "ingress",
            "request_id": "req-B",
            "wallet_id": "wallet-B",
            "original_operation_anchor_id": "ingress-B",
            "request_disposition": "execution_intent",
            "occurred_at": utc(2).replace(tzinfo=None),
            "ingested_at": utc(2).replace(tzinfo=None),
        },
        {
            "event_id": "ingress-unknown",
            "kind": "ingress",
            "request_id": "req-unknown",
            "wallet_id": None,
            "original_operation_anchor_id": None,
            "request_disposition": "unknown",
            "occurred_at": utc(2).replace(tzinfo=None),
            "ingested_at": utc(2).replace(tzinfo=None),
        },
        {
            "event_id": "bogus-original",
            "kind": "ingress",
            "request_id": "req-bogus",
            "wallet_id": "wallet-A",
            "original_operation_anchor_id": "another-anchor",
            "request_disposition": "execution_intent",
            "occurred_at": utc(2).replace(tzinfo=None),
            "ingested_at": utc(2).replace(tzinfo=None),
        },
        {
            "event_id": "bogus-replay",
            "kind": "ingress",
            "request_id": "req-bogus-replay",
            "wallet_id": "wallet-A",
            "original_operation_anchor_id": "bogus-original",
            "request_disposition": "same_key_replay",
            "occurred_at": utc(2).replace(tzinfo=None),
            "ingested_at": utc(2).replace(tzinfo=None),
        },
        {
            "event_id": "conflicted-original",
            "kind": "ingress",
            "request_id": "req-conflict",
            "wallet_id": "wallet-A",
            "original_operation_anchor_id": "conflicted-original",
            "request_disposition": "execution_intent",
            "occurred_at": utc(2).replace(tzinfo=None),
            "ingested_at": utc(2).replace(tzinfo=None),
            "duplicate_conflict_at": utc(2).replace(tzinfo=None),
        },
        {
            "event_id": "conflicted-replay",
            "kind": "ingress",
            "request_id": "req-conflicted-replay",
            "wallet_id": "wallet-A",
            "original_operation_anchor_id": "conflicted-original",
            "request_disposition": "same_key_replay",
            "occurred_at": utc(2).replace(tzinfo=None),
            "ingested_at": utc(2).replace(tzinfo=None),
        },
    ]:
        await session.execute(insert(event_table).values(**record))

    historical = await read_evidence(
        scope, Window(utc(2), utc(3), "first_observed_evidence"), Limits(), session
    )
    ingress = await read_evidence(
        scope, Window(utc(2), utc(3), "ingress"), Limits(), session
    )

    assert historical.window_ingress == ()
    assert historical.rows == ()
    assert tuple(row.source_id for row in ingress.rows) == ("ingress-A", "terminal-A")
    ingress_row = ingress.window_ingress[0]
    assert ingress_row.environment == "staging"
    assert ingress_row.server_release == "commit-abc"
    assert ingress_row.deployment == "deploy-abc"
    assert ingress_row.client_version == "sdk-py-1.2"
    assert {row.original_operation_anchor_id for row in ingress.rows} == {"ingress-A"}
    assert "prospective_capture_completeness_unverified" in ingress.coverage.gaps
    assert (
        next(
            source
            for source in ingress.coverage.sources
            if source.source == "insight_event"
        ).enumeration_complete
        is False
    )
    monkeypatch.setattr(sources, "_MAX_EVIDENCE_ROWS", 2)
    capped = await read_evidence(
        scope, Window(utc(2), utc(3), "ingress"), Limits(), session
    )
    assert {
        (row.source, row.source_id) for row in (*capped.rows, *capped.window_ingress)
    } == {("insight_event", "ingress-A"), ("insight_event", "replay-A")}
    assert capped.coverage.truncated is True
    assert "evidence_limit_reached" in capped.coverage.gaps


@pytest.mark.asyncio
async def test_post_transfer_replay_cannot_reown_original_ingress(
    scoped_session,
) -> None:
    from app.services.operation_insights.sources import read_evidence

    session, _ = scoped_session
    event_table = Table(
        "operation_insight_events",
        MetaData(),
        Column("event_id", String, primary_key=True),
        Column("kind", String),
        Column("request_id", String),
        Column("attempt_id", String),
        Column("logical_operation_id", String),
        Column("wallet_id", String),
        Column("ownership_epoch_id", String),
        Column("original_operation_anchor_id", String),
        Column("request_disposition", String),
        Column("tool", String),
        Column("reason_code", String),
        Column("gateway_outcome", String),
        Column("effect_state", String),
        Column("http_status_code", String),
        Column("occurred_at", DateTime),
        Column("ingested_at", DateTime),
        Column("duplicate_conflict_at", DateTime),
        Column("environment", String),
        Column("server_release", String),
        Column("deployment", String),
        Column("client_version", String),
    )
    async with session.bind.begin() as connection:
        await connection.run_sync(event_table.create)
    for record in [
        dict(
            event_id="original",
            kind="ingress",
            request_id="request-1",
            wallet_id="wallet-A",
            original_operation_anchor_id="original",
            request_disposition="execution_intent",
            occurred_at=utc(2),
            ingested_at=utc(2),
        ),
        dict(
            event_id="late-replay",
            kind="ingress",
            request_id="request-2",
            wallet_id="wallet-A",
            original_operation_anchor_id="original",
            request_disposition="same_key_replay",
            occurred_at=utc(7),
            ingested_at=utc(7),
        ),
        dict(
            event_id="late-terminal",
            kind="terminal",
            request_id="request-1",
            wallet_id="wallet-A",
            original_operation_anchor_id="original",
            gateway_outcome="failed",
            occurred_at=utc(7),
            ingested_at=utc(7),
        ),
    ]:
        await session.execute(insert(event_table).values(**record))
    old_scope = Scope(
        frozenset({"wallet-A"}),
        (AuthorizedOwnershipEpoch("wallet-A", "epoch-old", utc(1), utc(5)),),
    )
    new_scope = Scope(
        frozenset({"wallet-A"}),
        (AuthorizedOwnershipEpoch("wallet-A", "epoch-new", utc(5), utc(20)),),
    )
    auth = sys.modules["app.services.operation_insights.auth"]
    auth.assert_scope_bound = lambda _scope, _session: None  # type: ignore[attr-defined]

    old_operation = await read_evidence(
        old_scope, Window(utc(2), utc(3), "ingress"), Limits(), session
    )
    old_current_window = await read_evidence(
        old_scope, Window(utc(7), utc(8), "ingress"), Limits(), session
    )
    new_current_window = await read_evidence(
        new_scope, Window(utc(7), utc(8), "ingress"), Limits(), session
    )

    assert {row.source_id for row in old_operation.rows} == {
        "original",
        "late-terminal",
    }
    assert old_current_window.window_ingress == ()
    assert new_current_window.window_ingress == ()


@pytest.mark.asyncio
async def test_unknown_wallet_count_withholds_uncertified_capture(
    scoped_session,
) -> None:
    from app.services.operation_insights.sources import read_unknown_wallet_count

    session, bound_scope = scoped_session
    scope = Scope(
        bound_scope.wallet_ids,
        bound_scope.authorized_ownership_epochs,
        allow_unknown_wallet_counts=True,
    )
    auth = sys.modules["app.services.operation_insights.auth"]
    auth.assert_scope_bound = lambda _scope, _session: None  # type: ignore[attr-defined]
    event_table = Table(
        "operation_insight_events",
        MetaData(),
        Column("event_id", String, primary_key=True),
        Column("kind", String),
        Column("wallet_id", String),
        Column("occurred_at", DateTime),
        Column("ingested_at", DateTime),
        Column("duplicate_conflict_at", DateTime),
    )
    async with session.bind.begin() as connection:
        await connection.run_sync(event_table.create)
    await session.execute(
        insert(event_table).values(
            event_id="walletless-private",
            kind="ingress",
            wallet_id=None,
            occurred_at=utc(4),
            ingested_at=utc(4),
        )
    )
    await session.execute(
        insert(event_table).values(
            event_id="walletless-outside",
            kind="ingress",
            wallet_id=None,
            occurred_at=utc(10),
            ingested_at=utc(10),
        )
    )
    first = await read_unknown_wallet_count(
        scope, Window(utc(3), utc(10), "ingress"), session
    )
    second = await read_unknown_wallet_count(
        scope,
        Window(utc(3).replace(second=1), utc(10).replace(second=1), "ingress"),
        session,
    )

    assert first.status == "partial"
    assert first.count is None
    assert second.count is None
    assert second.bucket_start == first.bucket_start
    assert second.bucket_end == first.bucket_end
    assert "walletless-private" not in repr(first)


@pytest.mark.asyncio
async def test_empty_disabled_capture_is_never_complete_zero(scoped_session) -> None:
    from app.services.operation_insights.sources import read_unknown_wallet_count

    session, bound_scope = scoped_session
    scope = Scope(
        bound_scope.wallet_ids,
        bound_scope.authorized_ownership_epochs,
        allow_unknown_wallet_counts=True,
    )
    auth = sys.modules["app.services.operation_insights.auth"]
    auth.assert_scope_bound = lambda _scope, _session: None  # type: ignore[attr-defined]
    event_table = Table(
        "operation_insight_events",
        MetaData(),
        Column("event_id", String, primary_key=True),
        Column("kind", String),
        Column("wallet_id", String),
        Column("occurred_at", DateTime),
        Column("ingested_at", DateTime),
        Column("duplicate_conflict_at", DateTime),
    )
    async with session.bind.begin() as connection:
        await connection.run_sync(event_table.create)

    result = await read_unknown_wallet_count(
        scope, Window(utc(3), utc(10), "ingress"), session
    )

    assert result.status == "partial"
    assert result.count is None
    assert result.bucket_start == utc(3)
    assert result.bucket_end == utc(10)


@pytest.mark.asyncio
async def test_receiptless_dispatch_keeps_verified_debit_and_subject_permit(
    scoped_session,
) -> None:
    from app.services.operation_insights.sources import read_evidence

    session, scope = scoped_session
    session.add(WalletModel(wallet_id="wallet-A", wallet_type="agent"))
    session.add(
        IdempotencyRecordModel(
            record_id="idm-A",
            wallet_id="wallet-A",
            endpoint="/mcp/invoke",
            idempotency_key="never-project-me",
            request_hash="0" * 64,
            operation_kind="upstream_mcp",
            created_at=utc(2),
            ledger_entry_id="debit-A",
        )
    )
    session.add(
        PermitModel(
            permit_id="permit-A",
            issuer_wallet_id="wallet-A",
            subject_wallet_id="wallet-A",
            scopes_json="[]",
            allowed_tools_json="[]",
            max_credits=Decimal("10"),
            expires_at=utc(9),
            nonce="nonce-A",
            signature="synthetic-signature",
            key_id="synthetic-signing-key",
            issued_at=utc(1),
        )
    )
    session.add(
        LedgerEntryModel(
            entry_id="debit-A",
            wallet_id="wallet-A",
            action="debit",
            amount=Decimal("-3"),
            balance_after=Decimal("7"),
            operation_key="idm-A",
            timestamp=utc(2),
        )
    )
    session.add(
        McpDispatchAttemptModel(
            attempt_id="attempt-A",
            idempotency_record_id="idm-A",
            wallet_id="wallet-A",
            permit_id="permit-A",
            public_tool_id="partner.echo",
            upstream_tool_name="raw.upstream.name",
            upstream_origin="https://secret.invalid",
            request_hash="0" * 64,
            ledger_entry_id="debit-A",
            credits_authorized=Decimal("3"),
            credits_charged=Decimal("3"),
            state="dispatch_claimed",
            created_at=utc(2),
            updated_at=utc(2),
            dispatched_at=utc(2),
        )
    )
    await session.flush()

    batch = await read_evidence(
        scope, Window(utc(2), utc(3), "first_observed_evidence"), Limits(), session
    )

    assert {row.source for row in batch.rows} == {
        "idempotency",
        "dispatch",
        "ledger",
        "permit",
    }
    assert (
        next(
            row for row in batch.rows if row.source == "ledger"
        ).state_facts.ledger_link_verified
        is True
    )
    assert all("secret.invalid" not in repr(row) for row in batch.rows)
    assert all("never-project-me" not in repr(row) for row in batch.rows)

    session.add(
        IdempotencyRecordModel(
            record_id="idm-B",
            wallet_id="wallet-A",
            endpoint="/mcp/invoke",
            idempotency_key="second-secret",
            request_hash="0" * 64,
            operation_kind="upstream_mcp",
            created_at=utc(2),
        )
    )
    session.add(
        McpDispatchAttemptModel(
            attempt_id="attempt-B",
            idempotency_record_id="idm-B",
            wallet_id="wallet-A",
            permit_id="permit-A",
            public_tool_id="partner.echo",
            upstream_tool_name="raw.upstream.name",
            upstream_origin="https://secret.invalid",
            request_hash="0" * 64,
            credits_authorized=Decimal("0"),
            credits_charged=Decimal("0"),
            state="prepared",
            created_at=utc(2),
            updated_at=utc(2),
        )
    )
    await session.flush()
    shared = await read_evidence(
        scope,
        Window(utc(2), utc(3), "first_observed_evidence"),
        Limits(page_size=1),
        session,
    )

    assert {row.source_id for row in shared.rows if row.source == "permit"} == set()
    assert "shared_context_anchor_ambiguous" in shared.coverage.gaps


@pytest.mark.asyncio
async def test_b_epoch_root_does_not_expose_a_epoch_linked_context(
    scoped_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.operation_insights.sources import read_evidence

    session, _ = scoped_session
    scope_b = Scope(
        wallet_ids=frozenset({"wallet-A"}),
        authorized_ownership_epochs=(
            AuthorizedOwnershipEpoch("wallet-A", "epoch-B", utc(5), utc(20)),
        ),
    )
    auth = sys.modules["app.services.operation_insights.auth"]

    def assert_b_scope(presented: Scope, current: AsyncSession) -> None:
        if presented is not scope_b or current is not session:
            raise PermissionError("scope_unbound")

    monkeypatch.setattr(auth, "assert_scope_bound", assert_b_scope)
    session.add(WalletModel(wallet_id="wallet-A", wallet_type="agent"))
    session.add(
        IdempotencyRecordModel(
            record_id="b-root",
            wallet_id="wallet-A",
            endpoint="/mcp/invoke",
            idempotency_key="synthetic-b-key",
            request_hash="0" * 64,
            operation_kind="upstream_mcp",
            created_at=utc(6),
        )
    )
    session.add(
        PermitModel(
            permit_id="a-permit",
            issuer_wallet_id="wallet-A",
            subject_wallet_id="wallet-A",
            scopes_json="[]",
            allowed_tools_json="[]",
            max_credits=Decimal("10"),
            expires_at=utc(15),
            nonce="a-nonce",
            signature="synthetic-signature",
            key_id="synthetic-signing-key",
            issued_at=utc(2),
        )
    )
    session.add(
        HumanApprovalModel(
            approval_id="a-approval",
            wallet_id="wallet-A",
            permit_id="a-permit",
            tool="partner.echo",
            idempotency_key="synthetic-a-approval-key",
            requested_at=utc(3),
            expires_at=utc(15),
            status="approved",
        )
    )
    session.add(
        PermitRequestModel(
            request_id="a-request",
            issuer_wallet_id="wallet-A",
            subject_wallet_id="wallet-A",
            idempotency_key="synthetic-a-request-key",
            scopes_json="[]",
            allowed_tools_json="[]",
            max_credits=Decimal("10"),
            permit_expires_at=utc(15),
            justification="synthetic",
            request_hash="0" * 64,
            original_request_hash="0" * 64,
            reserved_permit_id="a-permit",
            permit_id="a-permit",
            requested_at=utc(2),
            expires_at=utc(15),
            status="approved",
        )
    )
    session.add(
        McpDispatchAttemptModel(
            attempt_id="b-attempt",
            idempotency_record_id="b-root",
            wallet_id="wallet-A",
            permit_id="a-permit",
            approval_id="a-approval",
            public_tool_id="partner.echo",
            upstream_tool_name="raw.upstream.name",
            upstream_origin="https://example.invalid",
            request_hash="0" * 64,
            credits_authorized=Decimal("0"),
            credits_charged=Decimal("0"),
            state="prepared",
            created_at=utc(6),
            updated_at=utc(6),
        )
    )
    await session.flush()

    batch = await read_evidence(
        scope_b, Window(utc(6), utc(7), "first_observed_evidence"), Limits(), session
    )

    assert {(row.source, row.source_id) for row in batch.rows} == {
        ("idempotency", "b-root"),
        ("dispatch", "b-attempt"),
    }
    assert {row.ownership_epoch_id for row in batch.rows} == {"epoch-B"}
    assert "a-permit" not in repr(batch)
    assert "a-approval" not in repr(batch)
    assert "a-request" not in repr(batch)
    assert "linked_context_epoch_unverified" in batch.coverage.gaps


@pytest.mark.asyncio
async def test_b_epoch_permit_does_not_hide_missing_a_epoch_request_gap(
    scoped_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.operation_insights.sources import read_evidence

    session, _ = scoped_session
    scope_b = Scope(
        wallet_ids=frozenset({"wallet-A"}),
        authorized_ownership_epochs=(
            AuthorizedOwnershipEpoch("wallet-A", "epoch-B", utc(5), utc(20)),
        ),
    )
    auth = sys.modules["app.services.operation_insights.auth"]

    def assert_b_scope(presented: Scope, current: AsyncSession) -> None:
        if presented is not scope_b or current is not session:
            raise PermissionError("scope_unbound")

    monkeypatch.setattr(
        auth,
        "assert_scope_bound",
        assert_b_scope,
    )
    session.add(WalletModel(wallet_id="wallet-A", wallet_type="agent"))
    session.add(
        IdempotencyRecordModel(
            record_id="b-root-request-gap",
            wallet_id="wallet-A",
            endpoint="/mcp/invoke",
            idempotency_key="synthetic-root-key",
            request_hash="0" * 64,
            operation_kind="upstream_mcp",
            created_at=utc(6),
        )
    )
    session.add(
        PermitModel(
            permit_id="b-permit",
            issuer_wallet_id="wallet-A",
            subject_wallet_id="wallet-A",
            scopes_json="[]",
            allowed_tools_json="[]",
            max_credits=Decimal("0"),
            expires_at=utc(15),
            nonce="b-nonce",
            signature="synthetic-signature",
            key_id="synthetic-signing-key",
            issued_at=utc(6),
        )
    )
    session.add(
        PermitRequestModel(
            request_id="a-request-hidden",
            issuer_wallet_id="wallet-A",
            subject_wallet_id="wallet-A",
            idempotency_key="synthetic-a-request-key",
            scopes_json="[]",
            allowed_tools_json="[]",
            max_credits=Decimal("0"),
            permit_expires_at=utc(15),
            justification="synthetic",
            request_hash="0" * 64,
            original_request_hash="0" * 64,
            reserved_permit_id="b-permit",
            permit_id="b-permit",
            requested_at=utc(2),
            expires_at=utc(15),
            status="approved",
        )
    )
    session.add(
        McpDispatchAttemptModel(
            attempt_id="b-attempt-request-gap",
            idempotency_record_id="b-root-request-gap",
            wallet_id="wallet-A",
            permit_id="b-permit",
            public_tool_id="partner.echo",
            upstream_tool_name="raw.upstream.name",
            upstream_origin="https://example.invalid",
            request_hash="0" * 64,
            credits_authorized=Decimal("0"),
            credits_charged=Decimal("0"),
            state="prepared",
            created_at=utc(6),
            updated_at=utc(6),
        )
    )
    await session.flush()

    batch = await read_evidence(
        scope_b, Window(utc(6), utc(7), "first_observed_evidence"), Limits(), session
    )

    assert {(row.source, row.source_id) for row in batch.rows} == {
        ("idempotency", "b-root-request-gap"),
        ("dispatch", "b-attempt-request-gap"),
        ("permit", "b-permit"),
    }
    assert "a-request-hidden" not in repr(batch)
    assert "linked_context_epoch_unverified" in batch.coverage.gaps


@pytest.mark.asyncio
async def test_linked_evidence_fanout_stops_at_row_cap(
    scoped_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.operation_insights import sources

    session, scope = scoped_session
    monkeypatch.setattr(sources, "_MAX_EVIDENCE_ROWS", 2, raising=False)
    session.add(WalletModel(wallet_id="wallet-A", wallet_type="agent"))
    session.add(
        IdempotencyRecordModel(
            record_id="fanout-root",
            wallet_id="wallet-A",
            endpoint="/mcp/invoke",
            idempotency_key="synthetic-fanout-key",
            request_hash="0" * 64,
            operation_kind="upstream_mcp",
            created_at=utc(2),
        )
    )
    session.add(
        PermitModel(
            permit_id="fanout-permit",
            issuer_wallet_id="wallet-A",
            subject_wallet_id="wallet-A",
            scopes_json="[]",
            allowed_tools_json="[]",
            max_credits=Decimal("0"),
            expires_at=utc(9),
            nonce="fanout-nonce",
            signature="synthetic-signature",
            key_id="synthetic-signing-key",
            issued_at=utc(2),
        )
    )
    session.add(
        McpDispatchAttemptModel(
            attempt_id="fanout-attempt",
            idempotency_record_id="fanout-root",
            wallet_id="wallet-A",
            permit_id="fanout-permit",
            public_tool_id="partner.echo",
            upstream_tool_name="raw.upstream.name",
            upstream_origin="https://example.invalid",
            request_hash="0" * 64,
            credits_authorized=Decimal("0"),
            credits_charged=Decimal("0"),
            state="prepared",
            created_at=utc(2),
            updated_at=utc(2),
        )
    )
    await session.flush()

    batch = await sources.read_evidence(
        scope,
        Window(utc(2), utc(3), "first_observed_evidence"),
        Limits(page_size=1),
        session,
    )

    assert len(batch.rows) == 2
    assert {row.source for row in batch.rows} == {"idempotency", "dispatch"}
    assert batch.coverage.truncated is True
    assert "evidence_limit_reached" in batch.coverage.gaps


@pytest.mark.asyncio
async def test_historical_free_form_codes_and_tools_are_not_projected(
    scoped_session,
) -> None:
    from app.services.operation_insights.sources import read_evidence

    session, scope = scoped_session
    secret = "private_key_abcdef"  # pragma: allowlist secret (synthetic sentinel)
    session.add(WalletModel(wallet_id="wallet-A", wallet_type="agent"))
    session.add(
        IdempotencyRecordModel(
            record_id="secret-root",
            wallet_id="wallet-A",
            endpoint="/mcp/invoke",
            idempotency_key="synthetic-key",
            request_hash="0" * 64,
            operation_kind="upstream_mcp",
            created_at=utc(2),
        )
    )
    session.add(
        PermitModel(
            permit_id="synthetic-permit",
            issuer_wallet_id="wallet-A",
            subject_wallet_id="wallet-A",
            scopes_json="[]",
            allowed_tools_json="[]",
            max_credits=Decimal("0"),
            expires_at=utc(9),
            nonce="synthetic-nonce",
            signature="synthetic-signature",
            key_id="synthetic-signing-key",
            issued_at=utc(2),
        )
    )
    session.add(
        HumanApprovalModel(
            approval_id="secret-approval",
            wallet_id="wallet-A",
            permit_id="synthetic-permit",
            tool=secret,
            idempotency_key="synthetic-approval-key",
            requested_at=utc(2),
            expires_at=utc(9),
            status="approved",
        )
    )
    session.add(
        McpDispatchAttemptModel(
            attempt_id="secret-attempt",
            idempotency_record_id="secret-root",
            wallet_id="wallet-A",
            permit_id="synthetic-permit",
            approval_id="secret-approval",
            public_tool_id=secret,
            upstream_tool_name="raw.upstream.name",
            upstream_origin="https://example.invalid",
            request_hash="0" * 64,
            credits_authorized=Decimal("0"),
            credits_charged=Decimal("0"),
            state="returned_error",
            error_code=secret,
            created_at=utc(2),
            updated_at=utc(2),
        )
    )
    session.add(
        ReceiptModel(
            receipt_id="secret-receipt",
            idempotency_record_id="secret-root",
            dispatch_attempt_id="secret-attempt",
            permit_id="synthetic-permit",
            wallet_id="wallet-A",
            tool=secret,
            request_hash="0" * 64,
            credits_authorized=Decimal("0"),
            outcome="failed",
            reason_code=secret,
            signature="synthetic-signature",
            signature_key_id="synthetic-signing-key",
            created_at=utc(2),
        )
    )
    await session.flush()

    batch = await read_evidence(
        scope, Window(utc(2), utc(3), "first_observed_evidence"), Limits(), session
    )

    assert {row.source for row in batch.rows} == {
        "idempotency",
        "dispatch",
        "receipt",
        "permit",
        "approval",
    }
    assert secret not in repr(batch)
    assert all(row.tool is None and row.reason_code is None for row in batch.rows)


def test_historical_known_reason_keeps_its_original_code() -> None:
    from app.services.operation_insights.sources import _safe_reason

    assert _safe_reason("permit_expired") == "permit_expired"
    assert _safe_reason("private_key_abcdef") is None


def test_historical_tool_requires_registered_public_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.billing import ServiceCategory
    from app.services.operation_insights import sources
    from app.services.service_registry import ServiceRegistry

    registry = ServiceRegistry()
    registry.register_local(
        service_id="partner.echo",
        name="Synthetic echo",
        description="Synthetic test tool",
        category=ServiceCategory.SANDBOX,
        func=lambda: None,
    )
    monkeypatch.setattr(sources, "get_service_registry", lambda: registry)

    assert sources._public_legacy_tool("partner.echo") == "partner.echo"
    assert sources._public_legacy_tool("private_key_abcdef") is None


@pytest.mark.asyncio
async def test_legacy_audit_client_request_id_never_leaves_reader(
    scoped_session,
) -> None:
    from app.services.operation_insights.sources import read_evidence

    session, scope = scoped_session
    client_token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjbGllbnQifQ.signature"
    session.add(WalletModel(wallet_id="wallet-A", wallet_type="agent"))
    session.add(
        IdempotencyRecordModel(
            record_id="idm-audit",
            wallet_id="wallet-A",
            endpoint="/mcp/invoke",
            idempotency_key="synthetic-private",
            request_hash="0" * 64,
            created_at=utc(2),
        )
    )
    session.add(
        PermitModel(
            permit_id="permit-audit",
            issuer_wallet_id="wallet-A",
            subject_wallet_id="wallet-A",
            scopes_json="[]",
            allowed_tools_json="[]",
            max_credits=Decimal("0"),
            expires_at=utc(9),
            nonce="nonce-audit",
            signature="synthetic-signature",
            key_id="synthetic-signing-key",
            issued_at=utc(1),
        )
    )
    session.add(
        ControlPlaneAuditEventModel(
            event_id="audit-client-id",
            created_at=utc(4),
            event="mcp.denied",
            wallet_id="wallet-A",
            request_id=client_token,
            ok=False,
        )
    )
    session.add(
        ReceiptModel(
            receipt_id="receipt-audit",
            idempotency_record_id="idm-audit",
            permit_id="permit-audit",
            wallet_id="wallet-A",
            tool="partner.echo",
            request_hash="0" * 64,
            credits_authorized=Decimal("0"),
            outcome="denied",
            audit_event_id="audit-client-id",
            signature="synthetic-signature",
            signature_key_id="synthetic-signing-key",
            created_at=utc(4),
        )
    )
    await session.flush()
    statements: list[str] = []

    def watch(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(session.bind.sync_engine, "before_cursor_execute", watch)

    batch = await read_evidence(
        scope, Window(utc(2), utc(3), "first_observed_evidence"), Limits(), session
    )

    assert all(row.source != "audit" for row in batch.rows)
    audit_coverage = next(
        source for source in batch.coverage.sources if source.source == "audit"
    )
    assert audit_coverage.availability == "unavailable"
    assert "audit_anchor_unverified" in audit_coverage.gaps
    assert client_token not in repr(batch)
    assert all("control_plane_audit_events.request_id" not in sql for sql in statements)


@pytest.mark.asyncio
async def test_receipt_cross_root_dispatch_and_shared_audit_are_withheld(
    scoped_session,
) -> None:
    from app.services.operation_insights.sources import read_evidence

    session, scope = scoped_session
    session.add(WalletModel(wallet_id="wallet-A", wallet_type="agent"))
    for suffix in ("A", "B"):
        session.add(
            IdempotencyRecordModel(
                record_id=f"idm-{suffix}",
                wallet_id="wallet-A",
                endpoint="/mcp/invoke",
                idempotency_key=f"private-{suffix}",
                request_hash="0" * 64,
                created_at=utc(2),
            )
        )
    session.add(
        PermitModel(
            permit_id="permit-shared-audit",
            issuer_wallet_id="wallet-A",
            subject_wallet_id="wallet-A",
            scopes_json="[]",
            allowed_tools_json="[]",
            max_credits=Decimal("0"),
            expires_at=utc(9),
            nonce="nonce-shared",
            signature="synthetic-signature",
            key_id="synthetic-signing-key",
            issued_at=utc(1),
        )
    )
    session.add(
        McpDispatchAttemptModel(
            attempt_id="attempt-A",
            idempotency_record_id="idm-A",
            wallet_id="wallet-A",
            permit_id="permit-shared-audit",
            public_tool_id="partner.echo",
            upstream_tool_name="raw.upstream.name",
            upstream_origin="https://secret.invalid",
            request_hash="0" * 64,
            credits_authorized=Decimal("0"),
            credits_charged=Decimal("0"),
            state="prepared",
            created_at=utc(2),
            updated_at=utc(2),
        )
    )
    session.add(
        ControlPlaneAuditEventModel(
            event_id="audit-shared",
            created_at=utc(4),
            event="mcp.denied",
            wallet_id="wallet-A",
            ok=False,
        )
    )
    for suffix in ("A", "B"):
        session.add(
            ReceiptModel(
                receipt_id=f"receipt-{suffix}",
                idempotency_record_id=f"idm-{suffix}",
                dispatch_attempt_id="attempt-A" if suffix == "B" else None,
                permit_id="permit-shared-audit",
                wallet_id="wallet-A",
                tool="partner.echo",
                request_hash="0" * 64,
                credits_authorized=Decimal("0"),
                outcome="denied",
                audit_event_id="audit-shared",
                signature="synthetic-signature",
                signature_key_id="synthetic-signing-key",
                created_at=utc(4),
            )
        )
    await session.flush()

    batch = await read_evidence(
        scope, Window(utc(2), utc(3), "first_observed_evidence"), Limits(), session
    )

    receipt_b = next(row for row in batch.rows if row.source_id == "receipt-B")
    assert {(edge.source, edge.source_id) for edge in receipt_b.edges} == {
        ("idempotency", "idm-B")
    }
    assert "receipt_dispatch_link_unverified" in batch.coverage.gaps
    assert all(row.source_id != "audit-shared" for row in batch.rows)
    assert "audit_anchor_unverified" in batch.coverage.gaps


_READER_PG_URL = os.environ.get("AMW_INSIGHTS_READER_TEST_DATABASE_URL")
_DISPOSABLE_READER_PG_URL = (
    "postgresql+asyncpg://sellers@127.0.0.1:55489/amw_insights_reader_test"
)


def _require_reader_pg_url(url: str | None) -> str:
    if url != _DISPOSABLE_READER_PG_URL:
        raise RuntimeError("only the designated disposable reader database is allowed")
    return url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://sellers@127.0.0.1:5432/amw_insights_reader_test",
        "postgresql+asyncpg://sellers@127.0.0.1:55489/production",
        "postgresql+asyncpg://sellers@db.example.com:55489/amw_insights_reader_test",
    ],
)
def test_pg_reader_rejects_unsafe_database_urls(url: str) -> None:
    with pytest.raises(RuntimeError, match="designated disposable"):
        _require_reader_pg_url(url)


@pytest.mark.skipif(
    not _READER_PG_URL,
    reason="owner: insights reader; isolated PostgreSQL required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_real_pg_bound_scope_keeps_late_replay_out_of_new_owner() -> None:
    from app.core.oidc_iga import EnterprisePrincipal
    from app.db.models import (
        InsightReportingPrincipal,
        InsightReportingWalletGrant,
        InsightWalletOwnershipEpoch,
        SigningKeyModel,
    )
    from app.services.operation_insights.auth import (
        authorize_scope,
        reporting_read_transaction,
    )
    from app.services.operation_insights.sources import (
        read_evidence,
        read_unknown_wallet_count,
    )

    # Validate the exact URL before any connection, table creation, or seed write.
    engine = create_async_engine(_require_reader_pg_url(_READER_PG_URL))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    event_table = Table(
        "operation_insight_events",
        MetaData(),
        Column("event_id", String, primary_key=True),
        Column("kind", String, nullable=False),
        Column("request_id", String),
        Column("attempt_id", String),
        Column("logical_operation_id", String),
        Column("wallet_id", String),
        Column("ownership_epoch_id", String),
        Column("original_operation_anchor_id", String),
        Column("request_disposition", String),
        Column("tool", String),
        Column("reason_code", String),
        Column("gateway_outcome", String),
        Column("effect_state", String),
        Column("http_status_code", Integer),
        Column("occurred_at", DateTime, nullable=False),
        Column("ingested_at", DateTime, nullable=False),
        Column("duplicate_conflict_at", DateTime),
        Column("classification_version", Integer, nullable=False),
        Column("environment", String),
        Column("server_release", String),
        Column("deployment", String),
        Column("client_version", String),
    )
    suffix = uuid.uuid4().hex[:12]
    wallet_id = f"insight-{suffix}"
    subject_wallet_id = f"subject-{suffix}"
    signing_id = f"signing-{suffix}"
    permit_id = f"permit-cross-{suffix}"
    idem_one_id, idem_two_id = f"idem-one-{suffix}", f"idem-two-{suffix}"
    dispatch_id = f"attempt-one-{suffix}"
    subject_idem_id, subject_dispatch_id = (
        f"idem-subject-{suffix}",
        f"attempt-subject-{suffix}",
    )
    receipt_one_id, receipt_two_id = f"receipt-one-{suffix}", f"receipt-two-{suffix}"
    shared_audit_id, orphan_audit_id = (
        f"audit-shared-{suffix}",
        f"audit-orphan-{suffix}",
    )
    orphan_terminal_id = f"terminal-orphan-{suffix}"
    principal_a_id, principal_b_id = f"principal-a-{suffix}", f"principal-b-{suffix}"
    epoch_a_id, epoch_b_id = f"epoch-a-{suffix}", f"epoch-b-{suffix}"
    subject_epoch_id = f"epoch-subject-{suffix}"
    grant_a_id, grant_b_id = f"grant-a-{suffix}", f"grant-b-{suffix}"
    subject_grant_id = f"grant-subject-{suffix}"
    original_id, replay_id, terminal_id, walletless_id = (
        f"original-{suffix}",
        f"replay-{suffix}",
        f"terminal-{suffix}",
        f"walletless-{suffix}",
    )
    issuer = "https://example.okta.com/oauth2/default"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    principal_a = EnterprisePrincipal(
        subject=f"operator-a-{suffix}", provider="okta", issuer=issuer
    )
    principal_b = EnterprisePrincipal(
        subject=f"operator-b-{suffix}", provider="okta", issuer=issuer
    )
    seeded = False
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                SQLModel.metadata.create_all,
                tables=[
                    SQLModel.metadata.tables[name]
                    for name in (
                        "wallets",
                        "api_keys",
                        "signing_keys",
                        "ledger_entries",
                        "idempotency_records",
                        "permits",
                        "human_approvals",
                        "permit_requests",
                        "mcp_dispatch_attempts",
                        "control_plane_audit_events",
                        "receipts",
                        "insight_reporting_principals",
                        "insight_wallet_ownership_epochs",
                        "insight_reporting_wallet_grants",
                    )
                ],
            )
            await connection.run_sync(event_table.create, checkfirst=True)
        async with factory() as session:
            session.add_all(
                [
                    WalletModel(wallet_id=wallet_id, wallet_type="agent"),
                    WalletModel(wallet_id=subject_wallet_id, wallet_type="agent"),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    InsightReportingPrincipal(
                        principal_id=principal_a_id,
                        issuer=issuer,
                        subject=principal_a.subject,
                        starts_at=now - timedelta(days=1),
                        expires_at=now + timedelta(days=1),
                        allow_unknown_wallet_counts=True,
                    ),
                    InsightReportingPrincipal(
                        principal_id=principal_b_id,
                        issuer=issuer,
                        subject=principal_b.subject,
                        starts_at=now - timedelta(days=1),
                        expires_at=now + timedelta(days=1),
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    InsightWalletOwnershipEpoch(
                        ownership_epoch_id=epoch_a_id,
                        wallet_id=wallet_id,
                        owner_boundary_id="synthetic-owner-A",
                        evidence_from=utc(1),
                        evidence_until=utc(5),
                        history_complete=True,
                    ),
                    InsightWalletOwnershipEpoch(
                        ownership_epoch_id=epoch_b_id,
                        wallet_id=wallet_id,
                        owner_boundary_id="synthetic-owner-B",
                        evidence_from=utc(5),
                        evidence_until=utc(20),
                        history_complete=True,
                    ),
                    InsightWalletOwnershipEpoch(
                        ownership_epoch_id=subject_epoch_id,
                        wallet_id=subject_wallet_id,
                        owner_boundary_id="synthetic-owner-B",
                        evidence_from=utc(1),
                        evidence_until=utc(20),
                        history_complete=True,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    InsightReportingWalletGrant(
                        grant_id=grant_a_id,
                        principal_id=principal_a_id,
                        wallet_id=wallet_id,
                        ownership_epoch_id=epoch_a_id,
                        starts_at=now - timedelta(days=1),
                        expires_at=now + timedelta(days=1),
                        evidence_from=utc(1),
                        evidence_until=utc(5),
                    ),
                    InsightReportingWalletGrant(
                        grant_id=grant_b_id,
                        principal_id=principal_b_id,
                        wallet_id=wallet_id,
                        ownership_epoch_id=epoch_b_id,
                        starts_at=now - timedelta(days=1),
                        expires_at=now + timedelta(days=1),
                        evidence_from=utc(5),
                        evidence_until=utc(20),
                    ),
                    InsightReportingWalletGrant(
                        grant_id=subject_grant_id,
                        principal_id=principal_b_id,
                        wallet_id=subject_wallet_id,
                        ownership_epoch_id=subject_epoch_id,
                        starts_at=now - timedelta(days=1),
                        expires_at=now + timedelta(days=1),
                        evidence_from=utc(1),
                        evidence_until=utc(20),
                    ),
                ]
            )
            await session.flush()
            session.add(
                SigningKeyModel(
                    key_id=signing_id,
                    public_key_b64="synthetic-public-key",
                    created_at=utc(1),
                )
            )
            for record_id, record_wallet in (
                (idem_one_id, wallet_id),
                (idem_two_id, wallet_id),
                (subject_idem_id, subject_wallet_id),
            ):
                session.add(
                    IdempotencyRecordModel(
                        record_id=record_id,
                        wallet_id=record_wallet,
                        endpoint="/mcp/invoke",
                        idempotency_key=record_id,
                        request_hash="0" * 64,
                        created_at=utc(2),
                    )
                )
            await session.flush()
            session.add(
                PermitModel(
                    permit_id=permit_id,
                    issuer_wallet_id=wallet_id,
                    subject_wallet_id=subject_wallet_id,
                    scopes_json="[]",
                    allowed_tools_json="[]",
                    max_credits=Decimal("0"),
                    expires_at=utc(9),
                    nonce=f"nonce-{suffix}",
                    signature="synthetic-signature",
                    key_id=signing_id,
                    issued_at=utc(1),
                )
            )
            await session.flush()
            session.add(
                McpDispatchAttemptModel(
                    attempt_id=dispatch_id,
                    idempotency_record_id=idem_one_id,
                    wallet_id=wallet_id,
                    permit_id=permit_id,
                    public_tool_id="partner.echo",
                    upstream_tool_name="raw.upstream.name",
                    upstream_origin="https://secret.invalid",
                    request_hash="0" * 64,
                    credits_authorized=Decimal("0"),
                    credits_charged=Decimal("0"),
                    state="prepared",
                    created_at=utc(2),
                    updated_at=utc(2),
                )
            )
            session.add(
                McpDispatchAttemptModel(
                    attempt_id=subject_dispatch_id,
                    idempotency_record_id=subject_idem_id,
                    wallet_id=subject_wallet_id,
                    permit_id=permit_id,
                    public_tool_id="partner.echo",
                    upstream_tool_name="raw.upstream.name",
                    upstream_origin="https://secret.invalid",
                    request_hash="0" * 64,
                    credits_authorized=Decimal("0"),
                    credits_charged=Decimal("0"),
                    state="prepared",
                    created_at=utc(2),
                    updated_at=utc(2),
                )
            )
            session.add_all(
                [
                    ControlPlaneAuditEventModel(
                        event_id=shared_audit_id,
                        created_at=utc(4),
                        event="mcp.denied",
                        wallet_id=wallet_id,
                        ok=False,
                    ),
                    ControlPlaneAuditEventModel(
                        event_id=orphan_audit_id,
                        created_at=utc(7),
                        event="mcp.denied",
                        wallet_id=wallet_id,
                        ok=False,
                    ),
                ]
            )
            await session.flush()
            for receipt_id, record_id, attempt_id in (
                (receipt_one_id, idem_one_id, None),
                (receipt_two_id, idem_two_id, dispatch_id),
            ):
                session.add(
                    ReceiptModel(
                        receipt_id=receipt_id,
                        idempotency_record_id=record_id,
                        dispatch_attempt_id=attempt_id,
                        permit_id=permit_id,
                        wallet_id=wallet_id,
                        tool="partner.echo",
                        request_hash="0" * 64,
                        credits_authorized=Decimal("0"),
                        outcome="denied",
                        audit_event_id=shared_audit_id,
                        signature="synthetic-signature",
                        signature_key_id=signing_id,
                        created_at=utc(4),
                    )
                )
            await session.flush()
            for event_record in (
                dict(
                    event_id=original_id,
                    kind="ingress",
                    request_id=f"request-{suffix}",
                    wallet_id=wallet_id,
                    original_operation_anchor_id=original_id,
                    request_disposition="execution_intent",
                    occurred_at=utc(2).replace(tzinfo=None),
                    ingested_at=utc(2).replace(tzinfo=None),
                    classification_version=1,
                ),
                dict(
                    event_id=replay_id,
                    kind="ingress",
                    request_id=f"replay-request-{suffix}",
                    wallet_id=wallet_id,
                    original_operation_anchor_id=original_id,
                    request_disposition="same_key_replay",
                    occurred_at=utc(7).replace(tzinfo=None),
                    ingested_at=utc(7).replace(tzinfo=None),
                    classification_version=1,
                ),
                dict(
                    event_id=terminal_id,
                    kind="terminal",
                    request_id=f"request-{suffix}",
                    wallet_id=wallet_id,
                    original_operation_anchor_id=original_id,
                    gateway_outcome="failed",
                    occurred_at=utc(7).replace(tzinfo=None),
                    ingested_at=utc(7).replace(tzinfo=None),
                    classification_version=1,
                ),
                dict(
                    event_id=orphan_terminal_id,
                    kind="terminal",
                    wallet_id=wallet_id,
                    original_operation_anchor_id=None,
                    gateway_outcome="failed",
                    occurred_at=utc(7).replace(tzinfo=None),
                    ingested_at=utc(7).replace(tzinfo=None),
                    classification_version=1,
                ),
                dict(
                    event_id=walletless_id,
                    kind="ingress",
                    wallet_id=None,
                    request_disposition="unknown",
                    occurred_at=utc(4).replace(tzinfo=None),
                    ingested_at=utc(4).replace(tzinfo=None),
                    classification_version=1,
                ),
            ):
                await session.execute(insert(event_table).values(**event_record))
            await session.commit()
            seeded = True

        async with factory() as session:
            async with reporting_read_transaction(session):
                scope_a = await authorize_scope(
                    principal_a, frozenset({wallet_id}), False, session
                )
                old = await read_evidence(
                    scope_a, Window(utc(2), utc(3), "ingress"), Limits(), session
                )
                late = await read_evidence(
                    scope_a, Window(utc(7), utc(8), "ingress"), Limits(), session
                )
                legacy_a = await read_evidence(
                    scope_a,
                    Window(utc(2), utc(3), "first_observed_evidence"),
                    Limits(),
                    session,
                )
                late_legacy_a = await read_evidence(
                    scope_a,
                    Window(utc(7), utc(8), "first_observed_evidence"),
                    Limits(),
                    session,
                )
                assert {row.source_id for row in old.rows} == {original_id, terminal_id}
                assert (
                    next(row for row in old.rows if row.source_id == terminal_id)
                    .edges[0]
                    .source_id
                    == original_id
                )
                assert late.window_ingress == ()
                assert orphan_terminal_id not in repr(old)
                assert late_legacy_a.rows == ()
                assert orphan_audit_id not in repr(legacy_a)
                assert shared_audit_id not in repr(legacy_a)
                assert permit_id not in {row.source_id for row in legacy_a.rows}
                cross_receipt = next(
                    row for row in legacy_a.rows if row.source_id == receipt_two_id
                )
                assert {
                    (edge.source, edge.source_id) for edge in cross_receipt.edges
                } == {("idempotency", idem_two_id)}
                assert "receipt_dispatch_link_unverified" in legacy_a.coverage.gaps
                assert walletless_id not in repr(old)
                count_scope = await authorize_scope(
                    principal_a, frozenset({wallet_id}), True, session
                )
                one = await read_unknown_wallet_count(
                    count_scope, Window(utc(3), utc(10), "ingress"), session
                )
                zero = await read_unknown_wallet_count(
                    count_scope,
                    Window(utc(3) - timedelta(days=7), utc(3), "ingress"),
                    session,
                )
                assert (one.status, one.count) == ("partial", None)
                assert (zero.status, zero.count) == ("partial", None)
                assert walletless_id not in repr(one)
        async with factory() as session:
            async with reporting_read_transaction(session):
                scope_b = await authorize_scope(
                    principal_b, frozenset({wallet_id}), False, session
                )
                new = await read_evidence(
                    scope_b, Window(utc(7), utc(8), "ingress"), Limits(), session
                )
                assert new.window_ingress == ()
                assert new.rows == ()
                new_legacy = await read_evidence(
                    scope_b,
                    Window(utc(7), utc(8), "first_observed_evidence"),
                    Limits(),
                    session,
                )
                assert new_legacy.rows == ()
                assert orphan_audit_id not in repr(new_legacy)
                assert orphan_terminal_id not in repr(new)
                assert (
                    await read_unknown_wallet_count(
                        scope_b, Window(utc(3), utc(10), "ingress"), session
                    )
                ).status == "not_authorized"
                subject_scope = await authorize_scope(
                    principal_b, frozenset({subject_wallet_id}), False, session
                )
                subject_evidence = await read_evidence(
                    subject_scope,
                    Window(utc(2), utc(3), "first_observed_evidence"),
                    Limits(),
                    session,
                )
                assert {row.source_id for row in subject_evidence.rows} == {
                    subject_idem_id,
                    subject_dispatch_id,
                    permit_id,
                }
                assert all(
                    row.wallet_id == subject_wallet_id for row in subject_evidence.rows
                )
                assert all(
                    edge.wallet_id == subject_wallet_id
                    for row in subject_evidence.rows
                    for edge in row.edges
                )
    finally:
        if seeded:
            async with engine.begin() as connection:
                await connection.execute(
                    delete(event_table).where(
                        event_table.c.event_id.in_(
                            (
                                original_id,
                                replay_id,
                                terminal_id,
                                orphan_terminal_id,
                                walletless_id,
                            )
                        )
                    )
                )
                for model, key_column, ids in (
                    (
                        ReceiptModel,
                        ReceiptModel.receipt_id,
                        (receipt_one_id, receipt_two_id),
                    ),
                    (
                        McpDispatchAttemptModel,
                        McpDispatchAttemptModel.attempt_id,
                        (dispatch_id, subject_dispatch_id),
                    ),
                    (
                        ControlPlaneAuditEventModel,
                        ControlPlaneAuditEventModel.event_id,
                        (shared_audit_id, orphan_audit_id),
                    ),
                    (PermitModel, PermitModel.permit_id, (permit_id,)),
                    (
                        IdempotencyRecordModel,
                        IdempotencyRecordModel.record_id,
                        (idem_one_id, idem_two_id, subject_idem_id),
                    ),
                    (SigningKeyModel, SigningKeyModel.key_id, (signing_id,)),
                    (
                        InsightReportingWalletGrant,
                        InsightReportingWalletGrant.grant_id,
                        (grant_a_id, grant_b_id, subject_grant_id),
                    ),
                    (
                        InsightWalletOwnershipEpoch,
                        InsightWalletOwnershipEpoch.ownership_epoch_id,
                        (epoch_a_id, epoch_b_id, subject_epoch_id),
                    ),
                    (
                        InsightReportingPrincipal,
                        InsightReportingPrincipal.principal_id,
                        (principal_a_id, principal_b_id),
                    ),
                    (
                        WalletModel,
                        WalletModel.wallet_id,
                        (wallet_id, subject_wallet_id),
                    ),
                ):
                    await connection.execute(delete(model).where(key_column.in_(ids)))
        await engine.dispose()
