"""API observability: request IDs, /metrics, and optional error tracking.

Covers the gtm-48-api-observability slice: every response carries a
request ID that is also bound to the structured logs, /metrics exposes
process-local counters in Prometheus text format, and error tracking stays
off unless an operator sets SENTRY_DSN.
"""

from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.core import error_tracking
from app.core.observability_metrics import (
    record_request,
    render_prometheus_text,
    reset_metrics,
    snapshot,
)
from app.middleware.request_id import (
    REQUEST_ID_HEADER,
    RequestIDMiddleware,
    resolve_request_id,
)
from app.middleware.request_metrics import RequestMetricsMiddleware

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")

try:
    import importlib.util as _importlib_util

    _HAS_SENTRY_SDK = _importlib_util.find_spec("sentry_sdk") is not None
except Exception:
    _HAS_SENTRY_SDK = False


async def _observed_app():
    """Mini app echoing the request ID from state, header, and structlog."""

    async def echo(request: Request):
        from structlog.contextvars import get_contextvars

        return JSONResponse(
            {
                "state_id": getattr(request.state, "request_id", None),
                "context_id": get_contextvars().get("request_id"),
            }
        )

    application = Starlette(routes=[Route("/echo", echo, methods=["GET"])])
    application.add_middleware(RequestMetricsMiddleware)
    application.add_middleware(RequestIDMiddleware)
    return application


async def _get(app, path, headers=None):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        return await http.get(path, headers=headers or {})


# --- resolve_request_id ----------------------------------------------------


def test_valid_caller_id_is_preserved_verbatim():
    assert resolve_request_id("order-123_abc.X~9") == "order-123_abc.X~9"


def test_surrounding_whitespace_is_trimmed():
    assert resolve_request_id("  abc-123  ") == "abc-123"


@pytest.mark.parametrize(
    "bad",
    [None, "", "has space", "line\nbreak", "tab\there", "semi;colon", "x" * 129],
)
def test_unsafe_or_missing_id_is_replaced_with_fresh_hex(bad):
    assert _HEX32.match(resolve_request_id(bad)) is not None


def test_generated_ids_are_unique():
    assert resolve_request_id(None) != resolve_request_id(None)


# --- middleware behavior ---------------------------------------------------


@pytest.mark.anyio
async def test_generated_id_is_returned_and_visible_to_handlers():
    resp = await _get(await _observed_app(), "/echo")
    assert resp.status_code == 200
    header_id = resp.headers[REQUEST_ID_HEADER.lower()]
    assert _HEX32.match(header_id) is not None
    assert resp.json() == {"state_id": header_id, "context_id": header_id}


@pytest.mark.anyio
async def test_caller_id_flows_into_state_logs_and_response():
    resp = await _get(
        await _observed_app(), "/echo", headers={REQUEST_ID_HEADER: "order-42"}
    )
    assert resp.headers[REQUEST_ID_HEADER.lower()] == "order-42"
    assert resp.json() == {"state_id": "order-42", "context_id": "order-42"}


@pytest.mark.anyio
async def test_log_injection_value_is_replaced_not_reflected():
    resp = await _get(
        await _observed_app(), "/echo", headers={REQUEST_ID_HEADER: "a\nb"}
    )
    header_id = resp.headers[REQUEST_ID_HEADER.lower()]
    assert "\n" not in header_id
    assert _HEX32.match(header_id) is not None
    assert resp.json()["state_id"] == header_id


@pytest.mark.anyio
async def test_non_http_scopes_pass_through():
    seen = []

    async def spy(scope, receive, send):
        seen.append(scope["type"])

    async def noop():
        return {}

    async def send(message):
        pass

    for scope_type in ("lifespan", "websocket"):
        await RequestIDMiddleware(spy)({"type": scope_type}, noop, send)
    assert seen == ["lifespan", "websocket"]


# --- metrics module --------------------------------------------------------


@pytest.fixture
def clean_metrics():
    reset_metrics()
    try:
        yield
    finally:
        reset_metrics()


