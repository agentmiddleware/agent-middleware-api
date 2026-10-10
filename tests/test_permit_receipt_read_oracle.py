from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.receipts import get_receipt_service
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


async def _owner_with_receipt(client):
    """Provision a wallet, permit and receipt owned by one agent."""
    owner = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=owner["agent_wallet_id"],
        key_id=owner["key_id"],
        tool_name="oracle-probe-tool",
    )
    receipt = await get_receipt_service().create_receipt(
        permit_id=permit["permit_id"],
        wallet_id=owner["agent_wallet_id"],
        key_id=owner["key_id"],
        tool="oracle-probe-tool",
        request_payload={"message": "before"},
        response_payload={"message": "after"},
        ledger_entry_id=None,
        credits_authorized=Decimal("2"),
        credits_charged=Decimal("0"),
        outcome="success",
        audit_event_id=None,
    )
    return owner, permit, receipt


@pytest.mark.anyio
async def test_permit_read_hides_existence_from_other_wallets(client, clean_database):
    """GET /v1/permits/{id} must not reveal whether the id exists.

    An unrelated authenticated caller gets the same 404 for a real
    permit that is not theirs as for an id that was never issued.
    """
    _, permit, _ = await _owner_with_receipt(client)
    stranger = await provision_agent_wallet(client)

    not_mine = await client.get(
        f"/v1/permits/{permit['permit_id']}",
        headers=stranger["agent_headers"],
    )
    missing = await client.get(
        "/v1/permits/pmt-does-not-exist",
        headers=stranger["agent_headers"],
    )
    assert not_mine.status_code == 404
    assert not_mine.json() == missing.json() == {"detail": "permit_not_found"}


@pytest.mark.anyio
async def test_permit_receipts_list_hides_existence_from_other_wallets(
    client, clean_database
):
    """GET /v1/permits/{id}/receipts must not reveal whether the id exists."""
    _, permit, _ = await _owner_with_receipt(client)
    stranger = await provision_agent_wallet(client)

    not_mine = await client.get(
        f"/v1/permits/{permit['permit_id']}/receipts",
        headers=stranger["agent_headers"],
    )
    missing = await client.get(
        "/v1/permits/pmt-does-not-exist/receipts",
        headers=stranger["agent_headers"],
    )
    assert not_mine.status_code == 404
    assert not_mine.json() == missing.json() == {"detail": "permit_not_found"}


@pytest.mark.anyio
async def test_receipt_reads_hide_existence_from_other_wallets(client, clean_database):
    """Every receipt read route returns the same 404 for not-found/not-yours."""
    _, _, receipt = await _owner_with_receipt(client)
    stranger = await provision_agent_wallet(client)
    paths = (
        f"/v1/receipts/{receipt.receipt_id}",
        f"/v1/receipts/{receipt.receipt_id}/evidence",
        f"/v1/receipts/{receipt.receipt_id}/portable",
        f"/v1/evidence/{receipt.receipt_id}",
    )
    missing_paths = (
        "/v1/receipts/rcpt-does-not-exist",
        "/v1/receipts/rcpt-does-not-exist/evidence",
        "/v1/receipts/rcpt-does-not-exist/portable",
        "/v1/evidence/rcpt-does-not-exist",
    )
    for real, missing in zip(paths, missing_paths):
        not_mine = await client.get(real, headers=stranger["agent_headers"])
        gone = await client.get(missing, headers=stranger["agent_headers"])
        assert not_mine.status_code == 404, real
        assert not_mine.json() == gone.json() == {"detail": "receipt_not_found"}, real


@pytest.mark.anyio
async def test_receipt_lists_by_permit_hide_existence_from_other_wallets(
    client, clean_database
):
    """Permit-scoped receipt lists must not reveal whether the permit exists."""
    _, permit, _ = await _owner_with_receipt(client)
    stranger = await provision_agent_wallet(client)

    not_mine = await client.get(
        "/v1/receipts",
        params={"permit_id": permit["permit_id"]},
        headers=stranger["agent_headers"],
    )
    missing = await client.get(
        "/v1/receipts",
        params={"permit_id": "pmt-does-not-exist"},
        headers=stranger["agent_headers"],
    )
    assert not_mine.status_code == 404
    assert not_mine.json() == missing.json() == {"detail": "permit_not_found"}

    not_mine_path = await client.get(
        f"/v1/receipts/permit/{permit['permit_id']}",
        headers=stranger["agent_headers"],
    )
    missing_path = await client.get(
        "/v1/receipts/permit/pmt-does-not-exist",
        headers=stranger["agent_headers"],
    )
    assert not_mine_path.status_code == 404
    assert not_mine_path.json() == missing_path.json() == {"detail": "permit_not_found"}


@pytest.mark.anyio
async def test_owners_and_admins_can_still_read(client, clean_database):
    """The fix only flattens denials; legitimate reads keep working."""
    owner, permit, receipt = await _owner_with_receipt(client)

    for path in (
        f"/v1/permits/{permit['permit_id']}",
        f"/v1/permits/{permit['permit_id']}/receipts",
        f"/v1/receipts/{receipt.receipt_id}",
        f"/v1/receipts/{receipt.receipt_id}/evidence",
        f"/v1/receipts/{receipt.receipt_id}/portable",
        f"/v1/evidence/{receipt.receipt_id}",
        f"/v1/receipts/permit/{permit['permit_id']}",
    ):
        resp = await client.get(path, headers=owner["agent_headers"])
        assert resp.status_code == 200, path
        resp = await client.get(path, headers=BOOTSTRAP_HEADERS)
        assert resp.status_code == 200, path
