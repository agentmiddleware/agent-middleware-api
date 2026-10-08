"""The visible MCP example must stay honest and runnable.

Regression coverage for the marketplace finding that example scripts
advertise ``serve`` and ``register`` flags without saying what they
need: ``--register`` is local only (it prints decorated tool metadata
and contacts no server), while ``--list``, ``--generate``, and
``--serve`` need a running gateway. These tests run the script as a
prospect would and assert the honest wording plus a zero exit code for
the server-free path.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "examples" / "mcp_tool_example.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_register_is_local_only_and_succeeds_without_a_server() -> None:
    completed = _run("--register")

    assert completed.returncode == 0, completed.stderr
    assert "no backend registration" in completed.stdout.lower()
    for service_id in ("data-processor", "url-summarizer", "image-generator"):
        assert service_id in completed.stdout


def test_help_states_which_flags_need_a_gateway() -> None:
    completed = _run("--help")

    assert completed.returncode == 0, completed.stderr
    assert "needs B2A_API_URL" in completed.stdout
    assert "legacy standalone MCP server" in completed.stdout
