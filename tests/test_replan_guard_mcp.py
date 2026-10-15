"""The re-plan bypass on the real governed path.

``POST /mcp`` auto-mints a fresh permit whenever no ``permit_id`` is given,
so an agent that restarts or re-plans with a new idempotency key used to get
a new permit, a new budget, and a second dispatch and debit for the same
action. These tests drive that path end to end and pin what the wallet
re-plan guard changes (``enforce``) and what it must not change
(``log_only``, same-key replay, deterministic failures).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services import replan_guard as replan_guard_module
from app.services.replan_guard import (
    ReplanGuardUnavailable,
    get_replan_guard,
    reset_replan_guard_for_tests,
)
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import provision_agent_wallet
from tests.test_upstream_retry_cap_enforcement import (
    FakeUpstreamExecutor,
    _register_upstream,
)

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
LOCAL_TOOL = "replan-guard-local"


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
def guard_env(monkeypatch):
    """Standard MCP on, guard in enforce, per-process store, no velocity cap."""

    def configure(**env):
        base = {
            "ENABLE_STANDARD_MCP_ENDPOINT": "true",
            "WALLET_REPLAN_GUARD": "enforce",
            "WALLET_VELOCITY_MAX_CREDITS": "0",
            "WALLET_VELOCITY_MAX_CALLS": "0",
            "REDIS_URL": "",
        }
        base.update({k: str(v) for k, v in env.items()})
        for key, value in base.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()

    reset_replan_guard_for_tests()
    configure()
    yield configure
    reset_replan_guard_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def local_tool():
    calls: list[dict] = []

    def tool(note: str = "") -> dict:
        calls.append({"note": note})
        return {"ok": True, "note": note}

    registry = get_service_registry()
    registry.register_local(
        service_id=LOCAL_TOOL,
        name="Replan Guard Local",
        description="Local tool for the wallet re-plan guard",
        category=ServiceCategory.AGENT_COMMS,
        func=tool,
        credits_per_unit=2.0,
        unit_name="call",
    )
    yield calls
    registry.unregister_local(LOCAL_TOOL)


def _call(tool: str, arguments: dict, request_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }


async def _post(client, provisioned, tool, arguments, key: str | None = None):
    headers = {**provisioned["agent_headers"], **MCP_HEADERS}
    if key is not None:
        headers["Idempotency-Key"] = key
    resp = await client.post("/mcp", json=_call(tool, arguments), headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _debits(client, provisioned, tool) -> int:
    ledger = await client.get(
        f"/v1/billing/ledger/{provisioned['agent_wallet_id']}",
        headers=provisioned["agent_headers"],
    )
    return sum(
        1
        for e in ledger.json()["entries"]
        if e["action"] == "debit" and tool in e["description"]
    )


# ── the bypass itself ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_keyless_replan_on_auto_minted_permits_is_refused(
    client, guard_env, local_tool, clean_database
):
    provisioned = await provision_agent_wallet(client)
    first = await _post(client, provisioned, LOCAL_TOOL, {"note": "pay invoice 7"})
    assert first["result"]["isError"] is False
    first_permit = first["result"]["receipt"]["permit_id"]

    # Re-planned: keys reordered-equivalent, no idempotency key, so /mcp mints
    # a brand-new permit for it.
    second = await _post(client, provisioned, LOCAL_TOOL, {"note": "pay invoice 7"})
    error = second["error"]
    assert error["code"] == -32003
    assert error["message"] == "wallet_duplicate_request"
    receipt = error["data"]["receipt"]
    assert receipt["outcome"] == "denied"
    assert receipt["reason_code"] == "wallet_duplicate_request"
    assert receipt["credits_charged"] == "0"
    # A different permit: the per-permit duplicate guard could not see this.
    assert receipt["permit_id"] != first_permit
    assert error["data"]["details"]["scope"] == "wallet"

    assert len(local_tool) == 1
    assert await _debits(client, provisioned, LOCAL_TOOL) == 1


@pytest.mark.anyio
async def test_new_client_key_replan_is_refused_and_denial_replays(
    client, guard_env, local_tool, clean_database
):
    provisioned = await provision_agent_wallet(client)
    ok = await _post(client, provisioned, LOCAL_TOOL, {"note": "x"}, key="plan-1")
    assert ok["result"]["isError"] is False

    denied = await _post(client, provisioned, LOCAL_TOOL, {"note": "x"}, key="plan-2")
    assert denied["error"]["message"] == "wallet_duplicate_request"
    # The denied key is bound to its denial, like every governed denial.
    again = await _post(client, provisioned, LOCAL_TOOL, {"note": "x"}, key="plan-2")
    assert again["error"]["message"] == "wallet_duplicate_request"
    assert (
        again["error"]["data"]["receipt"]["receipt_id"]
        == denied["error"]["data"]["receipt"]["receipt_id"]
    )
    assert len(local_tool) == 1


@pytest.mark.anyio
async def test_same_key_retry_still_replays_the_original_receipt(
    client, guard_env, local_tool, clean_database
):
    provisioned = await provision_agent_wallet(client)
    first = await _post(client, provisioned, LOCAL_TOOL, {"note": "x"}, key="same")
    replay = await _post(client, provisioned, LOCAL_TOOL, {"note": "x"}, key="same")
    assert (
        replay["result"]["receipt"]["receipt_id"]
        == first["result"]["receipt"]["receipt_id"]
    )
    assert len(local_tool) == 1
    assert await _debits(client, provisioned, LOCAL_TOOL) == 1


@pytest.mark.anyio
async def test_different_arguments_and_case_are_not_duplicates(
    client, guard_env, local_tool, clean_database
):
    provisioned = await provision_agent_wallet(client)
    for note in ("a", "b", "A"):
        body = await _post(client, provisioned, LOCAL_TOOL, {"note": note})
        assert body["result"]["isError"] is False, body
    assert len(local_tool) == 3


@pytest.mark.anyio
async def test_cross_permit_replan_on_the_legacy_transport_is_refused(
    client, guard_env, local_tool, clean_database
):
    """Two explicitly issued permits, same wallet, same arguments, new key."""
    from datetime import timedelta

    from app.core.time import utc_now

    provisioned = await provision_agent_wallet(client)
    permit_ids = []
    for i in range(2):
        resp = await client.post(
            "/v1/permits",
            json={
                "issuer_wallet_id": provisioned["agent_wallet_id"],
                "subject_wallet_id": provisioned["agent_wallet_id"],
                "allowed_tools": [LOCAL_TOOL],
                "max_credits": "10",
                "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
            },
            headers={**provisioned["agent_headers"], "Idempotency-Key": f"pm-{i}"},
        )
        assert resp.status_code in (200, 201), resp.text
        permit_ids.append(resp.json()["permit_id"])

    async def legacy(permit_id: str, key: str) -> dict:
        resp = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": LOCAL_TOOL,
                    "arguments": {"note": "same"},
                    "mcpContext": {
                        "wallet_id": provisioned["agent_wallet_id"],
                        "permit_id": permit_id,
                        "idempotency_key": key,
                    },
                },
            },
            headers=provisioned["agent_headers"],
        )
        return resp.json()

    first = await legacy(permit_ids[0], "legacy-1")
    assert "result" in first, first
    second = await legacy(permit_ids[1], "legacy-2")
    assert second["error"]["message"] == "wallet_duplicate_request", second
    assert len(local_tool) == 1


# ── log_only must never block ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_log_only_default_logs_but_dispatches(
    client, guard_env, local_tool, clean_database, monkeypatch, caplog
):
    monkeypatch.delenv("WALLET_REPLAN_GUARD")
    get_settings.cache_clear()
    assert get_settings().WALLET_REPLAN_GUARD.value == "log_only"
    provisioned = await provision_agent_wallet(client)
    with caplog.at_level("WARNING", logger="app.services.replan_guard"):
        for _ in range(2):
            body = await _post(client, provisioned, LOCAL_TOOL, {"note": "dup"})
            assert body["result"]["isError"] is False
    assert len(local_tool) == 2
    assert await _debits(client, provisioned, LOCAL_TOOL) == 2
    assert any("replan_guard_would_deny" in r.getMessage() for r in caplog.records)


@pytest.mark.anyio
async def test_log_only_store_outage_never_blocks(
    client, guard_env, local_tool, clean_database, monkeypatch
):
    guard_env(WALLET_REPLAN_GUARD="log_only")

    async def down():
        raise ReplanGuardUnavailable("redis_unreachable")

    monkeypatch.setattr(get_replan_guard(), "_client", down)
    provisioned = await provision_agent_wallet(client)
    body = await _post(client, provisioned, LOCAL_TOOL, {"note": "x"})
    assert body["result"]["isError"] is False


# ── release on deterministic failure, keep on ambiguity ──────────────────────


@pytest.mark.anyio
async def test_upstream_returned_error_releases_lock_and_refunds_velocity(
    client, guard_env, clean_database
):
    guard_env(WALLET_VELOCITY_MAX_CALLS=1)
    provisioned = await provision_agent_wallet(client)
    tool = "replan-guard-upstream-error"
    executor = FakeUpstreamExecutor(mode="returned_error")
    _register_upstream(tool, executor)
    try:
        failed = await _post(client, provisioned, tool, {"message": "m"})
        assert failed["error"]["data"]["receipt"]["outcome"] == "failed_refunded"
        executor.mode = "success"
        # A fresh key retrying the identical call is legitimate after a
        # deterministic, refunded failure: the lock and the single velocity
        # slot both came back.
        retried = await _post(client, provisioned, tool, {"message": "m"})
        assert retried["result"]["isError"] is False, retried
        assert executor.dispatch_count == 2
    finally:
        get_service_registry().unregister_local(tool)


@pytest.mark.anyio
async def test_delivery_uncertain_keeps_the_lock(client, guard_env, clean_database):
    provisioned = await provision_agent_wallet(client)
    tool = "replan-guard-upstream-uncertain"
    executor = FakeUpstreamExecutor(mode="delivery_uncertain")
    _register_upstream(tool, executor)
    try:
        first = await _post(client, provisioned, tool, {"message": "m"})
        assert first["result"]["receipt"]["outcome"] == "delivery_uncertain"
        executor.mode = "success"
        # The charge stands and the call may have landed: a re-plan under a
        # new key must not dispatch it again.
        second = await _post(client, provisioned, tool, {"message": "m"})
        assert second["error"]["message"] == "wallet_duplicate_request"
        assert executor.dispatch_count == 1
        assert await _debits(client, provisioned, tool) == 1
    finally:
        get_service_registry().unregister_local(tool)


@pytest.mark.anyio
async def test_pre_effect_denial_releases_the_reservation(
    client, guard_env, local_tool, clean_database, monkeypatch
):
    """A denial after the guard reserved (here: insufficient funds) gives it back."""
    from app.services import agent_money

    provisioned = await provision_agent_wallet(client)
    money = agent_money.get_agent_money()
    original = money.charge
    attempts = {"n": 0}

    async def broke_once(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("simulated pre-debit failure")
        return await original(*args, **kwargs)

    monkeypatch.setattr(money, "charge", broke_once)
    failed = await _post(client, provisioned, LOCAL_TOOL, {"note": "retry-me"})
    assert "error" in failed
    assert local_tool == []
    ok = await _post(client, provisioned, LOCAL_TOOL, {"note": "retry-me"})
    assert ok["result"]["isError"] is False, ok
    assert len(local_tool) == 1


# ── velocity across all permits ──────────────────────────────────────────────


@pytest.mark.anyio
async def test_wallet_velocity_spans_auto_minted_permits(
    client, guard_env, local_tool, clean_database
):
    guard_env(WALLET_VELOCITY_MAX_CREDITS="4")
    provisioned = await provision_agent_wallet(client)
    for note in ("one", "two"):
        body = await _post(client, provisioned, LOCAL_TOOL, {"note": note})
        assert body["result"]["isError"] is False
    over = await _post(client, provisioned, LOCAL_TOOL, {"note": "three"})
    assert over["error"]["message"] == "wallet_velocity_exceeded"
    details = over["error"]["data"]["details"]
    assert details["limit"] == "credits"
    assert details["limit_credits"] == "4"
    assert details["window_credits"] == "4"
    assert len(local_tool) == 2


# ── enforce fails closed, retryably, when the store cannot answer ────────────


@pytest.mark.anyio
async def test_enforce_store_outage_is_retryable_and_charges_nothing(
    client, guard_env, local_tool, clean_database, monkeypatch
):
    guard = get_replan_guard()
    real_client = guard._client

    async def down():
        raise ReplanGuardUnavailable("redis_unreachable")

    monkeypatch.setattr(guard, "_client", down)
    provisioned = await provision_agent_wallet(client)
    body = await _post(client, provisioned, LOCAL_TOOL, {"note": "x"}, key="k-out")
    assert body["error"]["code"] == -32005
    assert body["error"]["message"] == "wallet_guard_unavailable"
    assert local_tool == []
    assert await _debits(client, provisioned, LOCAL_TOOL) == 0

    # Store back: the SAME key runs (it was released, not burned).
    monkeypatch.setattr(guard, "_client", real_client)
    ok = await _post(client, provisioned, LOCAL_TOOL, {"note": "x"}, key="k-out")
    assert ok["result"]["isError"] is False, ok
    assert len(local_tool) == 1


def test_guard_module_exposes_reason_codes():
    assert replan_guard_module.REASON_DUPLICATE == "wallet_duplicate_request"
    assert replan_guard_module.REASON_VELOCITY == "wallet_velocity_exceeded"
