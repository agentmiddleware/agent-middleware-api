from __future__ import annotations

from fastapi.routing import APIRoute

from app.main import app
from tests.conftest import iter_routes


PUBLIC_PATH_PREFIXES = (
    "/docs",
    "/redoc",
    "/llm.txt",
    "/static",
    "/.well-known",
)
PUBLIC_PATHS = {"/", "/openapi.json", "/mcp/tools", "/mcp/tools.json"}


def test_state_changing_core_trust_routes_have_auth_dependencies():
    checked = 0
    for route in iter_routes(app.routes):
        if not isinstance(route, APIRoute):
            continue
        if not (set(route.methods or set()) & {"POST", "PUT", "PATCH", "DELETE"}):
            continue
        if route.path in PUBLIC_PATHS:
            continue
        if route.path.startswith(PUBLIC_PATH_PREFIXES):
            continue
        dependency_names = {
            getattr(dependency.call, "__name__", "")
            for dependency in route.dependant.dependencies
        }
        if route.path.startswith(("/v1/permits", "/v1/receipts", "/v1/audit", "/mcp")):
            checked += 1
            assert "get_auth_context" in dependency_names
    assert checked >= 4
