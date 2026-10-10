"""Gate: every money-moving route carries the idempotency marker.

Foundational guard for the class where idempotency keys are optional on
money writes. ``app/idempotency_gate.py`` provides the
``@requires_idempotency`` marker. This test enumerates every FastAPI
route that moves money (charge, refund, transfer, top-up, x402 settle,
permit reserve) across the real router objects and fails if any lacks
the marker, so a new money route cannot land without one.

The enforcement test below it records which of those routes already
require a key. Routes that still accept a retry as a new money movement
are strict xfail entries: they pass as expected failures today, and
the suite goes red the moment one starts enforcing, which forces the
entry to be updated.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from app.idempotency_gate import MONEY_ROUTE_REGISTRY, marker_of
from app.routers import billing, permits, webhooks, x402

SCANNED_ROUTERS = (
    billing.router,
    billing.expansion_router,
    permits.router,
    permits.action_router,
    webhooks.router,
    x402.router,
)

# Full "METHOD path" labels for the money-moving routes this gate covers.
EXPECTED_MONEY_ROUTES = {
    "POST /v1/billing/charge": "charge",
    "POST /v1/billing/dry-run/charge": "charge",
    "POST /v1/billing/dry-run/session/{session_id}/commit": "charge",
    "POST /v1/billing/transfer": "transfer",
    "POST /v1/billing/top-up": "top-up",
    "POST /v1/billing/top-up/prepare": "top-up",
    "POST /v1/webhooks/stripe": "refund",
    "POST /v1/x402/settle": "x402 settle",
    "POST /v1/permits": "permit reserve",
    "POST /v1/action-permits": "permit reserve",
}

# True when a retry cannot repeat the money effect. The False entries are
# the follow-up list: routes that still take an optional key or none.
ENFORCEMENT = {
    "POST /v1/billing/charge": False,
    "POST /v1/billing/dry-run/charge": True,
    "POST /v1/billing/dry-run/session/{session_id}/commit": True,
    "POST /v1/billing/transfer": False,
    "POST /v1/billing/top-up": True,
    "POST /v1/billing/top-up/prepare": False,
    "POST /v1/webhooks/stripe": True,
    "POST /v1/x402/settle": True,
    "POST /v1/permits": True,
    "POST /v1/action-permits": True,
}

# Substrings that flag a money-moving path in the forward scan, so a new
# route matching one cannot land unmarked. Webhook and permit-reserve
# paths carry no such substring and are pinned by EXPECTED_MONEY_ROUTES.
MONEY_PATH_SUBSTRINGS = (
    "charge",
    "commit",
    "transfer",
    "top-up",
    "top_up",
    "settle",
    "refund",
)


def _post_endpoints() -> dict[str, object]:
    found: dict[str, object] = {}
    for router in SCANNED_ROUTERS:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            if "POST" not in route.methods:
                continue
            # APIRouter already folds its own prefix into route.path, so
            # only prepend when the path is still relative.
            if route.path.startswith(router.prefix):
                full = route.path
            else:
                full = router.prefix + route.path
            full = full.rstrip("/") or "/"
            found.setdefault(f"POST {full}", route.endpoint)
    return found


def test_covered_money_routes_exist_and_are_marked():
    endpoints = _post_endpoints()
    for route_key in sorted(EXPECTED_MONEY_ROUTES):
        endpoint = endpoints.get(route_key)
        assert endpoint is not None, f"{route_key} is not mounted"
        marker = marker_of(endpoint)
        assert marker is not None, f"{route_key} lacks the marker"
        assert marker["route_key"] == route_key
        assert marker["endpoint"] == endpoint.__name__


def test_registry_matches_covered_routes():
    assert set(MONEY_ROUTE_REGISTRY) == set(EXPECTED_MONEY_ROUTES)
    for route_key, record in MONEY_ROUTE_REGISTRY.items():
        assert record["enforced"] is ENFORCEMENT[route_key], route_key


def test_new_money_routes_cannot_land_unmarked():
    unmarked = []
    for route_key, endpoint in sorted(_post_endpoints().items()):
        path = route_key.split(" ", 1)[1]
        looks_like_money = path in {
            key.split(" ", 1)[1] for key in EXPECTED_MONEY_ROUTES
        } or any(part in path for part in MONEY_PATH_SUBSTRINGS)
        if looks_like_money and marker_of(endpoint) is None:
            unmarked.append(route_key)
    assert unmarked == [], f"money routes without the marker: {unmarked}"


def _enforcement_case(route_key: str):
    if ENFORCEMENT[route_key]:
        return pytest.param(route_key)
    return pytest.param(
        route_key,
        marks=pytest.mark.xfail(
            strict=True,
            reason="route still accepts a retry as a new money movement",
        ),
    )


@pytest.mark.parametrize(
    "route_key", [_enforcement_case(key) for key in sorted(ENFORCEMENT)]
)
def test_money_route_enforces_idempotency(route_key):
    marker = MONEY_ROUTE_REGISTRY[route_key]
    assert marker["enforced"] is True, (
        f"{route_key} does not enforce a key yet: {marker['mechanism']}"
    )
