from __future__ import annotations

import json
import os
import subprocess
import sys


_ROUTE_DUMP_SCRIPT = """
import json
from fastapi.routing import APIRoute
from app.main import app
print(json.dumps(sorted(route.path for route in app.routes if isinstance(route, APIRoute))))
"""


def _routes_for_mode(mode: str) -> set[str]:
    env = os.environ.copy()
    env["API_SURFACE_MODE"] = mode
    env.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    env.setdefault("VALID_API_KEYS", "test-key")
    result = subprocess.run(
        [sys.executable, "-c", _ROUTE_DUMP_SCRIPT],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return set(json.loads(result.stdout))


def test_trust_plane_mode_mounts_core_routes_only():
    routes = _routes_for_mode("trust_plane")

    required_exact = {
        "/mcp/messages",
        "/mcp/tools.json",
        "/v1/audit/events",
        "/v1/trust/readiness",
        "/health/dependencies",
    }
    for path in required_exact:
        assert path in routes

    for prefix in ("/v1/permits", "/v1/receipts"):
        assert any(path.startswith(prefix) for path in routes)

    absent = {
        "/v1/awi/sessions",
        "/v1/telemetry/events",
        "/v1/sandbox/environments",
        "/v1/oracle/crawl",
        "/.well-known/awi.json",
    }
    assert routes.isdisjoint(absent)


def test_full_mode_mounts_representative_proof_routes():
    routes = _routes_for_mode("full")

    proof_routes = {
        "/v1/awi/sessions",
        "/v1/telemetry/events",
        "/v1/sandbox/environments",
        "/v1/oracle/crawl",
        "/.well-known/awi.json",
    }
    assert proof_routes <= routes


def test_invalid_surface_mode_fails_app_import():
    env = os.environ.copy()
    env["API_SURFACE_MODE"] = "everything"
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "API_SURFACE_MODE" in result.stderr
