#!/usr/bin/env python3
"""One-command local trial: permit to signed receipt to offline verify.

Boots the real quickstart-posture server on a free loopback port with
throwaway state, drives the core loop over HTTP as a self-provisioned
non-admin caller, verifies the receipt offline with the SDK verifier,
prints a short transcript, then stops the server and deletes the
throwaway state::

    make trial

Stages: boot -> key -> permit -> invoke -> receipt -> verify. Any stage
that breaks its invariant exits non-zero before the summary line, so a
passing run means every stage held.

The kept artifacts land in ``data/trial-run/``: the portable receipt
bundle, the issuer key set, and the exact verifier command to re-run by
hand. Nothing else persists: the database, the signing seed, the minted
key, and the server log are all deleted with the throwaway directory.

Loopback only by design: the run mints a credential and sends it on
every request, and self-provision exists only on dev-like postures.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SDK_SRC = ROOT / "b2a_sdk" / "src"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "trial-run"
GOVERNED_TOOL = "partner.notes.write"
# The quickstart dogfood tool bills a fixed 2 credits/call
# (DOGFOOD_CREDITS_PER_UNIT in app/services/dogfood_tool.py). Pinning it
# here means a server that regressed metering to 0 fails the trial instead
# of passing with a free receipt.
EXPECTED_CREDITS_PER_CALL = Decimal("2")
PERMIT_MAX_CREDITS = 10
BOOT_TIMEOUT_SECONDS = 120.0
# Kept artifacts: the receipt a stranger re-verifies, the key set they
# verify it against, and nothing credential-bearing.
ARTIFACTS = ("receipt-bundle.json", "trust-keys.json")


class TrialFailure(RuntimeError):
    pass


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _child_env(prepend: Path) -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{prepend}{os.pathsep}{existing}" if existing else str(prepend)
    return env


def boot_server(port: int, state_dir: Path, log_path: Path) -> subprocess.Popen:
    """Start the real quickstart entry point with throwaway state."""
    with log_path.open("wb") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "scripts" / "quickstart.py"),
                "--port",
                str(port),
                "--state-dir",
                str(state_dir),
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + BOOT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise TrialFailure(
                "server exited during boot; tail of "
                f"{log_path}:\n"
                + "\n".join(
                    log_path.read_text(encoding="utf-8", errors="replace").splitlines()[
                        -20:
                    ]
                )
            )
        try:
            if httpx.get(base_url + "/health", timeout=2).status_code == 200:
                return process
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise TrialFailure(
        f"server did not become healthy within {BOOT_TIMEOUT_SECONDS:.0f}s; "
        f"see {log_path}"
    )


def stop_server(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.send_signal(signal.SIGINT)
        process.wait(timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        try:
            process.terminate()
            process.wait(timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TrialFailure(message)


def verify_bundle(bundle_path: Path, keys_path: Path) -> str:
    """Verify an exported bundle offline; return the verifier's output.

    Raises TrialFailure unless the verifier exits 0. A tampered bundle
    exits 1 and fails here, which is the point of the stage.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "b2a_sdk.verify_cli",
            "--bundle",
            str(bundle_path),
            "--keys",
            str(keys_path),
        ],
        env=_child_env(SDK_SRC),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise TrialFailure(
            f"offline verification failed (exit {result.returncode}): "
            f"{result.stdout}{result.stderr}".strip()
        )
    return result.stdout


