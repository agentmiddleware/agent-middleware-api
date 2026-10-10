from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.time import to_naive_utc
from app.db.database import get_session_factory
from app.db.models import PermitModel
from app.main import app
from app.services.permits import PermitService
from b2a_sdk.edge_client import LocalPermitValidator
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    create_tool_permit,
    provision_agent_wallet,
)


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


def _check_at(monkeypatch, checked_at: datetime) -> None:
    monkeypatch.setattr("app.services.permits.utc_now", lambda: checked_at)
    monkeypatch.setattr("app.schemas.trust.utc_now", lambda: checked_at, raising=False)


@pytest.mark.anyio
@pytest.mark.parametrize("offset_microseconds", [-1, 0, 1])
async def test_permit_read_and_verify_agree_at_expiry_without_resigning(
    client, clean_database, monkeypatch, offset_microseconds
):
    owner = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=owner["agent_wallet_id"],
        key_id=owner["key_id"],
        tool_name="lifecycle-tool",
    )
    expires_at = to_naive_utc(datetime.fromisoformat(permit["expires_at"]))
    _check_at(monkeypatch, expires_at + timedelta(microseconds=offset_microseconds))
    expected = "active" if offset_microseconds < 0 else "expired"

    fetched = await client.get(
        f"/v1/permits/{permit['permit_id']}", headers=owner["agent_headers"]
    )
    assert fetched.status_code == 200
    current = fetched.json()
    assert current["effective_status"] == expected
    assert current["status"] == "active"
    assert current["signature"] == permit["signature"]
    assert LocalPermitValidator.permit_signing_payload(current) == (
        LocalPermitValidator.permit_signing_payload(permit)
    )

    verified = await client.post(
        "/v1/permits/verify",
        json={
            "permit_id": permit["permit_id"],
            "wallet_id": owner["agent_wallet_id"],
            "tool": "lifecycle-tool",
            "estimated_credits": "1",
        },
        headers=owner["agent_headers"],
    )
    assert verified.status_code == 200
    verdict = verified.json()
    assert verdict["valid"] is (expected == "active")
    assert verdict["reason"] == (None if expected == "active" else "permit_expired")
    assert verdict["permit"]["effective_status"] == expected

    async with get_session_factory()() as session:
        stored = await session.get(PermitModel, permit["permit_id"])
        assert stored is not None
        assert stored.status == "active"
        assert stored.spent_credits == 0
        assert await PermitService().verify_signature(stored, session=session)


@pytest.mark.anyio
async def test_expired_permit_lists_filter_current_lifecycle_and_revocation_wins(
    client, clean_database, monkeypatch
):
    owner = await provision_agent_wallet(client)
    expired = await create_tool_permit(
        client,
        wallet_id=owner["agent_wallet_id"],
        key_id=owner["key_id"],
        tool_name="lifecycle-tool",
        idem_key="expired-lifecycle",
    )
    revoked = await create_tool_permit(
        client,
        wallet_id=owner["agent_wallet_id"],
        key_id=owner["key_id"],
        tool_name="lifecycle-tool",
        idem_key="revoked-lifecycle",
    )
    revoke = await client.post(
        f"/v1/permits/{revoked['permit_id']}/revoke", headers=owner["agent_headers"]
    )
    assert revoke.status_code == 200
    _check_at(
        monkeypatch,
        to_naive_utc(datetime.fromisoformat(revoked["expires_at"])) + timedelta(days=1),
    )

    read_revoked = await client.get(
        f"/v1/permits/{revoked['permit_id']}", headers=owner["agent_headers"]
    )
    assert read_revoked.json()["effective_status"] == "revoked"
    assert read_revoked.json()["signature"] == revoked["signature"]
    verify_revoked = await client.post(
        "/v1/permits/verify",
        json={"permit_id": revoked["permit_id"]},
        headers=owner["agent_headers"],
    )
    assert verify_revoked.json()["reason"] == "permit_revoked"
    assert verify_revoked.json()["permit"]["effective_status"] == "revoked"

    for route, headers in (
        ("/v1/permits", BOOTSTRAP_HEADERS),
        ("/v1/me/permits", owner["agent_headers"]),
    ):
        for lifecycle, expected_ids in (
            ("active", []),
            ("expired", [expired["permit_id"]]),
            ("revoked", [revoked["permit_id"]]),
        ):
            listed = await client.get(
                route, params={"status": lifecycle}, headers=headers
            )
            assert listed.status_code == 200
            payload = listed.json()
            assert payload["total"] == len(expected_ids)
            assert [p["permit_id"] for p in payload["permits"]] == expected_ids
            assert all(p["effective_status"] == lifecycle for p in payload["permits"])


@pytest.mark.anyio
async def test_expired_lifecycle_inspection_retains_auth_and_wallet_boundaries(
    client, clean_database, monkeypatch
):
    owner = await provision_agent_wallet(client)
    outsider = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=owner["agent_wallet_id"],
        key_id=owner["key_id"],
        tool_name="lifecycle-tool",
    )
    _check_at(monkeypatch, to_naive_utc(datetime.fromisoformat(permit["expires_at"])))
    route = f"/v1/permits/{permit['permit_id']}"
    assert (await client.get(route)).status_code == 401
    assert (
        await client.get(route, headers=outsider["agent_headers"])
    ).status_code == 403
    foreign_verify = await client.post(
        "/v1/permits/verify",
        json={"permit_id": permit["permit_id"]},
        headers=outsider["agent_headers"],
    )
    assert foreign_verify.status_code == 403
    foreign_list = await client.get(
        "/v1/permits", params={"status": "expired"}, headers=outsider["agent_headers"]
    )
    assert foreign_list.status_code == 200
    assert foreign_list.json()["total"] == 0
