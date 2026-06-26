from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_demo_trust_plane_script_proves_core_loop():
    result = subprocess.run(
        [sys.executable, "scripts/demo_trust_plane.py", "--json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    proof = json.loads(result.stdout)
    assert [item["stage"] for item in proof["control_loop_verified"]] == [
        "discover",
        "authenticate",
        "authorize",
        "invoke",
        "meter",
        "receipt",
        "audit",
        "govern",
    ]
    assert all(item["verified"] is True for item in proof["control_loop_verified"])
    assert proof["permit_id"].startswith("permit-")
    assert proof["paid_pilot_tool"] == "agent-comms-send"
    assert proof["message_id"]
    assert proof["payload_hash"]
    assert proof["success_receipt_id"].startswith("rcpt-")
    assert proof["signing_key_id"] == "demo-ed25519"
    assert proof["inspected_receipts"] == 1
    assert proof["inspected_audit_events"] >= 1
    assert proof["replay_receipt_id"] == proof["success_receipt_id"]
    assert proof["denial_receipt_id"].startswith("rcpt-")
    assert proof["denial_replay_receipt_id"] == proof["denial_receipt_id"]
    assert proof["denial_reason"] == "permit_tool_not_allowed"
    assert proof["ungoverned_denial_reason"] == "permit_required"
    assert proof["cross_wallet_status"] == 403
    assert proof["evidence_bundle_valid"] is True
    assert proof["tampered_receipt_valid"] is False
    assert proof["tampered_receipt_reason"] == "receipt_signature_invalid"
    assert proof["tampered_audit_valid"] is False
    assert proof["audit_chain_checked_events"] >= 1
