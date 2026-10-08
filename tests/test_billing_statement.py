"""Per-wallet statement export: CSV a pilot finance contact can reconcile."""

import csv
import io
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.routers.billing import _statement_cell, build_statement_csv
from app.schemas.billing import LedgerAction, LedgerEntry


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


def _entry(**overrides):
    base = {
        "entry_id": "e1",
        "wallet_id": "spn-test",
        "action": LedgerAction.CREDIT,
        "amount": 100.0,
        "amount_exact": "100",
        "balance_after": 100.0,
        "balance_after_exact": "100",
        "service_category": None,
        "description": "Fiat top-up via Stripe (pi_123)",
        "timestamp": datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        "metadata": {},
    }
    base.update(overrides)
    return LedgerEntry(**base)


def test_statement_cell_neutralizes_formulas():
    assert _statement_cell("=cmd|'/c calc'!A0") == "'=cmd|'/c calc'!A0"
    assert _statement_cell("+123") == "'+123"
    assert _statement_cell("-5") == "'-5"
    assert _statement_cell("@user") == "'@user"
    assert _statement_cell("Fiat top-up") == "Fiat top-up"
    assert _statement_cell(None) == ""
    assert _statement_cell(12.5) == "12.5"


def test_build_statement_csv_renders_header_and_rows():
    parsed = list(csv.reader(io.StringIO(build_statement_csv([_entry()]))))
    assert parsed[0] == [
        "entry_id",
        "timestamp",
        "action",
        "amount_exact",
        "balance_after_exact",
        "service_category",
        "description",
    ]
    assert parsed[1][0] == "e1"
    assert parsed[1][2] == "credit"
    assert parsed[1][3] == "100"


def test_build_statement_csv_empty_ledger_is_header_only():
    assert build_statement_csv([]).strip().splitlines() == [
        "entry_id,timestamp,action,amount_exact,"
        "balance_after_exact,service_category,description"
    ]


@pytest.mark.anyio
async def test_statement_endpoint_exports_funded_wallet(
    client, api_headers, clean_database
):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Statement Corp",
            "email": "billing@statement.example",
            "initial_credits": 50000.0,
        },
        headers=api_headers,
    )
    assert sponsor.status_code == 201
    wallet_id = sponsor.json()["wallet_id"]

    resp = await client.get(f"/v1/billing/statement/{wallet_id}", headers=api_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert wallet_id in resp.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0][0] == "entry_id"
    assert len(rows) >= 2
    assert any(row[2] == "credit" for row in rows[1:])


@pytest.mark.anyio
async def test_statement_endpoint_denies_other_tenant(
    client, api_headers, clean_database
):
    first = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Tenant One",
            "email": "one@example.com",
            "initial_credits": 10,
        },
        headers=api_headers,
    )
    second = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Tenant Two",
            "email": "two@example.com",
            "initial_credits": 10,
        },
        headers=api_headers,
    )
    key = await client.post(
        "/v1/api-keys",
        json={
            "wallet_id": first.json()["wallet_id"],
            "key_name": "tenant-key",
        },
        headers=api_headers,
    )
    resp = await client.get(
        f"/v1/billing/statement/{second.json()['wallet_id']}",
        headers={"X-API-Key": key.json()["api_key"]},
    )
    assert resp.status_code == 403
