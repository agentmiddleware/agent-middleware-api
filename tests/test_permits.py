from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from app.db.models import PermitModel
from app.main import app
from app.schemas.trust import PermitCreateRequest
from app.services.idempotency import get_idempotency_service
from app.services.permits import PermitError, get_permit_service
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_signed_permit_verifies_for_wallet_tool_and_budget(
    client,
    clean_database,
):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="trust-echo",
    )

    verify_resp = await client.post(
        "/v1/permits/verify",
        json={
            "permit_id": permit["permit_id"],
            "wallet_id": provisioned["agent_wallet_id"],
            "tool": "trust-echo",
            "estimated_credits": 2,
        },
        headers=provisioned["agent_headers"],
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["valid"] is True


@pytest.mark.anyio
async def test_permit_rejects_out_of_scope_tool(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="allowed-tool",
    )

    verify_resp = await client.post(
        "/v1/permits/verify",
        json={
            "permit_id": permit["permit_id"],
            "wallet_id": provisioned["agent_wallet_id"],
            "tool": "blocked-tool",
            "estimated_credits": 2,
        },
        headers=provisioned["agent_headers"],
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["valid"] is False
    assert verify_resp.json()["reason"] == "permit_tool_not_allowed"


@pytest.mark.anyio
async def test_permit_create_rejects_in_progress_idempotency_key(
    client,
    clean_database,
):
    provisioned = await provision_agent_wallet(client)
    request_payload = {
        "issuer_wallet_id": provisioned["agent_wallet_id"],
        "subject_wallet_id": provisioned["agent_wallet_id"],
        "subject_key_id": provisioned["key_id"],
        "allowed_tools": ["in-progress-permit-tool"],
        "scopes": ["tool:in-progress-permit-tool:invoke", "billing:charge"],
        "max_credits": 50,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(minutes=30)
        ).isoformat(),
    }
    await get_idempotency_service().begin(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint="/v1/permits",
        idempotency_key="permit-in-progress-key",
        request_payload=PermitCreateRequest(**request_payload).model_dump(mode="json"),
    )

    resp = await client.post(
        "/v1/permits",
        json=request_payload,
        headers={"X-API-Key": "test-key", "Idempotency-Key": "permit-in-progress-key"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "idempotency_in_progress"


@pytest.mark.anyio
async def test_permit_service_rejects_invalid_issuance_requests(
    client,
    clean_database,
):
    provisioned = await provision_agent_wallet(client)
    service = get_permit_service()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    base_request = {
        "issuer_wallet_id": provisioned["agent_wallet_id"],
        "subject_wallet_id": provisioned["agent_wallet_id"],
        "subject_key_id": provisioned["key_id"],
        "allowed_tools": ["service-issue-tool"],
        "scopes": ["tool:service-issue-tool:invoke", "billing:charge"],
        "max_credits": Decimal("10"),
        "expires_at": expires_at,
    }

    invalid_cases = [
        ({**base_request, "max_credits": Decimal("0")}, "max_credits_must_be_positive"),
        (
            {**base_request, "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
            "permit_expired_at_creation",
        ),
        ({**base_request, "issuer_wallet_id": "missing-wallet"}, "issuer_wallet_not_found"),
        ({**base_request, "subject_wallet_id": "missing-wallet"}, "subject_wallet_not_found"),
        ({**base_request, "max_credits": Decimal("100000")}, "permit_budget_exceeds_wallet_balance"),
    ]

    for payload, reason in invalid_cases:
        with pytest.raises(PermitError) as exc_info:
            await service.create_permit(PermitCreateRequest(**payload))
        assert exc_info.value.reason == reason


@pytest.mark.anyio
async def test_permit_service_budget_lifecycle_and_filters(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    service = get_permit_service()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    permit = await service.create_permit(
        PermitCreateRequest(
            issuer_wallet_id=provisioned["agent_wallet_id"],
            subject_wallet_id=provisioned["agent_wallet_id"],
            subject_key_id=provisioned["key_id"],
            allowed_tools=["service-budget-tool"],
            scopes=["tool:service-budget-tool:invoke"],
            max_credits=Decimal("10"),
            expires_at=expires_at.replace(tzinfo=None),
        )
    )

    assert "billing:charge" in permit.scopes
    fetched = await service.get_permit(permit.permit_id)
    assert fetched and fetched.permit_id == permit.permit_id

    permits, total = await service.list_permits(
        wallet_id=provisioned["agent_wallet_id"],
        status="active",
        subject_key_id=provisioned["key_id"],
        created_after=datetime.now(timezone.utc) - timedelta(minutes=5),
        created_before=datetime.now(timezone.utc) + timedelta(minutes=5),
        expires_after=datetime.now(timezone.utc),
        expires_before=expires_at + timedelta(minutes=5),
    )
    assert total == 1
    assert permits[0].permit_id == permit.permit_id

    await service.reserve_budget(permit.permit_id, Decimal("4"))
    validation = await service.validate_for_action(
        permit_id=permit.permit_id,
        wallet_id=provisioned["agent_wallet_id"],
        tool_name="service-budget-tool",
        estimated_credits=Decimal("7"),
        key_id=provisioned["key_id"],
    )
    assert validation.allowed is False
    assert validation.reason == "permit_budget_exceeded"

    await service.release_budget(permit.permit_id, Decimal("2"))
    validation = await service.validate_for_action(
        permit_id=permit.permit_id,
        wallet_id=provisioned["agent_wallet_id"],
        tool_name="service-budget-tool",
        estimated_credits=Decimal("7"),
        key_id=provisioned["key_id"],
    )
    assert validation.allowed is True

    with pytest.raises(PermitError) as missing_reserve:
        await service.reserve_budget("permit-missing", Decimal("1"))
    assert missing_reserve.value.reason == "permit_not_found"
    await service.release_budget("permit-missing", Decimal("1"))

    revoked = await service.revoke_permit(permit.permit_id)
    assert revoked.status == "revoked"
    assert revoked.revoked_at is not None
    validation = await service.validate_for_action(
        permit_id=permit.permit_id,
        wallet_id=provisioned["agent_wallet_id"],
        tool_name="service-budget-tool",
        estimated_credits=Decimal("1"),
        key_id=provisioned["key_id"],
    )
    assert validation.allowed is False
    assert validation.reason == "permit_revoked"


@pytest.mark.anyio
async def test_permit_service_validation_denial_reasons(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    other = await provision_agent_wallet(client)
    service = get_permit_service()
    permit = await service.create_permit(
        PermitCreateRequest(
            issuer_wallet_id=provisioned["agent_wallet_id"],
            subject_wallet_id=provisioned["agent_wallet_id"],
            subject_key_id=provisioned["key_id"],
            allowed_tools=["service-validate-tool"],
            scopes=["tool:service-validate-tool:invoke", "billing:charge"],
            max_credits=Decimal("10"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
    )

    cases = [
        {
            "permit_id": "permit-missing",
            "wallet_id": provisioned["agent_wallet_id"],
            "tool_name": "service-validate-tool",
            "estimated_credits": Decimal("1"),
            "key_id": provisioned["key_id"],
            "reason": "permit_not_found",
        },
        {
            "permit_id": permit.permit_id,
            "wallet_id": other["agent_wallet_id"],
            "tool_name": "service-validate-tool",
            "estimated_credits": Decimal("1"),
            "key_id": provisioned["key_id"],
            "reason": "permit_wallet_mismatch",
        },
        {
            "permit_id": permit.permit_id,
            "wallet_id": provisioned["agent_wallet_id"],
            "tool_name": "service-validate-tool",
            "estimated_credits": Decimal("1"),
            "key_id": "wrong-key",
            "reason": "permit_key_mismatch",
        },
        {
            "permit_id": permit.permit_id,
            "wallet_id": provisioned["agent_wallet_id"],
            "tool_name": "other-tool",
            "estimated_credits": Decimal("1"),
            "key_id": provisioned["key_id"],
            "reason": "permit_tool_not_allowed",
        },
    ]

    for case in cases:
        reason = case.pop("reason")
        validation = await service.validate_for_action(**case)
        assert validation.allowed is False
        assert validation.reason == reason

    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(PermitModel, permit.permit_id)
        assert model is not None
        model.allowed_tools_json = json.dumps([])
        model.scopes_json = json.dumps(["billing:charge"])
        session.add(model)
        await session.commit()

    validation = await service.validate_for_action(
        permit_id=permit.permit_id,
        wallet_id=provisioned["agent_wallet_id"],
        tool_name="service-validate-tool",
        estimated_credits=Decimal("1"),
        key_id=provisioned["key_id"],
    )
    assert validation.allowed is False
    assert validation.reason == "permit_scope_missing"

    async with factory() as session:
        model = await session.get(PermitModel, permit.permit_id)
        assert model is not None
        model.scopes_json = json.dumps(["tool:service-validate-tool:invoke", "billing:charge"])
        model.signature = "tampered"
        session.add(model)
        await session.commit()

    validation = await service.validate_for_action(
        permit_id=permit.permit_id,
        wallet_id=provisioned["agent_wallet_id"],
        tool_name="service-validate-tool",
        estimated_credits=Decimal("1"),
        key_id=provisioned["key_id"],
    )
    assert validation.allowed is False
    assert validation.reason == "permit_signature_invalid"
