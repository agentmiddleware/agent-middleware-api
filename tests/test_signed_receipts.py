"""
Tests for signed verifiable receipts: the ReceiptService crypto, the
per-wallet hash chain, and the HTTP verification endpoints.
"""

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.main import app
from app.services.receipts import (
    ReceiptService,
    build_signed_ledger_entry,
    get_receipt_service,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _fake_wallet():
    return SimpleNamespace(wallet_id="w-test", receipt_seq=0, last_receipt_hash=None)


# --- ReceiptService crypto ---


def test_sign_and_verify_round_trip():
    svc = ReceiptService()
    payload = b'{"x":1}'
    sig = svc.sign(payload)
    assert svc.verify(payload, sig) is True


def test_verify_fails_on_tampered_payload():
    svc = ReceiptService()
    sig = svc.sign(b'{"amount":"1.00000000"}')
    assert svc.verify(b'{"amount":"9999.00000000"}', sig) is False


def test_ed25519_exposes_public_key_when_available():
    svc = ReceiptService()
    if svc.algorithm == "ed25519":
        assert svc.public_key_b64() is not None
    else:  # HMAC fallback environment
        assert svc.public_key_b64() is None


# --- hash chain ---


def test_build_signed_entry_chains_and_verifies():
    svc = ReceiptService()
    wallet = _fake_wallet()

    e1 = build_signed_ledger_entry(
        svc,
        wallet=wallet,
        entry_id="e1",
        action="credit",
        amount=Decimal("100"),
        balance_after=Decimal("100"),
        description="first",
    )
    e2 = build_signed_ledger_entry(
        svc,
        wallet=wallet,
        entry_id="e2",
        action="debit",
        amount=Decimal("-10"),
        balance_after=Decimal("90"),
        description="second",
    )

    assert e1.chain_seq == 1 and e2.chain_seq == 2
    assert e1.prev_hash is None
    assert e2.prev_hash == e1.entry_hash  # linked
    assert e1.entry_hash != e2.entry_hash
    assert wallet.last_receipt_hash == e2.entry_hash
    assert svc.verify_entry(e1) is True
    assert svc.verify_entry(e2) is True


def test_verify_entry_detects_mutation():
    svc = ReceiptService()
    wallet = _fake_wallet()
    entry = build_signed_ledger_entry(
        svc,
        wallet=wallet,
        entry_id="e1",
        action="debit",
        amount=Decimal("-10"),
        balance_after=Decimal("90"),
    )
    assert svc.verify_entry(entry) is True
    # Mutate the amount after signing -> verification must fail.
    entry.amount = Decimal("-9999")
    assert svc.verify_entry(entry) is False


# --- HTTP endpoints ---


@pytest.mark.anyio
async def test_public_key_endpoint(client):
    resp = await client.get("/v1/billing/receipts/public-key")
    assert resp.status_code == 200
    body = resp.json()
    assert body["algorithm"] in ("ed25519", "hmac-sha256")
    if body["algorithm"] == "ed25519":
        assert body["public_key"]
        assert body["verifiable_offline"] is True


@pytest.mark.anyio
async def test_wallet_chain_verifies_end_to_end(client):
    headers = {"X-API-Key": "test-key"}

    # Sponsor with an initial deposit -> one signed CREDIT entry.
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": f"recv-{uuid.uuid4().hex[:6]}",
            "email": "r@test.example",
            "initial_credits": 1000,
        },
        headers=headers,
    )
    assert sponsor.status_code == 201
    sponsor_id = sponsor.json()["wallet_id"]

    # Provision an agent wallet -> TRANSFER entries on both chains.
    agent = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor_id,
            "agent_id": f"agt-{uuid.uuid4().hex[:6]}",
            "budget_credits": 200,
        },
        headers=headers,
    )
    assert agent.status_code == 201

    verify = await client.get(
        f"/v1/billing/receipts/wallet/{sponsor_id}/verify", headers=headers
    )
    assert verify.status_code == 200
    body = verify.json()
    assert body["entries_total"] == 2  # initial deposit + provisioning transfer
    assert body["chain_valid"] is True
    assert body["broken"] == []


@pytest.mark.anyio
async def test_single_receipt_is_verified(client):
    headers = {"X-API-Key": "test-key"}
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": f"recv-{uuid.uuid4().hex[:6]}",
            "email": "r@test.example",
            "initial_credits": 500,
        },
        headers=headers,
    )
    sponsor_id = sponsor.json()["wallet_id"]

    ledger = await client.get(f"/v1/billing/ledger/{sponsor_id}", headers=headers)
    assert ledger.status_code == 200
    entries = ledger.json()["entries"]
    assert entries
    entry_id = entries[0]["entry_id"]

    receipt = await client.get(
        f"/v1/billing/receipts/entry/{entry_id}", headers=headers
    )
    assert receipt.status_code == 200
    assert receipt.json()["verified"] is True


async def _sponsor_with_scoped_key(client, headers, credits=0):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": f"own-{uuid.uuid4().hex[:6]}",
            "email": "o@test.example",
            "initial_credits": credits,
        },
        headers=headers,
    )
    wallet_id = sponsor.json()["wallet_id"]
    key_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_id, "key_name": "scoped"},
        headers=headers,
    )
    return wallet_id, {"X-API-Key": key_resp.json()["api_key"]}


@pytest.mark.anyio
async def test_cross_wallet_chain_verify_denied(client):
    headers = {"X-API-Key": "test-key"}
    wallet_a, key_a = await _sponsor_with_scoped_key(client, headers)
    wallet_b, _ = await _sponsor_with_scoped_key(client, headers, credits=100)

    # Wallet A's key may verify its own chain...
    own = await client.get(
        f"/v1/billing/receipts/wallet/{wallet_a}/verify", headers=key_a
    )
    assert own.status_code == 200
    # ...but not wallet B's.
    denied = await client.get(
        f"/v1/billing/receipts/wallet/{wallet_b}/verify", headers=key_a
    )
    assert denied.status_code == 403


@pytest.mark.anyio
async def test_cross_wallet_receipt_entry_denied(client):
    headers = {"X-API-Key": "test-key"}
    wallet_a, key_a = await _sponsor_with_scoped_key(client, headers)
    wallet_b, _ = await _sponsor_with_scoped_key(client, headers, credits=100)

    ledger = await client.get(f"/v1/billing/ledger/{wallet_b}", headers=headers)
    entry_id = ledger.json()["entries"][0]["entry_id"]

    denied = await client.get(f"/v1/billing/receipts/entry/{entry_id}", headers=key_a)
    assert denied.status_code == 403


@pytest.mark.anyio
async def test_db_tamper_breaks_chain(client):
    headers = {"X-API-Key": "test-key"}
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": f"recv-{uuid.uuid4().hex[:6]}",
            "email": "r@test.example",
            "initial_credits": 750,
        },
        headers=headers,
    )
    sponsor_id = sponsor.json()["wallet_id"]

    # Tamper with the stored amount directly in the database.
    from app.db.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("UPDATE ledger_entries SET amount = :a WHERE wallet_id = :w"),
            {"a": "999999.00000000", "w": sponsor_id},
        )
        await session.commit()

    verify = await client.get(
        f"/v1/billing/receipts/wallet/{sponsor_id}/verify", headers=headers
    )
    body = verify.json()
    assert body["chain_valid"] is False
    assert any(b["reason"] == "invalid_signature_or_hash" for b in body["broken"])
