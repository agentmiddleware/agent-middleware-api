"""REQUIRE_IDEMPOTENCY_KEY gate on money-moving billing routes.

When the flag is off (the default), keyless money calls keep today's
behavior. When it is on, every money-moving billing route refuses a keyless
request with 400 idempotency_key_required before anything is minted,
charged, or moved, and a present-but-unusable key is refused with 400
invalid_idempotency_key instead of running unprotected.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.core.config import Settings, get_settings
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


@pytest.fixture
def require_idempotency(monkeypatch):
    """Opt into the strict gate for one test, then restore the default."""
    monkeypatch.setenv("REQUIRE_IDEMPOTENCY_KEY", "true")
    get_settings.cache_clear()
    try:
        yield
    finally:
        monkeypatch.delenv("REQUIRE_IDEMPOTENCY_KEY", raising=False)
        get_settings.cache_clear()


def test_require_flag_defaults_to_false():
    assert Settings().REQUIRE_IDEMPOTENCY_KEY is False


@pytest.mark.anyio
async def test_money_routes_work_without_key_by_default(
    client, api_headers, clean_database
):
    """The default is unchanged: keyless callers keep today's behavior."""
    assert get_settings().REQUIRE_IDEMPOTENCY_KEY is False
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "Default", "email": "d@t.com", "initial_credits": 5000},
        headers=api_headers,
    )
    agent = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor.json()["wallet_id"],
            "agent_id": "default-bot",
            "budget_credits": 1000,
        },
        headers=api_headers,
    )
    assert agent.status_code == 201
    charge = await client.post(
        f"/v1/billing/charge?wallet_id={agent.json()['wallet_id']}"
        "&service=iot_bridge&units=1",
        headers=api_headers,
    )
    assert charge.status_code == 200


async def _provision_agent(
    client, api_headers, tag, sponsor_credits=10000, budget=5000, key=None
):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": f"Sponsor {tag}",
            "email": f"{tag}@t.com",
            "initial_credits": sponsor_credits,
        },
        headers=api_headers,
    )
    assert sponsor.status_code == 201
    headers = dict(api_headers)
    if key is not None:
        headers["Idempotency-Key"] = key
    agent = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor.json()["wallet_id"],
            "agent_id": f"bot-{tag}",
            "budget_credits": budget,
        },
        headers=headers,
    )
    assert agent.status_code == 201
    return sponsor.json()["wallet_id"], agent.json()["wallet_id"]


def _required_body(resp):
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "idempotency_key_required"
    return detail


@pytest.mark.anyio
async def test_charge_requires_key_when_flag_on(
    client, api_headers, clean_database, require_idempotency
):
    _, agent_id = await _provision_agent(
        client, api_headers, "charge-req", key="setup-charge-req"
    )
    resp = await client.post(
        f"/v1/billing/charge?wallet_id={agent_id}&service=iot_bridge&units=10",
        headers=api_headers,
    )
    _required_body(resp)
    ledger = await client.get(f"/v1/billing/ledger/{agent_id}", headers=api_headers)
    debits = [e for e in ledger.json()["entries"] if e["action"] == "debit"]
    assert debits == []


@pytest.mark.anyio
async def test_transfer_requires_key_when_flag_on(
    client, api_headers, clean_database, require_idempotency
):
    sponsor_id, agent_id = await _provision_agent(
        client, api_headers, "xfer-req", key="setup-xfer-req"
    )
    resp = await client.post(
        f"/v1/billing/transfer?from_wallet_id={agent_id}"
        f"&to_wallet_id={sponsor_id}&amount=10",
        headers=api_headers,
    )
    _required_body(resp)


@pytest.mark.anyio
async def test_agent_wallet_creation_requires_key_when_flag_on(
    client, api_headers, clean_database, require_idempotency
):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Sponsor agent-req",
            "email": "agent-req@t.com",
            "initial_credits": 10000,
        },
        headers=api_headers,
    )
    sponsor_id = sponsor.json()["wallet_id"]
    before = (
        await client.get(f"/v1/billing/wallets/{sponsor_id}", headers=api_headers)
    ).json()
    resp = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor_id,
            "agent_id": "bot-agent-req",
            "budget_credits": 1000,
        },
        headers=api_headers,
    )
    _required_body(resp)
    after = (
        await client.get(f"/v1/billing/wallets/{sponsor_id}", headers=api_headers)
    ).json()
    assert after["balance"] == before["balance"]


@pytest.mark.anyio
async def test_child_wallet_creation_requires_key_when_flag_on(
    client, api_headers, clean_database, require_idempotency
):
    _, agent_id = await _provision_agent(
        client, api_headers, "child-req", key="setup-child-req"
    )
    resp = await client.post(
        "/v1/billing/wallets/child",
        json={
            "parent_wallet_id": agent_id,
            "child_agent_id": "child-req",
            "budget_credits": 100,
            "max_spend": 100,
        },
        headers=api_headers,
    )
    _required_body(resp)


