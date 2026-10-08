"""Adversarial checks for the audit hash chain and its verify route.

Each test names a break that verification used to miss or mis-report:
a time window that hides tampering or truncation, a sequence hole whose
hashes still line up, a deleted head anchor, a blank wallet id that shares
the wallet-less head, and a replay that adopts a row with a bad signature.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from app.db.models import AuditChainHeadModel, ControlPlaneAuditEventModel
from app.main import app
from app.services.audit_chain import AuditEventConflictError, verify_audit_chain
from app.services.audit_log import record_audit_event
from app.services.signing_keys import sha256_hex
from sqlalchemy import select

from tests.test_trust_helpers import BOOTSTRAP_HEADERS


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _chain_hash(previous_hash: str | None, payload_hash: str, signature: str) -> str:
    return sha256_hex(
        {
            "previous_hash": previous_hash,
            "payload_hash": payload_hash,
            "signature": signature,
        }
    )


def select_events(wallet_id: str | None):
    stmt = select(ControlPlaneAuditEventModel).order_by(ControlPlaneAuditEventModel.seq)
    if wallet_id is None:
        return stmt.where(ControlPlaneAuditEventModel.wallet_id.is_(None))
    return stmt.where(ControlPlaneAuditEventModel.wallet_id == wallet_id)


async def _provision_wallet(client: AsyncClient, *, name: str) -> dict[str, str]:
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": name,
            "email": f"{name}@example.com",
            "initial_credits": 1000,
            "require_kyc": False,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert sponsor.status_code == 201, sponsor.text
    sponsor_id = sponsor.json()["wallet_id"]
    agent = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor_id,
            "agent_id": name,
            "budget_credits": 100,
            "daily_limit": 50,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert agent.status_code == 201, agent.text
    wallet_id = agent.json()["wallet_id"]
    key = await client.post(
        "/v1/api-keys",
        json={
            "wallet_id": wallet_id,
            "key_name": name,
            "expires_in_days": 30,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert key.status_code == 201, key.text
    return {
        "wallet_id": wallet_id,
        "headers": {"X-API-Key": key.json()["api_key"]},
    }


@pytest.mark.anyio
async def test_time_window_does_not_hide_an_earlier_tampered_payload(clean_database):
    wallet_id = "wlt-window-tamper"
    base = datetime(2026, 1, 1, 0, 0, 0)
    for hour in range(3):
        await record_audit_event(
            event="trust.window",
            wallet_id=wallet_id,
            created_at=base + timedelta(hours=hour),
            metadata={"n": hour},
        )

    factory = get_session_factory()
    async with factory() as session:
        first = (await session.execute(select_events(wallet_id))).scalars().first()
        first.metadata_json = '{"n": 999}'
        session.add(first)
        await session.commit()

    # The window contains only the last event. Its own link is intact, so a
    # verifier that never opens the earlier rows used to answer valid.
    windowed = await verify_audit_chain(
        wallet_id=wallet_id,
        created_after=base + timedelta(hours=2),
    )
    assert windowed.valid is False
    assert windowed.reason == "audit_payload_hash_mismatch"


@pytest.mark.anyio
async def test_time_window_does_not_hide_tail_truncation(clean_database):
    wallet_id = "wlt-window-truncate"
    base = datetime(2026, 2, 1, 0, 0, 0)
    for hour in range(3):
        await record_audit_event(
            event="trust.truncate",
            wallet_id=wallet_id,
            created_at=base + timedelta(hours=hour),
            metadata={"n": hour},
        )

    factory = get_session_factory()
    async with factory() as session:
        rows = (await session.execute(select_events(wallet_id))).scalars().all()
        await session.delete(rows[-1])
        await session.commit()

    # A bound that matches every surviving row, and a bound that matches
    # nothing, both used to skip the head and report a valid chain.
    covered = await verify_audit_chain(
        wallet_id=wallet_id,
        created_after=base - timedelta(days=1),
    )
    empty = await verify_audit_chain(
        wallet_id=wallet_id,
        created_after=base + timedelta(days=30),
    )
    assert covered.valid is False
    assert covered.reason == "audit_chain_truncated"
    assert empty.valid is False
    assert empty.reason == "audit_chain_truncated"


@pytest.mark.anyio
async def test_verify_route_reports_truncation_inside_a_time_window(
    client, clean_database
):
    wallet_id = "wlt-route-truncate"
    base = datetime(2026, 2, 2, 0, 0, 0)
    for hour in range(2):
        await record_audit_event(
            event="trust.route",
            wallet_id=wallet_id,
            created_at=base + timedelta(hours=hour),
            metadata={"n": hour},
        )
    factory = get_session_factory()
    async with factory() as session:
        last = (await session.execute(select_events(wallet_id))).scalars().all()[-1]
        await session.delete(last)
        await session.commit()

    response = await client.post(
        "/v1/audit/verify-chain",
        json={
            "wallet_id": wallet_id,
            "created_after": "2000-01-01T00:00:00",
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["reason"] == "audit_chain_truncated"


@pytest.mark.anyio
async def test_sequence_gap_with_intact_hashes_is_rejected(clean_database):
    wallet_id = "wlt-seq-gap"
    for n in range(3):
        await record_audit_event(
            event="trust.gap",
            wallet_id=wallet_id,
            metadata={"n": n},
        )

    factory = get_session_factory()
    async with factory() as session:
        rows = (await session.execute(select_events(wallet_id))).scalars().all()
        # seq is not covered by the signature. Bumping the tail number and
        # the head leaves every hash in place and opens a hole at 3.
        rows[2].seq = 4
        head = await session.get(AuditChainHeadModel, wallet_id)
        head.last_seq = 4
        await session.commit()
        broken_id = rows[2].event_id

    result = await verify_audit_chain(wallet_id=wallet_id)
    assert result.valid is False
    assert result.reason == "audit_sequence_gap"
    assert result.broken_event_id == broken_id


@pytest.mark.anyio
async def test_deleting_the_head_and_the_tail_is_rejected(clean_database):
    wallet_id = "wlt-head-gone"
    for n in range(3):
        await record_audit_event(
            event="trust.head",
            wallet_id=wallet_id,
            metadata={"n": n},
        )

    factory = get_session_factory()
    async with factory() as session:
        rows = (await session.execute(select_events(wallet_id))).scalars().all()
        await session.delete(rows[-1])
        head = await session.get(AuditChainHeadModel, wallet_id)
        await session.delete(head)
        await session.commit()

    result = await verify_audit_chain(wallet_id=wallet_id)
    assert result.valid is False
    assert result.reason == "audit_chain_head_missing"

    global_result = await verify_audit_chain(wallet_id=None)
    assert global_result.valid is False
    assert global_result.reason == "audit_chain_head_missing"


@pytest.mark.anyio
async def test_out_of_order_created_at_window_stays_valid(clean_database):
    wallet_id = "wlt-time-order"
    later = datetime(2026, 6, 1, 12, 0, 0)
    earlier = later - timedelta(days=2)
    await record_audit_event(
        event="trust.order",
        wallet_id=wallet_id,
        created_at=later,
        metadata={"n": 1},
    )
    await record_audit_event(
        event="trust.order",
        wallet_id=wallet_id,
        created_at=earlier,
        metadata={"n": 2},
    )

    whole = await verify_audit_chain(wallet_id=wallet_id)
    assert whole.valid is True
    assert whole.checked_events == 2

    # The second append carries an earlier timestamp, so a created_before
    # bound keeps that row and drops the genesis row. The chain is still honest.
    window = await verify_audit_chain(
        wallet_id=wallet_id,
        created_before=later - timedelta(days=1),
    )
    assert window.valid is True, window
    assert window.checked_events == 1


@pytest.mark.anyio
async def test_blank_wallet_id_does_not_split_the_wallet_less_chain(clean_database):
    await record_audit_event(event="system.denied", wallet_id=None, metadata={"n": 1})
    await record_audit_event(event="system.denied", wallet_id="", metadata={"n": 2})
    await record_audit_event(event="system.denied", wallet_id="   ", metadata={"n": 3})

    result = await verify_audit_chain(wallet_id=None)
    assert result.valid is True, result
    assert result.checked_events == 3

    blank = await verify_audit_chain(wallet_id="")
    assert blank.valid is True, blank
    assert blank.checked_events == 3

    spaced = await verify_audit_chain(wallet_id="   ")
    assert spaced.valid is True, spaced
    assert spaced.checked_events == 3

    from app.services.audit_chain import sign_audit_model

    factory = get_session_factory()
    async with factory() as session:
        tail = (await session.execute(select_events(None))).scalars().all()[-1]
        tail_hash = tail.chain_hash
    pending = ControlPlaneAuditEventModel(
        event_id="audit-blank-sign",
        event="system.denied",
        wallet_id=None,
    )
    await sign_audit_model(pending)
    assert pending.seq == 4
    assert pending.previous_hash == tail_hash


@pytest.mark.anyio
async def test_replay_rejects_a_row_whose_signature_was_replaced(clean_database):
    wallet_id = "wlt-replay-sig"
    created_at = datetime(2026, 4, 1, 12, 0, 0)
    kwargs = {
        "event": "mcp.invoke",
        "event_id": "audit-replay-sig-tamper",
        "created_at": created_at,
        "wallet_id": wallet_id,
        "tool": "partner.lookup",
        "endpoint": "/mcp/invoke",
        "request_id": "replay-sig",
        "metadata": {"n": 1},
    }
    first = await record_audit_event(**kwargs)
    again = await record_audit_event(**kwargs)
    assert again.event_id == first.event_id

    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(ControlPlaneAuditEventModel, first.event_id)
        row.signature = base64.b64encode(b"x" * 64).decode()
        row.chain_hash = _chain_hash(row.previous_hash, row.payload_hash, row.signature)
        await session.commit()

    with pytest.raises(AuditEventConflictError, match="audit_event_integrity_conflict"):
        await record_audit_event(**kwargs)

    verdict = await verify_audit_chain(wallet_id=wallet_id)
    assert verdict.valid is False
    assert verdict.reason == "audit_signature_invalid"


@pytest.mark.anyio
async def test_tampered_previous_hash_is_rejected(clean_database):
    wallet_id = "wlt-prev-hash"
    await record_audit_event(event="trust.prev", wallet_id=wallet_id, metadata={"n": 1})
    await record_audit_event(event="trust.prev", wallet_id=wallet_id, metadata={"n": 2})

    factory = get_session_factory()
    async with factory() as session:
        rows = (await session.execute(select_events(wallet_id))).scalars().all()
        # Point the second link at a different predecessor and rebuild the
        # stored hashes so only the signature and the real link can catch it.
        rows[1].previous_hash = "ab" * 32
        payload = {
            "event_id": rows[1].event_id,
            "created_at": rows[1].created_at,
            "event": rows[1].event,
            "wallet_id": rows[1].wallet_id,
            "tool": rows[1].tool,
            "endpoint": rows[1].endpoint,
            "auth_source": rows[1].auth_source,
            "key_id": rows[1].key_id,
            "policy_decision_id": rows[1].policy_decision_id,
            "request_id": rows[1].request_id,
            "ok": rows[1].ok,
            "error": rows[1].error,
            "metadata_json": rows[1].metadata_json,
            "previous_hash": rows[1].previous_hash,
        }
        from app.services.audit_chain import audit_payload

        payload = audit_payload(**payload)
        rows[1].payload_hash = sha256_hex(payload)
        rows[1].chain_hash = _chain_hash(
            rows[1].previous_hash, rows[1].payload_hash, rows[1].signature
        )
        broken_id = rows[1].event_id
        await session.commit()

    result = await verify_audit_chain(wallet_id=wallet_id)
    assert result.valid is False
    assert result.reason == "audit_previous_hash_mismatch"
    assert result.broken_event_id == broken_id


@pytest.mark.anyio
async def test_concurrent_appends_stay_one_contiguous_chain(clean_database):
    wallet_id = "wlt-race"
    await asyncio.gather(
        *(
            record_audit_event(
                event="trust.race",
                wallet_id=wallet_id,
                metadata={"n": n},
            )
            for n in range(8)
        )
    )

    result = await verify_audit_chain(wallet_id=wallet_id)
    assert result.valid is True
    assert result.checked_events == 8

    factory = get_session_factory()
    async with factory() as session:
        rows = (await session.execute(select_events(wallet_id))).scalars().all()
        head = await session.get(AuditChainHeadModel, wallet_id)
    assert [row.seq for row in rows] == list(range(1, 9))
    assert rows[0].previous_hash is None
    for earlier, later in zip(rows, rows[1:]):
        assert later.previous_hash == earlier.chain_hash
    assert head is not None
    assert head.last_seq == 8
    assert head.last_chain_hash == rows[-1].chain_hash


@pytest.mark.anyio
async def test_wallet_key_cannot_verify_another_wallets_chain(client, clean_database):
    first = await _provision_wallet(client, name="audit-break-one")
    second = await _provision_wallet(client, name="audit-break-two")
    await record_audit_event(
        event="trust.scope",
        wallet_id=second["wallet_id"],
        metadata={"n": 1},
    )

    response = await client.post(
        "/v1/audit/verify-chain",
        json={"wallet_id": second["wallet_id"]},
        headers=first["headers"],
    )
    assert response.status_code == 403

    own = await client.post(
        "/v1/audit/verify-chain",
        json={},
        headers=second["headers"],
    )
    assert own.status_code == 200
    assert own.json()["valid"] is True
    assert own.json()["checked_events"] == 1


@pytest.mark.anyio
async def test_malformed_signature_is_an_invalid_chain_not_an_error(
    client, clean_database
):
    wallet_id = "wlt-bad-sig"
    event = await record_audit_event(
        event="trust.sig",
        wallet_id=wallet_id,
        metadata={"n": 1},
    )
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(ControlPlaneAuditEventModel, event.event_id)
        row.signature = "@@@"
        await session.commit()

    response = await client.post(
        "/v1/audit/verify-chain",
        json={"wallet_id": wallet_id},
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["reason"] == "audit_signature_invalid"
