"""Simulated-output labels on proof-surface endpoints.

Buyer-facing rule from the go-to-market review: any endpoint whose output is
simulated sample data (hash-derived statuses, canned device responses, sample
directories, placeholder diffs) must say so in its own summary or
description, so a demo reader never mistakes it for live behavior.

These tests read the router objects directly, so they need no mounted app,
no database, and no proof-surface flag.
"""

import pytest

from app.routers import broadcast, comms, iot, oracle, telemetry, telemetry_scope

# (router, path relative to the router prefix, HTTP method)
SIMULATED_ENDPOINTS = [
    (iot.router, "/devices/{device_id}/messages", "POST"),
    (iot.router, "/devices/{device_id}/subscribe", "POST"),
    (oracle.router, "/crawl", "POST"),
    (oracle.router, "/crawl/batch", "POST"),
    (oracle.router, "/register", "POST"),
    (broadcast.router, "", "POST"),
    (broadcast.router, "/jobs/{job_id}/metrics", "GET"),
    (comms.router, "/messages", "POST"),
    (telemetry.router, "/anomalies/{anomaly_id}/auto-pr", "POST"),
    (telemetry_scope.router, "/pipelines", "POST"),
    (telemetry_scope.router, "/pipelines/{pipeline_id}/auto-pr", "POST"),
]


def _find_route(router, path, method):
    # This FastAPI version stores the router prefix in route.path already
    # ("/v1/oracle/crawl", not "/crawl"), so accept either form.
    wanted = {path, router.prefix + path}
    for route in router.routes:
        if getattr(route, "path", None) in wanted and method in (
            route.methods or set()
        ):
            return route
    raise AssertionError(f"route {method} {router.prefix}{path} not found")


@pytest.mark.parametrize(
    "router,path,method",
    SIMULATED_ENDPOINTS,
    ids=[f"{m} {r.prefix}{p}" for r, p, m in SIMULATED_ENDPOINTS],
)
def test_simulated_endpoint_labels_itself(router, path, method):
    route = _find_route(router, path, method)
    copy = f"{route.summary or ''}\n{route.description or ''}".lower()
    assert "simulat" in copy, (
        f"{method} {router.prefix}{path} must label its output as simulated"
    )
