#!/usr/bin/env python3
"""Create and publish one consent-safe live governed MCP receipt.

This operator-only command provisions a dedicated, short-lived proof wallet,
invokes ``partner.echo`` once, exports the portable receipt and public key
snapshot, verifies both offline, and revokes the permit and API key.  It never
prints or writes credentials.

Run only against the canonical production origin, with Railway injecting the
bootstrap secret into the process environment::

    railway run uv run --with-requirements requirements.txt \
      python scripts/publish_live_proof.py \
      --output-dir site/proof --confirm-live-proof
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
SDK_SRC = ROOT / "b2a_sdk" / "src"
if str(SDK_SRC) not in sys.path:
    sys.path.insert(0, str(SDK_SRC))

from b2a_sdk.receipt_verifier import key_set_from_document, verify_bundle


CANONICAL_PRODUCTION_ORIGIN = "https://api.thisisatest.tech"
PUBLIC_TOOL = "partner.echo"
PUBLIC_MESSAGE = "Agent Middleware API public receipt proof"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _canonical_origin(value: str) -> str:
    origin = value.strip().rstrip("/")
    parsed = urlparse(origin)
    _require(parsed.scheme == "https", "proof origin must use HTTPS")
    _require(
        origin == CANONICAL_PRODUCTION_ORIGIN,
        "live proof may run only against the exact canonical production origin",
    )
    return origin


def _bootstrap_key() -> str:
    explicit = (os.environ.get("BOOTSTRAP_KEY") or "").strip()
    if explicit:
        return explicit

    configured = (os.environ.get("VALID_API_KEYS") or "").strip()
    # pydantic-settings accepts comma-separated values for this deployment.
    candidates = [item.strip() for item in configured.split(",") if item.strip()]
    _require(bool(candidates), "BOOTSTRAP_KEY or VALID_API_KEYS is required")
    return candidates[0]


def _json(response: httpx.Response, operation: str) -> dict[str, Any]:
    if response.status_code >= 400:
        raise RuntimeError(
            f"{operation} failed with HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )
    payload = response.json()
    _require(isinstance(payload, dict), f"{operation} returned non-object JSON")
    return payload


def _write_public_json(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    _require("api_key" not in serialized.lower(), "refusing to write credential data")
    path.write_text(serialized, encoding="utf-8")


def _cleanup_temporary_authority(
    client: httpx.Client,
    *,
    permit_id: str | None,
    agent_wallet_id: str | None,
    admin_headers: dict[str, str],
    agent_headers: dict[str, str] | None,
) -> None:
    """Revoke every temporary authority and fail the publication if any remain."""

    failures: list[str] = []
    if permit_id and agent_headers:
        try:
            response = client.post(
                f"/v1/permits/{permit_id}/revoke", headers=agent_headers
            )
            if response.status_code >= 400:
                failures.append(f"permit revoke returned HTTP {response.status_code}")
        except Exception as exc:
            failures.append(f"permit revoke request raised {type(exc).__name__}")
    if agent_wallet_id:
        try:
            response = client.post(
                "/v1/api-keys/emergency-revoke",
                headers=admin_headers,
                json={
                    "wallet_id": agent_wallet_id,
                    "reason": "public_proof_complete",
                    "create_new_key": False,
                },
            )
            if response.status_code >= 400:
                failures.append(
                    f"API-key emergency revoke returned HTTP {response.status_code}"
                )
        except Exception as exc:
            failures.append(
                f"API-key emergency revoke request raised {type(exc).__name__}"
            )
    if failures:
        raise RuntimeError(
            "temporary proof authority cleanup failed: " + "; ".join(failures)
        )


def publish(*, api_url: str, output_dir: Path) -> dict[str, Any]:
    origin = _canonical_origin(api_url)
    admin_headers = {"X-API-Key": _bootstrap_key()}
    run_id = secrets.token_hex(6)
    agent_headers: dict[str, str] | None = None
    agent_wallet_id: str | None = None
    permit_id: str | None = None
    portable_to_publish: dict[str, Any] | None = None
    keys_to_publish: dict[str, Any] | None = None
    publication_result: dict[str, Any] | None = None

    # A bootstrap credential must go directly to the canonical TLS endpoint;
    # do not inherit workstation HTTP(S)_PROXY settings.
    with httpx.Client(base_url=origin, timeout=60.0, trust_env=False) as client:
        health = _json(client.get("/health"), "health check")
        _require(health.get("status") in {"ok", "healthy"}, "gateway is not healthy")

        sponsor = _json(
            client.post(
                "/v1/billing/wallets/sponsor",
                headers=admin_headers,
                json={
                    "sponsor_name": "Agent Middleware API public proof",
                    "email": "proof-wallet@invalid.example",
                    "initial_credits": 10,
                    "require_kyc": False,
                    "metadata": {
                        "purpose": "public-self-issued-proof",
                        "customer_traction": False,
                        "run_id": run_id,
                    },
                },
            ),
            "create proof sponsor wallet",
        )
        sponsor_wallet_id = str(sponsor["wallet_id"])

        agent = _json(
            client.post(
                "/v1/billing/wallets/agent",
                headers=admin_headers,
                json={
                    "sponsor_wallet_id": sponsor_wallet_id,
                    "agent_id": f"public-proof-{run_id}",
                    "budget_credits": 5,
                    "daily_limit": 5,
                },
            ),
            "create proof agent wallet",
        )
        agent_wallet_id = str(agent["wallet_id"])

        try:
            # Enter cleanup scope before creating a live key. If the request
            # times out after the server commits, the admin emergency revoke
            # still disables every key for this dedicated throwaway wallet.
            key = _json(
                client.post(
                    "/v1/api-keys",
                    headers=admin_headers,
                    json={
                        "wallet_id": agent_wallet_id,
                        "key_name": f"public-proof-{run_id}",
                        "expires_in_days": 1,
                    },
                ),
                "create proof API key",
            )
            agent_api_key = key.get("api_key")
            _require(
                isinstance(agent_api_key, str) and bool(agent_api_key.strip()),
                "create proof API key returned no usable API key",
            )
            agent_headers = {"X-API-Key": agent_api_key}

            expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
            permit = _json(
                client.post(
                    "/v1/permits",
                    headers={
                        **agent_headers,
                        "Idempotency-Key": f"public-proof-permit-{run_id}",
                    },
                    json={
                        "issuer_wallet_id": agent_wallet_id,
                        "subject_wallet_id": agent_wallet_id,
                        "allowed_tools": [PUBLIC_TOOL],
                        "scopes": [
                            f"tool:{PUBLIC_TOOL}:invoke",
                            "billing:charge",
                        ],
                        "max_credits": 5,
                        "expires_at": expires_at.isoformat(),
                    },
                ),
                "create proof permit",
            )
            permit_id = str(permit["permit_id"])

            invocation = _json(
                client.post(
                    "/mcp/messages",
                    headers=agent_headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": f"public-proof-{run_id}",
                        "method": "tools/call",
                        "params": {
                            "name": PUBLIC_TOOL,
                            "arguments": {"message": PUBLIC_MESSAGE},
                            "mcpContext": {
                                "wallet_id": agent_wallet_id,
                                "permit_id": permit_id,
                                "idempotency_key": f"public-proof-invoke-{run_id}",
                            },
                        },
                    },
                ),
                "invoke partner.echo",
            )
            receipt = invocation.get("result", {}).get("receipt")
            _require(
                isinstance(receipt, dict), "governed invocation returned no receipt"
            )
            receipt_id = str(receipt["receipt_id"])

            portable = _json(
                client.get(
                    f"/v1/receipts/{receipt_id}/portable",
                    headers=agent_headers,
                ),
                "export portable receipt",
            )
            trust_keys = _json(
                client.get("/.well-known/trust-keys.json"),
                "fetch public trust keys",
            )

            result = verify_bundle(
                portable,
                key_set_from_document(trust_keys),
                expected_issuer=origin,
            )
            _require(result.ok, f"offline verification failed: {result.reason}")
            _require(result.claims.get("tool") == PUBLIC_TOOL, "wrong tool in receipt")
            _require(result.claims.get("outcome") == "success", "proof did not succeed")

            portable_to_publish = portable
            keys_to_publish = trust_keys
            publication_result = {
                "receipt_id": receipt_id,
                "permit_id": permit_id,
                "kid": portable.get("kid"),
                "issuer": portable.get("issuer"),
                "tool": result.claims.get("tool"),
                "outcome": result.claims.get("outcome"),
                "credits_charged": result.claims.get("credits_charged"),
                "created_at": result.claims.get("created_at"),
                "output_dir": str(output_dir),
            }
        finally:
            # Receipt evidence remains valid after the temporary authority is
            # revoked. Do not publish if either cleanup action fails: a proof
            # run that leaves live authority behind is not a successful run.
            _cleanup_temporary_authority(
                client,
                permit_id=permit_id,
                agent_wallet_id=agent_wallet_id,
                admin_headers=admin_headers,
                agent_headers=agent_headers,
            )

    _require(portable_to_publish is not None, "portable receipt was not produced")
    _require(keys_to_publish is not None, "public key snapshot was not produced")
    _require(
        publication_result is not None, "proof publication result was not produced"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_public_json(output_dir / "receipt.json", portable_to_publish)
    _write_public_json(output_dir / "trust-keys.json", keys_to_publish)
    return publication_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default=os.environ.get("PUBLIC_URL", CANONICAL_PRODUCTION_ORIGIN),
        help="Canonical production API origin (must be api.thisisatest.tech)",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--confirm-live-proof",
        action="store_true",
        help="Acknowledge this creates wallets and charges one live tool call",
    )
    args = parser.parse_args(argv)
    if not args.confirm_live_proof:
        parser.error("--confirm-live-proof is required")

    result = publish(api_url=args.api_url, output_dir=args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