def run_trial(base_url: str, output_dir: Path, run_id: str) -> dict[str, str]:
    """Drive the trial stages over HTTP; return the summary facts."""
    # trust_env=False keeps the minted credential on the loopback host even
    # when the caller's shell exports proxy variables.
    with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as client:
        print(f"[1/6] boot      server is up at {base_url}")

        minted = client.post(
            "/v1/dev-keys/self-provision",
            json={"agent_id": f"trial-run-{run_id}"},
        )
        require(
            minted.status_code in (200, 201),
            f"self-provision refused ({minted.status_code}): {minted.text}",
        )
        identity = minted.json()
        client.headers["X-API-Key"] = identity["api_key"]
        print(
            f"[2/6] key       minted wallet-scoped key {identity['key_id']} "
            f"on wallet {identity['wallet_id']}"
        )

        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        permit = client.post(
            "/v1/permits",
            headers={"Idempotency-Key": f"trial-{run_id}-permit"},
            json={
                "issuer_wallet_id": identity["wallet_id"],
                "subject_wallet_id": identity["wallet_id"],
                "subject_key_id": identity["key_id"],
                "allowed_tools": [GOVERNED_TOOL],
                "scopes": [f"tool:{GOVERNED_TOOL}:invoke", "billing:charge"],
                "max_credits": PERMIT_MAX_CREDITS,
                "expires_at": expires_at,
            },
        )
        require(
            permit.status_code == 201,
            f"permit creation failed ({permit.status_code}): {permit.text}",
        )
        permit_id = permit.json()["permit_id"]
        print(
            f"[3/6] permit    {permit_id} allows {GOVERNED_TOOL}, "
            f"capped at {PERMIT_MAX_CREDITS} credits"
        )

        invoked = client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": "trial-1",
                "method": "tools/call",
                "params": {
                    "name": GOVERNED_TOOL,
                    "arguments": {"text": f"trial run {run_id}"},
                    "mcpContext": {
                        "wallet_id": identity["wallet_id"],
                        "permit_id": permit_id,
                        "idempotency_key": f"trial-{run_id}-note-1",
                    },
                },
            },
        ).json()
        require(
            "result" in invoked,
            f"governed invoke failed: {invoked.get('error')}",
        )
        receipt = invoked["result"]["receipt"]
        require(receipt["outcome"] == "success", "receipt outcome != success")
        require(bool(receipt["signature"]), "receipt is unsigned")
        require(
            receipt["ledger_entry_id"] is not None,
            "success receipt has no ledger entry",
        )
        charged = Decimal(str(receipt["credits_charged"]))
        require(
            charged == EXPECTED_CREDITS_PER_CALL,
            f"charged {charged} credits, expected {EXPECTED_CREDITS_PER_CALL}",
        )
        print(
            f"[4/6] invoke    {GOVERNED_TOOL} ran, receipt "
            f"{receipt['receipt_id']}, charged {charged}"
        )

        portable = client.get(f"/v1/receipts/{receipt['receipt_id']}/portable")
        require(
            portable.status_code == 200,
            f"portable receipt export failed ({portable.status_code})",
        )
        bundle_path = output_dir / "receipt-bundle.json"
        bundle_path.write_text(portable.text, encoding="utf-8")
        # The key set must be fetchable with no credential at all, or a
        # stranger could never verify what they were handed.
        keys_url = client.base_url.join(".well-known/trust-keys.json")
        keys = httpx.get(str(keys_url), timeout=30, trust_env=False)
        require(keys.status_code == 200, "trust-keys.json not served")
        keys_path = output_dir / "trust-keys.json"
        keys_path.write_text(keys.text, encoding="utf-8")
        print(f"[5/6] receipt   portable bundle exported to {bundle_path.name}")

        verifier_output = verify_bundle(bundle_path, keys_path)
        verified_line = verifier_output.splitlines()[0] if verifier_output else ""
        print(f"[6/6] verify    {verified_line}")

    return {
        "receipt_id": receipt["receipt_id"],
        "credits_charged": str(charged),
        "permit_id": permit_id,
        "wallet_id": identity["wallet_id"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Loopback port for the throwaway server (default: a free port).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Where to keep the receipt bundle and key set "
        f"(default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--keep-state",
        action="store_true",
        help="Keep the throwaway server state directory for debugging "
        "instead of deleting it (prints its path).",
    )
    args = parser.parse_args(argv)

    # quickstart.py always binds 127.0.0.1; the port is the only choice.
    port = args.port or _free_port()
    output_dir: Path = args.output_dir
    state_dir = Path(tempfile.mkdtemp(prefix="trial-run-state-"))
    log_path = state_dir / "server.log"
    process: subprocess.Popen | None = None
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        for name in ARTIFACTS:
            (output_dir / name).unlink(missing_ok=True)
        process = boot_server(port, state_dir, log_path)
        summary = run_trial(
            f"http://127.0.0.1:{port}", output_dir, run_id=state_dir.name[-8:]
        )
        print(
            f"\nTrial passed in 6 stages: permit {summary['permit_id']} "
            f"authorized one {GOVERNED_TOOL} call, charged "
            f"{summary['credits_charged']} credits, receipt "
            f"{summary['receipt_id']} verified offline."
            f"\nRe-verify by hand from {output_dir}:"
            f"\n  PYTHONPATH=b2a_sdk/src python -m b2a_sdk.verify_cli "
            f"--bundle {output_dir / 'receipt-bundle.json'} "
            f"--keys {output_dir / 'trust-keys.json'}"
        )
        return 0
    except TrialFailure as failure:
        print(f"\nTRIAL FAILED: {failure}", file=sys.stderr)
        return 1
    except httpx.HTTPError as network_error:
        print(f"\nTRIAL FAILED: HTTP error: {network_error}", file=sys.stderr)
        return 1
    finally:
        stop_server(process)
        if args.keep_state:
            print(f"[trial] throwaway state kept at {state_dir}")
        else:
            shutil.rmtree(state_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
