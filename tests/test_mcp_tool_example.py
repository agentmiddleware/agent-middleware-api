"""Tests for examples/mcp_tool_example.py buyer-facing honesty.

The buyer review found the MCP tool example misleading: --register implied
server enrollment it never performed, and --serve launched a shim whose
invoke path targets a route the gateway does not expose
(/v1/billing/services/{id}/invoke). These tests pin the fixed behavior and
need no running server.
"""

import subprocess
import sys
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "mcp_tool_example.py"


def run_example(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(EXAMPLE), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_serve_is_retired_with_guidance():
    proc = run_example("--serve")
    assert proc.returncode == 2
    assert "retired" in proc.stderr
    assert "quickstart" in proc.stderr


def test_register_states_local_only():
    proc = run_example("--register")
    assert proc.returncode == 0
    assert "not enrolled on any server" in proc.stdout.lower() or (
        "local" in proc.stdout.lower() and "server" in proc.stdout.lower()
    )
    assert "partner-first-tool-runbook" in proc.stdout


def test_help_lists_supported_flags():
    proc = run_example("--help")
    assert proc.returncode == 0
    assert "--register" in proc.stdout
    assert "--serve" in proc.stdout
