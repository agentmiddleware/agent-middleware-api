from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import asc, desc, select

from app.db.database import get_session_factory
from app.db.models import ControlPlaneAuditEventModel
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


async def sign_audit_model(model: ControlPlaneAuditEventModel) -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(ControlPlaneAuditEventModel)
            .where(ControlPlaneAuditEventModel.wallet_id == model.wallet_id)
            .order_by(desc(ControlPlaneAuditEventModel.created_at))
            .limit(1)
        )
        previous = result.scalar_one_or_none()
    previous_hash = previous.chain_hash if previous else None
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
    signature, signature_key_id, _ = await get_signing_key_service().sign_payload(payload)
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
        asc(ControlPlaneAuditEventModel.created_at)
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
