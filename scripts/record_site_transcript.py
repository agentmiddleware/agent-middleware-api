#!/usr/bin/env python3
"""Record the governed-loop transcript the public site renders.

The landing page shows the governed loop as a terminal transcript: real
requests, real responses, and the offline verifier's real output. Nothing on
that page is typed in by hand — every line comes from ``site/proof/transcript.json``,
and this script is the only thing that writes that file.

It runs ``scripts/demo_trust_plane.py`` (the same proof ``make prove-trust-plane``
runs) against a throwaway local SQLite gateway with the demo signing key,
records every HTTP exchange the demo makes, and keeps the ones the page
shows. It then runs the SDK's offline verifier twice: once on the portable
receipt the demo produced, and once on the live receipt published at
``site/proof/receipt.json`` — that second output is what the proof section
prints, so it has to come from the real CLI too.

    python scripts/record_site_transcript.py          # rewrite the transcript
    python scripts/record_site_transcript.py --check  # fail if it is stale

``--check`` re-records and compares everything except the fields that change
on every run (ids, timestamps, hashes, signatures), so CI can tell "someone
edited the JSON by hand" from "the demo ran again".

Secrets never reach the file: the operator key and the minted agent key are
replaced with placeholders before anything is written.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import hashlib
import io
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "b2a_sdk" / "src"))

import demo_trust_plane as demo  # noqa: E402  (configures env on import)

TRANSCRIPT = ROOT / "site" / "proof" / "transcript.json"
LIVE_RECEIPT = ROOT / "site" / "proof" / "receipt.json"
LIVE_KEYS = ROOT / "site" / "proof" / "trust-keys.json"
LIVE_ISSUER = "https://api.thisisatest.tech"

OPERATOR_KEY_PLACEHOLDER = "$OPERATOR_API_KEY"
AGENT_KEY_PLACEHOLDER = "$AGENT_API_KEY"

#: Fields whose values legitimately differ between two honest recordings.
VOLATILE_KEYS = {
    "receipt_id",
    "permit_id",
    "wallet_id",
    "issuer_wallet_id",
    "subject_wallet_id",
    "subject_key_id",
    "key_id",
    "ledger_entry_id",
    "entry_id",
    "audit_event_id",
    "dispatch_attempt_id",
    "idempotency_record_id",
    "created_at",
    "expires_at",
    "issued_at",
    "timestamp",
    "request_hash",
    "response_hash",
    "payload_hash",
    "signature",
    "signing_input",
    "chain_hash",
    "previous_hash",
    "recorded_at",
    "balance_after",
    "balance_before",
}


class Recording:
    """Every HTTP exchange the demo makes, in order."""

    def __init__(self) -> None:
        self.exchanges: list[dict[str, Any]] = []
        self.secrets: list[str] = [demo.ADMIN_KEY]

    def note(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: Any,
        status: int,
        response: Any,
    ) -> None:
        """Append one exchange, and remember any API key the response minted."""
        if isinstance(response, dict) and isinstance(response.get("api_key"), str):
            self.secrets.append(response["api_key"])
        self.exchanges.append(
            {
                "method": method,
                "path": path,
                "headers": dict(headers),
                "body": copy.deepcopy(body),
                "status": status,
                "response": copy.deepcopy(response),
            }
        )

    def find(self, method: str, path: str, *, nth: int = 0, body_id: str | None = None):
        """Return the nth exchange matching method, path (sans query) and JSON-RPC id."""
        matches = [
            exchange
            for exchange in self.exchanges
            if exchange["method"] == method
            and exchange["path"].split("?")[0] == path
            and (body_id is None or (exchange["body"] or {}).get("id") == body_id)
        ]
        if len(matches) <= nth:
            raise SystemExit(
                f"demo made no {method} {path} exchange #{nth}"
                + (f" with id {body_id}" if body_id else "")
            )
        return matches[nth]


def _record(recording: Recording) -> None:
    """Wrap the demo's HTTP helpers so every exchange lands in the recording."""

    async def post_json(client, path, *, headers, json_body, expected_status):
        """The demo's POST helper, with the exchange recorded."""
        response = await client.post(path, headers=headers, json=json_body)
        demo.require(
            response.status_code == expected_status,
            f"{path} returned {response.status_code}: {response.text}",
        )
        payload = response.json()
        recording.note("POST", path, headers, json_body, response.status_code, payload)
        return payload

    async def get_json(client, path, *, headers, expected_status):
        """The demo's GET helper, with the exchange recorded."""
        response = await client.get(path, headers=headers)
        demo.require(
            response.status_code == expected_status,
            f"{path} returned {response.status_code}: {response.text}",
        )
        payload = response.json()
        recording.note("GET", path, headers, None, response.status_code, payload)
        return payload

    demo.post_json = post_json
    demo.get_json = get_json


