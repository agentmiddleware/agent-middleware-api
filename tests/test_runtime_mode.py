"""
Tests for app/core/runtime_mode.py — the per-service simulation flag.

Covers the three public entry points (is_simulation, require_simulation,
get_simulation_modes), the unknown-service error, and the /health/dependencies
surface that consumers read the state from.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.core import runtime_mode
from app.core.config import get_settings
from app.core.runtime_mode import (
    SERVICE_NAMES,
    UnknownServiceError,
    get_simulation_modes,
    is_simulation,
    require_simulation,
)
from app.main import app


HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """
    get_settings is lru_cached. Tests that mutate the cached instance's
    attributes must restore them afterwards; this fixture captures and
    restores each simulation field around every test.
    """
    settings = get_settings()
    fields = [
        "SIMULATION_MODE_ORACLE",
        "SIMULATION_MODE_RED_TEAM",
        "SIMULATION_MODE_RTAAS",
        "SIMULATION_MODE_MEDIA_ENGINE",
        "SIMULATION_MODE_IOT_BRIDGE",
        "SIMULATION_MODE_TELEMETRY_PM",
        "SIMULATION_MODE_AGENT_COMMS",
        "SIMULATION_MODE_CONTENT_FACTORY",
    ]
    saved = {f: getattr(settings, f) for f in fields}
    yield
    for f, v in saved.items():
        setattr(settings, f, v)


def test_service_names_are_complete():
    """The SERVICE_NAMES set must stay in sync with Settings fields."""
    expected = {
        "oracle",
        "red_team",
        "rtaas",
        "media_engine",
        "iot_bridge",
        "telemetry_pm",
        "agent_comms",
        "content_factory",
    }
    assert SERVICE_NAMES == expected


def test_default_is_simulation_true():
    """Every known service starts in simulation mode."""
    for name in SERVICE_NAMES:
        assert is_simulation(name) is True, f"{name} should default to simulation"


def test_is_simulation_reflects_settings_change():
    settings = get_settings()
    settings.SIMULATION_MODE_ORACLE = False
    assert is_simulation("oracle") is False
    assert is_simulation("red_team") is True  # others unaffected


def test_is_simulation_unknown_service():
    with pytest.raises(UnknownServiceError):
        is_simulation("nope")


def test_require_simulation_passes_when_simulating():
    """Sanity: by default, guard is a no-op."""
    require_simulation("oracle")  # should not raise


def test_require_simulation_raises_with_issue_reference():
    settings = get_settings()
    settings.SIMULATION_MODE_TELEMETRY_PM = False
    with pytest.raises(NotImplementedError) as exc:
        require_simulation("telemetry_pm", issue="#37")
    msg = str(exc.value)
    assert "telemetry_pm" in msg
    assert "#37" in msg
    assert "SIMULATION_MODE_TELEMETRY_PM" in msg


def test_get_simulation_modes_returns_all_services():
    modes = get_simulation_modes()
    assert set(modes.keys()) == SERVICE_NAMES
    assert all(v is True for v in modes.values())


def test_get_simulation_modes_reflects_toggles():
    settings = get_settings()
    settings.SIMULATION_MODE_MEDIA_ENGINE = False
    modes = get_simulation_modes()
    assert modes["media_engine"] is False
    # Everything else still True
    assert all(v for k, v in modes.items() if k != "media_engine")


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_health_dependencies_surfaces_simulation_modes(client):
    """/health/dependencies must expose simulation state for operators."""
    resp = await client.get("/health/dependencies")
    assert resp.status_code == 200
    body = resp.json()
    assert "simulation_modes" in body
    assert set(body["simulation_modes"].keys()) == SERVICE_NAMES


@pytest.mark.anyio
async def test_service_method_raises_when_simulation_disabled(client):
    """
    With the oracle flag off, hitting the crawl endpoint must trigger the
    guard. ASGITransport propagates the unhandled NotImplementedError
    directly (unlike a real uvicorn server, which would wrap it in a 500),
    so assert on the exception — that proves the guard actually fired.
    """
    settings = get_settings()
    settings.SIMULATION_MODE_ORACLE = False
    with pytest.raises(NotImplementedError, match="oracle"):
        await client.post(
            "/v1/oracle/crawl",
            json={"url": "https://api.example.com", "directory_type": "openapi"},
            headers=HEADERS,
        )
