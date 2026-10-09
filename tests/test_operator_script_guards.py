"""Static guards for operator shell scripts and the TS SDK manifest.

These assert the exact guard lines the audit asked for, plus a syntax check,
so a regression that drops them fails loudly here instead of in an incident.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _text(name: str) -> str:
    return (REPO_ROOT / name).read_text()


def _syntax_ok(name: str) -> None:
    result = subprocess.run(
        ["bash", "-n", str(REPO_ROOT / name)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


@needs_bash
def test_human_preflight_sets_pipeline_guards():
    body = _text("scripts/human_preflight.sh")

    assert "pipefail" in body
    _syntax_ok("scripts/human_preflight.sh")


@needs_bash
def test_boot_controlled_locks_down_signing_seed():
    body = _text("scripts/invariant_attacks/boot_controlled.sh")

    assert "umask 077" in body
    assert 'chmod 600 "$SEED_FILE"' in body
    _syntax_ok("scripts/invariant_attacks/boot_controlled.sh")


@needs_bash
def test_installer_never_pipes_download_into_shell():
    body = _text(".cursor/install.sh")

    assert "| sh" not in body
    assert 'test -s "$uv_installer"' in body
    _syntax_ok(".cursor/install.sh")


def test_typescript_sdk_pins_exact_versions():
    manifest = json.loads(_text("awi_sdk/typescript/package.json"))

    pinned = {
        **manifest["dependencies"],
        **manifest["devDependencies"],
    }
    for name in ("axios", "typescript", "@types/node"):
        version = pinned[name]
        assert version and version[0].isdigit(), (name, version)
