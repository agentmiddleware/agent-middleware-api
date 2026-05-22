from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.database import get_session_factory
from app.db.models import AuditChainHeadModel, ControlPlaneAuditEventModel
from app.main import app
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
            record_audit_event(event="trust.race", wallet_id=wallet_id, metadata={"n": n})
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
async def test_audit_chain_orders_by_monotonic_sequence(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]

    # Rapid same-wallet events can share a created_at timestamp; the chain must
    # still order deterministically and verify.
    for n in range(12):
        await record_audit_event(event="trust.seq", wallet_id=wallet_id, metadata={"n": n})

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
