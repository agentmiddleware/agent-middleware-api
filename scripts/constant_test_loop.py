#!/usr/bin/env python3
"""Production-ready constant smoke test: permit → invoke → receipt → replay → deny.

Exercises the complete governed loop against a live trust plane. Prefers the
production tool ``partner.echo`` (upstream MCP) when available, falls back to
``partner.notes.write`` (dogfood, requires ``ENABLE_DOGFOOD_TOOL=true`` locally):

1. Permit → invoke the governed tool with scoped permit → signed receipt
2. Replay same idempotency key → same receipt_id, no second debit
3. Out-of-scope tool is denied (when multiple tools exist)

The loop reads the agent credential only from $CI_SMOKE_AGENT_KEY (never
hardcoded, never logged, never printed). Optionally reads $CI_SMOKE_WALLET_ID
and $CI_SMOKE_KEY_ID for faster startup; fetches them from the API if missing.
Exits 0 on success, 1 on any invariant failure, 2 on configuration error.

Run locally (auto-provisions agent key)::

    make quickstart  # in terminal 1
    python scripts/constant_test_loop.py  # in terminal 2

Run against production (once CI_SMOKE_AGENT_KEY is set in CI)::

    API_URL=https://api.thisisatest.tech \\
        python scripts/constant_test_loop.py
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_URL = "http://127.0.0.1:8000"
# Prefer partner.echo (production governed tool) over partner.notes.write (dogfood)
PRODUCTION_GOVERNED_TOOL = "partner.echo"
DOGFOOD_GOVERNED_TOOL = "partner.notes.write"
OUT_OF_SCOPE_TOOL = "some.other.tool"  # Dummy tool not in permit scope
PERMIT_MAX_CREDITS = 10


class SmokeTestFailure(RuntimeError):
    """Raised when an invariant fails during the smoke test."""


class ConfigurationError(RuntimeError):
    """Raised when configuration is invalid (exits with status 2)."""


def require(condition: bool, message: str) -> None:
    """Fail immediately if condition is false."""
    if not condition:
        raise SmokeTestFailure(message)


def _get_agent_key() -> tuple[str, str, str]:
    """Read agent credential from $CI_SMOKE_AGENT_KEY or signal self-provision.
    
    Returns (api_key, wallet_id, key_id). If CI_SMOKE_AGENT_KEY is set but
    wallet_id/key_id are missing, returns (key, "", "") to signal they should
    be fetched from the API. Never logs or prints the key.
    """
    key = os.environ.get("CI_SMOKE_AGENT_KEY", "").strip()
    wallet_id = os.environ.get("CI_SMOKE_WALLET_ID", "").strip()
    key_id = os.environ.get("CI_SMOKE_KEY_ID", "").strip()
    
    if key and wallet_id and key_id:
        # All three provided - use them
        return (key, wallet_id, key_id)
    elif key:
        # Key provided but wallet_id/key_id missing - will fetch from API
        return (key, "", "")
    else:
        # Nothing provided - will self-provision in run_constant_test
        return ("", "", "")


def _get_api_url() -> str:
    """Read API URL from $API_URL or default to local quickstart.
    
    Validates that non-loopback URLs use HTTPS to prevent cleartext key leaks.
    """
    url = os.environ.get("API_URL", DEFAULT_API_URL).rstrip("/")
    
    # Enforce HTTPS for non-loopback URLs (same as partner_api_key_bootstrap.py)
    from urllib.parse import urlparse
    parsed = urlparse(url)
    is_loopback = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    
    if parsed.scheme == "http" and not is_loopback:
        raise ConfigurationError(
            f"refusing to send CI_SMOKE_AGENT_KEY over cleartext HTTP to "
            f"non-loopback host {parsed.hostname}. Use https:// or a loopback address."
        )
    
    return url


def _post_json(
    client: httpx.Client,
    path: str,
    body: dict[str, Any],
    *,
    expected_status: int,
) -> dict[str, Any]:
    """POST JSON and require expected_status."""
    resp = client.post(path, json=body)
    require(
        resp.status_code == expected_status,
        f"POST {path} → {resp.status_code}: {resp.text[:500]}",
    )
    data = resp.json()
    require(isinstance(data, dict), f"POST {path} returned non-object JSON")
    return data


def _get_json(
    client: httpx.Client,
    path: str,
    *,
    expected_status: int,
) -> dict[str, Any]:
    """GET JSON and require expected_status."""
    resp = client.get(path)
    require(
        resp.status_code == expected_status,
        f"GET {path} → {resp.status_code}: {resp.text[:500]}",
    )
    data = resp.json()
    require(isinstance(data, dict), f"GET {path} returned non-object JSON")
    return data


def _build_mcp_call(
    *,
    request_id: str,
    tool: str,
    wallet_id: str,
    permit_id: str,
    idempotency_key: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an MCP tools/call request with mcpContext."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": tool,
            "arguments": arguments or {},
            "mcpContext": {
                "wallet_id": wallet_id,
                "permit_id": permit_id,
                "idempotency_key": idempotency_key,
            },
        },
    }


def _first_jsonrpc_result(response: dict[str, Any]) -> dict[str, Any]:
    """Extract result from JSON-RPC response, failing if error is present."""
    require("result" in response, f"expected JSON-RPC result, got: {response}")
    return response["result"]


def _first_jsonrpc_error(response: dict[str, Any]) -> dict[str, Any]:
    """Extract error from JSON-RPC response, failing if result is present."""
    require("error" in response, f"expected JSON-RPC error, got: {response}")
    return response["error"]


def run_constant_test(api_url: str, agent_key: str, wallet_id: str, key_id: str) -> None:
    """Execute the constant test loop and assert all invariants."""
    print(f"[constant-test] target: {api_url}", file=sys.stderr)

    # Generate a unique run ID for this execution to make idempotency keys unique
    run_id = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')

    # If credentials not provided, self-provision
    if not agent_key:
        print("[constant-test] self-provisioning agent key", file=sys.stderr)
        with httpx.Client(base_url=api_url, timeout=30.0) as provision_client:
            provision_resp = _post_json(
                provision_client,
                "/v1/dev-keys/self-provision",
                {"agent_id": f"constant-test-{run_id}"},
                expected_status=201,
            )
            agent_key = provision_resp["api_key"]
            wallet_id = provision_resp["wallet_id"]
            key_id = provision_resp["key_id"]
            print(
                f"[constant-test] self-provisioned: wallet_id={wallet_id}",
                file=sys.stderr,
            )
    elif not wallet_id or not key_id:
        # Key provided but wallet_id/key_id missing - fetch from API
        print("[constant-test] fetching wallet_id and key_id from API", file=sys.stderr)
        headers = {
            "X-API-Key": agent_key,
            "Content-Type": "application/json",
        }
        with httpx.Client(base_url=api_url, headers=headers, timeout=30.0) as fetch_client:
            wallets_resp = _get_json(fetch_client, "/v1/billing/wallets", expected_status=200)
            wallets = wallets_resp.get("wallets", [])
            require(len(wallets) > 0, "no wallets found for this API key")
            # Use the first wallet (agent wallet)
            wallet_id = wallets[0]["wallet_id"]
            
            # Fetch key_id from the keys list
            keys_resp = _get_json(fetch_client, f"/v1/billing/wallets/{wallet_id}/keys", expected_status=200)
            keys = keys_resp.get("keys", [])
            require(len(keys) > 0, "no keys found for this wallet")
            
            # Derive key_prefix: first 8 characters (same as generate_api_key format)
            # Validate key format before deriving prefix
            if len(agent_key) < 8 or "_" not in agent_key:
                raise ConfigurationError("malformed API key: expected format <prefix>_<suffix>")
            key_prefix = agent_key[:8]
            
            matching_keys = [k for k in keys if k.get("key_prefix") == key_prefix]
            if len(matching_keys) == 0:
                raise ConfigurationError(f"no key found with prefix {key_prefix}")
            if len(matching_keys) > 1:
                raise ConfigurationError(f"ambiguous: {len(matching_keys)} keys with prefix {key_prefix}")
            key_id = matching_keys[0]["key_id"]
            
            print(
                f"[constant-test] fetched: wallet_id={wallet_id}, key_id={key_id}",
                file=sys.stderr,
            )

    # Never log or print the agent_key.
    headers = {
        "X-API-Key": agent_key,
        "Content-Type": "application/json",
    }

    with httpx.Client(base_url=api_url, headers=headers, timeout=30.0) as client:
        # Discover tools
        print("[constant-test] discovering tools", file=sys.stderr)
        tools = _get_json(client, "/mcp/tools.json", expected_status=200)
        tool_names = [tool["name"] for tool in tools.get("tools", [])]
        
        # Select governed tool: prefer production partner.echo over dogfood partner.notes.write
        governed_tool = None
        if PRODUCTION_GOVERNED_TOOL in tool_names:
            governed_tool = PRODUCTION_GOVERNED_TOOL
            print(f"[constant-test] using production tool: {governed_tool}", file=sys.stderr)
        elif DOGFOOD_GOVERNED_TOOL in tool_names:
            governed_tool = DOGFOOD_GOVERNED_TOOL
            print(f"[constant-test] using dogfood tool: {governed_tool} (ENABLE_DOGFOOD_TOOL=true)", file=sys.stderr)
        else:
            raise SmokeTestFailure(
                f"neither {PRODUCTION_GOVERNED_TOOL} nor {DOGFOOD_GOVERNED_TOOL} discoverable. "
                f"Available tools: {', '.join(tool_names)}"
            )

        # Issue scoped permit
        print("[constant-test] issuing scoped permit", file=sys.stderr)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=30)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Add Idempotency-Key header for permit creation (unique per run)
        permit_headers = {
            **headers,
            "Idempotency-Key": f"constant-test-permit-{run_id}",
        }
        resp = client.post(
            "/v1/permits",
            json={
                "issuer_wallet_id": wallet_id,
                "subject_wallet_id": wallet_id,
                "subject_key_id": key_id,
                "allowed_tools": [governed_tool],
                "scopes": [f"tool:{governed_tool}:invoke", "billing:charge"],
                "max_credits": PERMIT_MAX_CREDITS,
                "expires_at": expires_at,
            },
            headers=permit_headers,
        )
        require(
            resp.status_code == 201,
            f"POST /v1/permits → {resp.status_code}: {resp.text[:500]}",
        )
        permit = resp.json()
        permit_id = permit["permit_id"]
        print(f"[constant-test] permit_id={permit_id}", file=sys.stderr)

        # Invoke the governed tool (unique idempotency key per run)
        invoke_idempotency_key = f"constant-test-invoke-{run_id}"
        print(f"[constant-test] invoking {governed_tool}", file=sys.stderr)
        call_body = _build_mcp_call(
            request_id=f"constant-test-req-{run_id}",
            tool=governed_tool,
            wallet_id=wallet_id,
            permit_id=permit_id,
            idempotency_key=invoke_idempotency_key,
            arguments={"text": "constant test loop"},
        )
        first_call = _post_json(
            client, "/mcp/messages", call_body, expected_status=200
        )
        result = _first_jsonrpc_result(first_call)
        require(result["isError"] is False, f"tool call failed: {result}")
        receipt = result["receipt"]
        require(receipt["outcome"] == "success", "receipt outcome != success")
        require(
            receipt["ledger_entry_id"] is not None,
            "success receipt missing ledger entry",
        )
        charged = Decimal(str(receipt["credits_charged"]))
        require(charged > 0, f"success charged {charged} credits (expected > 0)")
        print(
            f"[constant-test] success: receipt_id={receipt['receipt_id']} "
            f"charged={charged}",
            file=sys.stderr,
        )

        # Check ledger debit
        print("[constant-test] verifying ledger debit", file=sys.stderr)
        ledger = _get_json(
            client, f"/v1/billing/ledger/{wallet_id}", expected_status=200
        )
        matching = [
            e for e in ledger["entries"] if e["entry_id"] == receipt["ledger_entry_id"]
        ]
        require(len(matching) == 1, "receipt ledger_entry_id not in wallet ledger")
        debit_amount = Decimal(str(matching[0]["amount"]))
        require(
            debit_amount == -charged,
            f"ledger debit {debit_amount} != receipt charge {-charged}",
        )
        debits_before_replay = len(
            [e for e in ledger["entries"] if governed_tool in e.get("description", "")]
        )

        # Replay same idempotency key → same receipt_id, no second debit
        print("[constant-test] replaying with same idempotency_key", file=sys.stderr)
        replay_call = _post_json(
            client, "/mcp/messages", call_body, expected_status=200
        )
        replay_result = _first_jsonrpc_result(replay_call)
        replay_receipt = replay_result["receipt"]
        require(
            replay_receipt["receipt_id"] == receipt["receipt_id"],
            "replay returned different receipt_id",
        )
        ledger_after_replay = _get_json(
            client, f"/v1/billing/ledger/{wallet_id}", expected_status=200
        )
        debits_after_replay = len(
            [
                e
                for e in ledger_after_replay["entries"]
                if governed_tool in e.get("description", "")
            ]
        )
        require(
            debits_after_replay == debits_before_replay,
            "replay created a second debit",
        )
        print(
            "[constant-test] replay OK: same receipt_id, no second debit",
            file=sys.stderr,
        )

        # Out-of-scope tool denial check (optional)
        # Only run if there are multiple tools available to test against.
        # A single-tool environment exercises the core loop but can't test
        # permit_tool_not_allowed without registering a second tool.
        if len(tool_names) > 1:
            print("[constant-test] attempting out-of-scope tool", file=sys.stderr)
            # Find a tool that's not the governed one
            other_tool = next((t for t in tool_names if t != governed_tool), None)
            if other_tool:
                denial_body = _build_mcp_call(
                    request_id=f"constant-test-deny-{run_id}",
                    tool=other_tool,
                    wallet_id=wallet_id,
                    permit_id=permit_id,
                    idempotency_key=f"constant-test-deny-{run_id}",
                    arguments={},
                )
                denial_call = _post_json(
                    client, "/mcp/messages", denial_body, expected_status=200
                )
                denial_error = _first_jsonrpc_error(denial_call)
                require(
                    denial_error["message"] == "permit_tool_not_allowed",
                    f"expected permit_tool_not_allowed, got {denial_error['message']}",
                )
                denial_receipt = denial_error["data"]["receipt"]
                require(
                    denial_receipt["outcome"] == "denied",
                    "denial receipt outcome != denied",
                )
                denial_charged = Decimal(str(denial_receipt["credits_charged"]))
                require(
                    denial_charged == Decimal("0"),
                    f"denial charged {denial_charged} credits (expected 0)",
                )
                print(
                    "[constant-test] denial OK: permit_tool_not_allowed, 0 credits charged",
                    file=sys.stderr,
                )
        else:
            print(
                "[constant-test] SKIPPED out-of-scope tool check (single tool only)",
                file=sys.stderr,
            )

    print("[constant-test] ALL INVARIANTS HELD", file=sys.stderr)


def _validate_api_url(url: str) -> str:
    """Validate API URL and enforce HTTPS for non-loopback hosts."""
    from urllib.parse import urlparse
    
    url = url.rstrip("/")
    parsed = urlparse(url)
    is_loopback = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    
    if parsed.scheme == "http" and not is_loopback:
        raise ConfigurationError(
            f"refusing to send CI_SMOKE_AGENT_KEY over cleartext HTTP to "
            f"non-loopback host {parsed.hostname}. Use https:// or a loopback address."
        )
    
    return url


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--api-url",
        default=None,
        help=(
            "API URL to test against (default: $API_URL or "
            f"{DEFAULT_API_URL}). Reads $CI_SMOKE_AGENT_KEY, "
            "$CI_SMOKE_WALLET_ID, $CI_SMOKE_KEY_ID for auth, or self-provisions."
        ),
    )
    args = parser.parse_args(argv)

    try:
        # Validate API URL (applies to both --api-url and $API_URL)
        api_url = _validate_api_url(args.api_url or _get_api_url())
        agent_key, wallet_id, key_id = _get_agent_key()
        run_constant_test(api_url, agent_key, wallet_id, key_id)
    except ConfigurationError as config_error:
        print(f"\n[constant-test] configuration error: {config_error}", file=sys.stderr)
        return 2
    except SmokeTestFailure as failure:
        print(f"\n[constant-test] FAILED: {failure}", file=sys.stderr)
        return 1
    except httpx.HTTPError as network_error:
        print(
            f"\n[constant-test] network error: {network_error}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
