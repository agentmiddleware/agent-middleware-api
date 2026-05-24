from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import app
from app.trust.readiness import build_trust_readiness_report
from tests.test_trust_helpers import BOOTSTRAP_HEADERS, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _items_by_id(report):
    return {item.id: item for item in report.items}


def test_report_maps_verified_core_and_unresolved_gaps():
    report = build_trust_readiness_report(settings=Settings())
    items = _items_by_id(report)

    assert report.verdict == "needs-work"
    assert report.total_items == len(report.items)
    assert items["signed_permits"].status == "verified"
    assert items["governed_mcp_replay"].status == "verified"
    assert items["signed_receipts_evidence"].status == "verified"
    assert items["paid_pilot_real_tool"].status == "verified"
    assert items["awi_full_paper"].status == "partially_verified"
    assert items["production_settlement"].status == "not_verified"
    assert items["compliance_grade_ledger"].status == "not_verified"
    assert "paid_pilot_real_tool" not in report.critical_gaps


def test_report_item_ids_are_unique():
    report = build_trust_readiness_report(settings=Settings())
    item_ids = [item.id for item in report.items]

    assert len(item_ids) == len(set(item_ids))


def test_strict_trust_mode_status_reflects_settings():
    report = build_trust_readiness_report(
        settings=Settings(
            ENVIRONMENT="production",
            TRUST_MODE_ENABLED=True,
            ALLOW_LEGACY_UNPERMITTED_MCP=False,
            TRUST_SIGNING_PRIVATE_KEY_B64="test-private-key",
        )
    )
    items = _items_by_id(report)

    assert items["strict_trust_mode"].status == "verified"
    assert items["strict_trust_mode"].severity == "info"


def test_production_legacy_mcp_is_blocked_in_readiness_report():
    report = build_trust_readiness_report(
        settings=Settings(
            ENVIRONMENT="production",
            TRUST_MODE_ENABLED=True,
            ALLOW_LEGACY_UNPERMITTED_MCP=True,
            TRUST_SIGNING_PRIVATE_KEY_B64="test-private-key",
        )
    )
    items = _items_by_id(report)

    assert items["strict_trust_mode"].status == "blocked"
    assert items["strict_trust_mode"].severity == "critical"
    assert "strict_trust_mode" in report.critical_gaps
    assert report.verdict == "blocked"


@pytest.mark.anyio
async def test_trust_readiness_requires_auth(client):
    response = await client.get("/v1/trust/readiness")

    assert response.status_code in (401, 403)


@pytest.mark.anyio
async def test_trust_readiness_requires_bootstrap_admin(client, clean_database):
    provisioned = await provision_agent_wallet(client)

    response = await client.get(
        "/v1/trust/readiness",
        headers=provisioned["agent_headers"],
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "admin_access_denied"


@pytest.mark.anyio
async def test_trust_readiness_endpoint_returns_gap_map(client):
    response = await client.get(
        "/v1/trust/readiness",
        headers=BOOTSTRAP_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    item_ids = {item["id"] for item in body["items"]}

    assert body["verdict"] in {"needs-work", "blocked", "pilot-ready"}
    assert "signed_permits" in item_ids
    assert "paid_pilot_real_tool" in item_ids
    assert body["by_status"]["verified"] >= 1