def _redact(value: Any, secrets: list[str]) -> Any:
    """Replace every recorded secret, wherever it appears in string values."""
    if isinstance(value, str):
        for secret in secrets:
            if secret == demo.ADMIN_KEY:
                value = value.replace(secret, OPERATOR_KEY_PLACEHOLDER)
            else:
                value = value.replace(secret, AGENT_KEY_PLACEHOLDER)
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()}
    return value


def _request_line(exchange: dict[str, Any]) -> str:
    """The exchange as one line a reader could paste, with the key redacted."""
    headers = exchange["headers"]
    parts = [f"{exchange['method']} {exchange['path']}"]
    if "X-API-Key" in headers:
        parts.append("X-API-Key: " + headers["X-API-Key"])
    if "Idempotency-Key" in headers:
        parts.append("Idempotency-Key: " + headers["Idempotency-Key"])
    return "\n".join(parts)


def _verify_cli(
    bundle_path: Path, keys_path: Path, issuer: str | None
) -> dict[str, Any]:
    """Run the SDK's offline verifier exactly as a visitor would, and keep its output.

    ``issuer`` is the ``--expect-issuer`` pin. The live receipt names its
    issuer and is pinned; the local demo gateway has no issuer configured, so
    its bundle is verified unpinned, which is what a visitor running the demo
    would do too.
    """
    from b2a_sdk import verify_cli

    args = ["--bundle", str(bundle_path), "--keys", str(keys_path)]
    if issuer:
        args += ["--expect-issuer", issuer]
    # main() returns the exit code (0 verified, 1 invalid, 2 undetermined)
    # and prints a failed verdict to stderr, so both streams are kept: the
    # recorded output is whatever a visitor would have seen on their screen.
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = int(verify_cli.main(args))
    output = (stdout.getvalue() + stderr.getvalue()).rstrip("\n")
    command = f"b2a-verify-receipt --bundle {bundle_path.name} --keys {keys_path.name}"
    if issuer:
        command += f" \\\n  --expect-issuer {issuer}"
    return {"command": command, "output": output, "exit_code": exit_code}


def _pick(mapping: dict[str, Any], keys: list[str]) -> list[list[str]]:
    """The named keys of a response as display rows, in the order given."""
    lines = []
    for key in keys:
        if key in mapping:
            lines.append([key, _fmt(mapping[key])])
    return lines


