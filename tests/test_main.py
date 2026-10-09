"""Focused coverage for app/main.py.

Covers the module's own public behavior: the non-finite float guard used by
the validation-error handler, the handler's 422-instead-of-500 edge case,
the liveness/readiness endpoints, the service-index root (JSON and HTML
branches), and dormant-surface mounting on an isolated app. Router-specific
behavior (CORS branches, duplicate-guard metrics, proof-surface gating) is
covered by its own test files and is not repeated here.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.core.config import get_settings
from app.main import (
    _json_safe_numbers,
    app,
    mount_dormant_trust_surfaces,
    request_validation_error_handler,
)
from tests.conftest import iter_routes


def _client(application: FastAPI = app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


def test_json_safe_numbers_spells_non_finite_floats():
    assert _json_safe_numbers(float("nan")) == "NaN"
    assert _json_safe_numbers(float("inf")) == "Infinity"
    assert _json_safe_numbers(float("-inf")) == "-Infinity"


def test_json_safe_numbers_recurses_and_passes_finite_values_through():
    payload = {
        "ok": 1.5,
        "count": 3,
        "name": "x",
        "missing": None,
        "nested": [float("nan"), {"deep": float("-inf")}],
    }
    assert _json_safe_numbers(payload) == {
        "ok": 1.5,
        "count": 3,
        "name": "x",
        "missing": None,
        "nested": ["NaN", {"deep": "-Infinity"}],
    }


@pytest.mark.anyio
async def test_validation_handler_spells_non_finite_input_in_422():
    """A refused input containing NaN/Infinity must answer 422, not 500.

    Starlette accepts the bare literals and the default handler echoes the
    refused input back, which plain json.dumps cannot serialize. This is the
    edge case app/main.py guards against.
    """
    exc = RequestValidationError(
        [
            {
                "loc": ("body", "amount"),
                "msg": "Input should be a valid number",
                "type": "value_error",
                "input": float("nan"),
            },
            {
                "loc": ("body", "limit"),
                "msg": "Input should be a valid number",
                "type": "value_error",
                "input": float("inf"),
            },
        ]
    )
    response = await request_validation_error_handler(None, exc)  # type: ignore[arg-type]
    assert response.status_code == 422
    body = json.loads(response.body.decode("utf-8"))
    inputs = [error["input"] for error in body["detail"]]
    assert "NaN" in inputs
    assert "Infinity" in inputs


@pytest.mark.anyio
async def test_health_reports_healthy_when_redis_answers(monkeypatch):
    async def fake_liveness() -> str:
        return "up"

    monkeypatch.setattr(main_module, "check_redis_liveness", fake_liveness)
    async with _client() as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["checks"] == {"redis": "up"}
    assert "version" in body
    assert "commit_sha" in body


@pytest.mark.anyio
async def test_health_reports_degraded_503_when_redis_down(monkeypatch):
    async def fake_liveness() -> str:
        return "down"

    monkeypatch.setattr(main_module, "check_redis_liveness", fake_liveness)
    async with _client() as client:
        response = await client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


@pytest.mark.anyio
async def test_health_ready_reports_not_ready_when_database_down(monkeypatch):
    class _FakeState:
        async def health_report(self) -> dict:
            return {"ok": True, "backend": "memory"}

    async def fake_mqtt() -> dict:
        return {"status": "up"}

    async def fake_database() -> dict:
        return {"status": "down"}

    monkeypatch.setattr(main_module, "get_durable_state", lambda: _FakeState())
    monkeypatch.setattr(main_module, "check_mqtt_readiness", fake_mqtt)
    monkeypatch.setattr(main_module, "check_database_readiness", fake_database)
    async with _client() as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"]["status"] == "down"
    assert body["checks"]["state_store"]["status"] == "up"


@pytest.mark.anyio
async def test_root_serves_json_service_index():
    async with _client() as client:
        response = await client.get("/", headers={"accept": "application/json"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == get_settings().APP_NAME
    assert body["version"] == get_settings().APP_VERSION
    assert "agent_first" in body
    assert "surface_boundaries" in body
    if not get_settings().ENABLE_PROOF_SURFACES:
        assert set(body["services"]) == {"agent_billing", "mcp_server"}
        assert body["surface_boundaries"]["proof_surfaces_mounted"] is False
    else:
        assert "agent_billing" in body["services"]


@pytest.mark.anyio
async def test_root_serves_html_operator_index_for_browser_accept():
    async with _client() as client:
        response = await client.get("/", headers={"accept": "text/html"})
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_mount_dormant_trust_surfaces_adds_dormant_paths_to_fresh_app():
    """Mounting targets an isolated app so the shared app is never mutated."""
    fresh = FastAPI()
    mount_dormant_trust_surfaces(fresh)
    paths = {route.path for route in iter_routes(fresh.routes)}
    for prefix in (
        "/v1/auth",
        "/v1/kyc",
        "/v1/planner",
        "/v1/pods",
        "/v1/x402",
    ):
        assert any(path.startswith(prefix) for path in paths), (
            f"missing dormant routes under {prefix}"
        )
    assert any(path.startswith("/v1/billing") for path in paths), (
        "missing billing expansion routes"
    )
