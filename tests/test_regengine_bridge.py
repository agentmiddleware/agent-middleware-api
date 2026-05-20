from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import regengine_bridge
from app.services.regengine_bridge import REGENGINE_AGENT_REVIEWS_TOOL
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _mcp_call(
    *,
    wallet_id: str,
    tool: str = REGENGINE_AGENT_REVIEWS_TOOL,
    permit_id: str | None,
    idempotency_key: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = {
        "wallet_id": wallet_id,
        "idempotency_key": idempotency_key,
    }
    if permit_id:
        context["permit_id"] = permit_id
    return {
        "jsonrpc": "2.0",
        "id": idempotency_key,
        "method": "tools/call",
        "params": {
            "name": tool,
            "arguments": arguments or {"limit": 2},
            "mcpContext": context,
        },
    }


def _tool_result_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    text = payload["result"]["content"][0]["text"]
    return json.loads(text)["items"]


@pytest.mark.anyio
async def test_regengine_fetch_uses_operator_configured_url_and_api_key(monkeypatch):
    captured: dict[str, Any] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"items": [{"artifact_id": "artifact-remote"}], "total": 1}

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(
            self,
            url: str,
            *,
            params: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeResponse:
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setenv("REGENGINE_API_URL", "https://regengine.example/api")
    monkeypatch.setenv("REGENGINE_API_KEY", "regengine-secret")
    monkeypatch.setattr(regengine_bridge.httpx, "AsyncClient", FakeAsyncClient)

    payload = await regengine_bridge._fetch_regengine_agent_reviews(
        regengine_bridge.RegEngineAgentReviewsListRequest(
            limit=5,
            min_risk_score=90,
        )
    )

    assert payload["items"][0]["artifact_id"] == "artifact-remote"
    assert captured == {
        "timeout": 15.0,
        "url": "https://regengine.example/api/v1/agent-reviews/items",
        "params": {"limit": 5, "offset": 0, "min_risk_score": 90},
        "headers": {
            "Accept": "application/json",
            "X-API-Key": "regengine-secret",
        },
    }


def test_regengine_api_url_rejects_non_http_targets(monkeypatch):
    monkeypatch.setenv("REGENGINE_API_URL", "file:///etc/passwd")

    with pytest.raises(RuntimeError, match="regengine_api_url_must_be_http"):
        regengine_bridge._regengine_api_url()


@pytest.mark.anyio
async def test_regengine_tool_is_discoverable_as_permit_required(client):
    response = await client.get("/mcp/tools.json")

    assert response.status_code == 200
    tools = {tool["name"]: tool for tool in response.json()["tools"]}
    tool = tools[REGENGINE_AGENT_REVIEWS_TOOL]
    assert tool["annotations"]["requiresPermit"] is True
    assert tool["annotations"]["integrationStatus"] == "platform"
    assert tool["annotations"]["creditsPerCall"] == 1.0


@pytest.mark.anyio
async def test_regengine_agent_reviews_success_replays_without_double_charge(
    client,
    clean_database,
    monkeypatch,
):
    regengine_bridge.ensure_regengine_bridge_registered()
    provisioned = await provision_agent_wallet(client)
    calls: list[regengine_bridge.RegEngineAgentReviewsListRequest] = []

    async def fake_fetch(
        request: regengine_bridge.RegEngineAgentReviewsListRequest,
    ) -> dict[str, Any]:
        calls.append(request)
        return {
            "items": [
                {
                    "artifact_id": "artifact-1",
                    "suggestion": "Review supplier lot mapping",
                    "risk_score": 91,
                }
            ],
            "total": 1,
        }

    monkeypatch.setattr(
        regengine_bridge,
        "_fetch_regengine_agent_reviews",
        fake_fetch,
    )
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=REGENGINE_AGENT_REVIEWS_TOOL,
        idem_key="regengine-permit-success",
    )
    body = _mcp_call(
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        idempotency_key="regengine-list-once",
        arguments={"limit": 1, "min_risk_score": 80},
    )

    first = await client.post(
        "/mcp/messages",
        json=body,
        headers=provisioned["agent_headers"],
    )
    replay = await client.post(
        "/mcp/messages",
        json=body,
        headers=provisioned["agent_headers"],
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    first_payload = first.json()
    replay_payload = replay.json()
    assert _tool_result_items(first_payload)[0]["artifact_id"] == "artifact-1"
    assert (
        replay_payload["result"]["receipt"]["receipt_id"]
        == first_payload["result"]["receipt"]["receipt_id"]
    )
    assert calls == [
        regengine_bridge.RegEngineAgentReviewsListRequest(
            limit=1,
            min_risk_score=80,
        )
    ]

    ledger_resp = await client.get(
        f"/v1/billing/ledger/{provisioned['agent_wallet_id']}",
        headers=provisioned["agent_headers"],
    )
    matching_debits = [
        entry
        for entry in ledger_resp.json()["entries"]
        if entry["service_category"] == "platform_fee"
        and REGENGINE_AGENT_REVIEWS_TOOL in entry["description"]
    ]
    assert len(matching_debits) == 1


@pytest.mark.anyio
async def test_regengine_agent_reviews_denies_without_permit_before_remote_call(
    client,
    clean_database,
    monkeypatch,
):
    regengine_bridge.ensure_regengine_bridge_registered()
    provisioned = await provision_agent_wallet(client)
    calls = {"count": 0}

    async def fake_fetch(
        request: regengine_bridge.RegEngineAgentReviewsListRequest,
    ) -> dict[str, Any]:
        calls["count"] += 1
        return {"items": [], "total": 0}

    monkeypatch.setattr(
        regengine_bridge,
        "_fetch_regengine_agent_reviews",
        fake_fetch,
    )
    response = await client.post(
        "/mcp/messages",
        json=_mcp_call(
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=None,
            idempotency_key="regengine-list-no-permit",
        ),
        headers=provisioned["agent_headers"],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["message"] == "permit_required"
    assert calls["count"] == 0


@pytest.mark.anyio
async def test_regengine_agent_reviews_wrong_scope_gets_denial_receipt(
    client,
    clean_database,
    monkeypatch,
):
    regengine_bridge.ensure_regengine_bridge_registered()
    provisioned = await provision_agent_wallet(client)
    calls = {"count": 0}

    async def fake_fetch(
        request: regengine_bridge.RegEngineAgentReviewsListRequest,
    ) -> dict[str, Any]:
        calls["count"] += 1
        return {"items": [], "total": 0}

    monkeypatch.setattr(
        regengine_bridge,
        "_fetch_regengine_agent_reviews",
        fake_fetch,
    )
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="regengine.agent_reviews.timeline",
        idem_key="regengine-permit-wrong-tool",
    )
    body = _mcp_call(
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        idempotency_key="regengine-list-wrong-scope",
    )

    response = await client.post(
        "/mcp/messages",
        json=body,
        headers=provisioned["agent_headers"],
    )
    replay = await client.post(
        "/mcp/messages",
        json=body,
        headers=provisioned["agent_headers"],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["message"] == "permit_tool_not_allowed"
    receipt = payload["error"]["data"]["receipt"]
    assert receipt["outcome"] == "denied"
    assert receipt["credits_charged"] == "0"
    assert receipt["ledger_entry_id"] is None
    assert replay.json()["error"]["data"]["receipt"]["receipt_id"] == receipt[
        "receipt_id"
    ]
    assert calls["count"] == 0
