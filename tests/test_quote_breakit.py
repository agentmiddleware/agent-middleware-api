"""Adversarial checks for signed quotes: expiry, tool, sign, category, replay.

These pin the charge to the quoted credits. A quote that is expired, spent by
someone else, or issued for another tool must not move money. A price the
storage check accepts must still be the amount debited.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.credits import credit_amount_fits_storage
from app.db.database import get_session_factory
from app.db.models import QuoteModel, WalletModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.quotes import get_quote_service
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

TOOL = "quote-break-echo"
# Float prints this 8-place value shorter than the stored form. The storage
# check still accepts it, because it compares the 8-place reconstruction.
OPAQUE_PRICE = Decimal("76613879.62108959")


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def registered_tool():
    registry = get_service_registry()

    def quote_echo(message: str = "ok") -> dict:
        return {"message": message}

    def register(
        price: float,
        *,
        category: ServiceCategory = ServiceCategory.AGENT_COMMS,
        exact: str | None = None,
    ) -> None:
        registry.register_local(
            service_id=TOOL,
            name="Quote Break Echo",
            description="Adversarial quote test tool",
            category=category,
            func=quote_echo,
            credits_per_unit=price,
            unit_name="call",
        )
        if exact is not None:
            registry.get_local(TOOL)["credits_per_unit_exact"] = exact

    register(2.0)
    yield register
    registry.unregister_local(TOOL)


async def _quote(client, headers, wallet_id: str, tool: str = TOOL, extra=None):
    body = {"wallet_id": wallet_id, "tool": tool}
    if extra:
        body.update(extra)
    return await client.post("/v1/quotes", json=body, headers=headers)


async def _invoke(
    client,
    headers,
    *,
    wallet_id,
    permit_id,
    quote_id=None,
    idem=None,
    arguments=None,
    tool: str = TOOL,
):
    context = {
        "wallet_id": wallet_id,
        "permit_id": permit_id,
        "idempotency_key": idem or f"inv-{uuid.uuid4().hex[:12]}",
    }
    if quote_id is not None:
        context["quote_id"] = quote_id
    return await client.post(
        f"/mcp/tools/{tool}/invoke",
        json={
            "name": tool,
            "arguments": arguments if arguments is not None else {"message": "hi"},
            "mcp_context": context,
        },
        headers=headers,
    )


async def _balance(wallet_id: str) -> Decimal:
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        return wallet.balance


async def _set_wallet(wallet_id: str, *, balance: Decimal, daily_limit) -> None:
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        wallet.balance = balance
        wallet.daily_limit = daily_limit
        session.add(wallet)
        await session.commit()


def _debited(before: Decimal, after: Decimal) -> Decimal:
    return before - after


@pytest.mark.asyncio
async def test_opaque_storable_price_charges_the_quoted_credits(
    client, clean_database, registered_tool
):
    """A price the storage check accepts must debit that price, not the float.

    ``Decimal(str(float(price)))`` drops digits that the 8-place storage check
    keeps. The charge used to compare the float display and fail after the
    debit, burning the quote.
    """
    assert credit_amount_fits_storage(OPAQUE_PRICE)
    assert Decimal(str(float(OPAQUE_PRICE))) != OPAQUE_PRICE

    registered_tool(1.0, exact=str(OPAQUE_PRICE))
    agent = await provision_agent_wallet(client)
    await _set_wallet(
        agent["agent_wallet_id"],
        balance=OPAQUE_PRICE + Decimal("10"),
        daily_limit=None,
    )
    permit = await create_tool_permit(
        client,
        wallet_id=agent["agent_wallet_id"],
        key_id=agent["key_id"],
        tool_name=TOOL,
        max_credits=str(OPAQUE_PRICE),
        idem_key="permit-quote-opaque",
    )
    quoted = await _quote(client, agent["agent_headers"], agent["agent_wallet_id"])
    assert quoted.status_code == 201, quoted.text
    assert Decimal(str(quoted.json()["quoted_credits"])) == OPAQUE_PRICE

    before = await _balance(agent["agent_wallet_id"])
    resp = await _invoke(
        client,
        agent["agent_headers"],
        wallet_id=agent["agent_wallet_id"],
        permit_id=permit["permit_id"],
        quote_id=quoted.json()["quote_id"],
        idem="opaque-charge-1",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("isError") is not True
    assert _debited(before, await _balance(agent["agent_wallet_id"])) == OPAQUE_PRICE
    receipt = body["receipt"]
    assert Decimal(str(receipt["credits_charged"])) == OPAQUE_PRICE


@pytest.mark.asyncio
async def test_same_idempotency_key_replays_quoted_charge_without_paying_again(
    client, clean_database, registered_tool
):
    """A lost response must be recoverable by retrying the same key.

    The quote is already spent by that key. The retry has to return the
    original receipt and must not debit again. A different key stays denied.
    """
    agent = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=agent["agent_wallet_id"],
        key_id=agent["key_id"],
        tool_name=TOOL,
        idem_key="permit-quote-replay",
    )
    quote = (
        await _quote(client, agent["agent_headers"], agent["agent_wallet_id"])
    ).json()

    before = await _balance(agent["agent_wallet_id"])
    first = await _invoke(
        client,
        agent["agent_headers"],
        wallet_id=agent["agent_wallet_id"],
        permit_id=permit["permit_id"],
        quote_id=quote["quote_id"],
        idem="quoted-replay-key",
    )
    assert first.status_code == 200, first.text
    receipt_id = first.json()["receipt"]["receipt_id"]
    after_first = await _balance(agent["agent_wallet_id"])
    assert _debited(before, after_first) == Decimal("2.0")

    second = await _invoke(
        client,
        agent["agent_headers"],
        wallet_id=agent["agent_wallet_id"],
        permit_id=permit["permit_id"],
        quote_id=quote["quote_id"],
        idem="quoted-replay-key",
    )
    assert second.status_code == 200, second.text
    assert second.json()["receipt"]["receipt_id"] == receipt_id
    assert await _balance(agent["agent_wallet_id"]) == after_first

    other = await _invoke(
        client,
        agent["agent_headers"],
        wallet_id=agent["agent_wallet_id"],
        permit_id=permit["permit_id"],
        quote_id=quote["quote_id"],
        idem="quoted-replay-other",
    )
    assert other.status_code == 403
    assert "quote_already_consumed" in other.text
    assert await _balance(agent["agent_wallet_id"]) == after_first

    # Same key, different arguments: not a second sale, and not the old receipt.
    clash = await _invoke(
        client,
        agent["agent_headers"],
        wallet_id=agent["agent_wallet_id"],
        permit_id=permit["permit_id"],
        quote_id=quote["quote_id"],
        idem="quoted-replay-key",
        arguments={"message": "different"},
    )
    assert clash.status_code != 200
    assert await _balance(agent["agent_wallet_id"]) == after_first
    assert clash.json().get("receipt", {}).get("receipt_id") != receipt_id


@pytest.mark.asyncio
async def test_expired_quote_cannot_be_consumed_or_revived(
    client, clean_database, registered_tool
):
    agent = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=agent["agent_wallet_id"],
        key_id=agent["key_id"],
        tool_name=TOOL,
        idem_key="permit-quote-expiry-sql",
    )
    service = get_quote_service()
    fresh = (
        await _quote(client, agent["agent_headers"], agent["agent_wallet_id"])
    ).json()
    spent = (
        await _quote(client, agent["agent_headers"], agent["agent_wallet_id"])
    ).json()
    assert await service.consume(spent["quote_id"], idempotency_key="spent-key")

    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
    factory = get_session_factory()
    async with factory() as session:
        for quote_id in (fresh["quote_id"], spent["quote_id"]):
            model = await session.get(QuoteModel, quote_id)
            model.expires_at = past
            session.add(model)
        await session.commit()

    assert await service.consume(fresh["quote_id"], idempotency_key="late") is False
    assert await service.release(spent["quote_id"]) is False

    async with factory() as session:
        fresh_row = await session.get(QuoteModel, fresh["quote_id"])
        spent_row = await session.get(QuoteModel, spent["quote_id"])
    assert fresh_row.status == "active"
    assert spent_row.status == "consumed"
    assert spent_row.consumed_by_idempotency_key == "spent-key"

    before = await _balance(agent["agent_wallet_id"])
    resp = await _invoke(
        client,
        agent["agent_headers"],
        wallet_id=agent["agent_wallet_id"],
        permit_id=permit["permit_id"],
        quote_id=fresh["quote_id"],
    )
    assert resp.status_code == 403
    assert "quote_expired" in resp.text
    assert await _balance(agent["agent_wallet_id"]) == before


@pytest.mark.asyncio
async def test_wrong_tool_case_and_foreign_quote_do_not_charge(
    client, clean_database, registered_tool
):
    agent = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=agent["agent_wallet_id"],
        key_id=agent["key_id"],
        tool_name=TOOL,
        idem_key="permit-quote-wrong-tool",
    )
    other = await get_quote_service().create_quote(
        wallet_id=agent["agent_wallet_id"],
        tool=TOOL.upper(),
        quoted_credits=Decimal("0.01"),
        category=ServiceCategory.AGENT_COMMS.value,
    )
    before = await _balance(agent["agent_wallet_id"])
    resp = await _invoke(
        client,
        agent["agent_headers"],
        wallet_id=agent["agent_wallet_id"],
        permit_id=permit["permit_id"],
        quote_id=other.quote_id,
    )
    assert resp.status_code == 403
    assert "quote_tool_mismatch" in resp.text
    assert await _balance(agent["agent_wallet_id"]) == before

    padded = await _quote(
        client,
        agent["agent_headers"],
        agent["agent_wallet_id"],
        tool=f" {TOOL}",
    )
    assert padded.status_code == 404


@pytest.mark.asyncio
async def test_negative_price_is_refused_and_does_not_mint(
    client, clean_database, registered_tool
):
    agent = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=agent["agent_wallet_id"],
        key_id=agent["key_id"],
        tool_name=TOOL,
        idem_key="permit-quote-negative",
    )
    registered_tool(-5.0)
    refused = await _quote(client, agent["agent_headers"], agent["agent_wallet_id"])
    assert refused.status_code == 400
    assert refused.json()["detail"] == "tool_price_invalid"

    registered_tool(2.0)
    quote = (
        await _quote(client, agent["agent_headers"], agent["agent_wallet_id"])
    ).json()
    registered_tool(-5.0)
    before = await _balance(agent["agent_wallet_id"])
    resp = await _invoke(
        client,
        agent["agent_headers"],
        wallet_id=agent["agent_wallet_id"],
        permit_id=permit["permit_id"],
        quote_id=quote["quote_id"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("isError") is not True
    assert _debited(before, await _balance(agent["agent_wallet_id"])) == Decimal("2.0")
    assert Decimal(str(body["receipt"]["credits_charged"])) == Decimal("2.0")
    read = await client.get(
        f"/v1/quotes/{quote['quote_id']}", headers=agent["agent_headers"]
    )
    assert read.json()["status"] == "consumed"


@pytest.mark.asyncio
async def test_category_change_and_price_hike_still_charge_the_quote(
    client, clean_database, registered_tool
):
    agent = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=agent["agent_wallet_id"],
        key_id=agent["key_id"],
        tool_name=TOOL,
        max_credits=50,
        idem_key="permit-quote-category",
    )
    quote = (
        await _quote(client, agent["agent_headers"], agent["agent_wallet_id"])
    ).json()
    assert quote["category"] == ServiceCategory.AGENT_COMMS.value
    assert Decimal(str(quote["quoted_credits"])) == Decimal("2.0")

    registered_tool(50.0, category=ServiceCategory.CONTENT_FACTORY)
    before = await _balance(agent["agent_wallet_id"])
    resp = await _invoke(
        client,
        agent["agent_headers"],
        wallet_id=agent["agent_wallet_id"],
        permit_id=permit["permit_id"],
        quote_id=quote["quote_id"],
    )
    assert resp.status_code == 200, resp.text
    assert _debited(before, await _balance(agent["agent_wallet_id"])) == Decimal("2.0")
    assert Decimal(str(resp.json()["receipt"]["credits_charged"])) == Decimal("2.0")


@pytest.mark.asyncio
async def test_client_cannot_name_the_price_or_a_currency(
    client, clean_database, registered_tool
):
    agent = await provision_agent_wallet(client)
    resp = await _quote(
        client,
        agent["agent_headers"],
        agent["agent_wallet_id"],
        extra={"quoted_credits": "-100", "currency": "EUR", "category": "oracle"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert Decimal(str(body["quoted_credits"])) == Decimal("2.0")
    assert body["category"] == ServiceCategory.AGENT_COMMS.value
    assert "currency" not in body


@pytest.mark.asyncio
async def test_concurrent_invokes_spend_one_quote(
    client, clean_database, registered_tool
):
    agent = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=agent["agent_wallet_id"],
        key_id=agent["key_id"],
        tool_name=TOOL,
        idem_key="permit-quote-race",
    )
    quote = (
        await _quote(client, agent["agent_headers"], agent["agent_wallet_id"])
    ).json()
    before = await _balance(agent["agent_wallet_id"])
    first, second = await asyncio.gather(
        _invoke(
            client,
            agent["agent_headers"],
            wallet_id=agent["agent_wallet_id"],
            permit_id=permit["permit_id"],
            quote_id=quote["quote_id"],
            idem="race-a",
        ),
        _invoke(
            client,
            agent["agent_headers"],
            wallet_id=agent["agent_wallet_id"],
            permit_id=permit["permit_id"],
            quote_id=quote["quote_id"],
            idem="race-b",
        ),
    )
    codes = sorted([first.status_code, second.status_code])
    assert codes == [200, 403], (first.text, second.text)
    denied = first if first.status_code == 403 else second
    assert "quote_already_consumed" in denied.text
    assert _debited(before, await _balance(agent["agent_wallet_id"])) == Decimal("2.0")
    factory = get_session_factory()
    async with factory() as session:
        rows = (await session.execute(select(QuoteModel))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "consumed"
