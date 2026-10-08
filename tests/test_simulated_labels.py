"""Simulated-output labeling (GTM fix #6).

Every simulated surface must carry an explicit ``simulated`` flag in its
responses so demos cannot present mock success, sample metrics, or modeled
scan findings as live results. Covers AWI, media, IoT, oracle, broadcast,
red team, RTaaS, and Sentinel auto approvals.
"""

import asyncio
import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from app.core.config import get_settings
from app.main import app
from app.schemas.awi import (
    AWIExecutionRequest,
    AWIRepresentationRequest,
    AWIRepresentationType,
    AWISessionCreate,
    AWIStandardAction,
)
from app.services.awi_session import AWISessionManager
from tests.test_trust_helpers import provision_agent_wallet

pytestmark = [pytest.mark.anyio, pytest.mark.proof]

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- AWI ---


async def test_awi_mock_execute_marks_simulated():
    """Unattached sessions run the mock fallback: simulated must be True."""
    manager = AWISessionManager()
    session = await manager.create_session(
        AWISessionCreate(target_url="https://example.com")
    )
    result = await manager.execute_action(
        AWIExecutionRequest(
            session_id=session.session_id,
            action=AWIStandardAction.NAVIGATE_TO,
            parameters={"url": "https://example.com/page"},
        )
    )
    assert result.status == "success"
    assert result.simulated is True


async def test_awi_embedding_and_screenshot_mark_simulated():
    """Synthesized representations are labeled; plain state rendering is not."""
    manager = AWISessionManager()
    session = await manager.create_session(
        AWISessionCreate(target_url="https://example.com")
    )
    embedding = await manager.request_representation(
        AWIRepresentationRequest(
            session_id=session.session_id,
            representation_type=AWIRepresentationType.EMBEDDING,
        )
    )
    assert embedding is not None
    assert embedding.simulated is True

    screenshot = await manager.request_representation(
        AWIRepresentationRequest(
            session_id=session.session_id,
            representation_type=AWIRepresentationType.LOW_RES_SCREENSHOT,
        )
    )
    assert screenshot is not None
    assert screenshot.simulated is True

    summary = await manager.request_representation(
        AWIRepresentationRequest(
            session_id=session.session_id,
            representation_type=AWIRepresentationType.SUMMARY,
        )
    )
    assert summary is not None
    assert summary.simulated is False


# --- Media ---


async def _ready_video_id(client, headers) -> str:
    upload = await client.post(
        "/v1/media/videos",
        json={
            "title": f"label probe {uuid.uuid4().hex[:8]}",
            "source_url": "https://example.com/v.mp4",
        },
        headers=headers,
    )
    assert upload.status_code == 202, upload.text
    video_id = upload.json()["video_id"]
    for _ in range(200):
        status = await client.get(f"/v1/media/videos/{video_id}", headers=headers)
        assert status.status_code == 200, status.text
        if status.json()["status"] == "ready":
            return video_id
        await asyncio.sleep(0.01)
    raise AssertionError(f"video {video_id} never reached ready")


async def test_media_hooks_clips_distribution_mark_simulated(client):
    video_id = await _ready_video_id(client, HEADERS)

    hooks = await client.get(f"/v1/media/videos/{video_id}/hooks", headers=HEADERS)
    assert hooks.status_code == 200
    hook_list = hooks.json()
    assert hook_list, "expected background hook detection to produce hooks"
    assert all(h["simulated"] is True for h in hook_list)

    clips = await client.post(
        f"/v1/media/videos/{video_id}/clips",
        json={"video_id": video_id, "max_clips": 1},
        headers=HEADERS,
    )
    assert clips.status_code == 202, clips.text
    clips_body = clips.json()
    assert clips_body["simulated"] is True
    assert clips_body["clips"]
    assert all(c["simulated"] is True for c in clips_body["clips"])

    dist = await client.post(
        "/v1/media/distribute",
        json={
            "clip_ids": [clips_body["clips"][0]["clip_id"]],
            "platforms": ["youtube_shorts"],
            "title": "label probe",
        },
        headers=HEADERS,
    )
    assert dist.status_code == 200, dist.text
    dist_body = dist.json()
    assert dist_body["simulated"] is True
    assert dist_body["results"]
    assert all(r["simulated"] is True for r in dist_body["results"])


# --- IoT ---


