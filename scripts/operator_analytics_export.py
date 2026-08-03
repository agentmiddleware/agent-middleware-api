#!/usr/bin/env python3
"""Operator analytics export over wallet / audit / ledger HTTP surfaces.

Bootstrap-admin only. Pulls existing trust-plane endpoints into one JSON
bundle for offline review — not a new product UI.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"error: {message}")


def _get(client: httpx.Client, path: str, params: dict[str, Any] | None = None) -> Any:
    resp = client.get(path, params=params or {})
    if resp.status_code >= 400:
        raise SystemExit(f"error: GET {path} → {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def export_bundle(
    *,
    api_url: str,
    bootstrap_key: str,
    wallet_id: str | None,
    audit_limit: int,
    ledger_limit: int,
) -> dict[str, Any]:
    base = api_url.rstrip("/")
    headers = {"X-API-Key": bootstrap_key}
    with httpx.Client(base_url=base, headers=headers, timeout=60.0) as client:
        health = _get(client, "/health")
        wallets_payload = _get(client, "/v1/billing/wallets")
        wallets = wallets_payload.get("wallets") or []
        if wallet_id:
            wallets = [w for w in wallets if w.get("wallet_id") == wallet_id]
            _require(bool(wallets), f"wallet_id not found: {wallet_id}")

        ledger_by_wallet: dict[str, Any] = {}
        for wallet in wallets:
            wid = wallet.get("wallet_id")
            if not wid:
                continue
            ledger_by_wallet[wid] = _get(
                client,
                f"/v1/billing/ledger/{wid}",
                params={"limit": ledger_limit},
            )

        audit_params: dict[str, Any] = {"limit": audit_limit, "offset": 0}
        if wallet_id:
            audit_params["wallet_id"] = wallet_id
        else:
            # Cross-wallet listing requires bootstrap; ask for summary when
            # no wallet filter so the export stays bounded.
            audit_params["summary"] = True
        audit = _get(client, "/v1/audit/events", params=audit_params)

        return {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "api_url": base,
            "health": health,
            "wallet_filter": wallet_id,
            "wallets": wallets,
            "ledger_by_wallet": ledger_by_wallet,
            "audit": audit,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export wallet/audit/ledger analytics for operators."
    )
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--bootstrap-key", required=True)
    parser.add_argument(
        "--wallet-id",
        default=None,
        help="Optional single-wallet filter (recommended for large tenants)",
    )
    parser.add_argument("--audit-limit", type=int, default=200)
    parser.add_argument("--ledger-limit", type=int, default=200)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write JSON to this path (default: stdout)",
    )
    args = parser.parse_args()

    bundle = export_bundle(
        api_url=args.api_url,
        bootstrap_key=args.bootstrap_key,
        wallet_id=args.wallet_id,
        audit_limit=args.audit_limit,
        ledger_limit=args.ledger_limit,
    )
    text = json.dumps(bundle, indent=2, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
