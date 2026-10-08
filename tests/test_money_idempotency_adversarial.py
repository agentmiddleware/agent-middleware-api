"""Adversarial checks for money-moving idempotency.

Same key and same arguments must replay the original result. Same key and
different arguments must answer idempotency_key_reused. A header that is
present but unusable must be refused before any debit, transfer, provision,
or settlement. An absent header stays an unkeyed call on the opt-in billing
routes.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel, LedgerEntryModel
from app.main import app
from app.services.idempotency import MAX_CLIENT_IDEMPOTENCY_KEY_LENGTH
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet
from tests.test_x402 import EVM_PAY_TO, EVM_PAYER, _settle_body

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


async def _debit_count(wallet_id: str) -> int:
    factory = get_session_factory()
    async with factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(LedgerEntryModel)
            .where(
                LedgerEntryModel.wallet_id == wallet_id,
                LedgerEntryModel.action == "debit",
            )
        )
    return int(count or 0)


async def _idempotency_count() -> int:
    factory = get_session_factory()
    async with factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(IdempotencyRecordModel)
        )
    return int(count or 0)


async def _funded_agent(
    client: AsyncClient, api_headers: dict, tag: str
) -> tuple[str, str]:
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": tag,
            "email": f"{tag}@example.com",
            "initial_credits": 10000,
        },
        headers=api_headers,
    )
    assert sponsor.status_code == 201, sponsor.text
    sponsor_id = sponsor.json()["wallet_id"]
    agent = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor_id,
            "agent_id": tag,
            "budget_credits": 5000,
        },
        headers=api_headers,
    )
    assert agent.status_code == 201, agent.text
    return sponsor_id, agent.json()["wallet_id"]


def _assert_invalid_key(response, reason_code: str) -> None:
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "invalid_idempotency_key"
    assert detail["reason_code"] == reason_code
    assert detail["remediation"]["type"] == "retry_with_valid_idempotency_key"


async def test_charge_same_key_same_body_replays_original_entry(
    client, api_headers, clean_database
):
    _sponsor, agent_id = await _funded_agent(client, api_headers, "replay-charge")
    headers = {**api_headers, "Idempotency-Key": "charge-replay-1"}
    url = f"/v1/billing/charge?wallet_id={agent_id}&service=iot_bridge&units=10"
    first = await client.post(url, headers=headers)
    assert first.status_code == 200, first.text
    second = await client.post(url, headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["entry_id"] == first.json()["entry_id"]
    assert second.json() == first.json()
    assert await _debit_count(agent_id) == 1


async def test_charge_same_key_different_units_is_reused(
    client, api_headers, clean_database
):
    _sponsor, agent_id = await _funded_agent(client, api_headers, "conflict-charge")
    headers = {**api_headers, "Idempotency-Key": "charge-conflict-1"}
    first = await client.post(
        f"/v1/billing/charge?wallet_id={agent_id}&service=iot_bridge&units=10",
        headers=headers,
    )
    assert first.status_code == 200, first.text
    conflict = await client.post(
        f"/v1/billing/charge?wallet_id={agent_id}&service=iot_bridge&units=11",
        headers=headers,
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["error"] == "idempotency_key_reused"
    assert await _debit_count(agent_id) == 1


async def test_charge_without_a_key_is_a_new_debit_each_time(
    client, api_headers, clean_database
):
    """An absent header is an unkeyed call. A blank header is not."""
    _sponsor, agent_id = await _funded_agent(client, api_headers, "unkeyed-charge")
    url = f"/v1/billing/charge?wallet_id={agent_id}&service=iot_bridge&units=1"
    first = await client.post(url, headers=api_headers)
    second = await client.post(url, headers=api_headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["entry_id"] != second.json()["entry_id"]
    assert await _debit_count(agent_id) == 2


@pytest.mark.parametrize(
    ("header_value", "reason_code"),
    [
        ("", "idempotency_key_blank"),
        ("   ", "idempotency_key_blank"),
        ("\t", "idempotency_key_blank"),
        ("x" * (MAX_CLIENT_IDEMPOTENCY_KEY_LENGTH + 1), "idempotency_key_too_long"),
        ("chg\x00key", "idempotency_key_control_characters"),
        ("chg\x7fkey", "idempotency_key_control_characters"),
        ("chg\nkey", "idempotency_key_control_characters"),
        (b"chg-\xe9-key", "idempotency_key_not_utf8"),
    ],
)
async def test_charge_rejects_unusable_key_before_any_debit(
    client, api_headers, clean_database, header_value, reason_code
):
    _sponsor, agent_id = await _funded_agent(client, api_headers, "bad-charge-key")
    url = f"/v1/billing/charge?wallet_id={agent_id}&service=iot_bridge&units=10"
    headers = [*api_headers.items(), ("Idempotency-Key", header_value)]
    for _ in range(2):
        response = await client.post(url, headers=headers)
        _assert_invalid_key(response, reason_code)
    assert await _debit_count(agent_id) == 0
    assert await _idempotency_count() == 0


async def test_charge_key_at_column_limit_replays(client, api_headers, clean_database):
    _sponsor, agent_id = await _funded_agent(client, api_headers, "max-charge-key")
    headers = {
        **api_headers,
        "Idempotency-Key": "k" * MAX_CLIENT_IDEMPOTENCY_KEY_LENGTH,
    }
    url = f"/v1/billing/charge?wallet_id={agent_id}&service=iot_bridge&units=2"
    first = await client.post(url, headers=headers)
    second = await client.post(url, headers=headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["entry_id"] == first.json()["entry_id"]
    assert await _debit_count(agent_id) == 1


async def test_charge_keeps_distinct_keys_that_differ_by_whitespace(
    client, api_headers, clean_database
):
    _sponsor, agent_id = await _funded_agent(client, api_headers, "space-charge-key")
    url = f"/v1/billing/charge?wallet_id={agent_id}&service=iot_bridge&units=1"
    receipts = []
    for key in ("k", " k", "k "):
        response = await client.post(
            url, headers={**api_headers, "Idempotency-Key": key}
        )
        assert response.status_code == 200, response.text
        receipts.append(response.json()["entry_id"])
        replay = await client.post(url, headers={**api_headers, "Idempotency-Key": key})
        assert replay.json()["entry_id"] == response.json()["entry_id"]
    assert len(set(receipts)) == 3
    assert await _debit_count(agent_id) == 3


async def test_charge_conflicting_header_lines_do_not_debit(
    client, api_headers, clean_database
):
    _sponsor, agent_id = await _funded_agent(client, api_headers, "dup-charge-key")
    url = f"/v1/billing/charge?wallet_id={agent_id}&service=iot_bridge&units=10"
    headers = [
        *api_headers.items(),
        ("Idempotency-Key", "charge-dup-a"),
        ("Idempotency-Key", "charge-dup-b"),
    ]
    for _ in range(2):
        response = await client.post(url, headers=headers)
        _assert_invalid_key(response, "idempotency_key_conflict")
    assert await _debit_count(agent_id) == 0

    repeated = [
        *api_headers.items(),
        ("Idempotency-Key", "charge-dup-same"),
        ("Idempotency-Key", "charge-dup-same"),
    ]
    first = await client.post(url, headers=repeated)
    second = await client.post(url, headers=repeated)
    assert first.status_code == 200, first.text
    assert second.json()["entry_id"] == first.json()["entry_id"]
    assert await _debit_count(agent_id) == 1


async def test_concurrent_charge_same_key_debits_once(
    client, api_headers, clean_database
):
    _sponsor, agent_id = await _funded_agent(client, api_headers, "race-charge")
    headers = {**api_headers, "Idempotency-Key": "charge-race-1"}
    url = f"/v1/billing/charge?wallet_id={agent_id}&service=iot_bridge&units=4"
    responses = await asyncio.gather(
        *[client.post(url, headers=headers) for _ in range(6)]
    )
    statuses = [response.status_code for response in responses]
    assert set(statuses) <= {200, 409}, [response.text for response in responses]
    winners = [response for response in responses if response.status_code == 200]
    assert winners, statuses
    assert len({response.json()["entry_id"] for response in winners}) == 1
    assert await _debit_count(agent_id) == 1


async def test_utf8_charge_key_replays_the_same_entry(
    client, api_headers, clean_database
):
    _sponsor, agent_id = await _funded_agent(client, api_headers, "utf8-charge")
    # httpx encodes str header values as ASCII, so the UTF-8 bytes go on the
    # wire directly. The stored key must be the UTF-8 text, not the latin-1
    # reading of those bytes.
    wire = "café-charge-1".encode("utf-8")
    headers = [*api_headers.items(), ("Idempotency-Key", wire)]
    url = f"/v1/billing/charge?wallet_id={agent_id}&service=iot_bridge&units=3"
    first = await client.post(url, headers=headers)
    second = await client.post(url, headers=headers)
    assert first.status_code == 200, first.text
    assert second.json()["entry_id"] == first.json()["entry_id"]
    assert await _debit_count(agent_id) == 1
    factory = get_session_factory()
    async with factory() as session:
        stored = list(
            await session.scalars(select(IdempotencyRecordModel.idempotency_key))
        )
    assert stored == ["café-charge-1"]


async def test_transfer_same_key_replays_and_different_args_conflict(
    client, api_headers, clean_database
):
    sponsor_id, source_id = await _funded_agent(client, api_headers, "xfer-replay")
    dest = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor_id,
            "agent_id": "xfer-replay-dest",
            "budget_credits": 100,
        },
        headers=api_headers,
    )
    assert dest.status_code == 201, dest.text
    dest_id = dest.json()["wallet_id"]
    headers = {**api_headers, "Idempotency-Key": "xfer-replay-1"}
    url = (
        f"/v1/billing/transfer?from_wallet_id={source_id}"
        f"&to_wallet_id={dest_id}&amount=25&correlation_id=corr-1"
    )
    first = await client.post(url, headers=headers)
    assert first.status_code == 200, first.text
    second = await client.post(url, headers=headers)
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    conflict = await client.post(
        f"/v1/billing/transfer?from_wallet_id={source_id}"
        f"&to_wallet_id={dest_id}&amount=25&correlation_id=corr-2",
        headers=headers,
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["error"] == "idempotency_key_reused"
    source = await client.get(f"/v1/billing/wallets/{source_id}", headers=api_headers)
    dest_wallet = await client.get(
        f"/v1/billing/wallets/{dest_id}", headers=api_headers
    )
    assert source.json()["balance"] == 4975.0
    assert dest_wallet.json()["balance"] == 125.0


@pytest.mark.parametrize(
    ("header_value", "reason_code"),
    [
        ("", "idempotency_key_blank"),
        ("   ", "idempotency_key_blank"),
        ("y" * (MAX_CLIENT_IDEMPOTENCY_KEY_LENGTH + 1), "idempotency_key_too_long"),
        ("xfer\x7fkey", "idempotency_key_control_characters"),
        (b"xfer-\xff", "idempotency_key_not_utf8"),
    ],
)
async def test_transfer_rejects_unusable_key_before_moving_credits(
    client, api_headers, clean_database, header_value, reason_code
):
    sponsor_id, source_id = await _funded_agent(client, api_headers, "bad-xfer-key")
    dest = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor_id,
            "agent_id": "bad-xfer-dest",
            "budget_credits": 50,
        },
        headers=api_headers,
    )
    dest_id = dest.json()["wallet_id"]
    url = (
        f"/v1/billing/transfer?from_wallet_id={source_id}"
        f"&to_wallet_id={dest_id}&amount=10"
    )
    headers = [*api_headers.items(), ("Idempotency-Key", header_value)]
    for _ in range(2):
        response = await client.post(url, headers=headers)
        _assert_invalid_key(response, reason_code)
    source = await client.get(f"/v1/billing/wallets/{source_id}", headers=api_headers)
    assert source.json()["balance"] == 5000.0
    assert await _idempotency_count() == 0


async def test_transfer_conflicting_header_lines_do_not_move_credits(
    client, api_headers, clean_database
):
    sponsor_id, source_id = await _funded_agent(client, api_headers, "dup-xfer")
    dest = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor_id,
            "agent_id": "dup-xfer-dest",
            "budget_credits": 20,
        },
        headers=api_headers,
    )
    dest_id = dest.json()["wallet_id"]
    url = (
        f"/v1/billing/transfer?from_wallet_id={source_id}"
        f"&to_wallet_id={dest_id}&amount=15"
    )
    headers = [
        *api_headers.items(),
        ("Idempotency-Key", "xfer-a"),
        ("Idempotency-Key", "xfer-b"),
    ]
    response = await client.post(url, headers=headers)
    _assert_invalid_key(response, "idempotency_key_conflict")
    source = await client.get(f"/v1/billing/wallets/{source_id}", headers=api_headers)
    assert source.json()["balance"] == 5000.0


async def test_blank_key_does_not_fund_a_second_agent_wallet(
    client, api_headers, clean_database
):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "blank-provision",
            "email": "blank-provision@example.com",
            "initial_credits": 1000,
        },
        headers=api_headers,
    )
    sponsor_id = sponsor.json()["wallet_id"]
    payload = {
        "sponsor_wallet_id": sponsor_id,
        "agent_id": "blank-bot",
        "budget_credits": 100,
    }
    headers = [*api_headers.items(), ("Idempotency-Key", "")]
    for _ in range(2):
        response = await client.post(
            "/v1/billing/wallets/agent", json=payload, headers=headers
        )
        _assert_invalid_key(response, "idempotency_key_blank")
    wallet = await client.get(f"/v1/billing/wallets/{sponsor_id}", headers=api_headers)
    assert wallet.json()["balance"] == 1000.0


async def test_direct_top_up_does_not_mint_with_or_without_a_key(
    client, api_headers, clean_database
):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "topup-closed",
            "email": "topup-closed@example.com",
            "initial_credits": 0,
        },
        headers=api_headers,
    )
    wallet_id = sponsor.json()["wallet_id"]
    body = {"wallet_id": wallet_id, "amount_fiat": 25.0}
    missing = await client.post("/v1/billing/top-up", json=body, headers=api_headers)
    blank = await client.post(
        "/v1/billing/top-up",
        json=body,
        headers=[*api_headers.items(), ("Idempotency-Key", "")],
    )
    assert missing.status_code == 410, missing.text
    assert blank.status_code == 410, blank.text
    wallet = await client.get(f"/v1/billing/wallets/{wallet_id}", headers=api_headers)
    assert wallet.json()["balance"] == 0.0


async def test_x402_missing_key_is_rejected():
    """The settle route declares the header required. Absence never settles."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/x402/settle",
            json=_settle_body(permit_id="permit-missing", wallet_id="wallet-missing"),
            headers={"X-API-Key": "test-key"},
        )
    assert response.status_code == 422, response.text
    assert "Idempotency-Key" in response.text


