from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import asc, desc, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db.database import get_session_factory
from app.db.models import AuditChainHeadModel, ControlPlaneAuditEventModel
from app.services.signing_keys import get_signing_key_service, sha256_hex


def audit_payload(
    *,
    event_id: str,
    created_at: datetime,
    event: str,
    wallet_id: str | None,
    tool: str | None,
    endpoint: str | None,
    auth_source: str | None,
    key_id: str | None,
    policy_decision_id: str | None,
    request_id: str | None,
    ok: bool,
    error: str | None,
    metadata_json: str | None,
    previous_hash: str | None,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "created_at": created_at,
        "event": event,
        "wallet_id": wallet_id,
        "tool": tool,
        "endpoint": endpoint,
        "auth_source": auth_source,
        "key_id": key_id,
        "policy_decision_id": policy_decision_id,
        "request_id": request_id,
        "ok": ok,
        "error": error,
        "metadata_json": metadata_json,
        "previous_hash": previous_hash,
    }


def _sign_with_previous(
    model: ControlPlaneAuditEventModel,
    previous_hash: str | None,
    *,
    signing_key_id: str,
) -> None:
    """Sign ``model`` as the successor of ``previous_hash`` (seq set by caller).

    Pure (no DB I/O) so it can run inside an open chain-head transaction. The
    active signing key must be ensured by the caller beforehand. seq is
    deliberately NOT part of the signed payload, so events signed before that
    column existed still verify.
    """
    payload = audit_payload(
        event_id=model.event_id,
        created_at=model.created_at,
        event=model.event,
        wallet_id=model.wallet_id,
        tool=model.tool,
        endpoint=model.endpoint,
        auth_source=model.auth_source,
        key_id=model.key_id,
        policy_decision_id=model.policy_decision_id,
        request_id=model.request_id,
        ok=model.ok,
        error=model.error,
        metadata_json=model.metadata_json,
        previous_hash=previous_hash,
    )
    payload_hash = sha256_hex(payload)
    payload["payload_hash"] = payload_hash
    signature, signature_key_id, _ = get_signing_key_service().sign_payload_with_key_id(
        payload, signing_key_id
    )
    model.payload_hash = payload_hash
    model.previous_hash = previous_hash
    model.chain_hash = sha256_hex(
        {
            "previous_hash": previous_hash,
            "payload_hash": payload_hash,
            "signature": signature,
        }
    )
    model.signature = signature
    model.signature_key_id = signature_key_id


async def sign_audit_model(model: ControlPlaneAuditEventModel) -> None:
    """Sign an audit event by reading the current chain head (no insert).

    Self-contained convenience used outside the append path; the persisted
    write path uses :func:`append_chained_audit_event`, which serializes
    concurrent writers.
    """
    key = await get_signing_key_service().ensure_active_key()
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(ControlPlaneAuditEventModel)
            .where(ControlPlaneAuditEventModel.wallet_id == model.wallet_id)
            .order_by(
                desc(ControlPlaneAuditEventModel.seq),
                desc(ControlPlaneAuditEventModel.created_at),
            )
            .limit(1)
        )
        previous = result.scalar_one_or_none()
    previous_hash = previous.chain_hash if previous else None
    model.seq = (previous.seq + 1) if previous else 1
    _sign_with_previous(model, previous_hash, signing_key_id=key.key_id)


class _HeadConflict(Exception):
    """A concurrent writer advanced the chain head; the append must retry."""


async def append_chained_audit_event(model: ControlPlaneAuditEventModel) -> None:
    """Sign and persist ``model`` as the next link in its wallet's audit chain.

    Concurrency is handled with optimistic control on the per-wallet head row:
    the new ``seq``/``previous_hash`` are derived from the head, then the head
    is advanced with a conditional ``UPDATE ... WHERE last_seq = <observed>``.
    If a concurrent writer advanced the head first the update matches no rows
    and the append retries against the new head. This works identically on
    SQLite and Postgres (no reliance on ``SELECT ... FOR UPDATE``), so two
    racing writers can never share a predecessor and fork the chain.
    """
    wallet_key = model.wallet_id or ""
    # Provision the active signing key before the transaction so signing inside
    # it is pure crypto (no nested DB write / lock).
    key = await get_signing_key_service().ensure_active_key()
    factory = get_session_factory()
    # Optimistic-concurrency retry budget. Audit events are integrity records
    # and must not be dropped, so the budget is generous; backoff is a small
    # flat jitter (not growing) so contended writers reconverge quickly without
    # inflating tail latency on slow/CPU-bound runners.
    attempts = 64
    for attempt in range(attempts):
        session = factory()
        try:
            async with session.begin():
                row = (
                    await session.execute(
                        select(
                            AuditChainHeadModel.last_seq,
                            AuditChainHeadModel.last_chain_hash,
                        ).where(AuditChainHeadModel.wallet_key == wallet_key)
                    )
                ).first()
                observed_seq = row[0] if row else 0
                previous_hash = row[1] if row else None
                model.seq = observed_seq + 1
                _sign_with_previous(model, previous_hash, signing_key_id=key.key_id)
                now = datetime.now(timezone.utc)
                if row is None:
                    # First event for this wallet; a unique PK collision means a
                    # concurrent writer won the race — retry against their head.
                    session.add(
                        AuditChainHeadModel(
                            wallet_key=wallet_key,
                            last_seq=model.seq,
                            last_chain_hash=model.chain_hash,
                            updated_at=now,
                        )
                    )
                    await session.flush()
                else:
                    result = await session.execute(
                        update(AuditChainHeadModel)
                        .where(
                            AuditChainHeadModel.wallet_key == wallet_key,
                            AuditChainHeadModel.last_seq == observed_seq,
                        )
                        .values(
                            last_seq=model.seq,
                            last_chain_hash=model.chain_hash,
                            updated_at=now,
                        )
                    )
                    if result.rowcount == 0:
                        raise _HeadConflict()
                session.add(model)
            return
        except (_HeadConflict, IntegrityError, OperationalError):
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(random.uniform(0.002, 0.02))
        finally:
            await session.close()
    raise RuntimeError("audit_chain_head_contention")


