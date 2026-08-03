#!/usr/bin/env python3
"""Gated design-partner API key bootstrap against a running API.

Uses a bootstrap/admin key (VALID_API_KEYS) only to provision:
  sponsor wallet → agent wallet → DB-scoped agent API key.

The agent secret is printed once. Requires network access to --api-url.
Does not mint keys without --bootstrap-key (fail closed).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"error: {message}")


def _post(client: httpx.Client, path: str, body: dict[str, Any]) -> dict[str, Any]:
    resp = client.post(path, json=body)
    if resp.status_code >= 400:
        raise SystemExit(f"error: POST {path} → {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    _require(isinstance(data, dict), f"POST {path} returned non-object JSON")
    return data


def provision(
    *,
    api_url: str,
    bootstrap_key: str,
    sponsor_name: str,
    agent_id: str,
    budget_credits: float,
    initial_credits: float,
    key_name: str,
) -> dict[str, Any]:
    base = api_url.rstrip("/")
    headers = {
        "X-API-Key": bootstrap_key,
        "Content-Type": "application/json",
    }
    with httpx.Client(base_url=base, headers=headers, timeout=60.0) as client:
        health = client.get("/health")
        _require(health.status_code == 200, f"/health → {health.status_code}")

        sponsor = _post(
            client,
            "/v1/billing/wallets/sponsor",
            {
                "sponsor_name": sponsor_name,
                "email": f"{agent_id}@partners.local",
                "initial_credits": initial_credits,
                "require_kyc": False,
            },
        )
        sponsor_wallet_id = sponsor.get("wallet_id")
        _require(bool(sponsor_wallet_id), "sponsor wallet_id missing")

        agent = _post(
            client,
            "/v1/billing/wallets/agent",
            {
                "sponsor_wallet_id": sponsor_wallet_id,
                "agent_id": agent_id,
                "budget_credits": budget_credits,
            },
        )
        agent_wallet_id = agent.get("wallet_id")
        _require(bool(agent_wallet_id), "agent wallet_id missing")

        key = _post(
            client,
            "/v1/api-keys",
            {
                "wallet_id": agent_wallet_id,
                "key_name": key_name,
            },
        )
        api_key = key.get("api_key")
        _require(bool(api_key), "api_key missing (shown only once)")

        return {
            "api_url": base,
            "sponsor_wallet_id": sponsor_wallet_id,
            "agent_wallet_id": agent_wallet_id,
            "agent_id": agent_id,
            "key_id": key.get("key_id"),
            "key_prefix": key.get("key_prefix"),
            "api_key": api_key,
            "note": (
                "Store api_key securely. Bootstrap key must not be shared "
                "with the partner agent."
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Provision a wallet-scoped partner API key (gated bootstrap)."
    )
    parser.add_argument(
        "--api-url",
        required=True,
        help="Public API origin (PUBLIC_URL), e.g. https://….up.railway.app",
    )
    parser.add_argument(
        "--bootstrap-key",
        required=True,
        help="Operator VALID_API_KEYS entry — never a partner-facing secret",
    )
    parser.add_argument("--sponsor-name", default="Design Partner")
    parser.add_argument("--agent-id", default="partner-agent-001")
    parser.add_argument("--budget-credits", type=float, default=1000.0)
    parser.add_argument("--initial-credits", type=float, default=10000.0)
    parser.add_argument("--key-name", default="partner-agent")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON including api_key (default: human summary)",
    )
    args = parser.parse_args()

    result = provision(
        api_url=args.api_url,
        bootstrap_key=args.bootstrap_key,
        sponsor_name=args.sponsor_name,
        agent_id=args.agent_id,
        budget_credits=args.budget_credits,
        initial_credits=args.initial_credits,
        key_name=args.key_name,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("Partner API key bootstrap OK")
        print(f"  api_url:            {result['api_url']}")
        print(f"  sponsor_wallet_id:  {result['sponsor_wallet_id']}")
        print(f"  agent_wallet_id:    {result['agent_wallet_id']}")
        print(f"  key_id:             {result['key_id']}")
        print(f"  key_prefix:         {result['key_prefix']}")
        print(f"  api_key (once):     {result['api_key']}")
        print(f"  note:               {result['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