async def test_iot_send_and_subscribe_mark_simulated(client):
    device_id = f"label-sensor-{uuid.uuid4().hex[:8]}"
    reg = await client.post(
        "/v1/iot/devices",
        json={
            "device_id": device_id,
            "protocol": "mqtt",
            "topic_acl": {
                f"device/{device_id}/command": "write",
                f"device/{device_id}/telemetry": "read",
            },
        },
        headers=HEADERS,
    )
    assert reg.status_code == 201, reg.text

    sent = await client.post(
        f"/v1/iot/devices/{device_id}/messages",
        json={
            "topic": f"device/{device_id}/command",
            "payload": {"action": "report_status"},
        },
        headers=HEADERS,
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["simulated"] is True

    sub = await client.post(
        f"/v1/iot/devices/{device_id}/subscribe?topic=device/{device_id}/telemetry",
        headers=HEADERS,
    )
    assert sub.status_code == 200, sub.text
    assert sub.json()["simulated"] is True


# --- Oracle ---


async def test_oracle_crawl_and_register_mark_simulated(client):
    crawl = await client.post(
        "/v1/oracle/crawl",
        json={
            "url": "https://api.anthropic.com",
            "directory_type": "openapi",
        },
        headers=HEADERS,
    )
    assert crawl.status_code == 202, crawl.text
    assert crawl.json()["simulated"] is True

    register = await client.post(
        "/v1/oracle/register",
        json={
            "targets": [
                {
                    "directory_url": "https://registry.example.com",
                    "directory_type": "well_known",
                }
            ]
        },
        headers=HEADERS,
    )
    assert register.status_code == 202, register.text
    reg_body = register.json()
    assert reg_body["simulated"] is True
    assert reg_body["results"]
    assert all(r["simulated"] is True for r in reg_body["results"])

    visibility = await client.get("/v1/oracle/visibility", headers=HEADERS)
    assert visibility.status_code == 200, visibility.text
    assert visibility.json()["simulated"] is True


# --- Broadcast ---


async def test_broadcast_job_and_metrics_mark_simulated(client):
    created = await client.post(
        "/v1/broadcast",
        json={
            "service_name": f"label-api-{uuid.uuid4().hex[:8]}",
            "base_url": "https://api.label.example.com",
            "generation_id": "gen-label",
            "agent_json": {"name": "label-api"},
        },
        headers=HEADERS,
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["simulated"] is True
    assert job["discovery_metrics"]["simulated"] is True
    assert job["targets"]
    assert all(t["simulated"] is True for t in job["targets"])

    metrics = await client.get(
        f"/v1/broadcast/jobs/{job['job_id']}/metrics", headers=HEADERS
    )
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["simulated"] is True

    listing = await client.get("/v1/broadcast/jobs", headers=HEADERS)
    assert listing.status_code == 200, listing.text
    jobs = listing.json()["jobs"]
    assert jobs
    assert all(j["simulated"] is True for j in jobs)


# --- Red team and RTaaS ---


async def test_red_team_scan_report_marks_simulated(client):
    launched = await client.post(
        "/v1/security/scans",
        json={"target_services": ["iot"], "intensity": "quick"},
        headers=HEADERS,
    )
    assert launched.status_code == 202, launched.text
    assert launched.json()["simulated"] is True
    scan_id = launched.json()["scan_id"]

    report = await client.get(f"/v1/security/scans/{scan_id}", headers=HEADERS)
    assert report.status_code == 200, report.text
    assert report.json()["simulated"] is True

    vulns = await client.get(
        f"/v1/security/scans/{scan_id}/vulnerabilities", headers=HEADERS
    )
    assert vulns.status_code == 200, vulns.text
    assert vulns.json()["simulated"] is True


async def test_rtaas_job_marks_simulated(client):
    created = await client.post(
        "/v1/rtaas/jobs",
        json={
            "tenant_id": f"label-tenant-{uuid.uuid4().hex[:8]}",
            "targets": [
                {"url": "https://api.external-tool.com/v1/users", "method": "GET"}
            ],
            "intensity": "quick",
        },
        headers=HEADERS,
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["simulated"] is True
    job_id = job["job_id"]

    vulns = await client.get(
        f"/v1/rtaas/jobs/{job_id}/vulnerabilities", headers=HEADERS
    )
    assert vulns.status_code == 200, vulns.text
    assert vulns.json()["simulated"] is True


# --- Sentinel auto approvals ---


async def test_permit_request_auto_approval_marks_simulated(
    client, clean_database, monkeypatch
):
    """Unconfigured Sentinel auto-approves in dev: the flag must say so."""
    settings = get_settings()
    monkeypatch.setattr(settings, "SIMULATION_MODE_HUMAN_APPROVAL", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    agent = await provision_agent_wallet(client)

    resp = await client.post(
        "/v1/permit-requests",
        json={
            "issuer_wallet_id": agent["sponsor_wallet_id"],
            "subject_wallet_id": agent["agent_wallet_id"],
            "allowed_tools": ["standard_tool"],
            "max_credits": 5,
            "expires_at": "2030-01-01T00:00:00Z",
            "justification": "label probe",
        },
        headers={**agent["agent_headers"], "Idempotency-Key": "label-preq-1"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["simulated"] is True
    assert body["decided_by"] == "simulation"
    assert body["reason"] == "simulated_auto_approval"