@pytest.mark.anyio
async def test_reclaim_requires_key_when_flag_on(
    client, api_headers, clean_database, require_idempotency
):
    _, agent_id = await _provision_agent(
        client, api_headers, "reclaim-req", key="setup-reclaim-req"
    )
    child = await client.post(
        "/v1/billing/wallets/child",
        json={
            "parent_wallet_id": agent_id,
            "child_agent_id": "child-reclaim-req",
            "budget_credits": 100,
            "max_spend": 100,
        },
        headers={**api_headers, "Idempotency-Key": "setup-child-reclaim-req"},
    )
    assert child.status_code == 201
    child_id = child.json()["wallet_id"]
    resp = await client.post(
        f"/v1/billing/wallets/{child_id}/reclaim", headers=api_headers
    )
    _required_body(resp)
    wallet = await client.get(f"/v1/billing/wallets/{child_id}", headers=api_headers)
    assert wallet.json()["status"] == "active"


@pytest.mark.anyio
async def test_top_up_prepare_requires_key_when_flag_on(
    client, api_headers, clean_database, require_idempotency
):
    sponsor_id, _ = await _provision_agent(
        client, api_headers, "prepare-req", key="setup-prepare-req"
    )
    resp = await client.post(
        f"/v1/billing/top-up/prepare?wallet_id={sponsor_id}&amount_fiat=10",
        headers=api_headers,
    )
    # Refused for the missing key before Stripe is ever touched: without the
    # gate this answers 400 topup_prepare_error (no Stripe keys in tests).
    _required_body(resp)


@pytest.mark.anyio
async def test_dry_run_commit_requires_key_when_flag_on(
    client, api_headers, clean_database, require_idempotency
):
    _, agent_id = await _provision_agent(
        client, api_headers, "commit-req", key="setup-commit-req"
    )
    session = await client.post(
        "/v1/billing/dry-run/session",
        json={"wallet_id": agent_id},
        headers=api_headers,
    )
    assert session.status_code == 201
    resp = await client.post(
        f"/v1/billing/dry-run/session/{session.json()['session_id']}/commit",
        headers=api_headers,
    )
    _required_body(resp)


@pytest.mark.anyio
async def test_blank_and_oversize_keys_rejected_on_money_routes(
    client, api_headers, clean_database
):
    """A present-but-unusable key must not run unprotected, in either mode."""
    _, agent_id = await _provision_agent(client, api_headers, "badkey")
    for bad_key in ["   ", "x" * 129]:
        resp = await client.post(
            f"/v1/billing/transfer?from_wallet_id={agent_id}"
            f"&to_wallet_id={agent_id}&amount=1",
            headers={**api_headers, "Idempotency-Key": bad_key},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "invalid_idempotency_key"
    resp = await client.post(
        f"/v1/billing/charge?wallet_id={agent_id}&service=iot_bridge&units=1",
        headers={**api_headers, "Idempotency-Key": "   "},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "invalid_idempotency_key"


@pytest.mark.anyio
async def test_keyed_charge_still_replays_when_flag_on(
    client, api_headers, clean_database, require_idempotency
):
    """The gate refuses keyless calls but leaves the keyed replay path intact."""
    _, agent_id = await _provision_agent(
        client, api_headers, "replay-req", key="setup-replay-req"
    )
    headers = {**api_headers, "Idempotency-Key": "replay-req-1"}
    url = f"/v1/billing/charge?wallet_id={agent_id}&service=iot_bridge&units=10"
    first = await client.post(url, headers=headers)
    assert first.status_code == 200
    second = await client.post(url, headers=headers)
    assert second.status_code == 200
    assert second.json()["entry_id"] == first.json()["entry_id"]
    ledger = await client.get(f"/v1/billing/ledger/{agent_id}", headers=api_headers)
    debits = [e for e in ledger.json()["entries"] if e["action"] == "debit"]
    assert len(debits) == 1


@pytest.mark.anyio
async def test_keyed_agent_wallet_provisioning_replays_when_flag_on(
    client, api_headers, clean_database, require_idempotency
):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Sponsor replay-prov",
            "email": "replay-prov@t.com",
            "initial_credits": 10000,
        },
        headers=api_headers,
    )
    sponsor_id = sponsor.json()["wallet_id"]
    headers = {**api_headers, "Idempotency-Key": "replay-prov-1"}
    body = {
        "sponsor_wallet_id": sponsor_id,
        "agent_id": "bot-replay-prov",
        "budget_credits": 1000,
    }
    first = await client.post("/v1/billing/wallets/agent", json=body, headers=headers)
    assert first.status_code == 201
    second = await client.post("/v1/billing/wallets/agent", json=body, headers=headers)
    assert second.status_code == 201
    assert second.json()["wallet_id"] == first.json()["wallet_id"]
