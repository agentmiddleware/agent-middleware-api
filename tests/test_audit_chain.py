from __future__ import annotations

import asyncio
from datetime import timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import AuditChainHeadModel, ControlPlaneAuditEventModel
from app.main import app
from app.services.audit_chain import AuditEventConflictError, verify_audit_chain
from app.services.audit_log import record_audit_event
from tests.test_trust_helpers import BOOTSTRAP_HEADERS, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_concurrent_audit_appends_do_not_fork_the_chain(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]

    # Concurrent same-wallet appends must serialize on the chain head so the
    # chain stays a single, verifiable line (no shared predecessor / fork).
    n_events = 10
    await asyncio.gather(
        *(
            record_audit_event(
                event="trust.race", wallet_id=wallet_id, metadata={"n": n}
            )
            for n in range(n_events)
        )
    )

    verify_resp = await client.post(
        "/v1/audit/verify-chain",
        json={"wallet_id": wallet_id},
        headers=provisioned["agent_headers"],
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["valid"] is True
    assert verify_resp.json()["checked_events"] == n_events

    factory = get_session_factory()
    async with factory() as session:
        seqs = [
            row[0]
            for row in (
                await session.execute(
                    select(ControlPlaneAuditEventModel.seq)
                    .where(ControlPlaneAuditEventModel.wallet_id == wallet_id)
                    .order_by(ControlPlaneAuditEventModel.seq)
                )
            ).all()
        ]
        head = await session.get(AuditChainHeadModel, wallet_id)
    # Sequences are contiguous with no duplicates, and the head points at the last.
    assert seqs == list(range(1, n_events + 1))
    assert head is not None
    assert head.last_seq == n_events


@pytest.mark.anyio
async def test_deterministic_audit_append_is_get_or_create_and_conflict_safe(
    client,
    clean_database,
):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    event_id = "audit-dsp-fixed-concurrency-claim"
    created_at = utc_now()
    kwargs = {
        "event": "mcp.invoke",
        "event_id": event_id,
        "created_at": created_at,
        "wallet_id": wallet_id,
        "tool": "partner.lookup",
        "endpoint": "/mcp/invoke",
        "request_id": "dsp-fixed-concurrency-claim",
        "metadata": {"dispatch_attempt_id": "dsp-fixed-concurrency-claim"},
    }

    first, second = await asyncio.gather(
        record_audit_event(**kwargs),
        record_audit_event(**kwargs),
    )

    assert first.event_id == second.event_id == event_id
    factory = get_session_factory()
    async with factory() as session:
        persisted = (
            (
                await session.execute(
                    select(ControlPlaneAuditEventModel).where(
                        ControlPlaneAuditEventModel.event_id == event_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(persisted) == 1
    assert (await verify_audit_chain(wallet_id=wallet_id)).valid is True

    with pytest.raises(AuditEventConflictError, match="audit_event_id_conflict"):
        await record_audit_event(
            **{
                **kwargs,
                "metadata": {"dispatch_attempt_id": "different-attempt"},
            }
        )


@pytest.mark.anyio
async def test_audit_chain_orders_by_monotonic_sequence(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]

    # Rapid same-wallet events can share a created_at timestamp; the chain must
    # still order deterministically and verify.
    for n in range(12):
        await record_audit_event(
            event="trust.seq", wallet_id=wallet_id, metadata={"n": n}
        )

    verify_resp = await client.post(
        "/v1/audit/verify-chain",
        json={"wallet_id": wallet_id},
        headers=provisioned["agent_headers"],
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["valid"] is True
    assert verify_resp.json()["checked_events"] == 12

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(ControlPlaneAuditEventModel.seq)
            .where(ControlPlaneAuditEventModel.wallet_id == wallet_id)
            .order_by(ControlPlaneAuditEventModel.seq)
        )
        seqs = [row[0] for row in result.all()]
    assert seqs == list(range(1, 13))


@pytest.mark.anyio
async def test_audit_chain_verifies_and_detects_tampering(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    await record_audit_event(event="trust.test", wallet_id=wallet_id, metadata={"n": 1})
    await record_audit_event(event="trust.test", wallet_id=wallet_id, metadata={"n": 2})

    verify_resp = await client.post(
        "/v1/audit/verify-chain",
        json={"wallet_id": wallet_id},
        headers=provisioned["agent_headers"],
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["valid"] is True
    assert verify_resp.json()["checked_events"] == 2

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(ControlPlaneAuditEventModel)
            .where(ControlPlaneAuditEventModel.wallet_id == wallet_id)
            .order_by(ControlPlaneAuditEventModel.created_at)
        )
        event = result.scalars().first()
        event.metadata_json = '{"n": 999}'
        session.add(event)
        await session.commit()

    tampered_resp = await client.post(
        "/v1/audit/verify-chain",
        json={"wallet_id": wallet_id},
        headers=BOOTSTRAP_HEADERS,
    )
    assert tampered_resp.status_code == 200
    assert tampered_resp.json()["valid"] is False
    assert tampered_resp.json()["reason"] == "audit_payload_hash_mismatch"


@pytest.mark.anyio
async def test_audit_chain_normalizes_offset_time_filters(
    clean_database,
    enforce_naive_utc_datetime_columns,
):
    wallet_id = "wlt-audit-time-filter"
    event = await record_audit_event(event="trust.time", wallet_id=wallet_id)
    event_utc = event.created_at.replace(tzinfo=timezone.utc)

    result = await verify_audit_chain(
        wallet_id=wallet_id,
        created_after=(event_utc - timedelta(minutes=1)).astimezone(
            timezone(timedelta(hours=5, minutes=30))
        ),
        created_before=(event_utc + timedelta(minutes=1)).astimezone(
            timezone(timedelta(hours=-7))
        ),
    )

    assert result.valid is True
    assert result.checked_events == 1


@pytest.mark.anyio
async def test_global_verify_covers_wallet_less_null_chain(clean_database):
    """Global verification must walk the wallet-less (wallet_id IS NULL) chain
    too. Tampering a system/denied-action record used to return valid=True
    because the NULL chain was dropped from the distinct list."""
    await record_audit_event(event="system.denied", wallet_id=None, metadata={"n": 1})
    await record_audit_event(event="system.denied", wallet_id=None, metadata={"n": 2})

    ok = await verify_audit_chain(wallet_id=None)
    assert ok.valid is True
    assert ok.checked_events == 2

    # Tamper the first wallet-less event.
    factory = get_session_factory()
    async with factory() as session:
        event = (
            (
                await session.execute(
                    select(ControlPlaneAuditEventModel)
                    .where(ControlPlaneAuditEventModel.wallet_id.is_(None))
                    .order_by(ControlPlaneAuditEventModel.seq)
                )
            )
            .scalars()
            .first()
        )
        event.metadata_json = '{"n": 6660}'
        session.add(event)
        await session.commit()

    tampered = await verify_audit_chain(wallet_id=None)
    assert tampered.valid is False
    assert tampered.reason == "audit_payload_hash_mismatch"


@pytest.mark.anyio
async def test_verify_detects_tail_truncation(clean_database):
    """Deleting the last events of a chain must be detected via the head
    anchor -- a valid prefix must not verify as a valid whole chain."""
    wallet_id = "wlt-truncation-test"
    for n in range(3):
        await record_audit_event(
            event="trust.trunc", wallet_id=wallet_id, metadata={"n": n}
        )

    assert (await verify_audit_chain(wallet_id=wallet_id)).valid is True

    # Delete the last event (seq=3); head still says last_seq=3.
    factory = get_session_factory()
    async with factory() as session:
        last = (
            (
                await session.execute(
                    select(ControlPlaneAuditEventModel)
                    .where(ControlPlaneAuditEventModel.wallet_id == wallet_id)
                    .order_by(ControlPlaneAuditEventModel.seq.desc())
                )
            )
            .scalars()
            .first()
        )
        await session.delete(last)
        await session.commit()

    result = await verify_audit_chain(wallet_id=wallet_id)
    assert result.valid is False
    assert result.reason == "audit_chain_truncated"

    # And the global path surfaces it too.
    global_result = await verify_audit_chain(wallet_id=None)
    assert global_result.valid is False
    assert global_result.reason == "audit_chain_truncated"


@pytest.mark.anyio
async def test_global_verify_detects_fully_deleted_wallet_via_head(clean_database):
    """Deleting ALL of a wallet's events must still be caught globally.

    Regression: the global verify enumerated wallets from the events table, so a
    wallet whose every event was deleted vanished from the check entirely. It is
    enumerated from the surviving chain-head rows too, so the truncation is
    caught.
    """
    wallet_id = "wlt-fulldelete-test"
    for n in range(3):
        await record_audit_event(
            event="trust.fulldel", wallet_id=wallet_id, metadata={"n": n}
        )
    assert (await verify_audit_chain(wallet_id=None)).valid is True

    factory = get_session_factory()
    async with factory() as session:
        events = (
            (
                await session.execute(
                    select(ControlPlaneAuditEventModel).where(
                        ControlPlaneAuditEventModel.wallet_id == wallet_id
                    )
                )
            )
            .scalars()
            .all()
        )
        for event in events:
            await session.delete(event)
        await session.commit()

    result = await verify_audit_chain(wallet_id=None)
    assert result.valid is False
    assert result.reason == "audit_chain_truncated"
