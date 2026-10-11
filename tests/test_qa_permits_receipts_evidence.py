from __future__ import annotations

"""Router-level QA for permits, receipts and evidence read surfaces.

Scope: app/routers/permits.py, app/routers/receipts.py,
app/routers/evidence.py. These router modules are owned by in-flight
work, so this file only adds tests. It pins down auth, tenant
isolation, pagination and error-handling behavior at the HTTP boundary.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from app.db.models import PermitModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    create_tool_permit,
    provision_agent_wallet,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _sponsor_headers(client: AsyncClient, sponsor_wallet_id: str) -> dict:
    key_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": sponsor_wallet_id, "key_name": "sponsor-qa"},
        headers=BOOTSTRAP_HEADERS,
    )
    assert key_resp.status_code == 201, key_resp.text
    return {"X-API-Key": key_resp.json()["api_key"]}


async def _invoke_with_permit(
    client: AsyncClient,
    provisioned: dict,
    permit: dict,
    tool_name: str,
    idem_key: str,
) -> dict:
    registry = get_service_registry()
    registry.register_local(
        service_id=tool_name,
        name="QA tool",
        description="router QA test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=lambda message="ok": {"message": message},
        credits_per_unit=2.0,
        unit_name="call",
    )
    try:
        resp = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": f"qa-{idem_key}",
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"message": "hi"},
                    "mcpContext": {
                        "wallet_id": provisioned["agent_wallet_id"],
                        "permit_id": permit["permit_id"],
                        "idempotency_key": f"qa-invoke-{idem_key}",
                    },
                },
            },
            headers=provisioned["agent_headers"],
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["result"]["receipt"]
    finally:
        registry.unregister_local(tool_name)


async def _invoke_tool(
    client: AsyncClient,
    provisioned: dict,
    tool_name: str,
    idem_key: str,
) -> tuple[dict, dict]:
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool_name,
        idem_key=f"qa-permit-{idem_key}",
    )
    return permit, await _invoke_with_permit(
        client, provisioned, permit, tool_name, idem_key
    )


async def _sponsor_issue_for_agent(
    client: AsyncClient,
    provisioned: dict,
    sponsor_headers: dict,
    tool_name: str,
    idem_key: str,
    max_credits: int = 50,
) -> dict:
    """Issue a sponsor -> agent permit (issuer differs from subject)."""
    issued = await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": provisioned["sponsor_wallet_id"],
            "subject_wallet_id": provisioned["agent_wallet_id"],
            "subject_key_id": provisioned["key_id"],
            "allowed_tools": [tool_name],
            "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
            "max_credits": max_credits,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=30)
            ).isoformat(),
        },
        headers={**sponsor_headers, "Idempotency-Key": f"qa-spon-{idem_key}"},
    )
    assert issued.status_code == 201, issued.text
    return issued.json()


async def _invoke_with_sponsor_permit(
    client: AsyncClient,
    provisioned: dict,
    sponsor_headers: dict,
    tool_name: str,
    idem_key: str,
) -> tuple[dict, dict]:
    """Invoke under a sponsor-issued permit so the sponsor is permit issuer."""
    permit = await _sponsor_issue_for_agent(
        client, provisioned, sponsor_headers, tool_name, idem_key
    )
    return permit, await _invoke_with_permit(
        client, provisioned, permit, tool_name, idem_key
    )


# Permits: list and get.


@pytest.mark.anyio
async def test_list_permits_requires_authentication(client, clean_database):
    resp = await client.get("/v1/permits")
    assert resp.status_code == 401, resp.text


@pytest.mark.anyio
async def test_list_permits_denies_foreign_wallet_filter(client, clean_database):
    viewer = await provision_agent_wallet(client)
    other = await provision_agent_wallet(client)
    resp = await client.get(
        "/v1/permits",
        params={"wallet_id": other["agent_wallet_id"]},
        headers=viewer["agent_headers"],
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "wallet_access_denied"


@pytest.mark.anyio
async def test_list_permits_defaults_to_caller_wallet(client, clean_database):
    first = await provision_agent_wallet(client)
    second = await provision_agent_wallet(client)
    await create_tool_permit(
        client,
        wallet_id=first["agent_wallet_id"],
        key_id=first["key_id"],
        tool_name="qa-own",
        idem_key="qa-own-a",
    )
    await create_tool_permit(
        client,
        wallet_id=first["agent_wallet_id"],
        key_id=first["key_id"],
        tool_name="qa-own",
        idem_key="qa-own-b",
    )
    await create_tool_permit(
        client,
        wallet_id=second["agent_wallet_id"],
        key_id=second["key_id"],
        tool_name="qa-own",
        idem_key="qa-own-c",
    )

    own = await client.get("/v1/permits", headers=first["agent_headers"])
    assert own.status_code == 200, own.text
    assert own.json()["total"] == 2
    for permit in own.json()["permits"]:
        assert permit["subject_wallet_id"] == first["agent_wallet_id"]

    page = await client.get(
        "/v1/permits",
        params={"wallet_id": first["agent_wallet_id"], "limit": 1, "offset": 0},
        headers=first["agent_headers"],
    )
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 2
    assert len(page.json()["permits"]) == 1
    assert page.json()["has_more"] is True
    assert page.json()["next_offset"] == 1

    tail = await client.get(
        "/v1/permits",
        params={"wallet_id": first["agent_wallet_id"], "limit": 1, "offset": 1},
        headers=first["agent_headers"],
    )
    assert tail.json()["has_more"] is False
    assert tail.json()["next_offset"] is None

    as_admin = await client.get("/v1/permits", headers=BOOTSTRAP_HEADERS)
    assert as_admin.status_code == 200, as_admin.text
    assert as_admin.json()["total"] == 3


@pytest.mark.anyio
async def test_get_permit_denies_unrelated_wallet(client, clean_database):
    owner = await provision_agent_wallet(client)
    stranger = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=owner["agent_wallet_id"],
        key_id=owner["key_id"],
        tool_name="qa-private",
        idem_key="qa-private-1",
    )
    unknown = await client.get(
        "/v1/permits/pmt-does-not-exist",
        headers=owner["agent_headers"],
    )
    assert unknown.status_code == 404, unknown.text
    assert unknown.json()["detail"] == "permit_not_found"
    resp = await client.get(
        f"/v1/permits/{permit['permit_id']}",
        headers=stranger["agent_headers"],
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "permit_not_found"


# Permits: create.


@pytest.mark.anyio
async def test_create_permit_replay_returns_same_permit(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    headers = {**provisioned["agent_headers"], "Idempotency-Key": "qa-replay-1"}
    payload = {
        "issuer_wallet_id": provisioned["agent_wallet_id"],
        "subject_wallet_id": provisioned["agent_wallet_id"],
        "subject_key_id": provisioned["key_id"],
        "allowed_tools": ["x"],
        "scopes": ["tool:x:invoke", "billing:charge"],
        "max_credits": 5,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
    }
    first = await client.post("/v1/permits", json=payload, headers=headers)
    assert first.status_code == 201, first.text
    second = await client.post("/v1/permits", json=payload, headers=headers)
    assert second.status_code == 201, second.text
    assert second.json()["permit_id"] == first.json()["permit_id"]


# Permits: revoke.


@pytest.mark.anyio
async def test_revoke_denies_subject_but_allows_issuer(client, clean_database):
    """Revocation is issuer-only; both parties may read the delegated permit."""
    provisioned = await provision_agent_wallet(client)
    sponsor_headers = await _sponsor_headers(client, provisioned["sponsor_wallet_id"])
    permit = await _sponsor_issue_for_agent(
        client, provisioned, sponsor_headers, "qa-revoke", "revoke-1", max_credits=5
    )
    permit_id = permit["permit_id"]

    as_subject_read = await client.get(
        f"/v1/permits/{permit_id}", headers=provisioned["agent_headers"]
    )
    assert as_subject_read.status_code == 200, as_subject_read.text
    as_issuer_read = await client.get(
        f"/v1/permits/{permit_id}", headers=sponsor_headers
    )
    assert as_issuer_read.status_code == 200, as_issuer_read.text

    unknown = await client.post(
        "/v1/permits/pmt-does-not-exist/revoke", headers=sponsor_headers
    )
    assert unknown.status_code == 404, unknown.text

    as_subject = await client.post(
        f"/v1/permits/{permit_id}/revoke", headers=provisioned["agent_headers"]
    )
    assert as_subject.status_code == 403, as_subject.text

    as_issuer = await client.post(
        f"/v1/permits/{permit_id}/revoke", headers=sponsor_headers
    )
    assert as_issuer.status_code == 200, as_issuer.text
    assert as_issuer.json()["status"] == "revoked"


@pytest.mark.anyio
async def test_revoke_is_idempotent(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="qa-revoke-twice",
        idem_key="qa-revoke-twice-1",
    )
    first = await client.post(
        f"/v1/permits/{permit['permit_id']}/revoke",
        headers=provisioned["agent_headers"],
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "revoked"
    second = await client.post(
        f"/v1/permits/{permit['permit_id']}/revoke",
        headers=provisioned["agent_headers"],
    )
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "revoked"


# Permits: verify.


@pytest.mark.anyio
async def test_verify_expired_permit_skips_context_gate(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="qa-expired",
        idem_key="qa-expired-1",
    )
    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(PermitModel, permit["permit_id"])
        assert model is not None
        model.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.add(model)
        await session.commit()

    resp = await client.post(
        "/v1/permits/verify",
        json={"permit_id": permit["permit_id"]},
        headers=provisioned["agent_headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["valid"] is False
    assert resp.json()["reason"] == "permit_expired"


# Permit receipts.


@pytest.mark.anyio
async def test_list_permit_receipts_denies_unrelated_wallet(client, clean_database):
    owner = await provision_agent_wallet(client)
    stranger = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=owner["agent_wallet_id"],
        key_id=owner["key_id"],
        tool_name="qa-prcvd",
        idem_key="qa-prcvd-1",
    )
    unknown = await client.get(
        "/v1/permits/pmt-does-not-exist/receipts",
        headers=owner["agent_headers"],
    )
    assert unknown.status_code == 404, unknown.text
    resp = await client.get(
        f"/v1/permits/{permit['permit_id']}/receipts",
        headers=stranger["agent_headers"],
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "permit_not_found"


# Receipts: list.


@pytest.mark.anyio
async def test_list_receipts_permit_wallet_mismatch_needs_admin(client, clean_database):
    first = await provision_agent_wallet(client)
    second = await provision_agent_wallet(client)
    unscoped = await client.get("/v1/receipts", headers=second["agent_headers"])
    assert unscoped.status_code == 403, unscoped.text
    permit = await create_tool_permit(
        client,
        wallet_id=first["agent_wallet_id"],
        key_id=first["key_id"],
        tool_name="qa-mismatch",
        idem_key="qa-mismatch-1",
    )
    unknown = await client.get(
        "/v1/receipts",
        params={"permit_id": "pmt-does-not-exist"},
        headers=first["agent_headers"],
    )
    assert unknown.status_code == 404, unknown.text
    resp = await client.get(
        "/v1/receipts",
        params={
            "permit_id": permit["permit_id"],
            "wallet_id": second["agent_wallet_id"],
        },
        headers=second["agent_headers"],
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "permit_not_found"


@pytest.mark.anyio
async def test_receipt_list_surfaces_agree_after_invoke(client, clean_database):
    """One charge is visible with the same id on all three list routes."""
    provisioned = await provision_agent_wallet(client)
    permit, receipt = await _invoke_tool(client, provisioned, "qa-rlist", "rlist")
    wallet = provisioned["agent_wallet_id"]
    headers = provisioned["agent_headers"]

    scoped = await client.get(
        "/v1/receipts", params={"wallet_id": wallet}, headers=headers
    )
    assert scoped.status_code == 200, scoped.text
    assert scoped.json()["total"] == 1

    by_permit = await client.get(
        "/v1/receipts", params={"permit_id": permit["permit_id"]}, headers=headers
    )
    assert by_permit.json()["total"] == 1

    by_outcome_miss = await client.get(
        "/v1/receipts",
        params={"wallet_id": wallet, "outcome": "denied"},
        headers=headers,
    )
    assert by_outcome_miss.json()["total"] == 0

    page = await client.get(
        "/v1/receipts",
        params={"wallet_id": wallet, "limit": 1, "offset": 0},
        headers=headers,
    )
    assert page.json()["has_more"] is False
    assert page.json()["next_offset"] is None
    assert page.json()["receipts"][0]["receipt_id"] == receipt["receipt_id"]

    by_path = await client.get(
        f"/v1/receipts/permit/{permit['permit_id']}", headers=headers
    )
    assert by_path.status_code == 200, by_path.text
    assert by_path.json()["total"] == 1
    assert by_path.json()["receipts"][0]["receipt_id"] == receipt["receipt_id"]

    by_permit_route = await client.get(
        f"/v1/permits/{permit['permit_id']}/receipts",
        params={"tool": "qa-rlist"},
        headers=headers,
    )
    assert by_permit_route.status_code == 200, by_permit_route.text
    assert by_permit_route.json()["total"] == 1
    assert by_permit_route.json()["receipts"][0]["receipt_id"] == receipt["receipt_id"]


@pytest.mark.anyio
async def test_receipts_for_permit_route_auth(client, clean_database):
    owner = await provision_agent_wallet(client)
    stranger = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=owner["agent_wallet_id"],
        key_id=owner["key_id"],
        tool_name="qa-rpermit",
        idem_key="qa-rpermit-1",
    )

    unknown = await client.get(
        "/v1/receipts/permit/pmt-does-not-exist",
        headers=owner["agent_headers"],
    )
    assert unknown.status_code == 404, unknown.text

    denied = await client.get(
        f"/v1/receipts/permit/{permit['permit_id']}",
        headers=stranger["agent_headers"],
    )
    assert denied.status_code == 404, denied.text
    assert denied.json()["detail"] == "permit_not_found"


# Receipts: single read, evidence, portable, verify.


@pytest.mark.anyio
async def test_delegated_permit_issuer_reads_receipt_evidence_and_bundle(
    client, clean_database
):
    """The sponsor behind a delegated permit reads through the permit branch.

    Covers GET receipt, receipt evidence, the buyer evidence bundle and the
    portable export for a caller that owns neither the receipt wallet nor an
    admin key, plus the stranger-denied case on each read surface.
    """
    owner = await provision_agent_wallet(client)
    stranger = await provision_agent_wallet(client)
    sponsor_headers = await _sponsor_headers(client, owner["sponsor_wallet_id"])
    _permit, receipt = await _invoke_with_sponsor_permit(
        client, owner, sponsor_headers, "qa-rev", "rev"
    )
    receipt_id = receipt["receipt_id"]

    for path in (
        f"/v1/receipts/{receipt_id}",
        f"/v1/receipts/{receipt_id}/evidence",
        f"/v1/evidence/{receipt_id}",
        f"/v1/receipts/{receipt_id}/portable",
    ):
        denied = await client.get(path, headers=stranger["agent_headers"])
        assert denied.status_code == 404, (path, denied.text)
        assert denied.json()["detail"] == "receipt_not_found"

    as_issuer = await client.get(f"/v1/receipts/{receipt_id}", headers=sponsor_headers)
    assert as_issuer.status_code == 200, as_issuer.text

    evidence = await client.get(
        f"/v1/receipts/{receipt_id}/evidence", headers=sponsor_headers
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["valid"] is True

    bundle = await client.get(f"/v1/evidence/{receipt_id}", headers=sponsor_headers)
    assert bundle.status_code == 200, bundle.text
    assert bundle.json()["receipt_id"] == receipt_id
    assert bundle.json()["valid"] is True

    portable = await client.get(
        f"/v1/receipts/{receipt_id}/portable", headers=sponsor_headers
    )
    assert portable.status_code == 200, portable.text
    assert portable.json()["receipt_id"] == receipt_id


@pytest.mark.anyio
async def test_unknown_receipt_id_returns_404_on_read_surfaces(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    for path in (
        "/v1/receipts/rcpt-does-not-exist",
        "/v1/receipts/rcpt-does-not-exist/portable",
    ):
        resp = await client.get(path, headers=provisioned["agent_headers"])
        assert resp.status_code == 404, (path, resp.text)


@pytest.mark.anyio
async def test_verify_unknown_receipt_admin_vs_wallet(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    as_wallet = await client.post(
        "/v1/receipts/verify",
        json={"receipt_id": "rcpt-does-not-exist"},
        headers=provisioned["agent_headers"],
    )
    assert as_wallet.status_code == 403, as_wallet.text

    as_admin = await client.post(
        "/v1/receipts/verify",
        json={"receipt_id": "rcpt-does-not-exist"},
        headers=BOOTSTRAP_HEADERS,
    )
    assert as_admin.status_code == 200, as_admin.text
    assert as_admin.json()["valid"] is False
    assert as_admin.json()["reason"] == "receipt_not_found"


# Refund reconciliation: auth and scoping.


@pytest.mark.anyio
async def test_refund_reconciliation_auth_and_unknown_retry(client, clean_database):
    # Wallet scoping with live items lives in test_refund_reconciliation.py;
    # this pins the credential gate and the unknown-item mapping.
    unauth_list = await client.get("/v1/receipts/reconciliation/refunds")
    assert unauth_list.status_code == 401, unauth_list.text

    unauth_retry = await client.post(
        "/v1/receipts/reconciliation/refunds/rcpt-does-not-exist/retry"
    )
    assert unauth_retry.status_code == 401, unauth_retry.text

    as_admin = await client.post(
        "/v1/receipts/reconciliation/refunds/rcpt-does-not-exist/retry",
        headers=BOOTSTRAP_HEADERS,
    )
    assert as_admin.status_code == 404, as_admin.text