@pytest.mark.parametrize(
    ("header_value", "reason_code"),
    [
        ("", "idempotency_key_blank"),
        ("   ", "idempotency_key_blank"),
        ("z" * (MAX_CLIENT_IDEMPOTENCY_KEY_LENGTH + 1), "idempotency_key_too_long"),
        ("x402\x7fkey", "idempotency_key_control_characters"),
        (b"x402-\xe9", "idempotency_key_not_utf8"),
    ],
)
async def test_x402_rejects_unusable_key_before_reservation(
    client, clean_database, header_value, reason_code
):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="x402.payment",
        max_credits=100,
        idem_key=f"x402-bad-key-permit-{reason_code}",
    )
    response = await client.post(
        "/v1/x402/settle",
        json=_settle_body(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            amount="0.03",
            pay_to=EVM_PAY_TO,
            payer=EVM_PAYER,
        ),
        headers=[
            *provisioned["agent_headers"].items(),
            ("Idempotency-Key", header_value),
        ],
    )
    _assert_invalid_key(response, reason_code)
    spent = await client.get(
        f"/v1/permits/{permit['permit_id']}",
        headers={"X-API-Key": "test-key"},
    )
    assert spent.status_code == 200, spent.text
    assert Decimal(str(spent.json()["spent_credits"])) == Decimal("0")


