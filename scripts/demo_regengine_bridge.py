#!/usr/bin/env python3
"""One-command proof for the governed RegEngine MCP bridge.

The demo runs the real FastAPI routers in-process against a throwaway local
SQLite database. RegEngine itself is stubbed in-process so this proof never
calls production; it verifies that the bridge is discoverable, permit-scoped,
metered, receipted, replay-safe, and denied before remote execution when the
permit scope is wrong.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BOOTSTRAP_API_KEY = "regengine-bridge-bootstrap-key"
SIGNING_PRIVATE_KEY_B64 = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _line(emit: bool, message: str) -> None:
    if emit:
        print(f"[regengine-bridge] {message}")


async def _get_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = await client.get(path, headers=headers)
    _require(
        response.status_code == 200,
        f"GET {path} returned {response.status_code}: {response.text}",
    )
    return response.json()


async def _post_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    json_body: dict[str, Any],
    headers: dict[str, str],
    expected_status: int = 200,
) -> dict[str, Any]:
    response = await client.post(path, json=json_body, headers=headers)
    _require(
        response.status_code == expected_status,
        f"POST {path} returned {response.status_code}: {response.text}",
    )
    return response.json()


def _jsonrpc_result(payload: dict[str, Any]) -> dict[str, Any]:
    _require("result" in payload, f"expected JSON-RPC result, got: {payload}")
    return payload["result"]


def _jsonrpc_error(payload: dict[str, Any]) -> dict[str, Any]:
    _require("error" in payload, f"expected JSON-RPC error, got: {payload}")
    return payload["error"]


def _mcp_call(
    *,
    request_id: str,
    wallet_id: str,
    permit_id: str | None,
    idempotency_key: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.services.regengine_bridge import REGENGINE_AGENT_REVIEWS_TOOL

    context = {
        "wallet_id": wallet_id,
        "idempotency_key": idempotency_key,
    }
    if permit_id:
        context["permit_id"] = permit_id
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": REGENGINE_AGENT_REVIEWS_TOOL,
            "arguments": arguments or {"limit": 2, "min_risk_score": 75},
            "mcpContext": context,
        },
    }


def _matching_regengine_debits(
    ledger: dict[str, Any],
    *,
    tool_name: str,
) -> list[dict[str, Any]]:
    return [
        entry
        for entry in ledger["entries"]
        if entry["service_category"] == "platform_fee"
        and tool_name in entry.get("description", "")
    ]


async def run_regengine_bridge_demo(
    *,
    client: httpx.AsyncClient,
    bootstrap_api_key: str,
    emit: bool = True,
) -> dict[str, Any]:
    from app.services import regengine_bridge
    from app.services.regengine_bridge import REGENGINE_AGENT_REVIEWS_TOOL

    bootstrap_headers = {"X-API-Key": bootstrap_api_key}
    fetch_calls: list[regengine_bridge.RegEngineAgentReviewsListRequest] = []
    original_fetch = regengine_bridge._fetch_regengine_agent_reviews

    async def fake_fetch(
        request: regengine_bridge.RegEngineAgentReviewsListRequest,
    ) -> dict[str, Any]:
        fetch_calls.append(request)
        return {
            "items": [
                {
                    "artifact_id": "artifact-demo-001",
                    "ingestion_run_id": "run-demo-001",
                    "suggestion": "Review supplier lot mapping before export.",
                    "risk_score": 88,
                    "compliance_gap_count": 2,
                    "review_status": "pending",
                    "advisory_receipt_state": "pending",
                    "chain_valid": True,
                    "evidence_ids": ["evidence-demo-001"],
                    "source_hashes": [
                        "5a9998521bde2c2baf315689ecb8d5da"
                        "135e77cf5929f26be5083b44f143b500"
                    ],
                }
            ],
            "total": 1,
        }

    regengine_bridge._fetch_regengine_agent_reviews = fake_fetch
    try:
        _line(emit, "discover RegEngine governed MCP tool")
        regengine_bridge.ensure_regengine_bridge_registered()
        tools_manifest = await _get_json(client, "/mcp/tools.json")
        tools = {tool["name"]: tool for tool in tools_manifest["tools"]}
        tool = tools.get(REGENGINE_AGENT_REVIEWS_TOOL)
        _require(tool is not None, "RegEngine MCP tool missing from discovery")
        annotations = tool.get("annotations", {})
        _require(
            annotations.get("requiresPermit") is True,
            f"RegEngine tool is not marked permit-required: {annotations}",
        )
        _require(
            annotations.get("integrationStatus") == "platform",
            f"RegEngine tool integration status drifted: {annotations}",
        )

        _line(emit, "create sponsor and agent wallets")
        sponsor = await _post_json(
            client,
            "/v1/billing/wallets/sponsor",
            headers=bootstrap_headers,
            expected_status=201,
            json_body={
                "sponsor_name": "RegEngine Bridge Sponsor",
                "email": "regengine-bridge@example.com",
                "initial_credits": 10000,
                "require_kyc": False,
            },
        )
        agent = await _post_json(
            client,
            "/v1/billing/wallets/agent",
            headers=bootstrap_headers,
            expected_status=201,
            json_body={
                "sponsor_wallet_id": sponsor["wallet_id"],
                "agent_id": "regengine-bridge-agent",
                "budget_credits": 1000,
                "daily_limit": 500,
            },
        )
        wallet_id = agent["wallet_id"]

        _line(emit, "mint wallet-scoped runtime key")
        key = await _post_json(
            client,
            "/v1/api-keys",
            headers=bootstrap_headers,
            expected_status=201,
            json_body={
                "wallet_id": wallet_id,
                "key_name": "regengine-bridge-runtime",
                "expires_in_days": 30,
            },
        )
        agent_headers = {"X-API-Key": key["api_key"]}

        _line(emit, "issue signed permit scoped to RegEngine review reads")
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        permit = await _post_json(
            client,
            "/v1/permits",
            headers={
                **bootstrap_headers,
                "Idempotency-Key": "regengine-bridge-permit-1",
            },
            expected_status=201,
            json_body={
                "issuer_wallet_id": wallet_id,
                "subject_wallet_id": wallet_id,
                "subject_key_id": key["key_id"],
                "allowed_tools": [REGENGINE_AGENT_REVIEWS_TOOL],
                "scopes": [
                    f"tool:{REGENGINE_AGENT_REVIEWS_TOOL}:invoke",
                    "billing:charge",
                ],
                "max_credits": 25,
                "expires_at": expires_at,
            },
        )

        _line(emit, "invoke RegEngine bridge through MCP trust plane")
        invoke_body = _mcp_call(
            request_id="regengine-bridge-call-1",
            wallet_id=wallet_id,
            permit_id=permit["permit_id"],
            idempotency_key="regengine-bridge-invoke-1",
            arguments={"limit": 1, "min_risk_score": 80},
        )
        invoke_payload = await _post_json(
            client,
            "/mcp/messages",
            headers=agent_headers,
            json_body=invoke_body,
        )
        invoke_result = _jsonrpc_result(invoke_payload)
        receipt = invoke_result["receipt"]
        _require(receipt["outcome"] == "success", f"unexpected receipt: {receipt}")
        _require(receipt["ledger_entry_id"], "success receipt missing ledger entry")

        result_body = json.loads(invoke_result["content"][0]["text"])
        _require(
            result_body["items"][0]["artifact_id"] == "artifact-demo-001",
            f"unexpected RegEngine payload: {result_body}",
        )
        _require(
            len(fetch_calls) == 1,
            f"RegEngine fetch should execute once before replay: {fetch_calls}",
        )

        _line(emit, "verify signed receipt and ledger debit")
        receipt_verify = await _post_json(
            client,
            "/v1/receipts/verify",
            headers=agent_headers,
            json_body={"receipt_id": receipt["receipt_id"]},
        )
        _require(receipt_verify["valid"] is True, f"receipt invalid: {receipt_verify}")
        ledger = await _get_json(
            client,
            f"/v1/billing/ledger/{wallet_id}",
            headers=agent_headers,
        )
        debits = _matching_regengine_debits(ledger, tool_name=REGENGINE_AGENT_REVIEWS_TOOL)
        _require(len(debits) == 1, f"expected one RegEngine debit, got {debits}")

        _line(emit, "replay same idempotency key without second fetch or charge")
        replay_payload = await _post_json(
            client,
            "/mcp/messages",
            headers=agent_headers,
            json_body=invoke_body,
        )
        replay_receipt = _jsonrpc_result(replay_payload)["receipt"]
        _require(
            replay_receipt["receipt_id"] == receipt["receipt_id"],
            "replay did not return the original receipt",
        )
        _require(len(fetch_calls) == 1, "replay executed the RegEngine fetch again")
        ledger_after_replay = await _get_json(
            client,
            f"/v1/billing/ledger/{wallet_id}",
            headers=agent_headers,
        )
        debits_after_replay = _matching_regengine_debits(
            ledger_after_replay,
            tool_name=REGENGINE_AGENT_REVIEWS_TOOL,
        )
        _require(
            len(debits_after_replay) == 1,
            "replay created a duplicate RegEngine debit",
        )

        _line(emit, "prove wrong-scope permit is denied before RegEngine fetch")
        wrong_scope = await _post_json(
            client,
            "/v1/permits",
            headers={
                **bootstrap_headers,
                "Idempotency-Key": "regengine-bridge-wrong-scope-permit",
            },
            expected_status=201,
            json_body={
                "issuer_wallet_id": wallet_id,
                "subject_wallet_id": wallet_id,
                "subject_key_id": key["key_id"],
                "allowed_tools": ["regengine.agent_reviews.timeline"],
                "scopes": ["tool:regengine.agent_reviews.timeline:invoke"],
                "max_credits": 25,
                "expires_at": expires_at,
            },
        )
        denial_body = _mcp_call(
            request_id="regengine-bridge-denial-1",
            wallet_id=wallet_id,
            permit_id=wrong_scope["permit_id"],
            idempotency_key="regengine-bridge-denial-1",
            arguments={"limit": 1},
        )
        denial_payload = await _post_json(
            client,
            "/mcp/messages",
            headers=agent_headers,
            json_body=denial_body,
        )
        denial_error = _jsonrpc_error(denial_payload)
        _require(
            denial_error["message"] == "permit_tool_not_allowed",
            f"unexpected denial: {denial_error}",
        )
        denial_receipt = denial_error["data"]["receipt"]
        _require(denial_receipt["outcome"] == "denied", "denial receipt missing")
        _require(
            denial_receipt["ledger_entry_id"] is None,
            "denied RegEngine call should not have a ledger debit",
        )
        _require(
            len(fetch_calls) == 1,
            "wrong-scope denial called RegEngine before authorization",
        )

        _line(emit, "verify audit chain")
        audit_chain = await _post_json(
            client,
            "/v1/audit/verify-chain",
            headers=agent_headers,
            json_body={"wallet_id": wallet_id},
        )
        _require(audit_chain["valid"] is True, f"audit chain invalid: {audit_chain}")

        result = {
            "status": "pass",
            "tool": REGENGINE_AGENT_REVIEWS_TOOL,
            "discovery": {
                "requires_permit": annotations["requiresPermit"],
                "integration_status": annotations["integrationStatus"],
                "credits_per_call": annotations["creditsPerCall"],
            },
            "agent": {
                "wallet_id": f"wallet-{wallet_id}",
                "runtime_wallet_id": wallet_id,
                "key_id": key["key_id"],
            },
            "permit": {
                "permit_id": permit["permit_id"],
                "allowed_tools": permit["allowed_tools"],
            },
            "invoke": {
                "artifact_id": result_body["items"][0]["artifact_id"],
                "risk_score": result_body["items"][0]["risk_score"],
                "receipt_id": receipt["receipt_id"],
                "ledger_entry_id": receipt["ledger_entry_id"],
            },
            "receipt": {
                "valid": receipt_verify["valid"],
                "reason": receipt_verify["reason"],
            },
            "replay": {
                "same_receipt": replay_receipt["receipt_id"] == receipt["receipt_id"],
                "fetch_calls_after_replay": len(fetch_calls),
            },
            "ledger": {
                "matching_debits": len(debits_after_replay),
                "entry_ids": [entry["entry_id"] for entry in debits_after_replay],
            },
            "denial": {
                "reason": denial_error["message"],
                "receipt_id": denial_receipt["receipt_id"],
                "ledger_entry_id": denial_receipt["ledger_entry_id"],
                "fetch_calls_after_denial": len(fetch_calls),
            },
            "audit": {"chain": audit_chain},
        }
        _line(emit, "RegEngine governed bridge proof complete")
        return result
    finally:
        regengine_bridge._fetch_regengine_agent_reviews = original_fetch


def _configure_local_environment(
    *,
    database_url: str,
    bootstrap_api_key: str,
) -> None:
    os.environ["DATABASE_URL"] = database_url
    os.environ["VALID_API_KEYS"] = bootstrap_api_key
    os.environ["TRUST_MODE_ENABLED"] = "true"
    os.environ["ALLOW_LEGACY_UNPERMITTED_MCP"] = "false"
    os.environ["TRUST_SIGNING_KEY_ID"] = "regengine-bridge-ed25519"
    os.environ["TRUST_SIGNING_PRIVATE_KEY_B64"] = SIGNING_PRIVATE_KEY_B64

    from app.core.config import get_settings

    get_settings.cache_clear()


async def run_in_process(
    *,
    database_url: str | None = None,
    bootstrap_api_key: str = BOOTSTRAP_API_KEY,
    emit: bool = True,
) -> dict[str, Any]:
    async def run_with_database(db_url: str) -> dict[str, Any]:
        _configure_local_environment(
            database_url=db_url,
            bootstrap_api_key=bootstrap_api_key,
        )

        from app.db.database import close_db, init_db
        from app.main import app

        await close_db()
        await init_db()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://regengine-bridge.local",
            ) as client:
                result = await run_regengine_bridge_demo(
                    client=client,
                    bootstrap_api_key=bootstrap_api_key,
                    emit=emit,
                )
            if emit:
                print("REGENGINE GOVERNED BRIDGE: PASS")
            return result
        finally:
            await close_db()

    if database_url:
        return await run_with_database(database_url)

    with tempfile.TemporaryDirectory(prefix="regengine-bridge-") as tmpdir:
        db_path = Path(tmpdir) / "regengine-bridge.db"
        return await run_with_database(f"sqlite+aiosqlite:///{db_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the governed RegEngine MCP bridge proof."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the machine-readable proof artifact.",
    )
    parser.add_argument(
        "--assert",
        dest="assert_mode",
        action="store_true",
        help="Compatibility flag for CI; failures already raise AssertionError.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional SQLAlchemy async database URL. Defaults to a temp SQLite DB.",
    )
    parser.add_argument(
        "--bootstrap-api-key",
        default=BOOTSTRAP_API_KEY,
        help="Bootstrap API key used to create proof wallets and runtime key.",
    )
    args = parser.parse_args()

    result = asyncio.run(
        run_in_process(
            database_url=args.database_url,
            bootstrap_api_key=args.bootstrap_api_key,
            emit=not args.json,
        )
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
