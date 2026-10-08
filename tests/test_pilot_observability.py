"""Pilot observability: request IDs, structured 500s, and /metrics.

Covers the smallest pilot-monitoring slice: every response carries an
X-Request-ID (propagated when the caller sends a usable one, minted
otherwise), unhandled errors answer with a fixed-shape 500 that names the
request ID but never leaks exception text, and GET /metrics reports
request, error, and latency counters.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from app.core.request_metrics import (
    get_metrics_snapshot,
    record_request,
    reset_metrics,
)
from app.middleware.request_id import (
    REQUEST_ID_HEADER,
    RequestIDMiddleware,
    resolve_request_id,
)


@pytest.fixture(autouse=True)
def _clean_metrics():
    reset_metrics()
    yield
    reset_metrics()


def _probe_app() -> Starlette:
    async def ok(request):
        return JSONResponse({"request_id": request.state.request_id})

    async def boom(request):
        raise RuntimeError("secret backend detail")

    app = Starlette(
        routes=[
            Route("/probe", ok),
            Route("/boom", boom),
        ]
    )
    app.add_middleware(RequestIDMiddleware)
    return app


def test_mints_request_id_when_caller_sends_none() -> None:
    first = TestClient(_probe_app()).get("/probe")
    second = TestClient(_probe_app()).get("/probe")

    assert first.headers[REQUEST_ID_HEADER]
    assert second.headers[REQUEST_ID_HEADER]
    assert first.headers[REQUEST_ID_HEADER] != second.headers[REQUEST_ID_HEADER]


def test_propagates_caller_supplied_request_id() -> None:
    response = TestClient(_probe_app()).get(
        "/probe", headers={REQUEST_ID_HEADER: "pilot-call-123"}
    )

    assert response.headers[REQUEST_ID_HEADER] == "pilot-call-123"
    assert response.json()["request_id"] == "pilot-call-123"


@pytest.mark.parametrize(
    "incoming",
    ["", "has spaces in it", "x" * 200, "semi;colon", 'quo"te'],
)
def test_unusable_request_id_is_replaced(incoming: str) -> None:
    response = TestClient(_probe_app()).get(
        "/probe", headers={REQUEST_ID_HEADER: incoming}
    )

    assert response.headers[REQUEST_ID_HEADER] != incoming
    assert response.headers[REQUEST_ID_HEADER]


def test_unhandled_error_returns_fixed_shape_with_request_id() -> None:
    response = TestClient(_probe_app(), raise_server_exceptions=False).get(
        "/boom", headers={REQUEST_ID_HEADER: "trace-me"}
    )

    assert response.status_code == 500
    assert response.headers[REQUEST_ID_HEADER] == "trace-me"
    body = response.json()
    assert body["error"] == "internal_error"
    assert body["request_id"] == "trace-me"
    assert "secret backend detail" not in response.text


def test_resolve_request_id_unit_cases() -> None:
    assert resolve_request_id(None) != ""
    assert resolve_request_id("abc-123_X.y:z~7") == "abc-123_X.y:z~7"
    assert resolve_request_id("no good") != "no good"


def test_metrics_counts_requests_errors_and_latency() -> None:
    client = TestClient(_probe_app(), raise_server_exceptions=False)
    client.get("/probe")
    client.get("/probe")
    client.get("/boom")

    snapshot = get_metrics_snapshot()
    assert snapshot["requests_total"] == 3
    assert snapshot["errors_total"] == 1
    assert snapshot["uptime_seconds"] >= 0
    assert "scope_note" in snapshot and "reset" in snapshot["scope_note"]

    probe = snapshot["routes"]["GET /probe"]
    assert probe["requests"] == 2
    assert probe["errors"] == 0
    assert probe["latency_avg_seconds"] >= 0
    assert probe["latency_sum_seconds"] >= probe["latency_avg_seconds"]

    boom = snapshot["routes"]["GET /boom"]
    assert boom["requests"] == 1
    assert boom["errors"] == 1


def test_metrics_scrape_does_not_count_itself() -> None:
    record_request(
        route_template="/probe",
        method="GET",
        raw_path="/probe",
        status_code=200,
        latency_seconds=0.001,
    )
    record_request(
        route_template="/metrics",
        method="GET",
        raw_path="/metrics",
        status_code=200,
        latency_seconds=0.001,
    )

    assert get_metrics_snapshot()["requests_total"] == 1


def test_gateway_health_carries_request_id_and_metrics_is_public() -> None:
    from app.main import app

    client = TestClient(app)
    health = client.get("/health")
    assert health.headers[REQUEST_ID_HEADER]

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    body = metrics.json()
    assert body["requests_total"] >= 1
    assert "routes" in body and "scope_note" in body


def test_gateway_echoes_caller_request_id() -> None:
    from app.main import app

    response = TestClient(app).get(
        "/health", headers={REQUEST_ID_HEADER: "gateway-trace-9"}
    )
    assert response.headers[REQUEST_ID_HEADER] == "gateway-trace-9"


def test_plain_text_probe_keeps_middleware_shape() -> None:
    app = Starlette(routes=[Route("/t", lambda request: PlainTextResponse("ok"))])
    app.add_middleware(RequestIDMiddleware)

    response = TestClient(app).get("/t")
    assert response.headers[REQUEST_ID_HEADER]
    assert get_metrics_snapshot()["requests_total"] == 1
