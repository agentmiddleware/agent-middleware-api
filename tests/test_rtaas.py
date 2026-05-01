"""
Tests for Pillar 12: Red-Team-as-a-Service.
Validates multi-tenant external security scanning.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


HEADERS = {"X-API-Key": "test-key"}


@pytest.mark.anyio
async def test_create_rtaas_job(client):
    """Create an RTaaS scanning job against external endpoints."""
    resp = await client.post("/v1/rtaas/jobs", json={
        "tenant_id": "agent-builder-01",
        "targets": [
            {"url": "https://api.external-tool.com/v1/users", "method": "GET"},
            {"url": "https://api.external-tool.com/v1/users", "method": "POST"},
        ],
        "intensity": "standard",
    }, headers=HEADERS)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "completed"
    assert data["targets_count"] == 2
    assert data["total_tests_run"] > 0
    assert 0 <= data["security_score"] <= 100


@pytest.mark.anyio
async def test_rtaas_returns_vulnerabilities(client):
    """RTaaS jobs should return structured vulnerability reports."""
    resp = await client.post("/v1/rtaas/jobs", json={
        "tenant_id": "vuln-test",
        "targets": [
            {"url": "https://api.test-tool.io/auth", "method": "POST"},
            {"url": "https://api.test-tool.io/data", "method": "GET"},
            {"url": "https://api.test-tool.io/admin", "method": "DELETE"},
        ],
        "intensity": "thorough",
    }, headers=HEADERS)
    data = resp.json()

    for vuln in data["vulnerabilities"]:
        assert "vuln_id" in vuln
        assert "severity" in vuln
        assert "category" in vuln
        assert "remediation" in vuln
        assert vuln["cwe_id"].startswith("CWE-")


@pytest.mark.anyio
async def test_rtaas_list_jobs(client):
    """Can list RTaaS jobs filtered by tenant."""
    await client.post("/v1/rtaas/jobs", json={
        "tenant_id": "list-test-tenant",
        "targets": [{"url": "https://example.com/api"}],
    }, headers=HEADERS)

    resp = await client.get("/v1/rtaas/jobs?tenant_id=list-test-tenant", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


@pytest.mark.anyio
async def test_rtaas_get_job_by_id(client):
    """Retrieve a specific job by ID."""
    create = await client.post("/v1/rtaas/jobs", json={
        "tenant_id": "id-test",
        "targets": [{"url": "https://example.com/api"}],
    }, headers=HEADERS)
    job_id = create.json()["job_id"]

    resp = await client.get(f"/v1/rtaas/jobs/{job_id}", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["job_id"] == job_id


@pytest.mark.anyio
async def test_rtaas_get_vulnerabilities_endpoint(client):
    """Dedicated vulnerabilities endpoint works."""
    create = await client.post("/v1/rtaas/jobs", json={
        "tenant_id": "vuln-endpoint-test",
        "targets": [{"url": "https://api.vulnerable.io/login"}],
    }, headers=HEADERS)
    job_id = create.json()["job_id"]

    resp = await client.get(f"/v1/rtaas/jobs/{job_id}/vulnerabilities", headers=HEADERS)
    assert resp.status_code == 200
    assert "vulnerabilities" in resp.json()


@pytest.mark.anyio
async def test_rtaas_job_not_found(client):
    resp = await client.get("/v1/rtaas/jobs/rtaas-nonexistent", headers=HEADERS)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_rtaas_requires_api_key(client):
    resp = await client.post("/v1/rtaas/jobs", json={
        "tenant_id": "test",
        "targets": [{"url": "https://example.com"}],
    })
    assert resp.status_code in (401, 403)
