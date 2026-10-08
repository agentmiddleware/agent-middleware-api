"""CI guard for the documented one-command trial (docs/trial.md).

Runs the exact buyer command (``scripts/trial_run.py``) with throwaway
server state and asserts every documented observable: exit code 0, all
six stage lines, the passing summary, the kept receipt bundle plus key
set, and that the kept bundle verifies offline with the SDK verifier. A
final test tampers the kept bundle and requires the verifier to refuse
it, proving the verify stage actually checks the signature.

If docs/trial.md and the code disagree, this test is what breaks.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TRIAL_SCRIPT = REPO_ROOT / "scripts" / "trial_run.py"
STAGE_MARKERS = ("[1/6]", "[2/6]", "[3/6]", "[4/6]", "[5/6]", "[6/6]")
# Budgeted at five minutes for slow machines and cold dependency caches;
# a normal laptop finishes in about one.
TRIAL_TIMEOUT_SECONDS = 300


@pytest.fixture(scope="module")
def trial_run(tmp_path_factory):
    """Run the buyer command once; every test below inspects that run."""
    output_dir = tmp_path_factory.mktemp("trial-output")
    completed = subprocess.run(
        [sys.executable, str(TRIAL_SCRIPT), "--output-dir", str(output_dir)],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=TRIAL_TIMEOUT_SECONDS,
    )
    return completed, output_dir


def _verify(bundle_path: Path, keys_path: Path) -> subprocess.CompletedProcess:
    sdk_src = REPO_ROOT / "b2a_sdk" / "src"
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{sdk_src}{os.pathsep}{existing}" if existing else str(sdk_src)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "b2a_sdk.verify_cli",
            "--bundle",
            str(bundle_path),
            "--keys",
            str(keys_path),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_trial_exits_zero(trial_run) -> None:
    completed, _ = trial_run
    assert completed.returncode == 0, (
        f"trial exited {completed.returncode}\n"
        f"--- stdout ---\n{completed.stdout}\n"
        f"--- stderr ---\n{completed.stderr}"
    )


def test_trial_prints_every_stage(trial_run) -> None:
    completed, _ = trial_run
    for marker in STAGE_MARKERS:
        assert marker in completed.stdout, (
            f"stage marker {marker} missing from trial output:\n{completed.stdout}"
        )
    assert "Trial passed in 6 stages" in completed.stdout
    assert "VERIFIED" in completed.stdout


def test_trial_keeps_bundle_that_verifies_offline(trial_run) -> None:
    _, output_dir = trial_run
    bundle_path = output_dir / "receipt-bundle.json"
    keys_path = output_dir / "trust-keys.json"
    assert bundle_path.exists(), "trial kept no receipt-bundle.json"
    assert keys_path.exists(), "trial kept no trust-keys.json"
    signed = json.loads(json.loads(bundle_path.read_text())["signing_input"])
    assert signed["outcome"] == "success"
    assert signed["tool"] == "partner.notes.write"
    verified = _verify(bundle_path, keys_path)
    assert verified.returncode == 0, (
        f"kept bundle did not verify: {verified.stdout}{verified.stderr}"
    )


def test_tampered_bundle_does_not_verify(trial_run, tmp_path) -> None:
    """Flip one signed fact; the verifier must refuse the bundle."""
    _, output_dir = trial_run
    forged_path = tmp_path / "forged-receipt.json"
    bundle = json.loads((output_dir / "receipt-bundle.json").read_text())
    original = bundle["signing_input"]
    forged = original.replace('"outcome":"success"', '"outcome":"denied"')
    assert forged != original, "tamper did not change the signed bytes"
    bundle["signing_input"] = forged
    forged_path.write_text(json.dumps(bundle))
    refused = _verify(forged_path, output_dir / "trust-keys.json")
    assert refused.returncode != 0, "tampered bundle verified: fail-closed broken"
