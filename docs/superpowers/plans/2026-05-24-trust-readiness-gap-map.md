# Trust Readiness Gap Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tested, operator-facing trust-readiness gap map that separates verified MCP trust-plane capabilities from partial, demo-only, or not-yet-claimable product claims.

**Architecture:** Add a pure report builder under `app/trust/` and expose it through a bootstrap-admin-only FastAPI router. Keep the report static where it maps product claims, and dynamic only for current trust-mode settings so tests stay deterministic.

**Tech Stack:** FastAPI, Pydantic, existing `AuthContext`, existing `Settings`, pytest/httpx.

---

### Task 1: Trust Readiness Service

**Files:**
- Create: `app/trust/readiness.py`
- Modify: `app/trust/__init__.py`
- Test: `tests/test_trust_readiness.py`

- [x] **Step 1: Write failing service tests**

Add tests that call `build_trust_readiness_report(settings=Settings(...))` directly and assert:

```python
def test_report_maps_verified_core_and_unresolved_gaps():
    report = build_trust_readiness_report(settings=Settings())
    ids = {item.id: item for item in report.items}
    assert ids["signed_permits"].status == "verified"
    assert ids["governed_mcp_replay"].status == "verified"
    assert ids["awi_full_paper"].status == "partially_verified"
    assert ids["production_settlement"].status == "not_verified"
    assert report.verdict == "needs-work"

def test_strict_trust_mode_status_reflects_settings():
    report = build_trust_readiness_report(
        settings=Settings(
            ENVIRONMENT="production",
            TRUST_MODE_ENABLED=True,
            ALLOW_LEGACY_UNPERMITTED_MCP=False,
            TRUST_SIGNING_PRIVATE_KEY_B64="test-private-key",
        )
    )
    ids = {item.id: item for item in report.items}
    assert ids["strict_trust_mode"].status == "verified"
```

- [x] **Step 2: Implement the service**

Create Pydantic models:

```python
class TrustReadinessItem(BaseModel):
    id: str
    area: str
    status: Literal["verified", "partially_verified", "demo_only", "not_verified", "blocked"]
    severity: Literal["critical", "high", "medium", "low", "info"]
    claim: str
    evidence: list[str] = Field(default_factory=list)
    gap: str | None = None
    recommended_next_step: str

class TrustReadinessReport(BaseModel):
    checked_at: datetime
    verdict: Literal["pilot-ready", "needs-work", "blocked"]
    total_items: int
    by_status: dict[str, int]
    critical_gaps: list[str]
    items: list[TrustReadinessItem]
```

Add `build_trust_readiness_report(settings: Settings | None = None)`.

- [x] **Step 3: Run service tests**

Run:

```bash
uv run pytest -q tests/test_trust_readiness.py
```

Expected: service tests pass.

### Task 2: Operator Endpoint

**Files:**
- Create: `app/routers/trust_readiness.py`
- Modify: `app/main.py`
- Test: `tests/test_trust_readiness.py`

- [x] **Step 1: Write failing HTTP tests**

Add tests:

```python
async def test_trust_readiness_requires_auth(client):
    response = await client.get("/v1/trust/readiness")
    assert response.status_code in (401, 403)

async def test_trust_readiness_requires_bootstrap_admin(wallet_client):
    response = await wallet_client.get("/v1/trust/readiness")
    assert response.status_code == 403

async def test_trust_readiness_endpoint_returns_gap_map(client):
    response = await client.get("/v1/trust/readiness", headers={"X-API-Key": "test-key"})
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] in {"needs-work", "blocked", "pilot-ready"}
    assert any(item["id"] == "paid_pilot_real_tool" for item in body["items"])
```

- [x] **Step 2: Implement router and registration**

Create `app/routers/trust_readiness.py`:

```python
router = APIRouter(prefix="/v1/trust", tags=["Trust Readiness"])

@router.get("/readiness", response_model=TrustReadinessReport)
async def get_trust_readiness(auth: AuthContext = Depends(get_auth_context)):
    auth.require_bootstrap_admin()
    return build_trust_readiness_report()
```

Register it in `app/main.py` under `CORE_TRUST_ROUTERS`.

- [x] **Step 3: Run endpoint tests**

Run:

```bash
uv run pytest -q tests/test_trust_readiness.py
```

Expected: endpoint tests pass.

### Task 3: Docs And API Contract

**Files:**
- Modify: `README.md`
- Modify: `docs/production-beta-roadmap.md`
- Modify: `docs/openapi.json`

- [x] **Step 1: Document the new surface**

Add a concise README note under governance/readiness that `GET /v1/trust/readiness` is the operator gap map and does not certify production readiness.

- [x] **Step 2: Regenerate OpenAPI**

Run:

```bash
uv run python scripts/export_openapi.py
```

Expected: `docs/openapi.json` includes `/v1/trust/readiness`.

- [x] **Step 3: Run focused verification**

Run:

```bash
uv run pytest -q tests/test_trust_readiness.py tests/test_discovery_drift.py tests/test_trust_boundary.py
```

Expected: all pass.

### Task 4: Final Verification

**Files:**
- No new files.

- [x] **Step 1: Run trust sprint verification**

Run:

```bash
uv run pytest -q tests/test_trust_readiness.py tests/test_demo_trust_plane.py tests/test_mcp_trust_mode.py tests/test_permits.py tests/test_receipts.py tests/test_audit_chain.py tests/test_me_trust_ledger.py tests/test_discovery_drift.py tests/test_trust_boundary.py
```

Expected: all pass.

- [x] **Step 2: Inspect diff**

Run:

```bash
git diff --stat
git diff -- app/trust/readiness.py app/routers/trust_readiness.py tests/test_trust_readiness.py
```

Expected: focused changes only.