async def test_x402_same_key_replays_and_different_amount_conflicts(
    client, clean_database
):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    permit = await create_tool_permit(
        client,
        wallet_id=wallet_id,
        key_id=provisioned["key_id"],
        tool_name="x402.payment",
        max_credits=100,
        idem_key="x402-replay-permit",
    )
    headers = {**provisioned["agent_headers"], "Idempotency-Key": "x402-replay-1"}
    body = _settle_body(
        permit_id=permit["permit_id"],
        wallet_id=wallet_id,
        amount="0.02",
        pay_to=EVM_PAY_TO,
        payer=EVM_PAYER,
    )
    first = await client.post("/v1/x402/settle", json=body, headers=headers)
    assert first.status_code == 200, first.text
    second = await client.post("/v1/x402/settle", json=body, headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["receipt_id"] == first.json()["receipt_id"]

    other = dict(body)
    other["amount"] = "0.04"
    conflict = await client.post("/v1/x402/settle", json=other, headers=headers)
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"] == "idempotency_key_reused"
    spent = await client.get(
        f"/v1/permits/{permit['permit_id']}",
        headers={"X-API-Key": "test-key"},
    )
    assert Decimal(str(spent.json()["spent_credits"])) == Decimal("20")


async def test_x402_conflicting_header_lines_do_not_reserve(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="x402.payment",
        max_credits=100,
        idem_key="x402-dup-permit",
    )
    response = await client.post(
        "/v1/x402/settle",
        json=_settle_body(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            amount="0.01",
            pay_to=EVM_PAY_TO,
            payer=EVM_PAYER,
        ),
        headers=[
            *provisioned["agent_headers"].items(),
            ("Idempotency-Key", "x402-a"),
            ("Idempotency-Key", "x402-b"),
        ],
    )
    _assert_invalid_key(response, "idempotency_key_conflict")
    spent = await client.get(
        f"/v1/permits/{permit['permit_id']}",
        headers={"X-API-Key": "test-key"},
    )
    assert Decimal(str(spent.json()["spent_credits"])) == Decimal("0")
