"""Service-layer ownership for permit revocation and budget releases.

The web route checks today, but these service functions must refuse a
non-owning caller on their own so a future caller cannot revoke a permit
or erase its spending for anyone. Every budget release also writes one
audit entry through the existing audit logger.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel, McpDispatchAttemptModel
from app.main import app
from app.schemas.trust import PermitCreateRequest
from app.services.audit_log import list_audit_events
from app.services.permits import PermitError, get_permit_service
from tests.test_trust_helpers import provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _mint_permit(client, wallet_id, **overrides):
    params: dict = {
        "issuer_wallet_id": wallet_id,
        "subject_wallet_id": wallet_id,
        "allowed_tools": ["authz-tool"],
        "scopes": ["tool:authz-tool:invoke"],
        "max_credits": Decimal("10"),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    params.update(overrides)
    return await get_permit_service().create_permit(PermitCreateRequest(**params))


@pytest.mark.anyio
async def test_revoke_refuses_non_owner_and_anonymous_at_service_layer(
    client, clean_database
):
    owner = await provision_agent_wallet(client)
    other = await provision_agent_wallet(client)
    permit = await _mint_permit(client, owner["agent_wallet_id"])

    with pytest.raises(PermitError) as denied:
        await get_permit_service().revoke_permit(
            permit.permit_id, caller_wallet_id=other["agent_wallet_id"]
        )
    assert denied.value.reason == "permit_access_denied"

    with pytest.raises(PermitError) as anonymous:
        await get_permit_service().revoke_permit(permit.permit_id)
    assert anonymous.value.reason == "permit_access_denied"

    still_active = await get_permit_service().get_permit(permit.permit_id)
    assert still_active is not None and still_active.status == "active"


@pytest.mark.anyio
async def test_revoke_owner_and_admin_succeed(client, clean_database):
    owner = await provision_agent_wallet(client)
    service = get_permit_service()
    permit = await _mint_permit(client, owner["agent_wallet_id"])

    revoked = await service.revoke_permit(
        permit.permit_id, caller_wallet_id=owner["agent_wallet_id"]
    )
    assert revoked.status == "revoked"

    other_permit = await _mint_permit(client, owner["agent_wallet_id"])
    admin_revoked = await service.revoke_permit(
        other_permit.permit_id, is_bootstrap_admin=True
    )
    assert admin_revoked.status == "revoked"


@pytest.mark.anyio
async def test_release_budget_refuses_non_owner_and_audits_owner(
    client, clean_database
):
    owner = await provision_agent_wallet(client)
    other = await provision_agent_wallet(client)
    service = get_permit_service()
    permit = await _mint_permit(client, owner["agent_wallet_id"])
    await service.reserve_budget(permit.permit_id, Decimal("4"))

    with pytest.raises(PermitError) as denied:
        await service.release_budget(
            permit.permit_id,
            Decimal("4"),
            caller_wallet_id=other["agent_wallet_id"],
        )
    assert denied.value.reason == "permit_access_denied"
    untouched = await service.get_permit(permit.permit_id)
    assert untouched is not None and untouched.spent_credits == Decimal("4")

    await service.release_budget(
        permit.permit_id,
        Decimal("4"),
        caller_wallet_id=owner["agent_wallet_id"],
    )
    released = await service.get_permit(permit.permit_id)
    assert released is not None and released.spent_credits == Decimal("0")

    events = await list_audit_events(
        event="permit_budget_released",
        wallet_id=owner["agent_wallet_id"],
    )
    matches = [e for e in events if e.metadata.get("permit_id") == permit.permit_id]
    assert len(matches) == 1
    assert matches[0].metadata["amount"] == "4"
    assert matches[0].metadata["actor"] == "owner"


@pytest.mark.anyio
async def test_release_tool_call_refuses_non_owner(client, clean_database):
    owner = await provision_agent_wallet(client)
    other = await provision_agent_wallet(client)
    service = get_permit_service()
    permit = await _mint_permit(
        client,
        owner["agent_wallet_id"],
        max_calls_per_tool={"authz-tool": 3},
    )
    validation = await service.authorize_and_reserve(
        permit_id=permit.permit_id,
        wallet_id=owner["agent_wallet_id"],
        tool_name="authz-tool",
        estimated_credits=Decimal("1"),
        key_id=owner["key_id"],
    )
    assert validation.allowed is True

    with pytest.raises(PermitError) as denied:
        await service.release_tool_call(
            permit.permit_id,
            "authz-tool",
            caller_wallet_id=other["agent_wallet_id"],
        )
    assert denied.value.reason == "permit_access_denied"

    await service.release_tool_call(
        permit.permit_id,
        "authz-tool",
        caller_wallet_id=owner["agent_wallet_id"],
    )
    validation = await service.validate_for_action(
        permit_id=permit.permit_id,
        wallet_id=owner["agent_wallet_id"],
        tool_name="authz-tool",
        estimated_credits=Decimal("1"),
        key_id=owner["key_id"],
    )
    assert validation.allowed is True


@pytest.mark.anyio
async def test_release_dispatch_budget_refuses_non_owner_and_audits_system(
    client, clean_database
):
    owner = await provision_agent_wallet(client)
    other = await provision_agent_wallet(client)
    service = get_permit_service()
    permit = await _mint_permit(client, owner["agent_wallet_id"])
    await service.reserve_budget(permit.permit_id, Decimal("3"))

    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            session.add(
                IdempotencyRecordModel(
                    record_id="idem-authz-1",
                    wallet_id=owner["agent_wallet_id"],
                    endpoint="/mcp/invoke",
                    idempotency_key="authz-1",
                    request_hash="b" * 64,
                )
            )
            session.add(
                McpDispatchAttemptModel(
                    attempt_id="att-authz-1",
                    idempotency_record_id="idem-authz-1",
                    wallet_id=owner["agent_wallet_id"],
                    permit_id=permit.permit_id,
                    public_tool_id="authz-tool",
                    upstream_tool_name="partner_lookup",
                    upstream_origin="https://partner.example",
                    request_hash="b" * 64,
                    credits_authorized=Decimal("3"),
                    state="returned_error",
                )
            )

    with pytest.raises(PermitError) as denied:
        await service.release_dispatch_budget_once(
            "att-authz-1", caller_wallet_id=other["agent_wallet_id"]
        )
    assert denied.value.reason == "permit_access_denied"

    assert (
        await service.release_dispatch_budget_once("att-authz-1", is_system=True)
        is True
    )
    assert (
        await service.release_dispatch_budget_once("att-authz-1", is_system=True)
        is False
    )

    events = await list_audit_events(
        event="permit_dispatch_budget_released",
        wallet_id=owner["agent_wallet_id"],
    )
    matches = [
        e
        for e in events
        if e.metadata.get("attempt_id") == "att-authz-1"
        and e.metadata.get("permit_id") == permit.permit_id
    ]
    assert len(matches) == 1
    assert matches[0].metadata["actor"] == "system"
