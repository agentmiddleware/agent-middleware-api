"""Money movement, auth and tenant-isolation gap coverage.

Covers paths the existing suite exercises only on the happy path or not at
all: fractional transfer precision, transfer failure rollback, transfer
input/auth edges, service-level refund ownership, permit reservation
ownership, JWT scoped to one wallet used against another wallet's money
endpoint, and unknown-key refusal on a money endpoint.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.agent_money import get_agent_money
from app.services.permits import get_permit_service
from app.schemas.trust import PermitCreateRequest
from tests.test_trust_helpers import BOOTSTRAP_HEADERS, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def jwt_service(monkeypatch):
    from app.core.config import get_settings
    from app.core.jwt import get_jwt_service

    monkeypatch.setenv(
        "TRUST_SIGNING_PRIVATE_KEY_B64",
        "dGVzdC1zaWduaW5nLWtleS1tYXRlcmlhbC0zMmJ5dGU=",
    )
    get_settings.cache_clear()
    try:
        yield get_jwt_service()
    finally:
        get_settings.cache_clear()


@pytest.fixture
def live_key(monkeypatch):
    from app.services.api_key_service import APIKeyService

    async def is_key_live(_self, _key_id: str, _wallet_id: str) -> bool:
        return True

    monkeypatch.setattr(APIKeyService, "consume_derived_key_use", is_key_live)


async def _sponsor(client, name: str, credits: float) -> str:
    resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": name,
            "email": f"{name}@example.com",
            "initial_credits": credits,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert resp.status_code == 201
    return resp.json()["wallet_id"]


async def _balance(client, wallet_id: str) -> Decimal:
    resp = await client.get(
        f"/v1/billing/wallets/{wallet_id}", headers=BOOTSTRAP_HEADERS
    )
    assert resp.status_code == 200
    return Decimal(resp.json()["balance_exact"])


async def _ledger_count(client, wallet_id: str) -> int:
    resp = await client.get(
        f"/v1/billing/ledger/{wallet_id}", headers=BOOTSTRAP_HEADERS
    )
    assert resp.status_code == 200
    return len(resp.json()["entries"])


# --------------------------------------------------------------------------
# transfer
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_transfer_keeps_fractional_amounts_exact(client, clean_database):
    sender = await _sponsor(client, "frac-sender", 1000.0)
    receiver = await _sponsor(client, "frac-receiver", 0.0)

    resp = await client.post(
        "/v1/billing/transfer",
        params={"from_wallet_id": sender, "to_wallet_id": receiver, "amount": 10.55},
        headers=BOOTSTRAP_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert Decimal(str(data["amount"])) == Decimal("10.55")

    assert await _balance(client, sender) == Decimal("989.45")
    assert await _balance(client, receiver) == Decimal("10.55")

    resp = await client.post(
        "/v1/billing/transfer",
        params={"from_wallet_id": sender, "to_wallet_id": receiver, "amount": 0.05},
        headers=BOOTSTRAP_HEADERS,
    )
    assert resp.status_code == 200
    assert await _balance(client, sender) == Decimal("989.40")
    assert await _balance(client, receiver) == Decimal("10.60")


@pytest.mark.anyio
async def test_failed_transfer_moves_nothing(client, clean_database):
    sender = await _sponsor(client, "rollback-sender", 100.0)
    receiver = await _sponsor(client, "rollback-receiver", 50.0)
    before_sender = await _balance(client, sender)
    before_receiver = await _balance(client, receiver)
    sender_ledger_before = await _ledger_count(client, sender)
    receiver_ledger_before = await _ledger_count(client, receiver)

    resp = await client.post(
        "/v1/billing/transfer",
        params={"from_wallet_id": sender, "to_wallet_id": receiver, "amount": 10000.0},
        headers=BOOTSTRAP_HEADERS,
    )
    assert resp.status_code == 402

    assert await _balance(client, sender) == before_sender
    assert await _balance(client, receiver) == before_receiver
    assert await _ledger_count(client, sender) == sender_ledger_before
    assert await _ledger_count(client, receiver) == receiver_ledger_before


@pytest.mark.anyio
async def test_negative_transfer_is_refused(client, clean_database):
    sender = await _sponsor(client, "neg-sender", 100.0)
    receiver = await _sponsor(client, "neg-receiver", 0.0)

    resp = await client.post(
        "/v1/billing/transfer",
        params={"from_wallet_id": sender, "to_wallet_id": receiver, "amount": -5.0},
        headers=BOOTSTRAP_HEADERS,
    )
    assert resp.status_code == 422

    assert await _balance(client, sender) == Decimal("100")
    assert await _balance(client, receiver) == Decimal("0")


@pytest.mark.anyio
async def test_transfer_without_credentials_is_refused(client, clean_database):
    sender = await _sponsor(client, "anon-sender", 100.0)
    receiver = await _sponsor(client, "anon-receiver", 0.0)
    sender_balance = await _balance(client, sender)
    receiver_balance = await _balance(client, receiver)
    sender_ledger = await _ledger_count(client, sender)
    receiver_ledger = await _ledger_count(client, receiver)

    resp = await client.post(
        "/v1/billing/transfer",
        params={"from_wallet_id": sender, "to_wallet_id": receiver, "amount": 10.0},
    )
    assert resp.status_code == 401
    assert await _balance(client, sender) == sender_balance
    assert await _balance(client, receiver) == receiver_balance
    assert await _ledger_count(client, sender) == sender_ledger
    assert await _ledger_count(client, receiver) == receiver_ledger


@pytest.mark.anyio
async def test_transfer_from_unowned_wallet_moves_nothing(client, clean_database):
    first = await provision_agent_wallet(client)
    second = await provision_agent_wallet(client)
    wallet_a = first["agent_wallet_id"]
    wallet_b = second["agent_wallet_id"]
    before_a = await _balance(client, wallet_a)
    before_b = await _balance(client, wallet_b)

    resp = await client.post(
        "/v1/billing/transfer",
        params={"from_wallet_id": wallet_b, "to_wallet_id": wallet_a, "amount": 1.0},
        headers=first["agent_headers"],
    )
    assert resp.status_code == 403

    assert await _balance(client, wallet_a) == before_a
    assert await _balance(client, wallet_b) == before_b


# --------------------------------------------------------------------------
# charge
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fractional_charge_stays_exact(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]

    resp = await client.post(
        f"/v1/billing/charge?wallet_id={wallet_id}&service=iot_bridge&units=0.3",
        headers=BOOTSTRAP_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert Decimal(data["amount_exact"]) == Decimal("-0.6")
    assert Decimal(data["balance_after_exact"]) == Decimal("999.4")


@pytest.mark.anyio
async def test_unknown_key_is_refused_on_charge(client, clean_database):
    wallet_id = await _sponsor(client, "unknown-key-wallet", 100.0)

    resp = await client.post(
        f"/v1/billing/charge?wallet_id={wallet_id}&service=iot_bridge",
        headers={"X-API-Key": "no-such-key-12345"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "invalid_api_key"
    assert await _balance(client, wallet_id) == Decimal("100")


# --------------------------------------------------------------------------
# refund (service level, there is no HTTP refund route)
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_refund_naming_another_wallet_is_refused(client, clean_database):
    first = await provision_agent_wallet(client)
    second = await provision_agent_wallet(client)
    wallet_a = first["agent_wallet_id"]
    wallet_b = second["agent_wallet_id"]

    charge = await client.post(
        f"/v1/billing/charge?wallet_id={wallet_a}&service=iot_bridge&units=5",
        headers=BOOTSTRAP_HEADERS,
    )
    assert charge.status_code == 200
    entry_id = charge.json()["entry_id"]
    before_a = await _balance(client, wallet_a)
    before_b = await _balance(client, wallet_b)

    with pytest.raises(ValueError, match=r"^Debit ledger entry not found:") as exc:
        await get_agent_money().refund_charge(
            wallet_id=wallet_b,
            charge_entry_id=entry_id,
            description="cross-wallet refund attempt",
        )
    assert str(exc.value) == f"Debit ledger entry not found: {entry_id}"

    assert await _balance(client, wallet_a) == before_a
    assert await _balance(client, wallet_b) == before_b


@pytest.mark.anyio
async def test_refund_of_unknown_charge_is_refused(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    before = await _balance(client, wallet_id)

    with pytest.raises(
        ValueError,
        match=r"^Debit ledger entry not found: ledger-entry-that-does-not-exist$",
    ):
        await get_agent_money().refund_charge(
            wallet_id=wallet_id,
            charge_entry_id="ledger-entry-that-does-not-exist",
        )

    assert await _balance(client, wallet_id) == before


# --------------------------------------------------------------------------
# permit reserve ownership
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reserve_against_another_wallet_permit_is_denied(client, clean_database):
    owner = await provision_agent_wallet(client)
    stranger = await provision_agent_wallet(client)
    service = get_permit_service()
    permit = await service.create_permit(
        PermitCreateRequest(
            issuer_wallet_id=owner["agent_wallet_id"],
            subject_wallet_id=owner["agent_wallet_id"],
            subject_key_id=owner["key_id"],
            allowed_tools=["qa-tool"],
            scopes=["tool:qa-tool:invoke", "billing:charge"],
            max_credits=Decimal("10"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
    )

    validation = await service.authorize_and_reserve(
        permit_id=permit.permit_id,
        wallet_id=stranger["agent_wallet_id"],
        tool_name="qa-tool",
        estimated_credits=Decimal("2"),
        key_id=owner["key_id"],
    )

    assert validation.allowed is False
    assert validation.reason == "permit_wallet_mismatch"
    fresh = await service.get_permit(permit.permit_id)
    assert fresh is not None
    assert fresh.spent_credits == Decimal("0")

    owner_reservation = await service.authorize_and_reserve(
        permit_id=permit.permit_id,
        wallet_id=owner["agent_wallet_id"],
        tool_name="qa-tool",
        estimated_credits=Decimal("2"),
        key_id=owner["key_id"],
    )
    assert owner_reservation.allowed is True
    fresh = await service.get_permit(permit.permit_id)
    assert fresh is not None
    assert fresh.spent_credits == Decimal("2")


# --------------------------------------------------------------------------
# JWT scoped to one wallet used against another wallet
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_jwt_for_one_wallet_cannot_charge_another(
    client, clean_database, jwt_service, live_key
):
    first = await provision_agent_wallet(client)
    second = await provision_agent_wallet(client)
    wallet_a = first["agent_wallet_id"]
    wallet_b = second["agent_wallet_id"]
    before_b = await _balance(client, wallet_b)
    ledger_b_before = await _ledger_count(client, wallet_b)

    token = jwt_service.create_access_token(
        wallet_id=wallet_a,
        key_id=first["key_id"],
        scopes=["billing:charge"],
    )
    jwt_headers = {"Authorization": f"Bearer {token}"}

    denied = await client.post(
        f"/v1/billing/charge?wallet_id={wallet_b}&service=iot_bridge&units=1",
        headers=jwt_headers,
    )
    assert denied.status_code == 403
    assert await _balance(client, wallet_b) == before_b
    assert await _ledger_count(client, wallet_b) == ledger_b_before

    allowed = await client.post(
        f"/v1/billing/charge?wallet_id={wallet_a}&service=iot_bridge&units=1",
        headers=jwt_headers,
    )
    assert allowed.status_code == 200
    assert Decimal(allowed.json()["amount_exact"]) == Decimal("-2")
