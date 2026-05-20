from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_regengine_bridge_demo_proves_governed_operator_review_loop():
    result = subprocess.run(
        [sys.executable, "scripts/demo_regengine_bridge.py", "--assert", "--json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    proof = json.loads(result.stdout)
    assert proof["status"] == "pass"
    assert proof["tool"] == "regengine.agent_reviews.list"
    assert proof["discovery"]["requires_permit"] is True
    assert proof["invoke"]["artifact_id"] == "artifact-demo-001"
    assert proof["invoke"]["receipt_id"].startswith("rcpt-")
    assert proof["receipt"]["valid"] is True
    assert proof["replay"]["same_receipt"] is True
    assert proof["replay"]["fetch_calls_after_replay"] == 1
    assert proof["ledger"]["matching_debits"] == 1
    assert proof["denial"]["reason"] == "permit_tool_not_allowed"
    assert proof["denial"]["ledger_entry_id"] is None
    assert proof["denial"]["fetch_calls_after_denial"] == 1
    assert proof["audit"]["chain"]["valid"] is True