@dataclass(frozen=True)
class AuditChainVerification:
    valid: bool
    checked_events: int
    first_event_id: str | None = None
    last_event_id: str | None = None
    reason: str | None = None
    broken_event_id: str | None = None


async def verify_audit_chain(
    *,
    wallet_id: str | None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> AuditChainVerification:
    if wallet_id is None:
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(ControlPlaneAuditEventModel.wallet_id).distinct()
            )
            wallet_ids = [row[0] for row in result.all() if row[0] is not None]
        checked = 0
        first_event_id: str | None = None
        last_event_id: str | None = None
        for current_wallet_id in wallet_ids:
            result = await verify_audit_chain(
                wallet_id=current_wallet_id,
                created_after=created_after,
                created_before=created_before,
            )
            checked += result.checked_events
            first_event_id = first_event_id or result.first_event_id
            last_event_id = result.last_event_id or last_event_id
            if not result.valid:
                return AuditChainVerification(
                    False,
                    checked,
                    first_event_id,
                    last_event_id,
                    result.reason,
                    result.broken_event_id,
                )
        return AuditChainVerification(True, checked, first_event_id, last_event_id)

    stmt = select(ControlPlaneAuditEventModel).order_by(
        asc(ControlPlaneAuditEventModel.seq),
        asc(ControlPlaneAuditEventModel.created_at),
    )
    if wallet_id:
        stmt = stmt.where(ControlPlaneAuditEventModel.wallet_id == wallet_id)
    if created_after:
        stmt = stmt.where(ControlPlaneAuditEventModel.created_at >= created_after)
    if created_before:
        stmt = stmt.where(ControlPlaneAuditEventModel.created_at <= created_before)

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(stmt)
        events = list(result.scalars().all())

    previous_hash: str | None = None
    first_event_id = events[0].event_id if events else None
    last_event_id = events[-1].event_id if events else None
    for event in events:
        payload = audit_payload(
            event_id=event.event_id,
            created_at=event.created_at,
            event=event.event,
            wallet_id=event.wallet_id,
            tool=event.tool,
            endpoint=event.endpoint,
            auth_source=event.auth_source,
            key_id=event.key_id,
            policy_decision_id=event.policy_decision_id,
            request_id=event.request_id,
            ok=event.ok,
            error=event.error,
            metadata_json=event.metadata_json,
            previous_hash=event.previous_hash,
        )
        payload_hash = sha256_hex(payload)
        if event.payload_hash != payload_hash:
            return AuditChainVerification(
                False,
                len(events),
                first_event_id,
                last_event_id,
                "audit_payload_hash_mismatch",
                event.event_id,
            )
        if event.previous_hash != previous_hash:
            return AuditChainVerification(
                False,
                len(events),
                first_event_id,
                last_event_id,
                "audit_previous_hash_mismatch",
                event.event_id,
            )
        if not event.signature or not event.signature_key_id:
            return AuditChainVerification(
                False,
                len(events),
                first_event_id,
                last_event_id,
                "audit_signature_missing",
                event.event_id,
            )
        signed_payload = {
            **payload,
            "payload_hash": event.payload_hash,
            "alg": "Ed25519",
            "kid": event.signature_key_id,
        }
        ok = await get_signing_key_service().verify_payload(
            signed_payload,
            signature=event.signature,
            key_id=event.signature_key_id,
        )
        if not ok:
            return AuditChainVerification(
                False,
                len(events),
                first_event_id,
                last_event_id,
                "audit_signature_invalid",
                event.event_id,
            )
        expected_chain_hash = sha256_hex(
            {
                "previous_hash": event.previous_hash,
                "payload_hash": event.payload_hash,
                "signature": event.signature,
            }
        )
        if event.chain_hash != expected_chain_hash:
            return AuditChainVerification(
                False,
                len(events),
                first_event_id,
                last_event_id,
                "audit_chain_hash_mismatch",
                event.event_id,
            )
        previous_hash = event.chain_hash

    return AuditChainVerification(
        True,
        len(events),
        first_event_id,
        last_event_id,
    )
