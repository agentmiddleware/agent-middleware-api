"""Credit-cap preservation and storage-compatible signed permit inputs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

from app.db.database import get_session_factory
from app.db.models import LedgerEntryModel, PermitModel, WalletModel
from app.main import app
from app.schemas.trust import PermitCreateRequest, PermitRequestCreate
from app.services.permits import get_permit_service
from tests.test_trust_helpers import BOOTSTRAP_HEADERS, provision_agent_wallet

TOOL = "accounting-input-validation"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as instance:
        yield instance


async def _create_zero_cap_wallet(client: AsyncClient) -> dict[str, Any]:
    provisioned = await provision_agent_wallet(client)
    response = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": provisioned["sponsor_wallet_id"],
            "agent_id": "zero-daily-cap-regression",
            "budget_credits": 10,
            "daily_limit": 0,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.anyio
async def test_zero_daily_limit_is_preserved_in_response_and_storage(
    client: AsyncClient, clean_database
) -> None:
    created = await _create_zero_cap_wallet(client)
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, created["wallet_id"])
        assert wallet is not None
        observed = (created["daily_limit"], wallet.daily_limit)
    assert observed == (0, Decimal("0")), (
        f"An explicit zero daily cap must not become an absent cap: {observed!r}"
    )


@pytest.mark.anyio
async def test_zero_daily_limit_denies_charge_without_mutating_accounting(
    client: AsyncClient, clean_database
) -> None:
    created = await _create_zero_cap_wallet(client)
    wallet_id = created["wallet_id"]
    response = await client.post(
        "/v1/billing/charge",
        params={"wallet_id": wallet_id, "service": "platform_fee", "units": 1},
        headers=BOOTSTRAP_HEADERS,
    )
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        debits = list(
            (
                await session.execute(
                    select(LedgerEntryModel).where(
                        LedgerEntryModel.wallet_id == wallet_id,
                        LedgerEntryModel.action == "debit",
                    )
                )
            )
            .scalars()
            .all()
        )
        observed = {
            "status": response.status_code,
            "balance": str(wallet.balance),
            "debit_count": len(debits),
            "hourly_spent": str(wallet.hourly_spent),
            "daily_spent": str(wallet.daily_spent),
        }
        assert response.status_code in {402, 403}, observed
        assert wallet.balance == Decimal("10"), observed
        assert not debits, observed
        assert wallet.hourly_spent == Decimal("0"), observed
        assert wallet.daily_spent == Decimal("0"), observed


def _permit_payload(provisioned: dict[str, Any]) -> dict[str, Any]:
    return {
        "issuer_wallet_id": provisioned["agent_wallet_id"],
        "subject_wallet_id": provisioned["agent_wallet_id"],
        "subject_key_id": provisioned["key_id"],
        "allowed_tools": [TOOL],
        "scopes": [f"tool:{TOOL}:invoke", "billing:charge"],
        "max_credits": "2",
        "aggregate_value_cap": "1",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("max_credits", "1.000000001"),
        ("aggregate_value_cap", "0.500000001"),
    ],
)
async def test_permit_rejects_excess_decimal_scale_before_issuing_signed_authority(
    client: AsyncClient, clean_database, field: str, invalid_value: str
) -> None:
    provisioned = await provision_agent_wallet(client)
    payload = _permit_payload(provisioned)
    payload[field] = invalid_value
    response = await client.post(
        "/v1/permits",
        json=payload,
        headers={
            **provisioned["agent_headers"],
            "Idempotency-Key": f"invalid-decimal-scale-{field}",
        },
    )
    factory = get_session_factory()
    async with factory() as session:
        permits = list(
            (
                await session.execute(
                    select(PermitModel).where(
                        PermitModel.subject_wallet_id == provisioned["agent_wallet_id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        # Diagnostic values are accounting data only; never emit auth headers.
        observed = {
            "status": response.status_code,
            "issued_permit_count": len(permits),
            "requested_value": invalid_value,
            "stored_values": [str(getattr(permit, field)) for permit in permits],
            "stored_signatures_valid": [
                await get_permit_service().verify_signature(permit)
                for permit in permits
            ],
        }
    assert response.status_code == 422, observed
    assert not permits, observed


@pytest.mark.anyio
async def test_eight_decimal_permit_values_round_trip_with_valid_signature(
    client: AsyncClient, clean_database
) -> None:
    provisioned = await provision_agent_wallet(client)
    payload = _permit_payload(provisioned)
    payload["max_credits"] = "1.00000001"
    payload["aggregate_value_cap"] = "0.50000001"
    response = await client.post(
        "/v1/permits",
        json=payload,
        headers={
            **provisioned["agent_headers"],
            "Idempotency-Key": "valid-eight-decimal-scale",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert Decimal(body["max_credits"]) == Decimal(payload["max_credits"])
    assert Decimal(body["aggregate_value_cap"]) == Decimal(
        payload["aggregate_value_cap"]
    )
    factory = get_session_factory()
    async with factory() as session:
        permit = await session.get(PermitModel, body["permit_id"])
        assert permit is not None
        assert await get_permit_service().verify_signature(permit) is True


@pytest.mark.anyio
@pytest.mark.dormant
async def test_zero_daily_limit_is_reported_by_velocity_status(
    client: AsyncClient, clean_database
) -> None:
    created = await _create_zero_cap_wallet(client)
    response = await client.get(
        f"/v1/billing/wallets/{created['wallet_id']}/velocity",
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["daily_limit"] == 0
    assert response.json()["daily_pct"] == 0


@pytest.mark.anyio
async def test_omitted_daily_limit_remains_absent_and_allows_funded_charge(
    client: AsyncClient, clean_database
) -> None:
    provisioned = await provision_agent_wallet(client)
    response = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": provisioned["sponsor_wallet_id"],
            "agent_id": "omitted-daily-cap-regression",
            "budget_credits": 10,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201
    wallet_id = response.json()["wallet_id"]
    assert response.json()["daily_limit"] is None
    assert response.json()["daily_limit_exact"] is None
    charged = await client.post(
        "/v1/billing/charge",
        params={"wallet_id": wallet_id, "service": "platform_fee", "units": 1},
        headers=BOOTSTRAP_HEADERS,
    )
    assert charged.status_code == 200
    assert Decimal(charged.json()["amount_exact"]) == Decimal("-0.1")
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        assert wallet.daily_limit is None
        assert wallet.balance == Decimal("9.9")


@pytest.mark.parametrize("field", ["max_credits", "aggregate_value_cap"])
@pytest.mark.parametrize(
    "value",
    ["0.000000001", "1000000000000", "NaN", "Infinity", "-Infinity"],
)
def test_permit_amount_rejects_unrepresentable_numeric_values(
    field: str, value: str
) -> None:
    payload = _permit_payload({"agent_wallet_id": "schema-wallet", "key_id": None})
    payload[field] = value
    with pytest.raises(ValidationError) as error:
        PermitCreateRequest.model_validate(payload)
    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("field", ["max_credits", "aggregate_value_cap"])
@pytest.mark.parametrize(
    "value", ["0.00000001", "999999999999.99999999", "1.0000000100"]
)
def test_permit_amount_accepts_exact_storage_boundaries(field: str, value: str) -> None:
    payload = _permit_payload({"agent_wallet_id": "schema-wallet", "key_id": None})
    payload[field] = value
    permit = PermitCreateRequest.model_validate(payload)
    assert getattr(permit, field) == Decimal(value)


@pytest.mark.parametrize(
    "value", ["1.000000001", "1000000000000", "NaN", "Infinity", "-Infinity"]
)
def test_approval_request_rejects_amount_that_cannot_be_minted_exactly(
    value: str,
) -> None:
    payload = _permit_payload({"agent_wallet_id": "schema-wallet", "key_id": None})
    payload["max_credits"] = value
    payload["justification"] = "Request an exactly representable credit allowance."
    with pytest.raises(ValidationError) as error:
        PermitRequestCreate.model_validate(payload)
    assert error.value.errors()[0]["loc"] == ("max_credits",)


@pytest.mark.parametrize("value", ["0.00000001", "999999999999.99999999"])
def test_approval_request_accepts_exact_storage_boundaries(value: str) -> None:
    payload = _permit_payload({"agent_wallet_id": "schema-wallet", "key_id": None})
    payload["max_credits"] = value
    payload["justification"] = "Request an exactly representable credit allowance."
    request = PermitRequestCreate.model_validate(payload)
    assert request.max_credits == Decimal(value)


@pytest.mark.anyio
@pytest.mark.parametrize("explicit_null", [False, True])
async def test_absent_aggregate_value_cap_keeps_a_valid_permit(
    client: AsyncClient, clean_database, explicit_null: bool
) -> None:
    provisioned = await provision_agent_wallet(client)
    payload = _permit_payload(provisioned)
    if explicit_null:
        payload["aggregate_value_cap"] = None
    else:
        del payload["aggregate_value_cap"]
    response = await client.post(
        "/v1/permits",
        json=payload,
        headers={
            **provisioned["agent_headers"],
            "Idempotency-Key": "omitted-aggregate-value-cap",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["aggregate_value_cap"] is None
    factory = get_session_factory()
    async with factory() as session:
        permit = await session.get(PermitModel, body["permit_id"])
        assert permit is not None
        assert permit.aggregate_value_cap is None
        assert await get_permit_service().verify_signature(permit) is True