def _fmt(value: Any) -> str:
    """Render a response value the way a reader wants to see it.

    The API serialises Decimals as ``25.00000000`` and timestamps with
    microseconds; the page shows ``25`` and seconds. The JSON the page links
    to keeps the raw values — this only shapes the excerpt.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (list, dict)):
        return json.dumps(value, separators=(", ", ": "))
    text = str(value)
    if re.fullmatch(r"-?\d+\.\d+", text):
        text = text.rstrip("0").rstrip(".") or "0"
    text = re.sub(r"(T\d{2}:\d{2}:\d{2})\.\d+", r"\1", text)
    return text


def build_transcript(recording: Recording, summary: dict[str, Any]) -> dict[str, Any]:
    """Project the recording into the steps the page shows, with their copy."""
    tools = recording.find("GET", "/mcp/tools.json")
    permit = recording.find("POST", "/v1/permits")
    invoke = recording.find("POST", "/mcp/messages", body_id="demo-call-1", nth=0)
    replay = recording.find("POST", "/mcp/messages", body_id="demo-call-1", nth=1)
    ledger_after_replay = recording.find(
        "GET", f"/v1/billing/ledger/{summary['agent_wallet_id']}", nth=1
    )
    denial = recording.find("POST", "/mcp/messages", body_id="demo-denial-1", nth=0)
    audit = recording.find("POST", "/v1/audit/verify-chain", nth=0)
    portable = recording.find(
        "GET", f"/v1/receipts/{summary['success_receipt_id']}/portable"
    )

    allowed = next(
        (
            tool
            for tool in tools["response"]["tools"]
            if tool["name"] == demo.ALLOWED_TOOL
        ),
        None,
    )
    if allowed is None:
        raise SystemExit(f"/mcp/tools.json does not list {demo.ALLOWED_TOOL}")
    # The manifest carries cost and permit metadata under MCP-style
    # annotations, not at the top level of the tool entry.
    allowed_annotations = allowed.get("annotations") or {}
    if (
        not isinstance(allowed_annotations, dict)
        or "creditsPerCall" not in allowed_annotations
    ):
        raise SystemExit(
            f"/mcp/tools.json entry for {demo.ALLOWED_TOOL} carries no cost annotation"
        )
    receipt = invoke["response"]["result"]["receipt"]
    replay_receipt = replay["response"]["result"]["receipt"]
    denial_error = denial["response"]["error"]
    denial_receipt = denial_error["data"]["receipt"]
    debits = [
        entry
        for entry in ledger_after_replay["response"]["entries"]
        if entry.get("service_category") == "agent_comms"
        and demo.ALLOWED_TOOL in entry.get("description", "")
    ]

    with tempfile.TemporaryDirectory() as tmp:
        bundle_path = Path(tmp) / "receipt.json"
        keys_path = Path(tmp) / "trust-keys.json"
        bundle_path.write_text(json.dumps(portable["response"], indent=2))
        key_document = recording.find("GET", "/.well-known/trust-keys.json")["response"]
        keys_path.write_text(json.dumps(key_document, indent=2))
        local_verification = _verify_cli(bundle_path, keys_path, None)
    if local_verification["exit_code"] != 0 or not local_verification[
        "output"
    ].startswith("VERIFIED"):
        raise SystemExit(
            "the demo's receipt did not verify offline; refusing to record a "
            f"transcript that would show it:\n{local_verification['output']}"
        )

    steps = [
        {
            "id": "discover",
            "loop": "01 · Discover",
            "title": "The agent reads the manifest.",
            "request": _request_line(tools),
            "response": _pick(allowed, ["name"])
            + _pick(
                allowed_annotations, ["creditsPerCall", "unitName", "requirePermit"]
            ),
            "note": "Which tools exist and what each call costs. Discovery is public; nothing here can be invoked yet.",
        },
        {
            "id": "authorize",
            "loop": "02 · Authenticate → 03 · Authorize",
            "title": "The operator issues one scoped permit.",
            "request": _request_line(permit),
            "response": _pick(
                permit["response"],
                ["permit_id", "allowed_tools", "max_credits", "expires_at", "key_id"],
            ),
            "note": "One tool, one agent identity, a budget, an expiry, signed by the operator's key. The agent cannot mint this for itself.",
        },
        {
            "id": "invoke",
            "loop": "04 · Invoke → 05 · Meter → 06 · Receipt",
            "title": "The call executes and is charged once.",
            "request": _request_line(invoke),
            "response": _pick(
                receipt,
                [
                    "receipt_id",
                    "outcome",
                    "credits_charged",
                    "ledger_entry_id",
                    "permit_id",
                ],
            ),
            "note": "The gateway dispatches, debits the scoped budget, and returns a signed receipt that names the permit and the ledger entry.",
        },
        {
            "id": "replay",
            "loop": "05 · Meter, again",
            "title": "The same idempotency key comes back.",
            "request": _request_line(replay),
            "response": _pick(
                replay_receipt, ["receipt_id", "outcome", "credits_charged"]
            )
            + [["ledger debits for this tool", str(len(debits))]],
            "note": "Same receipt id, no second dispatch, no second debit. A timed-out client can retry without fear.",
        },
        {
            "id": "deny",
            "loop": "08 · Govern",
            "title": "An out-of-scope tool is refused at the boundary.",
            "request": _request_line(denial),
            "response": [["error", denial_error["message"]]]
            + _pick(denial_receipt, ["receipt_id", "outcome", "ledger_entry_id"]),
            "note": "The permit named one tool. Asking for another is denied before dispatch, receipted as a denial, and never charged.",
        },
        {
            "id": "audit",
            "loop": "07 · Audit",
            "title": "The ledger's event chain still verifies.",
            "request": _request_line(audit),
            "response": _pick(audit["response"], ["valid", "checked_events"]),
            "note": "Every event is hash-chained to the one before it. Edit a stored row and the chain breaks, which the demo also proves.",
        },
        {
            "id": "verify",
            "loop": "06 · Receipt, offline",
            "title": "The receipt verifies with no credential and no callback.",
            "request": local_verification["command"],
            "output": local_verification["output"],
            "note": "The SDK verifier checks the Ed25519 signature against the published key set. It never imports the gateway.",
        },
    ]

    # One read each of the published receipt and key set feeds the verifier,
    # the claims, and the digests, so none of them can describe a different
    # version of either file if one is replaced while this runs. The verifier
    # sees snapshots of those bytes under the same file names, so the
    # recorded command reads the same.
    live_bundle_bytes = LIVE_RECEIPT.read_bytes()
    live_keys_bytes = LIVE_KEYS.read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / LIVE_RECEIPT.name
        snapshot.write_bytes(live_bundle_bytes)
        keys_snapshot = Path(tmp) / LIVE_KEYS.name
        keys_snapshot.write_bytes(live_keys_bytes)
        live_verification = _verify_cli(snapshot, keys_snapshot, LIVE_ISSUER)
    live_claims = json.loads(
        json.loads(live_bundle_bytes.decode("utf-8"))["signing_input"]
    )

    return {
        "schema_version": "1.0",
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recorded_by": "python scripts/record_site_transcript.py",
        "source": {
            "proof": "make prove-trust-plane (scripts/demo_trust_plane.py)",
            "gateway": "throwaway local SQLite gateway, real FastAPI routers",
            "signing_key_id": summary["signing_key_id"],
            "label": "Recorded from a local gateway run, not the live API. Every line is a real request or a real response.",
        },
        "summary": {
            "permit_id": summary["permit_id"],
            "receipt_id": summary["success_receipt_id"],
            "replay_receipt_id": summary["replay_receipt_id"],
            "denial_reason": summary["denial_reason"],
            "offline_verified": summary["offline_verified"],
        },
        "steps": steps,
        "live_receipt_verification": {
            "receipt_id": live_claims["receipt_id"],
            # The exact bytes the verdict was produced from. The build checks
            # this against the published file, so a receipt.json edited or
            # republished after recording (even under the same id) cannot
            # ship with this verdict beside it.
            "bundle_sha256": hashlib.sha256(live_bundle_bytes).hexdigest(),
            # And the key set it was checked against (site/proof/trust-keys.json):
            # a rotated or edited key file after recording would leave a verdict
            # beside a command that no longer reproduces it. The field is named
            # for the document, not the keys, so the secret scanner does not
            # read a public digest as a credential.
            "trust_document_sha256": hashlib.sha256(live_keys_bytes).hexdigest(),
            **live_verification,
        },
    }


async def record() -> tuple[dict[str, Any], list[str]]:
    """Run the demo, project it, redact it; return the transcript and its secrets.

    The secrets come back alongside so the caller can prove none survived
    redaction before anything is written.
    """
    recording = Recording()
    _record(recording)
    silent = io.StringIO()
    with contextlib.redirect_stdout(silent):
        summary = await demo.run_demo(json_output=True)
    transcript = build_transcript(recording, summary)
    return _redact(transcript, recording.secrets), list(recording.secrets)


def _stable(value: Any) -> Any:
    """Strip the fields that differ between two honest recordings."""
    if isinstance(value, dict):
        return {
            key: _stable(item)
            for key, item in value.items()
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_stable(item) for item in value]
    if isinstance(value, str):
        # ids and timestamps also appear inside rendered response lines
        value = re.sub(
            r"\b(rcpt|permit|agt|spn|key_|dsp|idm|audit)-?[0-9a-f]{8,}\b", "<id>", value
        )
        value = re.sub(r"\d{4}-\d{2}-\d{2}T[0-9:.+]+", "<time>", value)
        value = re.sub(r"[0-9a-f]{32,}", "<hex>", value)
        value = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "<uuid>",
            value,
        )
    return value


def main() -> int:
    """Record the transcript, or with --check compare a fresh recording to it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail if the committed transcript is stale"
    )
    args = parser.parse_args()

    transcript, secrets = asyncio.run(record())
    rendered = json.dumps(transcript, indent=2, sort_keys=True) + "\n"
    # Every value redaction targeted, plus the demo signing key, which the
    # demo never sends over HTTP but which must never leak either.
    for secret in (*secrets, demo.DEMO_PRIVATE_KEY_B64):
        if secret and secret in rendered:
            raise SystemExit("refusing to write a transcript that contains a secret")

    if args.check:
        if not TRANSCRIPT.exists():
            print(f"{TRANSCRIPT} is missing; run without --check to record it")
            return 1
        committed = json.loads(TRANSCRIPT.read_text(encoding="utf-8"))
        if _stable(committed) != _stable(transcript):
            print(f"{TRANSCRIPT} is stale or hand-edited; re-run without --check")
            return 1
        print("transcript is current")
        return 0

    TRANSCRIPT.write_text(rendered, encoding="utf-8")
    print(f"wrote {TRANSCRIPT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
