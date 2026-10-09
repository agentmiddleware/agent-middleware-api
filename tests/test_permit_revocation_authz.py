"""Service-level authorization for permit revocation and budget releases.

The revoke route always checked wallet access, but ``PermitService``
itself trusted every caller: any future in-process caller could revoke or
erase spending for anyone. Revocation now carries the caller's identity
into the service and fails closed, and every release that actually moves
budget or counters is recorded in the log.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.permits import PermitError, get_permit_service
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_revoke_route_denies_foreign_wallet(client, clean_database):
    """Only the issuing wallet (or an admin) may revoke through the route."""
    victim = await provision_agent_wallet(client)
    attacker = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=victim["agent_wallet_id"],
        key_id=victim["key_id"],
        tool_name="revoke-authz-tool",
        idem_key="revoke-authz-permit",
    )

    denied = await client.post(
        f"/v1/permits/{permit['permit_id']}/revoke",
        headers=attacker["agent_headers"],
    )
    assert denied.status_code == 403

    still_there = await client.get(
        f"/v1/permits/{permit['permit_id']}",
        headers=victim["agent_headers"],
    )
    assert still_there.status_code == 200
    assert still_there.json()["status"] == "active"

    owned = await client.post(
        f"/v1/permits/{permit['permit_id']}/revoke",
        headers=victim["agent_headers"],
    )
    assert owned.status_code == 200
    assert owned.json()["status"] == "revoked"


@pytest.mark.anyio
async def test_revoke_service_enforces_caller_identity(client, clean_database):
    """The service denies a wrong or omitted caller without the route.

    Regression: ``revoke_permit`` took only a permit id, so any future
    caller could revoke anyone's permit. On the old code this test fails
    because the service accepts no caller identity at all.
    """
    victim = await provision_agent_wallet(client)
    attacker = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=victim["agent_wallet_id"],
        key_id=victim["key_id"],
        tool_name="revoke-service-authz-tool",
        idem_key="revoke-service-authz-permit",
    )
    service = get_permit_service()

    with pytest.raises(PermitError) as foreign:
        await service.revoke_permit(
            permit["permit_id"],
            caller_wallet_id=attacker["agent_wallet_id"],
        )
    assert foreign.value.reason == "permit_access_denied"

    with pytest.raises(PermitError) as anonymous:
        await service.revoke_permit(permit["permit_id"])
    assert anonymous.value.reason == "permit_access_denied"

    revoked = await service.revoke_permit(
        permit["permit_id"],
        caller_wallet_id=victim["agent_wallet_id"],
    )
    assert revoked.status == "revoked"

    with pytest.raises(PermitError) as missing:
        await service.revoke_permit(
            "permit-missing",
            caller_wallet_id=victim["agent_wallet_id"],
        )
    assert missing.value.reason == "permit_not_found"


@pytest.mark.anyio
async def test_budget_release_is_logged(client, clean_database, caplog):
    """Every release that moves budget leaves a log record behind.

    Regression: releases were silent, so nothing distinguished a real
    refund from spending erased without a trace. On the old code this
    test fails because no record is emitted.
    """
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="release-audit-tool",
        idem_key="release-audit-permit",
    )
    service = get_permit_service()

    with caplog.at_level(logging.INFO, logger="app.services.permits"):
        await service.release_budget(permit["permit_id"], Decimal("1"))
    assert any(
        record.name == "app.services.permits"
        and record.getMessage() == "permit_budget_released"
        and record.permit_id == permit["permit_id"]
        for record in caplog.records
    )

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.services.permits"):
        await service.release_budget("permit-missing", Decimal("1"))
    assert not any(
        record.name == "app.services.permits"
        and record.getMessage() == "permit_budget_released"
        for record in caplog.records
    )
