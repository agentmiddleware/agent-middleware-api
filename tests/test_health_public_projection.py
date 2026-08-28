"""Public projection of /health/dependencies (wedge posture).

With proof surfaces unmounted — the required production posture — the
unauthenticated dependency report must cover only what the trust-plane wedge
runs on: postgres, redis, signing key, upstream MCP, version + commit SHA,
and the resolved environment posture. Production-like deployments additionally
report sanitized Sentinel readiness because human approval is a mounted core
path there. Per-service simulation modes and dependencies only frozen surfaces
consume (mqtt, stripe, llm) are not a public billboard.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.health import (
    PUBLIC_DEPENDENCY_KEYS,
    build_public_dependency_report,
    gather_dependency_report,
)
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def _restore_health_posture():
    settings = get_settings()
    fields = (
        "ENVIRONMENT",
        "ENABLE_PROOF_SURFACES",
        "SIMULATION_MODE_HUMAN_APPROVAL",
        "SENTINEL_API_URL",
        "SENTINEL_API_KEY",
    )
    saved = {field: getattr(settings, field) for field in fields}
    settings.ENVIRONMENT = "local"
    settings.ENABLE_PROOF_SURFACES = False
    settings.SIMULATION_MODE_HUMAN_APPROVAL = True
    settings.SENTINEL_API_URL = ""
    settings.SENTINEL_API_KEY = ""
    yield
    for field, value in saved.items():
        setattr(settings, field, value)


@pytest.mark.anyio
async def test_public_payload_reports_wedge_dependencies_only(client):
    assert get_settings().ENABLE_PROOF_SURFACES is False
    resp = await client.get("/health/dependencies")
    assert resp.status_code == 200
    body = resp.json()

    assert set(body["dependencies"].keys()) == set(PUBLIC_DEPENDENCY_KEYS)
    assert "simulation_modes" not in body
    assert "enable_dogfood_tool" not in body
    assert "enable_dogfood_second_tool" not in body
    # Nothing in the payload names a simulated proof-surface service.
    rendered = resp.text
    for service in (
        "agent_comms",
        "content_factory",
        "human_approval",
        "iot_bridge",
        "media_engine",
        "oracle",
        "red_team",
        "rtaas",
        "telemetry_pm",
    ):
        assert service not in rendered

    # Version + SHA + posture stay, so the payload still proves what runs.
    assert body["version"]
    assert "commit_sha" in body
    assert body["enable_proof_surfaces"] is False
    assert "production_like" in body


@pytest.mark.anyio
async def test_production_public_payload_includes_failed_sentinel_without_secrets(
    client,
    monkeypatch,
):
    settings = get_settings()
    secret_url = "https://private-sentinel.example"
    secret_key = "sentinel-key-that-must-not-leak"
    settings.ENVIRONMENT = "production"
    settings.SIMULATION_MODE_HUMAN_APPROVAL = False
    settings.SENTINEL_API_URL = secret_url
    settings.SENTINEL_API_KEY = secret_key

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, **_kwargs):
            raise RuntimeError(f"do not expose {secret_url} or {secret_key}")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", Client)

    resp = await client.get("/health/dependencies")
    body = resp.json()

    assert body["dependencies"]["sentinel"] == {
        "status": "down",
        "reason": "human_approval_unavailable",
    }
    assert body["status"] == "degraded"
    assert "sentinel" in body["unhealthy"]
    assert secret_url not in resp.text
    assert secret_key not in resp.text


@pytest.mark.anyio
async def test_production_simulated_sentinel_is_publicly_down_without_network(
    client,
    monkeypatch,
):
    settings = get_settings()
    settings.ENVIRONMENT = "production"
    settings.SIMULATION_MODE_HUMAN_APPROVAL = True

    import httpx

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *_args, **_kwargs: pytest.fail("simulation must not create a client"),
    )

    body = (await client.get("/health/dependencies")).json()

    assert body["dependencies"]["sentinel"]["status"] == "down"
    assert body["dependencies"]["sentinel"]["reason"] == (
        "human_approval_not_configured"
    )
    assert "sentinel" in body["unhealthy"]


@pytest.mark.anyio
async def test_local_public_projection_still_omits_failed_sentinel():
    full = await gather_dependency_report()
    full["dependencies"]["sentinel"] = {
        "status": "down",
        "reason": "human_approval_unavailable",
        "error": None,
    }
    full["status"] = "degraded"
    full["unhealthy"] = ["sentinel"]

    public = build_public_dependency_report(full)

    assert "sentinel" not in public["dependencies"]
    assert public["status"] == "healthy"
    assert public["unhealthy"] == []


@pytest.mark.anyio
async def test_production_projection_synthesizes_missing_sentinel_as_down():
    full = await gather_dependency_report()
    full["production_like"] = True
    full["dependencies"].pop("sentinel")

    public = build_public_dependency_report(full)

    assert public["dependencies"]["sentinel"] == {
        "status": "down",
        "reason": "human_approval_unavailable",
    }
    assert public["status"] == "degraded"
    assert "sentinel" in public["unhealthy"]


@pytest.mark.anyio
@pytest.mark.parametrize("sentinel", [None, [], "malformed"])
async def test_production_projection_synthesizes_malformed_sentinel_as_down(sentinel):
    full = await gather_dependency_report()
    full["production_like"] = True
    full["dependencies"]["sentinel"] = sentinel

    public = build_public_dependency_report(full)

    assert public["dependencies"]["sentinel"] == {
        "status": "down",
        "reason": "human_approval_unavailable",
    }
    assert public["status"] == "degraded"
    assert "sentinel" in public["unhealthy"]


@pytest.mark.anyio
async def test_production_projection_publishes_only_sanitized_sentinel_up():
    full = await gather_dependency_report()
    full["production_like"] = True
    full["dependencies"]["sentinel"] = {
        "status": "up",
        "url": "https://private-sentinel.example",
        "credential": "must-not-leak",
    }

    public = build_public_dependency_report(full)

    assert public["dependencies"]["sentinel"] == {"status": "up"}
    assert "https://private-sentinel.example" not in str(public)
    assert "must-not-leak" not in str(public)


@pytest.mark.anyio
async def test_full_payload_returns_when_proof_surfaces_enabled(client):
    cfg = get_settings()
    previous = cfg.ENABLE_PROOF_SURFACES
    cfg.ENABLE_PROOF_SURFACES = True
    try:
        resp = await client.get("/health/dependencies")
    finally:
        cfg.ENABLE_PROOF_SURFACES = previous
    body = resp.json()
    assert "simulation_modes" in body
    assert {"mqtt", "stripe", "llm", "sentinel"} <= set(body["dependencies"].keys())


@pytest.mark.anyio
async def test_projection_recomputes_verdict_from_public_deps():
    """A hidden proof-surface dependency can never flip the public status."""
    full = await gather_dependency_report()
    full["dependencies"]["llm"] = {"status": "down", "error": "boom"}
    full["status"] = "degraded"
    full["unhealthy"] = ["llm"]

    public = build_public_dependency_report(full)
    assert public["status"] == "healthy"
    assert public["unhealthy"] == []
    assert "llm" not in public["dependencies"]


@pytest.mark.anyio
async def test_projection_keeps_wedge_failures_visible():
    full = await gather_dependency_report()
    full["dependencies"]["signing_key"] = {"status": "down", "error": "invalid"}

    public = build_public_dependency_report(full)
    assert public["status"] == "degraded"
    assert public["unhealthy"] == ["signing_key"]


@pytest.mark.anyio
async def test_projection_reports_runtime_degradation():
    full = await gather_dependency_report()
    full["runtime_degradation"] = {"degraded": True, "reasons": ["db_pool"]}

    public = build_public_dependency_report(full)
    assert public["status"] == "degraded"
    assert "runtime_degradation" in public["unhealthy"]


@pytest.mark.anyio
async def test_ready_and_dependencies_agree_on_mqtt(client):
    """/health/ready derives mqtt from the same sim-aware check.

    The old ready endpoint reported mqtt "up, configured: true" whenever a
    broker URL was set, while /health/dependencies reported not_used for the
    same deployment (iot_bridge simulated). They must never disagree again.
    """
    ready = (await client.get("/health/ready")).json()
    assert ready["checks"]["mqtt"]["status"] == "not_used"
    assert "iot_bridge" in ready["checks"]["mqtt"]["reason"]

    full = await gather_dependency_report()
    assert full["dependencies"]["mqtt"]["status"] == "not_used"
    assert ready["checks"]["mqtt"]["status"] == full["dependencies"]["mqtt"]["status"]
