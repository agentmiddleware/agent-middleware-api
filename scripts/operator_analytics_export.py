#!/usr/bin/env python3
"""Operator analytics export over wallet / audit / ledger HTTP surfaces.

The legacy path uses bootstrap-admin access. The insight path uses an
enterprise reporting bearer and scoped read-only endpoints.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"error: {message}")


def _require_safe_api_url(api_url: str, credential: str = "bootstrap key") -> str:
    base = api_url.strip().rstrip("/")
    parsed = urlparse(base)
    host = (parsed.hostname or "").lower()
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "https":
        return base
    if parsed.scheme == "http" and loopback:
        return base
    raise SystemExit(
        "error: --api-url must be https:// for non-loopback hosts "
        f"({credential} must not travel in cleartext)"
    )


def _bootstrap_key(cli_value: str | None) -> str:
    key = (os.environ.get("BOOTSTRAP_KEY") or "").strip()
    if key:
        return key
    if cli_value:
        print(
            "warning: prefer BOOTSTRAP_KEY env over --bootstrap-key "
            "(argv is visible to local process listings)",
            file=sys.stderr,
        )
        return cli_value.strip()
    raise SystemExit(
        "error: set BOOTSTRAP_KEY in the environment "
        "(or pass --bootstrap-key for local-only use)"
    )


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
    base = _require_safe_api_url(api_url)
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


def export_insights(
    *,
    api_url: str,
    wallet_ids: tuple[str, ...],
    as_of: str,
    days: int,
    time_basis: str,
    output: Path,
    format: str,
    include_unknown_wallet_counts: bool,
) -> None:
    """Fetch the server-authorized report without bootstrap or body echoing."""
    base = _require_safe_api_url(api_url, credential="reporting bearer")
    token = (os.environ.get("AMW_INSIGHTS_BEARER_TOKEN") or "").strip()
    _require(bool(token), "set AMW_INSIGHTS_BEARER_TOKEN in the environment")
    _require(
        bool(wallet_ids), "provide at least one --wallet-id or --insight-wallet-id"
    )
    _require(output.parent.is_dir(), "--out parent directory must already exist")
    _require(not output.exists(), "--out must not already exist")
    params: list[tuple[str, str]] = [
        ("wallet_id", wallet_id) for wallet_id in wallet_ids
    ]
    params.extend(
        [
            ("as_of", as_of),
            ("days", str(days)),
            ("time_basis", time_basis),
            ("format", format),
            (
                "include_unknown_wallet_counts",
                str(include_unknown_wallet_counts).lower(),
            ),
        ]
    )
    content_type = "application/json" if format == "json" else "application/zip"
    try:
        with httpx.Client(
            base_url=base,
            headers={"Authorization": f"Bearer {token}"},
            timeout=310.0,
        ) as client:
            with client.stream(
                "GET", "/v1/operator/insights/report", params=params
            ) as response:
                if response.status_code >= 400:
                    raise SystemExit(
                        f"error: insight report request returned {response.status_code}"
                    )
                if content_type not in response.headers.get("content-type", ""):
                    raise SystemExit(
                        "error: insight report response type was unexpected"
                    )
                descriptor = os.open(
                    output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                try:
                    with os.fdopen(descriptor, "wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
                except BaseException:
                    output.unlink(missing_ok=True)
                    raise
    except httpx.HTTPError:
        raise SystemExit("error: insight report request failed") from None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export wallet/audit/ledger analytics for operators."
    )
    parser.add_argument("--api-url", required=True)
    parser.add_argument(
        "--bootstrap-key",
        default=None,
        help="Deprecated: prefer BOOTSTRAP_KEY env (argv is process-visible)",
    )
    parser.add_argument(
        "--wallet-id",
        default=None,
        help="Optional single-wallet filter (recommended for large tenants)",
    )
    parser.add_argument("--audit-limit", type=int, default=200)
    parser.add_argument("--ledger-limit", type=int, default=200)
    parser.add_argument("--insights", action="store_true")
    parser.add_argument("--insight-wallet-id", action="append", default=[])
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--days", type=int, choices=(7, 30), default=None)
    parser.add_argument(
        "--time-basis", choices=("ingress", "first_observed_evidence"), default=None
    )
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    parser.add_argument("--include-unknown-wallet-counts", action="store_true")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write insight JSON or CSV ZIP here; legacy defaults to stdout",
    )
    args = parser.parse_args()

    if args.insights:
        _require(
            args.bootstrap_key is None, "--bootstrap-key is not accepted for insights"
        )
        _require(args.as_of is not None, "--as-of is required for insights")
        _require(args.days is not None, "--days is required for insights")
        _require(args.time_basis is not None, "--time-basis is required for insights")
        _require(args.out is not None, "--out is required for insights")
        export_insights(
            api_url=args.api_url,
            wallet_ids=tuple(
                ([args.wallet_id] if args.wallet_id else []) + args.insight_wallet_id
            ),
            as_of=args.as_of,
            days=args.days,
            time_basis=args.time_basis,
            output=args.out,
            format=args.format,
            include_unknown_wallet_counts=args.include_unknown_wallet_counts,
        )
        print(f"wrote {args.out}", file=sys.stderr)
        return 0

    bundle = export_bundle(
        api_url=args.api_url,
        bootstrap_key=_bootstrap_key(args.bootstrap_key),
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
