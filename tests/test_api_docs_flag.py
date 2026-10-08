"""ENABLE_API_DOCS flag: unmount interactive docs for customer pilots.

Swagger UI (/docs), ReDoc (/redoc), and /openapi.json are mounted
unauthenticated on the same origin as the API. Operators set
ENABLE_API_DOCS=false on pilots and internet-reachable deployments to
shrink the recon surface; the agent manifest must then stop advertising
those routes instead of pointing at 404s.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from app.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent

_PROBE = (
    "import json; "
    "from app.main import app; "
    "from app.routers.well_known import get_agent_first_metadata; "
    "meta = get_agent_first_metadata(); "
    "print(json.dumps({"
    "'docs_url': app.docs_url, "
    "'redoc_url': app.redoc_url, "
    "'openapi_url': app.openapi_url, "
    "'doc_routes': sorted("
    "r.path for r in app.routes "
    "if getattr(r, 'path', '') in ('/docs', '/redoc', '/openapi.json')), "
    "'interactive_docs_url': "
    "meta['human_observability']['interactive_docs_url'], "
    "'manifest_redoc_url': meta['human_observability']['redoc_url']"
    "}))"
)


def _probe_with_env(extra_env: dict[str, str]) -> dict:
    env = dict(os.environ)
    env.update(extra_env)
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_docs_mounted_by_default() -> None:
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"


def test_docs_disabled_unmounts_routes_and_manifest_links() -> None:
    state = _probe_with_env({"ENABLE_API_DOCS": "false"})
    assert state["docs_url"] is None
    assert state["redoc_url"] is None
    assert state["openapi_url"] is None
    assert state["doc_routes"] == []
    assert state["interactive_docs_url"] is None
    assert state["manifest_redoc_url"] is None


def test_docs_enabled_keeps_routes_and_manifest_links() -> None:
    state = _probe_with_env({"ENABLE_API_DOCS": "true"})
    assert state["docs_url"] == "/docs"
    assert state["interactive_docs_url"] == "/docs"
    assert state["manifest_redoc_url"] == "/redoc"
    assert state["doc_routes"] == ["/docs", "/openapi.json", "/redoc"]
