"""Adversarial checks for wallet transfers and billing wallet routes.

These tests hit the local app and the wallet engine only. They do not call
Stripe, webhooks, or any live charging endpoint.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db.database import get_session_factory
from app.db.models import LedgerEntryModel, WalletModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.agent_money import InsufficientFundsError, get_agent_money

BOOTSTRAP = {"X-API-Key": "test-key"}

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _balance(wallet_id: str) -> Decimal:
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        return wallet.balance


async def _wallet_count() -> int:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(func.count()).select_from(WalletModel))
        return int(result.scalar_one())


async def _ledger_count(wallet_id: str) -> int:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(LedgerEntryModel)
            .where(LedgerEntryModel.wallet_id == wallet_id)
        )
        return int(result.scalar_one())


async def _set_status(wallet_id: str, status: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        wallet.status = status
        session.add(wallet)
        await session.commit()


async def _sponsor(
    client: AsyncClient,
    *,
    name: str,
    credits: float,
    currency: str | None = None,
) -> dict:
    body: dict = {
        "sponsor_name": name,
        "email": f"{name}@break.example",
        "initial_credits": credits,
    }
    if currency is not None:
        body["currency"] = currency
    response = await client.post(
        "/v1/billing/wallets/sponsor",
        json=body,
        headers=BOOTSTRAP,
    )
    return {"status": response.status_code, "body": response.json()}


async def _agent(client: AsyncClient, sponsor_id: str, agent_id: str, budget: float):
    response = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor_id,
            "agent_id": agent_id,
            "budget_credits": budget,
        },
        headers=BOOTSTRAP,
    )
    assert response.status_code == 201, response.text
    return response.json()["wallet_id"]


async def test_negative_zero_and_self_transfer_do_not_move_money(
    client: AsyncClient, clean_database
) -> None:
    """Negative, zero, and self transfers are refused before any balance write."""
    created = await _sponsor(client, name="hold", credits=25)
    assert created["status"] == 201
    wallet_id = created["body"]["wallet_id"]
    before = await _balance(wallet_id)

    negative = await client.post(
        "/v1/billing/transfer",
        params={
            "from_wallet_id": wallet_id,
            "to_wallet_id": "agt-does-not-matter",
            "amount": -5,
        },
        headers=BOOTSTRAP,
    )
    zero = await client.post(
        "/v1/billing/transfer",
        params={
            "from_wallet_id": wallet_id,
            "to_wallet_id": "agt-does-not-matter",
            "amount": 0,
        },
        headers=BOOTSTRAP,
    )
    same = await client.post(
        "/v1/billing/transfer",
        params={
            "from_wallet_id": wallet_id,
            "to_wallet_id": wallet_id,
            "amount": 1,
        },
        headers=BOOTSTRAP,
    )

    assert negative.status_code == 422
    assert zero.status_code == 422
    assert same.status_code == 400
    assert await _balance(wallet_id) == before


async def test_engine_rejects_non_positive_and_unstorable_transfers(
    client: AsyncClient, clean_database
) -> None:
    """Direct engine calls must refuse amounts the ledger cannot store safely.

    A negative amount would invert the debit into a credit. Zero is not a
    transfer. NaN, a value past the Numeric(20, 8) range, and a fraction
    finer than 8 decimal places all survive a ``> 0`` check and then change
    shape when SQLite binds the decimal through a float.
    """
    created = await _sponsor(client, name="engine-amt", credits=100)
    source = await _agent(client, created["body"]["wallet_id"], "src", 40)
    dest = await _agent(client, created["body"]["wallet_id"], "dst", 10)
    money = get_agent_money()
    attacks = [
        Decimal("-1"),
        Decimal("0"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1000000000000"),
        Decimal("0.000000001"),
        Decimal("999999999999.99"),
    ]

    for amount in attacks:
        with pytest.raises(ValueError):
            await money.transfer(source, dest, amount)

    assert await _balance(source) == Decimal("40")
    assert await _balance(dest) == Decimal("10")

    with pytest.raises(ValueError, match="same wallet"):
        await money.transfer(source, source, Decimal("1"))
    assert await _balance(source) == Decimal("40")


async def test_http_rejects_dust_and_overscale_transfer_amounts(
    client: AsyncClient, clean_database
) -> None:
    """A transfer smaller than the ledger scale, or too big to store, must not post."""
    created = await _sponsor(client, name="http-amt", credits=100)
    source = await _agent(client, created["body"]["wallet_id"], "src", 40)
    dest = await _agent(client, created["body"]["wallet_id"], "dst", 10)

    dust = await client.post(
        "/v1/billing/transfer",
        params={
            "from_wallet_id": source,
            "to_wallet_id": dest,
            "amount": "0.000000001",
        },
        headers=BOOTSTRAP,
    )
    huge = await client.post(
        "/v1/billing/transfer",
        params={
            "from_wallet_id": source,
            "to_wallet_id": dest,
            "amount": "1000000000000",
        },
        headers=BOOTSTRAP,
    )
    overscale = await client.post(
        "/v1/billing/transfer",
        params={
            "from_wallet_id": source,
            "to_wallet_id": dest,
            "amount": "999999999999.99",
        },
        headers=BOOTSTRAP,
    )

    assert dust.status_code == 400, dust.text
    assert huge.status_code == 422, huge.text
    # Under the 1e12 request cap, but not a Numeric(20, 8) value. The route
    # must refuse it as a transfer error and leave both balances alone.
    assert overscale.status_code == 400, overscale.text
    assert await _balance(source) == Decimal("40")
    assert await _balance(dest) == Decimal("10")


async def test_concurrent_debits_cannot_drive_a_wallet_below_zero(
    client: AsyncClient, clean_database
) -> None:
    """Two debits of the same full balance must leave a non-negative balance."""
    created = await _sponsor(client, name="race", credits=100)
    sponsor_id = created["body"]["wallet_id"]
    source = await _agent(client, sponsor_id, "race-src", 40)
    first = await _agent(client, sponsor_id, "race-a", 1)
    second = await _agent(client, sponsor_id, "race-b", 1)
    money = get_agent_money()

    transfer_results = await asyncio.gather(
        money.transfer(source, first, Decimal("40")),
        money.transfer(source, second, Decimal("40")),
        return_exceptions=True,
    )
    transfer_ok = [item for item in transfer_results if not isinstance(item, Exception)]
    assert len(transfer_ok) == 1
    assert all(
        isinstance(item, InsufficientFundsError)
        for item in transfer_results
        if item not in transfer_ok
    )
    assert await _balance(source) == Decimal("0")
    assert await _balance(first) + await _balance(second) == Decimal("42")

    fee_wallet = await _agent(client, sponsor_id, "race-fee", 0.1)
    charge_results = await asyncio.gather(
        money.charge(fee_wallet, ServiceCategory.PLATFORM_FEE, Decimal("1")),
        money.charge(fee_wallet, ServiceCategory.PLATFORM_FEE, Decimal("1")),
        return_exceptions=True,
    )
    assert not any(isinstance(item, Exception) for item in charge_results)
    # One platform fee is 0.1, which is the whole balance. The other debit
    # must be refused, and the balance must not go negative.
    assert await _balance(fee_wallet) == Decimal("0")


async def test_frozen_wallet_cannot_be_debited(
    client: AsyncClient, clean_database
) -> None:
    """A frozen source cannot transfer or be charged. Its balance stays put."""
    created = await _sponsor(client, name="frozen", credits=100)
    sponsor_id = created["body"]["wallet_id"]
    source = await _agent(client, sponsor_id, "frozen-src", 30)
    dest = await _agent(client, sponsor_id, "frozen-dst", 5)
    await _set_status(source, "frozen")

    transfer = await client.post(
        "/v1/billing/transfer",
        params={"from_wallet_id": source, "to_wallet_id": dest, "amount": 10},
        headers=BOOTSTRAP,
    )
    charge = await client.post(
        f"/v1/billing/charge?wallet_id={source}&service=platform_fee&units=1",
        headers=BOOTSTRAP,
    )

    assert transfer.status_code == 400, transfer.text
    assert charge.status_code == 403, charge.text
    assert "frozen" in charge.text.lower()
    assert await _balance(source) == Decimal("30")
    assert await _balance(dest) == Decimal("5")


async def test_missing_or_foreign_currency_does_not_mint_credits(
    client: AsyncClient, clean_database
) -> None:
    """Blank or non-USD currency must not open a wallet or post a balance."""
    for currency in ("", "   ", "EUR", "US", "usd1"):
        refused = await _sponsor(
            client, name=f"cur-{currency or 'blank'}", credits=50, currency=currency
        )
        assert refused["status"] == 422, refused

    assert await _wallet_count() == 0

    money = get_agent_money()
    with pytest.raises(ValueError, match="currency"):
        await money.create_sponsor_wallet(
            sponsor_name="engine-blank",
            email="blank@break.example",
            initial_credits=Decimal("50"),
            currency=" ",
        )
    with pytest.raises(ValueError, match="currency"):
        await money.create_sponsor_wallet(
            sponsor_name="engine-eur",
            email="eur@break.example",
            initial_credits=Decimal("50"),
            currency="EUR",
        )
    assert await _wallet_count() == 0

    # The only accepted code still mints, including the lowercase form.
    allowed = await _sponsor(client, name="usd", credits=15, currency="usd")
    assert allowed["status"] == 201, allowed
    assert await _balance(allowed["body"]["wallet_id"]) == Decimal("15")


async def test_negative_and_unstorable_sponsor_credits_are_refused(
    client: AsyncClient, clean_database
) -> None:
    """A negative or unstorable opening balance must not create a wallet."""
    money = get_agent_money()
    with pytest.raises(ValueError, match="negative"):
        await money.create_sponsor_wallet(
            sponsor_name="engine-neg",
            email="neg@break.example",
            initial_credits=Decimal("-20"),
        )
    assert await _wallet_count() == 0

    negative = await _sponsor(client, name="neg", credits=-20)
    dust = await _sponsor(client, name="dust", credits=1e-9)
    overscale = await _sponsor(client, name="wide", credits=999999999999.99)
    assert negative["status"] == 422
    assert dust["status"] == 422, dust
    assert overscale["status"] == 422, overscale
    assert await _wallet_count() == 0
    with pytest.raises(ValueError, match="precision"):
        await money.create_sponsor_wallet(
            sponsor_name="engine-dust",
            email="dust@break.example",
            initial_credits=Decimal("0.000000001"),
        )
    with pytest.raises(ValueError, match="precision"):
        await money.create_agent_wallet(
            sponsor_wallet_id="spn-missing",
            agent_id="dust-agent",
            budget_credits=Decimal("0.000000001"),
        )
    assert await _wallet_count() == 0


async def test_reused_idempotency_key_cannot_change_destination(
    client: AsyncClient, clean_database
) -> None:
    """The same transfer key with a different destination must not move money again."""
    created = await _sponsor(client, name="idem", credits=100)
    sponsor_id = created["body"]["wallet_id"]
    source = await _agent(client, sponsor_id, "idem-src", 50)
    first = await _agent(client, sponsor_id, "idem-a", 1)
    second = await _agent(client, sponsor_id, "idem-b", 1)
    headers = {**BOOTSTRAP, "Idempotency-Key": "break-xfer-dest"}

    original = await client.post(
        "/v1/billing/transfer",
        params={"from_wallet_id": source, "to_wallet_id": first, "amount": 15},
        headers=headers,
    )
    assert original.status_code == 200, original.text

    conflict = await client.post(
        "/v1/billing/transfer",
        params={"from_wallet_id": source, "to_wallet_id": second, "amount": 15},
        headers=headers,
    )
    replay = await client.post(
        "/v1/billing/transfer",
        params={"from_wallet_id": source, "to_wallet_id": first, "amount": 15},
        headers=headers,
    )

    assert conflict.status_code == 409, conflict.text
    assert replay.status_code == 200, replay.text
    assert await _balance(source) == Decimal("35")
    assert await _balance(first) == Decimal("16")
    assert await _balance(second) == Decimal("1")
    # Provisioning writes one ledger row. The conflicting transfer must not
    # add another.
    assert await _ledger_count(second) == 1


async def test_transfer_auth_bypass_does_not_move_money(
    client: AsyncClient, clean_database
) -> None:
    """A missing key, an unknown key, or another wallet's key cannot debit."""
    created = await _sponsor(client, name="auth", credits=100)
    sponsor_id = created["body"]["wallet_id"]
    source = await _agent(client, sponsor_id, "auth-src", 40)
    dest = await _agent(client, sponsor_id, "auth-dst", 10)
    key = await client.post(
        "/v1/api-keys",
        json={"wallet_id": dest, "key_name": "dest-only"},
        headers=BOOTSTRAP,
    )
    assert key.status_code == 201, key.text
    params = {"from_wallet_id": source, "to_wallet_id": dest, "amount": 5}

    missing = await client.post("/v1/billing/transfer", params=params)
    unknown = await client.post(
        "/v1/billing/transfer",
        params=params,
        headers={"X-API-Key": "not-a-real-key"},
    )
    foreign = await client.post(
        "/v1/billing/transfer",
        params=params,
        headers={"X-API-Key": key.json()["api_key"]},
    )

    assert missing.status_code == 401, missing.text
    assert unknown.status_code == 403, unknown.text
    assert foreign.status_code == 403, foreign.text
    assert await _balance(source) == Decimal("40")
    assert await _balance(dest) == Decimal("10")
