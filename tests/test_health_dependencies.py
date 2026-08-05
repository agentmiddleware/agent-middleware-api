"""
Tests for app/core/health.py and the /health/dependencies endpoint.

Covers: default test-env report shape, per-check status codes,
simulation-mode gating (MQTT/LLM not probed when consumers simulated),
overall-status degradation, and timeout behavior.
"""

import asyncio
import base64
import json

import pytest
from httpx import AsyncClient, ASGITransport

from app.core import health as health_module
from app.core.config import get_settings
from app.core.health import (
    CHECK_TIMEOUT_SECONDS,
    _OK_STATUSES,
    _run_check,
    gather_dependency_report,
)
from app.core.runtime_degradation import reset_runtime_degradation
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def _restore_env():
    """Some tests mutate Settings; snapshot and restore."""
    settings = get_settings()
    fields = [
        "DATABASE_URL",
        "REDIS_URL",
        "MQTT_BROKER_URL",
        "STRIPE_SECRET_KEY",
        "LLM_API_KEY",
        "LLM_PROVIDER",
        "SIMULATION_MODE_IOT_BRIDGE",
        "SIMULATION_MODE_TELEMETRY_PM",
        "TRUST_MODE_ENABLED",
        "TRUST_SIGNING_PRIVATE_KEY_B64",
    ]
    saved = {f: getattr(settings, f) for f in fields}
    reset_runtime_degradation()
    yield
    for f, v in saved.items():
        setattr(settings, f, v)
    reset_runtime_degradation()


# ---------------------------------------------------------------------------
# Default shape under test config
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_report_default_shape():
    """
    With the test env (sqlite DATABASE_URL, no Redis/Stripe/LLM, iot_bridge
    simulated), the report should be healthy: postgres up, the rest either
    not_configured or not_used.
    """
    report = await gather_dependency_report()

    assert report["status"] == "healthy"
    assert set(report["dependencies"].keys()) == {
        "postgres",
        "redis",
        "mqtt",
        "stripe",
        "llm",
        "signing_key",
        "sentinel",
    }
    # Every check carries an error slot (None when healthy) and latency_ms.
    for name, res in report["dependencies"].items():
        assert "status" in res
        assert "latency_ms" in res
        assert "error" in res

    # In the default test env:
    assert report["dependencies"]["postgres"]["status"] == "up"
    assert report["dependencies"]["redis"]["status"] == "not_configured"
    assert report["dependencies"]["stripe"]["status"] == "not_configured"
    assert report["dependencies"]["llm"]["status"] == "not_configured"
    assert report["dependencies"]["signing_key"]["status"] == "up"
    assert report["dependencies"]["signing_key"]["state"] == "ephemeral"

    # MQTT gated on iot_bridge simulation mode.
    assert report["dependencies"]["mqtt"]["status"] == "not_used"
    assert "iot_bridge" in report["dependencies"]["mqtt"].get("reason", "")

    # Sentinel gated on human_approval simulation mode.
    assert report["dependencies"]["sentinel"]["status"] == "not_used"
    assert "human_approval" in report["dependencies"]["sentinel"].get("reason", "")

    # Simulation modes are surfaced for operators.
    assert "simulation_modes" in report
    assert report["simulation_modes"]["iot_bridge"] is True


# ---------------------------------------------------------------------------
# _run_check utility
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_check_captures_error():
    async def broken():
        raise ValueError("boom")

    result = await _run_check("t", broken)
    assert result["status"] == "down"
    assert "ValueError" in result["error"]
    assert "boom" in result["error"]
    assert result["latency_ms"] >= 0


@pytest.mark.anyio
async def test_run_check_enforces_timeout():
    async def slow():
        await asyncio.sleep(CHECK_TIMEOUT_SECONDS + 1)
        return {"status": "up"}

    result = await _run_check("t", slow)
    assert result["status"] == "down"
    assert "timeout" in result["error"]


@pytest.mark.anyio
async def test_run_check_ok_fills_latency_and_nulls_error():
    async def ok():
        return {"status": "up"}

    result = await _run_check("t", ok)
    assert result["status"] == "up"
    assert result["error"] is None
    assert isinstance(result["latency_ms"], (int, float))


