"""
Contract: simulation registry and /health/dependencies stay aligned.

Ensures every SIMULATION_MODE_* setting is registered in runtime_mode and exposed
via the dependency health endpoint.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.runtime_mode import (
    SERVICE_NAMES,
    get_simulation_modes,
    simulation_settings_field,
)
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_all_simulation_mode_settings_mapped_in_runtime_registry():
    """Each SIMULATION_MODE_* field pairs with exactly one runtime service."""
    fields = sorted(
        name for name in Settings.model_fields if name.startswith("SIMULATION_MODE_")
    )
    inverted = sorted({simulation_settings_field(svc) for svc in SERVICE_NAMES})
    assert fields == inverted


def test_simulation_settings_field_unknown_raises():
    from app.core.runtime_mode import UnknownServiceError

    with pytest.raises(UnknownServiceError):
        simulation_settings_field("not_a_service")


@pytest.mark.anyio
async def test_health_dependencies_simulation_modes_complete(client):
    resp = await client.get("/health/dependencies")
    assert resp.status_code == 200
    body = resp.json()
    sm = body["simulation_modes"]
    assert set(sm.keys()) == SERVICE_NAMES
    assert sm == get_simulation_modes()