def test_render_names_process_local_reset_in_help_text(clean_metrics):
    record_request("/health", 200, 0.01)
    text = render_prometheus_text()
    assert "Process-local, resets on restart" in text
    assert 'amw_http_requests_total{route="/health",status="200"} 1' in text
    assert 'amw_http_request_latency_seconds_avg{route="/health"}' in text


def test_snapshot_is_a_copy_not_a_view(clean_metrics):
    record_request("/health", 200, 0.02)
    snap = snapshot()
    snap["requests"][("/health", "200")] = 999
    assert snapshot()["requests"][("/health", "200")] == 1


@pytest.mark.anyio
async def test_metrics_middleware_labels_by_route_template(clean_metrics):
    async def item(request: Request):
        return JSONResponse({"ok": True})

    application = Starlette(routes=[Route("/items/{item_id}", item)])
    application.add_middleware(RequestMetricsMiddleware)
    resp = await _get(application, "/items/abc-123")
    assert resp.status_code == 200
    text = render_prometheus_text()
    assert 'route="/items/{item_id}"' in text
    assert "/items/abc-123" not in text


@pytest.mark.anyio
async def test_metrics_middleware_counts_errors(clean_metrics):
    async def boom(request: Request):
        return JSONResponse({"detail": "nope"}, status_code=500)

    application = Starlette(routes=[Route("/boom", boom)])
    application.add_middleware(RequestMetricsMiddleware)
    await _get(application, "/boom")
    assert 'amw_http_requests_total{route="/boom",status="500"} 1' in (
        render_prometheus_text()
    )


# --- real app wiring -------------------------------------------------------


@pytest.mark.anyio
async def test_real_app_answers_include_request_id(clean_metrics):
    from app.main import app as real_app

    async with AsyncClient(
        transport=ASGITransport(app=real_app), base_url="http://test"
    ) as http:
        resp = await http.get("/health")
    assert resp.status_code in (200, 503)
    assert _HEX32.match(resp.headers[REQUEST_ID_HEADER.lower()]) is not None


@pytest.mark.anyio
async def test_real_app_metrics_endpoint_reports_traffic(clean_metrics):
    from app.main import app as real_app

    async with AsyncClient(
        transport=ASGITransport(app=real_app), base_url="http://test"
    ) as http:
        await http.get("/health")
        resp = await http.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert 'amw_http_requests_total{route="/health"' in resp.text
    assert "Process-local, resets on restart" in resp.text


def test_real_app_registers_observability_middleware():
    from app.main import app as real_app

    registered = {middleware.cls for middleware in real_app.user_middleware}
    assert RequestIDMiddleware in registered
    assert RequestMetricsMiddleware in registered
    assert "/metrics" in {
        route.path for route in real_app.routes if hasattr(route, "path")
    }


# --- error tracking --------------------------------------------------------


@pytest.fixture
def clean_tracking():
    error_tracking.reset_for_tests()
    try:
        yield
    finally:
        error_tracking.reset_for_tests()


def test_tracking_stays_off_without_a_dsn(clean_tracking):
    assert error_tracking.init_error_tracking(dsn="") is False
    assert error_tracking.is_enabled() is False


def test_capture_is_a_safe_noop_when_disabled(clean_tracking):
    error_tracking.capture_exception(ValueError("boom"))
    error_tracking.capture_message("alert without backend")
    assert error_tracking.is_enabled() is False


def test_tracking_without_sdk_warns_and_stays_off(clean_tracking, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _no_sentry(name, *args, **kwargs):
        if name == "sentry_sdk" or name.startswith("sentry_sdk."):
            raise ImportError("No module named 'sentry_sdk'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_sentry)
    assert (
        error_tracking.init_error_tracking(dsn="https://x@example.invalid/1") is False
    )
    assert error_tracking.is_enabled() is False


@pytest.mark.skipif(not _HAS_SENTRY_SDK, reason="sentry-sdk not installed")
def test_tracking_enables_with_dsn_when_sdk_present(clean_tracking):
    assert (
        error_tracking.init_error_tracking(
            dsn="https://x@example.invalid/1", environment="test"
        )
        is True
    )
    assert error_tracking.is_enabled() is True