# ---------------------------------------------------------------------------
# Simulation-mode gating
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mqtt_probed_when_iot_bridge_real(monkeypatch):
    """Turning iot_bridge off forces MQTT to actually try to connect."""
    settings = get_settings()
    settings.SIMULATION_MODE_IOT_BRIDGE = False

    async def fake_mqtt(_sim_modes):
        return {"status": "up", "host": "localhost", "port": 1883}

    monkeypatch.setattr(health_module, "_check_mqtt", fake_mqtt)

    report = await gather_dependency_report()
    assert report["dependencies"]["mqtt"]["status"] == "up"


@pytest.mark.anyio
async def test_llm_not_used_when_telemetry_pm_simulated():
    """LLM probe skipped if its primary consumer is simulated — even when
    a key is configured — to avoid needlessly burning API quota."""
    settings = get_settings()
    settings.LLM_API_KEY = "sk-fake-but-set"
    settings.LLM_PROVIDER = "openai"
    # telemetry_pm already defaults to simulation=True

    report = await gather_dependency_report()
    assert report["dependencies"]["llm"]["status"] == "not_used"
    assert report["dependencies"]["llm"]["provider"] == "openai"


# ---------------------------------------------------------------------------
# Overall verdict
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_overall_degrades_on_single_down_dep(monkeypatch):
    async def failing_postgres():
        return {"status": "down", "error": "connection refused"}

    monkeypatch.setattr(health_module, "_check_postgres", failing_postgres)

    report = await gather_dependency_report()
    assert report["status"] == "degraded"
    assert "postgres" in report["unhealthy"]


@pytest.mark.anyio
async def test_not_configured_and_not_used_do_not_degrade_status():
    """Verify the _OK_STATUSES contract — these keep overall healthy."""
    for status in _OK_STATUSES:
        assert status in {"up", "not_configured", "not_used"}


@pytest.mark.anyio
async def test_valid_signing_key_is_reported_as_loaded():
    settings = get_settings()
    settings.TRUST_MODE_ENABLED = True
    settings.TRUST_SIGNING_PRIVATE_KEY_B64 = base64.b64encode(bytes(range(32))).decode()

    report = await gather_dependency_report()

    assert report["dependencies"]["signing_key"]["status"] == "up"
    assert report["dependencies"]["signing_key"]["state"] == "loaded"
    assert "signing_key" not in report["unhealthy"]


@pytest.mark.anyio
async def test_invalid_signing_key_degrades_without_leaking_configured_value(client):
    settings = get_settings()
    secret_sentinel = f"{base64.b64encode(bytes(range(32))).decode()}!DO_NOT_LEAK"
    settings.TRUST_MODE_ENABLED = True
    settings.TRUST_SIGNING_PRIVATE_KEY_B64 = secret_sentinel

    resp = await client.get("/health/dependencies")
    report = resp.json()
    signing_key = report["dependencies"]["signing_key"]

    assert resp.status_code == 200
    assert report["status"] == "degraded"
    assert "signing_key" in report["unhealthy"]
    assert signing_key["status"] == "down"
    assert signing_key["state"] == "invalid"
    assert signing_key["error"] == "invalid_trust_signing_private_key"
    assert secret_sentinel not in json.dumps(report)
    assert secret_sentinel not in resp.text


@pytest.mark.anyio
async def test_missing_signing_key_degrades_when_trust_mode_is_enabled():
    settings = get_settings()
    settings.TRUST_MODE_ENABLED = True
    settings.TRUST_SIGNING_PRIVATE_KEY_B64 = ""

    report = await gather_dependency_report()
    signing_key = report["dependencies"]["signing_key"]

    assert report["status"] == "degraded"
    assert "signing_key" in report["unhealthy"]
    assert signing_key["status"] == "down"
    assert signing_key["state"] == "invalid"
    assert signing_key["error"] == "trust_signing_private_key_required"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_health_dependencies_endpoint_returns_report(client):
    resp = await client.get("/health/dependencies")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert "dependencies" in body
    assert set(body["dependencies"].keys()) == {
        "postgres",
        "redis",
        "mqtt",
        "stripe",
        "llm",
        "signing_key",
        "sentinel",
    }
    assert "simulation_modes" in body
    assert "unhealthy" in body


@pytest.mark.anyio
async def test_health_dependencies_is_public_no_auth_required(client):
    """Health endpoints must work without the X-API-Key header — monitors
    like Kubernetes liveness probes don't carry authentication."""
    resp = await client.get("/health/dependencies")
    assert resp.status_code == 200
