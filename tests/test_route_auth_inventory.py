from __future__ import annotations

from fastapi.routing import APIRoute

from app.main import app


PUBLIC_PATH_PREFIXES = (
    "/docs",
    "/redoc",
    "/llm.txt",
    "/static",
    "/.well-known",
)
PUBLIC_PATHS = {"/", "/openapi.json", "/mcp/tools", "/mcp/tools.json"}
CORE_STATE_CHANGING_PREFIXES = (
    "/v1/api-keys",
    "/v1/audit",
    "/v1/billing",
    "/v1/kyc",
    "/v1/permits",
    "/v1/planner",
    "/v1/policies",
    "/v1/receipts",
    "/v1/signing-keys",
    "/v1/trust",
    "/mcp",
)
AUTH_DEPENDENCIES = {"get_auth_context", "verify_api_key"}


def test_state_changing_core_trust_routes_have_auth_dependencies():
    checked = 0
    for route in app.routes:
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
        if route.path.startswith(CORE_STATE_CHANGING_PREFIXES):
            checked += 1
            assert dependency_names & AUTH_DEPENDENCIES, route.path
    assert checked >= 20
