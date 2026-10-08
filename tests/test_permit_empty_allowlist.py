from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.trust import PermitCreateRequest
from app.services.permits import get_permit_service
from tests.test_trust_helpers import provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_empty_allowlist_without_scopes_denies_every_tool(client, clean_database):
    """An empty tool allowlist denies every tool when no scope grants it.

    Issuance derives scopes from the allowlist, so a permit minted with an
    empty allowlist and no explicit scopes carries only ``billing:charge``.
    Validation must deny any tool invoke under it instead of skipping the
    tool check. The denial currently surfaces as ``permit_scope_missing``;
    an explicit allowlist-first check may report ``permit_tool_not_allowed``
    instead, so this test locks the denial, not the exact reason string.
    """
    provisioned = await provision_agent_wallet(client)
    service = get_permit_service()
    permit = await service.create_permit(
        PermitCreateRequest(
            issuer_wallet_id=provisioned["agent_wallet_id"],
            subject_wallet_id=provisioned["agent_wallet_id"],
            subject_key_id=provisioned["key_id"],
            allowed_tools=[],
            scopes=[],
            max_credits=Decimal("10"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
    )
    assert permit.scopes == ["billing:charge"]

    for tool_name in ("some-tool", "any-other-tool"):
        validation = await service.validate_for_action(
            permit_id=permit.permit_id,
            wallet_id=provisioned["agent_wallet_id"],
            tool_name=tool_name,
            estimated_credits=Decimal("1"),
            key_id=provisioned["key_id"],
        )
        assert validation.allowed is False
        assert validation.reason in (
            "permit_scope_missing",
            "permit_tool_not_allowed",
        )


@pytest.mark.anyio
async def test_empty_allowlist_with_explicit_scopes_allows_granted_tool(
    client, clean_database
):
    """An empty allowlist still honors explicitly granted scopes.

    The deny rule for an empty allowlist has one exception: a scope that
    explicitly names the tool (``tool:<name>:invoke``) grants it. Any tool
    without such a scope stays denied.
    """
    provisioned = await provision_agent_wallet(client)
    service = get_permit_service()
    permit = await service.create_permit(
        PermitCreateRequest(
            issuer_wallet_id=provisioned["agent_wallet_id"],
            subject_wallet_id=provisioned["agent_wallet_id"],
            subject_key_id=provisioned["key_id"],
            allowed_tools=[],
            scopes=["tool:granted-tool:invoke", "billing:charge"],
            max_credits=Decimal("10"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
    )

    granted = await service.validate_for_action(
        permit_id=permit.permit_id,
        wallet_id=provisioned["agent_wallet_id"],
        tool_name="granted-tool",
        estimated_credits=Decimal("1"),
        key_id=provisioned["key_id"],
    )
    assert granted.allowed is True

    denied = await service.validate_for_action(
        permit_id=permit.permit_id,
        wallet_id=provisioned["agent_wallet_id"],
        tool_name="other-tool",
        estimated_credits=Decimal("1"),
        key_id=provisioned["key_id"],
    )
    assert denied.allowed is False
