from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import AuditChainHeadModel, ControlPlaneAuditEventModel
from app.services.audit_chain import (
    AUDIT_PAYLOAD_VERSION,
    audit_payload,
    verify_audit_chain,
)
from app.services.audit_log import record_audit_event
from app.services.signing_keys import get_signing_key_service, sha256_hex


@pytest.mark.anyio
async def test_new_entries_bind_seq_in_signed_payload(clean_database):
    """New entries sign their chain position plus a version marker.

    The stored payload hash must match the sequence-bound shape and must not
    match the historic shape, which proves the sequence number is covered by
    the signature and not just stored alongside it.
    """
    wallet_id = "wlt-seq-v2-bound"
    await record_audit_event(event="trust.seq", wallet_id=wallet_id, metadata={"n": 1})
    await record_audit_event(event="trust.seq", wallet_id=wallet_id, metadata={"n": 2})

    result = await verify_audit_chain(wallet_id=wallet_id)
    assert result.valid is True
    assert result.checked_events == 2

    factory = get_session_factory()
    async with factory() as session:
        events = (
            (
                await session.execute(
                    select(ControlPlaneAuditEventModel)
                    .where(ControlPlaneAuditEventModel.wallet_id == wallet_id)
                    .order_by(ControlPlaneAuditEventModel.seq)
                )
            )
            .scalars()
            .all()
        )
    assert [event.seq for event in events] == [1, 2]
    for event in events:
        base_kwargs = {
            "event_id": event.event_id,
            "created_at": event.created_at,
            "event": event.event,
            "wallet_id": event.wallet_id,
            "tool": event.tool,
            "endpoint": event.endpoint,
            "auth_source": event.auth_source,
            "key_id": event.key_id,
            "policy_decision_id": event.policy_decision_id,
            "request_id": event.request_id,
            "ok": event.ok,
            "error": event.error,
            "metadata_json": event.metadata_json,
            "previous_hash": event.previous_hash,
        }
        assert event.payload_hash == sha256_hex(
            audit_payload(**base_kwargs, seq=event.seq)
        )
        assert event.payload_hash != sha256_hex(audit_payload(**base_kwargs))
        signed = audit_payload(**base_kwargs, seq=event.seq)
        assert signed["seq"] == event.seq
        assert signed["audit_payload_version"] == AUDIT_PAYLOAD_VERSION


@pytest.mark.anyio
async def test_historic_entries_without_seq_still_verify(clean_database):
    """Entries signed before the sequence number joined the payload verify.

    Builds one entry in the old shape (no sequence number, no marker), signs
    it, stores it with its head row, and checks the chain verifies. This is
    the backward compatibility guard for every entry written before this fix.
    """
    wallet_id = "wlt-seq-v1-compat"
    created_at = utc_now()
    payload = audit_payload(
        event_id="audit-v1-compat",
        created_at=created_at,
        event="trust.legacy",
        wallet_id=wallet_id,
        tool=None,
        endpoint=None,
        auth_source=None,
        key_id=None,
        policy_decision_id=None,
        request_id=None,
        ok=True,
        error=None,
        metadata_json=json.dumps({"n": 1}),
        previous_hash=None,
    )
    assert "seq" not in payload
    assert "audit_payload_version" not in payload

    key = await get_signing_key_service().ensure_active_key()
    payload_hash = sha256_hex(payload)
    signing_payload = dict(payload)
    signing_payload["payload_hash"] = payload_hash
    signature, signature_key_id, _ = get_signing_key_service().sign_payload_with_key_id(
        signing_payload, key.key_id
    )
    chain_hash = sha256_hex(
        {
            "previous_hash": None,
            "payload_hash": payload_hash,
            "signature": signature,
        }
    )
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            session.add(
                ControlPlaneAuditEventModel(
                    event_id="audit-v1-compat",
                    created_at=created_at,
                    seq=1,
                    event="trust.legacy",
                    wallet_id=wallet_id,
                    ok=True,
                    metadata_json=json.dumps({"n": 1}),
                    payload_hash=payload_hash,
                    previous_hash=None,
                    chain_hash=chain_hash,
                    signature=signature,
                    signature_key_id=signature_key_id,
                )
            )
            session.add(
                AuditChainHeadModel(
                    wallet_key=wallet_id,
                    last_seq=1,
                    last_chain_hash=chain_hash,
                )
            )

    result = await verify_audit_chain(wallet_id=wallet_id)
    assert result.valid is True
    assert result.checked_events == 1


@pytest.mark.anyio
async def test_reordered_chain_is_detected(clean_database):
    """Swapping the sequence numbers of two entries breaks verification.

    The payload hash check runs before the predecessor link check, so a
    renumbered entry is reported as a payload mismatch on the entry that now
    sorts first, because its stored signature no longer matches its position.
    """
    wallet_id = "wlt-seq-reorder"
    first = await record_audit_event(
        event="trust.seq", wallet_id=wallet_id, metadata={"n": 1}
    )
    second = await record_audit_event(
        event="trust.seq", wallet_id=wallet_id, metadata={"n": 2}
    )
    assert (await verify_audit_chain(wallet_id=wallet_id)).valid is True

    factory = get_session_factory()
    async with factory() as session:
        event_a = await session.get(ControlPlaneAuditEventModel, first.event_id)
        event_b = await session.get(ControlPlaneAuditEventModel, second.event_id)
        assert event_a is not None and event_b is not None
        event_a.seq, event_b.seq = event_b.seq, event_a.seq
        session.add(event_a)
        session.add(event_b)
        await session.commit()

    result = await verify_audit_chain(wallet_id=wallet_id)
    assert result.valid is False
    assert result.reason == "audit_payload_hash_mismatch"
    assert result.broken_event_id == second.event_id


@pytest.mark.anyio
async def test_seq_tamper_with_fixed_head_is_detected(clean_database):
    """Renumbering an entry while fixing the unsigned head still fails.

    The head row carries no signature, so an attacker with database write
    access could renumber the last entry and move the head to match. The visit
    order and predecessor links are unchanged by that, so only the bound
    sequence number catches it.
    """
    wallet_id = "wlt-seq-tamper"
    await record_audit_event(event="trust.seq", wallet_id=wallet_id, metadata={"n": 1})
    last = await record_audit_event(
        event="trust.seq", wallet_id=wallet_id, metadata={"n": 2}
    )
    assert (await verify_audit_chain(wallet_id=wallet_id)).valid is True

    factory = get_session_factory()
    async with factory() as session:
        event = await session.get(ControlPlaneAuditEventModel, last.event_id)
        assert event is not None
        event.seq = 7
        session.add(event)
        head = await session.get(AuditChainHeadModel, wallet_id)
        assert head is not None
        head.last_seq = 7
        session.add(head)
        await session.commit()

    result = await verify_audit_chain(wallet_id=wallet_id)
    assert result.valid is False
    assert result.reason == "audit_payload_hash_mismatch"
    assert result.broken_event_id == last.event_id
