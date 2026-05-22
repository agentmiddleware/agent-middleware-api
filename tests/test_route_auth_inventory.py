"""
Route auth inventory guard.

Fails if any state-changing route (POST/PUT/PATCH/DELETE) is reachable without
an authentication dependency. This is a structural regression test: it does not
exercise the routes, it inspects the resolved FastAPI dependency graph.

When you add a new state-changing route, it must either depend on
``get_auth_context`` / ``verify_api_key`` (directly or transitively) or be
added to ``PUBLIC_STATE_CHANGING_ROUTES`` below with a documented reason.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from app.core.auth import get_auth_context, verify_api_key
from app.main import app

# Routes intentionally reachable without an API key. Each entry needs a reason
# because every addition widens the unauthenticated attack surface.
PUBLIC_STATE_CHANGING_ROUTES: dict[tuple[str, str], str] = {
    ("POST", "/v1/planner/optimize"): (
        "Stateless advisory action-selection. No side effects, no wallet "
        "mutation; safe to expose unauthenticated by design."
    ),
    ("POST", "/v1/webhooks/stripe"): (
        "Authenticated by Stripe webhook signature (STRIPE_WEBHOOK_SECRET), "
        "not by the X-API-Key scheme. Rejects missing/invalid signatures."
    ),
    ("POST", "/v1/webhooks/stripe/identity"): (
        "Authenticated by Stripe webhook signature (STRIPE_WEBHOOK_SECRET), "
        "not by the X-API-Key scheme. Rejects missing/invalid signatures."
    ),
}

_AUTH_CALLS = {get_auth_context, verify_api_key}


def _route_has_auth(route: APIRoute) -> bool:
    """True if an auth dependency appears anywhere in the route's dependant tree."""
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False

    seen: set[int] = set()
    stack = [dependant]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if getattr(node, "call", None) in _AUTH_CALLS:
            return True
        stack.extend(node.dependencies)
    return False


def _state_changing_routes() -> list[tuple[str, str, APIRoute]]:
    rows: list[tuple[str, str, APIRoute]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = (route.methods or set()) & {"POST", "PUT", "PATCH", "DELETE"}
        for method in sorted(methods):
            rows.append((method, route.path, route))
    return rows


def test_all_state_changing_routes_require_auth():
    unauthenticated: list[str] = []
    for method, path, route in _state_changing_routes():
        if (method, path) in PUBLIC_STATE_CHANGING_ROUTES:
            continue
        if not _route_has_auth(route):
            unauthenticated.append(f"{method} {path}")

    assert not unauthenticated, (
        "State-changing routes missing an auth dependency:\n  "
        + "\n  ".join(sorted(unauthenticated))
        + "\n\nEither add get_auth_context/verify_api_key as a dependency, or "
        "register the route in PUBLIC_STATE_CHANGING_ROUTES with a reason."
    )


def test_public_allowlist_has_no_stale_entries():
    """Every allowlisted route must still exist, so the list can't rot."""
    live = {(m, p) for m, p, _ in _state_changing_routes()}
    stale = [
        f"{m} {p}" for (m, p) in PUBLIC_STATE_CHANGING_ROUTES if (m, p) not in live
    ]
    assert not stale, f"Stale PUBLIC_STATE_CHANGING_ROUTES entries: {stale}"
