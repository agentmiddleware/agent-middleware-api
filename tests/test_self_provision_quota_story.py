"""Quota story for self-serve dev key provisioning.

The audit found self-provisioning had no documented quota story: each call
mints a fresh sponsor plus agent wallet, bounded per call but with no
cross-call cap. That shape is deliberate (local-only, single operator), and
it is now written down in docs/static-dev-api-keys.md with cleanup through
`make quickstart QUICKSTART_ARGS="--reset"` and revocation through
/v1/api-keys. These tests pin the behavior the docs promise: the per-call
bound holds exactly at its edge, repeated calls accumulate distinct funded
wallets, and the documented wording exists.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def self_provision_settings():
    """Enable the endpoint locally; restore every mutated field afterwards."""
    settings = get_settings()
    saved = {
        name: getattr(settings, name)
        for name in ("ENVIRONMENT", "ENABLE_DEV_KEY_SELF_PROVISION")
    }
    settings.ENVIRONMENT = "local"
    settings.ENABLE_DEV_KEY_SELF_PROVISION = True
    try:
        yield settings
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)


@pytest.fixture()
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "test-key"},
    ) as c:
        yield c


async def test_budget_max_boundary_accepted(
    client, self_provision_settings, clean_database
):
    resp = await client.post(
        "/v1/dev-keys/self-provision",
        json={"agent_id": "max-boundary", "budget_credits": 100000},
    )
    assert resp.status_code == 201, resp.text


async def test_budget_just_over_max_rejected(client, self_provision_settings):
    resp = await client.post(
        "/v1/dev-keys/self-provision",
        json={"agent_id": "over-max", "budget_credits": 100001},
    )
    assert resp.status_code == 422


async def test_repeated_calls_mint_distinct_funded_wallets(
    client, self_provision_settings, clean_database
):
    # No cross-call cap and no dedup: every call mints a fresh sponsor plus
    # agent wallet, so repeated provisioning accumulates wallets until the
    # operator resets. The docs promise exactly this shape.
    from app.services.agent_money import get_agent_money

    first = await client.post(
        "/v1/dev-keys/self-provision",
        json={"agent_id": "quota-first", "budget_credits": 400},
    )
    second = await client.post(
        "/v1/dev-keys/self-provision",
        json={"agent_id": "quota-second", "budget_credits": 600},
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    first_body, second_body = first.json(), second.json()
    assert first_body["wallet_id"] != second_body["wallet_id"]
    assert first_body["sponsor_wallet_id"] != second_body["sponsor_wallet_id"]

    money = get_agent_money()
    first_wallet = await money.get_wallet(first_body["wallet_id"])
    second_wallet = await money.get_wallet(second_body["wallet_id"])
    assert Decimal(str(first_wallet.balance)) == Decimal("400")
    assert Decimal(str(second_wallet.balance)) == Decimal("600")


def test_quota_story_is_documented():
    """The documented quota contract must exist where the audit looked."""
    dev_keys_doc = (ROOT / "docs" / "static-dev-api-keys.md").read_text(
        encoding="utf-8"
    )
    assert "Quota story" in dev_keys_doc
    assert "--reset" in dev_keys_doc
    assert "emergency-revoke" in dev_keys_doc

    demo_doc = (ROOT / "docs" / "demo-instance.md").read_text(encoding="utf-8")
    assert "Reset and key hygiene" in demo_doc
    assert "trial workspace" in demo_doc
