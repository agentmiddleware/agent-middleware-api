#!/usr/bin/env python3
"""Mint a first credential or permit without hand-built JSON.

The quickstart (``docs/quickstart.md`` steps 3 and 4) asks a newcomer to
pipe ``curl`` output through inline Python to pick fields out of nested
JSON. When provisioning fails that pipeline prints an empty export and no
explanation. This script does the same two calls and either prints
``export`` lines or one readable error.

Subcommands:

``provision``
    POST ``/v1/dev-keys/self-provision`` (no credential needed) and print
    ``AGENT_API_KEY``, ``WALLET_ID`` and ``KEY_ID``. Only the local
    quickstart server enables this route; anywhere else it answers 404.

``permit``
    POST ``/v1/permits`` as a wallet-scoped key and print ``PERMIT_ID``.
    Computes the ``expires_at`` timestamp itself so callers do not have
    to. A wallet-scoped key may only permit wallets it has authority
    over (its own, or wallets it funds); anything else is refused.

Exit codes: ``0`` on success, ``2`` when the target cannot serve the
request (unreachable, disabled route, denied). ``stderr`` always carries
the human-readable reason; ``stdout`` carries only the ``export`` lines
so it stays safe to ``eval``.

Examples:
    python scripts/first_credential.py provision \\
        --api-url http://127.0.0.1:8000 --agent-id quickstart-stranger
    python scripts/first_credential.py permit \\
        --api-url http://127.0.0.1:8000 --api-key "$AGENT_API_KEY" \\
        --wallet-id "$WALLET_ID" --key-id "$KEY_ID"
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

PROVISION_PATH = "/v1/dev-keys/self-provision"
PERMIT_PATH = "/v1/permits"


def _post_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
    """POST JSON and return the decoded body, raising readable errors."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = _read_error_body(exc)
        raise CredentialError(_http_hint(exc.code, url, detail)) from exc
    except urllib.error.URLError as exc:
        raise CredentialError(
            f"cannot reach {url}: {exc.reason}. "
            "Is the server running (for example `make quickstart`)?"
        ) from exc


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - best effort error reporting only
        return ""
    try:
        parsed = json.loads(raw)
    except ValueError:
        return raw.strip()[:300]
    for key in ("detail", "error", "message"):
        value = parsed.get(key) if isinstance(parsed, dict) else None
        if value:
            return str(value)[:300]
    return raw.strip()[:300]


def _http_hint(status: int, url: str, detail: str) -> str:
    suffix = f" Server said: {detail}" if detail else ""
    if status == 404 and url.endswith(PROVISION_PATH):
        return (
            "self-provisioning is not enabled on this server (404). "
            "It exists only on the local quickstart server (`make "
            f"quickstart`).{suffix}"
        )
    if status in (401, 403):
        return (
            f"the server refused the request ({status}). For permits, a "
            "wallet-scoped key may only permit wallets it has authority "
            f"over, its own or ones it funds.{suffix}"
        )
    if status == 409:
        return (
            "the server reported a conflict (409), usually an idempotency "
            f"key reused with a different payload.{suffix}"
        )
    return f"the server answered {status}.{suffix}"


class CredentialError(Exception):
    """A failure with a message safe to show a newcomer."""


def provision(api_url: str, agent_id: str) -> dict[str, str]:
    data = _post_json(api_url.rstrip("/") + PROVISION_PATH, {"agent_id": agent_id}, {})
    missing = [key for key in ("api_key", "wallet_id", "key_id") if not data.get(key)]
    if missing:
        raise CredentialError(
            "the server answered without "
            + ", ".join(missing)
            + ". Is this the quickstart server?"
        )
    return {
        "AGENT_API_KEY": data["api_key"],
        "WALLET_ID": data["wallet_id"],
        "KEY_ID": data["key_id"],
    }


def issue_permit(
    api_url: str,
    api_key: str,
    wallet_id: str,
    key_id: str,
    tool: str,
    max_credits: float,
    idempotency_key: str,
    ttl_minutes: int = 30,
) -> dict[str, str]:
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    data = _post_json(
        api_url.rstrip("/") + PERMIT_PATH,
        {
            "issuer_wallet_id": wallet_id,
            "subject_wallet_id": wallet_id,
            "subject_key_id": key_id,
            "allowed_tools": [tool],
            "scopes": [f"tool:{tool}:invoke", "billing:charge"],
            "max_credits": max_credits,
            "expires_at": expires_at,
        },
        {"X-API-Key": api_key, "Idempotency-Key": idempotency_key},
    )
    if not data.get("permit_id"):
        raise CredentialError(
            "the server answered without a permit_id. Is this the quickstart server?"
        )
    return {"PERMIT_ID": data["permit_id"]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    provision_parser = sub.add_parser(
        "provision", help="mint a wallet-scoped key (quickstart server only)"
    )
    provision_parser.add_argument("--api-url", required=True)
    provision_parser.add_argument("--agent-id", default="quickstart-stranger")

    permit_parser = sub.add_parser(
        "permit", help="issue yourself a permit for one tool"
    )
    permit_parser.add_argument("--api-url", required=True)
    permit_parser.add_argument("--api-key", required=True)
    permit_parser.add_argument("--wallet-id", required=True)
    permit_parser.add_argument("--key-id", required=True)
    permit_parser.add_argument("--tool", default="partner.notes.write")
    permit_parser.add_argument("--max-credits", type=float, default=7.0)
    permit_parser.add_argument("--idempotency-key", default="quickstart-permit-1")
    permit_parser.add_argument("--ttl-minutes", type=int, default=30)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "provision":
            exports = provision(args.api_url, args.agent_id)
        else:
            exports = issue_permit(
                args.api_url,
                args.api_key,
                args.wallet_id,
                args.key_id,
                args.tool,
                args.max_credits,
                args.idempotency_key,
                args.ttl_minutes,
            )
    except CredentialError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for name, value in exports.items():
        print(f"export {name}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
