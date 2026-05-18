# Agent Operations Control Plane Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the first shippable agent-operations spine real: scoped agent key -> MCP tool invocation -> policy decision -> billing ledger -> durable audit -> operator inspection.

**Architecture:** Add a small policy decision module and durable audit store, then route both MCP invocation surfaces through one shared invocation helper. The helper resolves the service, evaluates wallet authority, records a policy decision, charges the wallet, executes the local tool, and persists an audit record with the same identifiers used by tests and operator inspection.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy async sessions, Alembic, Pydantic v2, pytest/anyio, existing `AuthContext`, `AgentMoney`, `ServiceRegistry`, and MCP router.

---

## Scope

This plan implements the first control-plane slice from the North Star spec. It intentionally does not implement A2A, OpenAI Apps SDK descriptors, a full dashboard, or broad compliance language. The output is working, testable software that proves the product loop:

```text
discover -> authenticate -> invoke -> meter -> govern
```

## File Structure

- Create `app/policy/__init__.py`: package exports.
- Create `app/policy/decisions.py`: policy decision dataclass and wallet/tool invocation evaluator.
- Create `app/services/audit_log.py`: async durable audit write/list helpers.
- Create `app/schemas/audit.py`: API response models for operator audit inspection.
- Create `app/routers/audit.py`: bootstrap/admin audit listing route.
- Create `migrations/versions/014_control_plane_audit.py`: durable audit table.
- Modify `app/db/models.py`: add `ControlPlaneAuditEventModel`.
- Modify `app/routers/mcp.py`: route `/mcp/messages` and `/mcp/tools/{service_id}/invoke` through one invocation helper.
- Modify `app/main.py`: include audit router.
- Modify `tests/conftest.py`: clean audit table between tests.
- Modify `tests/test_mcp_generator.py`: add `/mcp/messages` auth regression tests.
- Create `tests/test_discovery_drift.py`: contract checks for discovery surfaces that describe MCP, auth, and simulation truth.

---

### Task 1: Add Policy Decision Primitives

**Files:**
- Create: `app/policy/__init__.py`
- Create: `app/policy/decisions.py`
- Test: `tests/test_policy_decisions.py`

- [ ] **Step 1: Write the failing policy tests**

Create `tests/test_policy_decisions.py`:

```python
from app.core.auth import AuthContext
from app.policy.decisions import evaluate_tool_invocation


def test_bootstrap_admin_can_invoke_for_any_wallet():
    auth = AuthContext(source="env", raw_key="test-key", is_bootstrap_admin=True)

    decision = evaluate_tool_invocation(
        auth=auth,
        wallet_id="wallet-any",
        tool_name="echo",
        estimated_cost=2.0,
        request_id="req-1",
    )

    assert decision.allowed is True
    assert decision.reason == "allowed"
    assert decision.wallet_id == "wallet-any"
    assert decision.tool_name == "echo"
    assert decision.estimated_cost == 2.0
    assert decision.request_id == "req-1"
    assert decision.decision_id.startswith("pol-")


def test_wallet_key_can_invoke_for_own_wallet():
    auth = AuthContext(
        source="db",
        raw_key="runtime-key",
        key_id="key-1",
        wallet_id="wallet-1",
    )

    decision = evaluate_tool_invocation(
        auth=auth,
        wallet_id="wallet-1",
        tool_name="echo",
        estimated_cost=1.0,
        request_id="req-2",
    )

    assert decision.allowed is True
    assert decision.reason == "allowed"
    assert decision.key_id == "key-1"


def test_wallet_key_cannot_invoke_for_other_wallet():
    auth = AuthContext(
        source="db",
        raw_key="runtime-key",
        key_id="key-1",
        wallet_id="wallet-1",
    )

    decision = evaluate_tool_invocation(
        auth=auth,
        wallet_id="wallet-2",
        tool_name="echo",
        estimated_cost=1.0,
        request_id="req-3",
    )

    assert decision.allowed is False
    assert decision.reason == "wallet_access_denied"
    assert decision.wallet_id == "wallet-2"
```

- [ ] **Step 2: Run the policy tests to verify they fail**

Run:

```bash
pytest tests/test_policy_decisions.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.policy'`.

- [ ] **Step 3: Add the policy package exports**

Create `app/policy/__init__.py`:

```python
from .decisions import PolicyDecision, evaluate_tool_invocation

__all__ = ["PolicyDecision", "evaluate_tool_invocation"]
```

- [ ] **Step 4: Add the policy decision implementation**

Create `app/policy/decisions.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
import uuid

from app.core.auth import AuthContext


@dataclass(frozen=True)
class PolicyDecision:
    decision_id: str
    allowed: bool
    reason: str
    wallet_id: str
    tool_name: str
    auth_source: str
    key_id: str | None
    estimated_cost: float | None
    request_id: str | None

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_tool_invocation(
    *,
    auth: AuthContext,
    wallet_id: str,
    tool_name: str,
    estimated_cost: float | None,
    request_id: str | None,
) -> PolicyDecision:
    if auth.is_bootstrap_admin or auth.wallet_id == wallet_id:
        return PolicyDecision(
            decision_id=f"pol-{uuid.uuid4().hex[:16]}",
            allowed=True,
            reason="allowed",
            wallet_id=wallet_id,
            tool_name=tool_name,
            auth_source=auth.source,
            key_id=auth.key_id,
            estimated_cost=estimated_cost,
            request_id=request_id,
        )

    return PolicyDecision(
        decision_id=f"pol-{uuid.uuid4().hex[:16]}",
        allowed=False,
        reason="wallet_access_denied",
        wallet_id=wallet_id,
        tool_name=tool_name,
        auth_source=auth.source,
        key_id=auth.key_id,
        estimated_cost=estimated_cost,
        request_id=request_id,
    )
```

- [ ] **Step 5: Run the policy tests to verify they pass**

Run:

```bash
pytest tests/test_policy_decisions.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add app/policy/__init__.py app/policy/decisions.py tests/test_policy_decisions.py
git commit -m "feat: add policy decision primitives"
```

---

### Task 2: Add Durable Control-Plane Audit Storage

**Files:**
- Modify: `app/db/models.py`
- Create: `migrations/versions/014_control_plane_audit.py`
- Create: `app/services/audit_log.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_audit_log.py`

- [ ] **Step 1: Write the failing audit service test**

Create `tests/test_audit_log.py`:

```python
import pytest

from app.services.audit_log import list_audit_events, record_audit_event


@pytest.mark.anyio
async def test_record_and_list_audit_events(clean_database):
    event = await record_audit_event(
        event="mcp.invoke",
        wallet_id="wallet-1",
        tool="echo",
        endpoint="/mcp/messages",
        auth_source="db",
        key_id="key-1",
        policy_decision_id="pol-1",
        request_id="req-1",
        ok=True,
        metadata={"cost": 2.0},
    )

    events = await list_audit_events(wallet_id="wallet-1")

    assert event.event_id.startswith("audit-")
    assert len(events) == 1
    assert events[0].event == "mcp.invoke"
    assert events[0].wallet_id == "wallet-1"
    assert events[0].tool == "echo"
    assert events[0].policy_decision_id == "pol-1"
    assert events[0].metadata["cost"] == 2.0
```

- [ ] **Step 2: Run the audit test to verify it fails**

Run:

```bash
pytest tests/test_audit_log.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.audit_log'`.

- [ ] **Step 3: Add the SQLModel audit model**

Add this class to `app/db/models.py` after `OptimizerTelemetryModel`:

```python
class ControlPlaneAuditEventModel(SQLModel, table=True):
    """Durable control-plane audit event for agent operations."""

    __tablename__ = "control_plane_audit_events"

    event_id: str = Field(primary_key=True, max_length=50)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    event: str = Field(max_length=128, index=True)
    wallet_id: Optional[str] = Field(default=None, max_length=64, index=True)
    tool: Optional[str] = Field(default=None, max_length=128, index=True)
    endpoint: Optional[str] = Field(default=None, max_length=256, index=True)
    auth_source: Optional[str] = Field(default=None, max_length=32)
    key_id: Optional[str] = Field(default=None, max_length=64, index=True)
    policy_decision_id: Optional[str] = Field(default=None, max_length=64, index=True)
    request_id: Optional[str] = Field(default=None, max_length=100, index=True)
    ok: bool = Field(default=True, index=True)
    error: Optional[str] = Field(default=None)
    metadata_json: Optional[str] = Field(default=None)
```

- [ ] **Step 4: Add the Alembic migration**

Create `migrations/versions/014_control_plane_audit.py`:

```python
"""Durable control-plane audit events.

Revision ID: 014_control_plane_audit
Revises: 013_optimizer_telemetry
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "014_control_plane_audit"
down_revision: Union[str, None] = "013_optimizer_telemetry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "control_plane_audit_events",
        sa.Column("event_id", sa.String(length=50), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("event", sa.String(length=128), nullable=False),
        sa.Column("wallet_id", sa.String(length=64), nullable=True),
        sa.Column("tool", sa.String(length=128), nullable=True),
        sa.Column("endpoint", sa.String(length=256), nullable=True),
        sa.Column("auth_source", sa.String(length=32), nullable=True),
        sa.Column("key_id", sa.String(length=64), nullable=True),
        sa.Column("policy_decision_id", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_control_plane_audit_events_created_at", "control_plane_audit_events", ["created_at"])
    op.create_index("ix_control_plane_audit_events_event", "control_plane_audit_events", ["event"])
    op.create_index("ix_control_plane_audit_events_wallet_id", "control_plane_audit_events", ["wallet_id"])
    op.create_index("ix_control_plane_audit_events_tool", "control_plane_audit_events", ["tool"])
    op.create_index("ix_control_plane_audit_events_endpoint", "control_plane_audit_events", ["endpoint"])
    op.create_index("ix_control_plane_audit_events_key_id", "control_plane_audit_events", ["key_id"])
    op.create_index("ix_control_plane_audit_events_policy_decision_id", "control_plane_audit_events", ["policy_decision_id"])
    op.create_index("ix_control_plane_audit_events_request_id", "control_plane_audit_events", ["request_id"])
    op.create_index("ix_control_plane_audit_events_ok", "control_plane_audit_events", ["ok"])


def downgrade() -> None:
    op.drop_index("ix_control_plane_audit_events_ok", table_name="control_plane_audit_events")
    op.drop_index("ix_control_plane_audit_events_request_id", table_name="control_plane_audit_events")
    op.drop_index("ix_control_plane_audit_events_policy_decision_id", table_name="control_plane_audit_events")
    op.drop_index("ix_control_plane_audit_events_key_id", table_name="control_plane_audit_events")
    op.drop_index("ix_control_plane_audit_events_endpoint", table_name="control_plane_audit_events")
    op.drop_index("ix_control_plane_audit_events_tool", table_name="control_plane_audit_events")
    op.drop_index("ix_control_plane_audit_events_wallet_id", table_name="control_plane_audit_events")
    op.drop_index("ix_control_plane_audit_events_event", table_name="control_plane_audit_events")
    op.drop_index("ix_control_plane_audit_events_created_at", table_name="control_plane_audit_events")
    op.drop_table("control_plane_audit_events")
```

- [ ] **Step 5: Add the audit service**

Create `app/services/audit_log.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any
import uuid

from sqlalchemy import desc, select

from app.db.database import get_session_factory
from app.db.models import ControlPlaneAuditEventModel


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    created_at: datetime
    event: str
    wallet_id: str | None
    tool: str | None
    endpoint: str | None
    auth_source: str | None
    key_id: str | None
    policy_decision_id: str | None
    request_id: str | None
    ok: bool
    error: str | None
    metadata: dict[str, Any]


def _to_event(row: ControlPlaneAuditEventModel) -> AuditEvent:
    metadata: dict[str, Any] = {}
    if row.metadata_json:
        metadata = json.loads(row.metadata_json)
    return AuditEvent(
        event_id=row.event_id,
        created_at=row.created_at,
        event=row.event,
        wallet_id=row.wallet_id,
        tool=row.tool,
        endpoint=row.endpoint,
        auth_source=row.auth_source,
        key_id=row.key_id,
        policy_decision_id=row.policy_decision_id,
        request_id=row.request_id,
        ok=row.ok,
        error=row.error,
        metadata=metadata,
    )


async def record_audit_event(
    *,
    event: str,
    wallet_id: str | None = None,
    tool: str | None = None,
    endpoint: str | None = None,
    auth_source: str | None = None,
    key_id: str | None = None,
    policy_decision_id: str | None = None,
    request_id: str | None = None,
    ok: bool = True,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    model = ControlPlaneAuditEventModel(
        event_id=f"audit-{uuid.uuid4().hex[:16]}",
        event=event,
        wallet_id=wallet_id,
        tool=tool,
        endpoint=endpoint,
        auth_source=auth_source,
        key_id=key_id,
        policy_decision_id=policy_decision_id,
        request_id=request_id,
        ok=ok,
        error=error,
        metadata_json=json.dumps(metadata or {}, default=str),
    )
    factory = get_session_factory()
    async with factory() as session:
        session.add(model)
        await session.commit()
        await session.refresh(model)
    return _to_event(model)


async def list_audit_events(
    *,
    wallet_id: str | None = None,
    key_id: str | None = None,
    tool: str | None = None,
    request_id: str | None = None,
    limit: int = 50,
) -> list[AuditEvent]:
    stmt = select(ControlPlaneAuditEventModel).order_by(
        desc(ControlPlaneAuditEventModel.created_at)
    ).limit(limit)
    if wallet_id:
        stmt = stmt.where(ControlPlaneAuditEventModel.wallet_id == wallet_id)
    if key_id:
        stmt = stmt.where(ControlPlaneAuditEventModel.key_id == key_id)
    if tool:
        stmt = stmt.where(ControlPlaneAuditEventModel.tool == tool)
    if request_id:
        stmt = stmt.where(ControlPlaneAuditEventModel.request_id == request_id)

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(stmt)
        return [_to_event(row) for row in result.scalars().all()]
```

- [ ] **Step 6: Clean audit rows between tests**

In `tests/conftest.py`, add this delete before `DELETE FROM optimizer_telemetry`:

```python
        await session.execute(text("DELETE FROM control_plane_audit_events"))
```

- [ ] **Step 7: Run the audit test to verify it passes**

Run:

```bash
pytest tests/test_audit_log.py -q
```

Expected: `1 passed`.

- [ ] **Step 8: Run the migration test**

Run:

```bash
pytest tests/test_migrations.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/db/models.py app/services/audit_log.py migrations/versions/014_control_plane_audit.py tests/conftest.py tests/test_audit_log.py
git commit -m "feat: persist control plane audit events"
```

---

### Task 3: Add Operator Audit Inspection API

**Files:**
- Create: `app/schemas/audit.py`
- Create: `app/routers/audit.py`
- Modify: `app/main.py`
- Test: `tests/test_audit_routes.py`

- [ ] **Step 1: Write the failing audit route tests**

Create `tests/test_audit_routes.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.audit_log import record_audit_event


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_bootstrap_admin_can_list_audit_events(client, clean_database):
    await record_audit_event(
        event="mcp.invoke",
        wallet_id="wallet-1",
        tool="echo",
        endpoint="/mcp/messages",
        auth_source="db",
        key_id="key-1",
        policy_decision_id="pol-1",
        request_id="req-1",
        ok=True,
        metadata={"cost": 2.0},
    )

    response = await client.get(
        "/v1/audit/events?wallet_id=wallet-1",
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["events"][0]["wallet_id"] == "wallet-1"
    assert data["events"][0]["metadata"]["cost"] == 2.0


@pytest.mark.anyio
async def test_db_wallet_key_cannot_list_audit_events(client, clean_database):
    response = await client.get(
        "/v1/audit/events",
        headers={"X-API-Key": "not-a-real-db-key"},
    )

    assert response.status_code in {403, 503}
```

- [ ] **Step 2: Run the audit route tests to verify they fail**

Run:

```bash
pytest tests/test_audit_routes.py -q
```

Expected: FAIL with `404 Not Found` for `/v1/audit/events`.

- [ ] **Step 3: Add audit schemas**

Create `app/schemas/audit.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    event_id: str
    created_at: datetime
    event: str
    wallet_id: str | None
    tool: str | None
    endpoint: str | None
    auth_source: str | None
    key_id: str | None
    policy_decision_id: str | None
    request_id: str | None
    ok: bool
    error: str | None
    metadata: dict[str, Any]


class AuditEventListResponse(BaseModel):
    events: list[AuditEventResponse]
    total: int
```

- [ ] **Step 4: Add the audit router**

Create `app/routers/audit.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.auth import AuthContext, get_auth_context
from app.schemas.audit import AuditEventListResponse, AuditEventResponse
from app.services.audit_log import list_audit_events

router = APIRouter(prefix="/v1/audit", tags=["Control Plane Audit"])


@router.get("/events", response_model=AuditEventListResponse)
async def get_audit_events(
    wallet_id: str | None = Query(None),
    key_id: str | None = Query(None),
    tool: str | None = Query(None),
    request_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
) -> AuditEventListResponse:
    auth.require_bootstrap_admin()
    events = await list_audit_events(
        wallet_id=wallet_id,
        key_id=key_id,
        tool=tool,
        request_id=request_id,
        limit=limit,
    )
    return AuditEventListResponse(
        events=[AuditEventResponse(**event.__dict__) for event in events],
        total=len(events),
    )
```

- [ ] **Step 5: Register the audit router**

In `app/main.py`, add `audit` to the router imports:

```python
    audit,
```

Then include it near other operator/control-plane routers:

```python
app.include_router(audit.router)
```

- [ ] **Step 6: Run the audit route tests to verify they pass**

Run:

```bash
pytest tests/test_audit_routes.py -q
```

Expected: `2 passed`.

- [ ] **Step 7: Commit**

```bash
git add app/schemas/audit.py app/routers/audit.py app/main.py tests/test_audit_routes.py
git commit -m "feat: add audit inspection API"
```

---

### Task 4: Unify MCP Invocation Semantics

**Files:**
- Modify: `app/routers/mcp.py`
- Test: `tests/test_mcp_generator.py`

- [ ] **Step 1: Add failing `/mcp/messages` auth, wallet, charge, and audit tests**

Insert this helper immediately before `class TestMcpInvokeRoute` in `tests/test_mcp_generator.py`:

```python
async def _create_funded_agent_wallet(client: AsyncClient, agent_id: str) -> str:
    headers = {"X-API-Key": "test-key"}
    sponsor_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": f"{agent_id} sponsor",
            "email": f"{agent_id}@example.com",
            "initial_credits": 10000,
            "require_kyc": False,
        },
        headers=headers,
    )
    assert sponsor_resp.status_code == 201
    sponsor_wallet_id = sponsor_resp.json()["wallet_id"]

    agent_resp = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor_wallet_id,
            "agent_id": agent_id,
            "budget_credits": 1000,
            "daily_limit": 250,
        },
        headers=headers,
    )
    assert agent_resp.status_code == 201
    return agent_resp.json()["wallet_id"]
```

Replace the current `test_invoke_tool_accepts_api_key_header` method and add the JSON-RPC regression tests inside `class TestMcpInvokeRoute`:

```python
    @pytest.mark.anyio
    async def test_invoke_tool_accepts_api_key_header(self, clean_database):
        registry = get_service_registry()

        def echo_tool(value: str = "ok") -> dict:
            return {"value": value}

        registry.register_local(
            service_id="header-auth-echo",
            name="Header Auth Echo",
            description="Echo for auth route testing",
            category=ServiceCategory.AGENT_COMMS,
            func=echo_tool,
            credits_per_unit=2.0,
            unit_name="call",
        )

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                wallet_id = await _create_funded_agent_wallet(
                    client,
                    "header-auth-agent",
                )
                response = await client.post(
                    "/mcp/tools/header-auth-echo/invoke",
                    json={
                        "name": "header-auth-echo",
                        "arguments": {"value": "hello"},
                        "mcp_context": {"wallet_id": wallet_id},
                    },
                    headers={"X-API-Key": "test-key"},
                )

            assert response.status_code == 200
            assert response.json()["isError"] is False
        finally:
            registry.unregister_local("header-auth-echo")

    @pytest.mark.anyio
    async def test_messages_tools_call_requires_api_key_header(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/mcp/messages",
                json={
                    "jsonrpc": "2.0",
                    "id": "call-1",
                    "method": "tools/call",
                    "params": {
                        "name": "anything",
                        "arguments": {},
                        "mcpContext": {"wallet_id": "wallet-test"},
                    },
                },
            )

        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_messages_tools_call_rejects_cross_wallet_db_key(self, clean_database):
        registry = get_service_registry()

        def echo_tool(value: str = "ok") -> dict:
            return {"value": value}

        registry.register_local(
            service_id="cross-wallet-echo",
            name="Cross Wallet Echo",
            description="Echo for cross-wallet auth testing",
            category=ServiceCategory.AGENT_COMMS,
            func=echo_tool,
            credits_per_unit=1.0,
            unit_name="call",
        )

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                owned_wallet_id = await _create_funded_agent_wallet(
                    client,
                    "owned-runtime-agent",
                )
                other_wallet_id = await _create_funded_agent_wallet(
                    client,
                    "other-runtime-agent",
                )
                key_resp = await client.post(
                    "/v1/api-keys",
                    json={
                        "wallet_id": owned_wallet_id,
                        "key_name": "runtime",
                        "expires_in_days": 30,
                    },
                    headers={"X-API-Key": "test-key"},
                )
                assert key_resp.status_code == 201

                response = await client.post(
                    "/mcp/messages",
                    json={
                        "jsonrpc": "2.0",
                        "id": "call-1",
                        "method": "tools/call",
                        "params": {
                            "name": "cross-wallet-echo",
                            "arguments": {"value": "hello"},
                            "mcpContext": {"wallet_id": other_wallet_id},
                        },
                    },
                    headers={"X-API-Key": key_resp.json()["api_key"]},
                )

            assert response.status_code == 200
            payload = response.json()
            assert payload["error"]["code"] == -32003
            assert "wallet_access_denied" in payload["error"]["message"]
        finally:
            registry.unregister_local("cross-wallet-echo")

    @pytest.mark.anyio
    async def test_messages_tools_call_charges_wallet_and_records_audit(self, clean_database):
        registry = get_service_registry()

        def paid_echo(value: str = "ok") -> dict:
            return {"value": value}

        registry.register_local(
            service_id="jsonrpc-paid-echo",
            name="JSON-RPC Paid Echo",
            description="Echo for JSON-RPC billing and audit testing",
            category=ServiceCategory.AGENT_COMMS,
            func=paid_echo,
            credits_per_unit=2.0,
            unit_name="call",
        )

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                wallet_id = await _create_funded_agent_wallet(
                    client,
                    "jsonrpc-paid-agent",
                )
                response = await client.post(
                    "/mcp/messages",
                    json={
                        "jsonrpc": "2.0",
                        "id": "paid-call-1",
                        "method": "tools/call",
                        "params": {
                            "name": "jsonrpc-paid-echo",
                            "arguments": {"value": "hello"},
                            "mcpContext": {"wallet_id": wallet_id},
                        },
                    },
                    headers={"X-API-Key": "test-key"},
                )
                assert response.status_code == 200
                assert response.json()["result"]["isError"] is False

                ledger_resp = await client.get(
                    f"/v1/billing/ledger/{wallet_id}",
                    headers={"X-API-Key": "test-key"},
                )
                assert ledger_resp.status_code == 200
                assert any(
                    "jsonrpc-paid-echo" in entry.get("description", "")
                    for entry in ledger_resp.json()["entries"]
                )

                audit_resp = await client.get(
                    f"/v1/audit/events?wallet_id={wallet_id}&tool=jsonrpc-paid-echo",
                    headers={"X-API-Key": "test-key"},
                )
                assert audit_resp.status_code == 200
                audit_events = audit_resp.json()["events"]
                assert len(audit_events) == 1
                assert audit_events[0]["metadata"]["transport"] == "jsonrpc"
        finally:
            registry.unregister_local("jsonrpc-paid-echo")
```

- [ ] **Step 2: Run the new MCP tests to verify they fail**

Run:

```bash
pytest tests/test_mcp_generator.py::TestMcpInvokeRoute -q
```

Expected: At least `test_messages_tools_call_requires_api_key_header` fails because `/mcp/messages` does not require header auth yet.

- [ ] **Step 3: Update imports in `app/routers/mcp.py`**

Add these imports:

```python
from decimal import Decimal

from ..policy.decisions import PolicyDecision, evaluate_tool_invocation
from ..services.agent_money import AgentMoney, get_agent_money
from ..services.audit_log import record_audit_event
from ..schemas.billing import InsufficientFundsResponse
```

Keep the existing `ServiceCategory` import.

- [ ] **Step 4: Change `/mcp/messages` to require auth and billing dependencies**

Change the route signature:

```python
async def handle_messages(
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
) -> JSONResponse:
```

Change the `tools/call` branch to pass those dependencies:

```python
            result = await _handle_tools_call(
                params,
                auth=auth,
                money=money,
                transport="jsonrpc",
                endpoint="/mcp/messages",
                request_id=str(request_id) if request_id is not None else None,
            )
```

- [ ] **Step 5: Replace `_handle_tools_call` with a shared helper**

Replace the current `_handle_tools_call` function with this implementation:

```python
async def _execute_registered_tool(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    wallet_id: str,
    auth: AuthContext,
    money: AgentMoney,
    transport: str,
    endpoint: str,
    request_id: str | None,
) -> dict:
    if not tool_name:
        raise ValueError("Missing tool name")
    if not wallet_id:
        raise ValueError("Missing wallet_id in mcpContext")

    registry = get_service_registry()
    service = registry.get_local(tool_name)
    if not service:
        service = await registry.get_persistent(tool_name)
    if not service:
        raise ValueError(f"Tool not found: {tool_name}")

    func = registry.get_local_func(tool_name)
    if not func:
        raise ValueError(f"Tool not executable: {tool_name}")

    estimated_cost = float(service.get("credits_per_unit", 1.0))
    decision = evaluate_tool_invocation(
        auth=auth,
        wallet_id=wallet_id,
        tool_name=tool_name,
        estimated_cost=estimated_cost,
        request_id=request_id,
    )
    if not decision.allowed:
        await _audit_mcp_invocation(
            decision=decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error=decision.reason,
        )
        raise PermissionError(decision.reason)

    category = ServiceCategory(service.get("category", ServiceCategory.PLATFORM_FEE.value))
    charge_result = await money.charge(
        wallet_id=wallet_id,
        service_category=category,
        units=Decimal("1"),
        request_path=endpoint,
        description=f"MCP {transport} invoke {tool_name}",
    )
    if isinstance(charge_result, InsufficientFundsResponse):
        await _audit_mcp_invocation(
            decision=decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error="insufficient_funds",
        )
        raise ValueError("insufficient_funds")

    import asyncio

    try:
        if asyncio.iscoroutinefunction(func):
            result = await func(**arguments)
        else:
            result = func(**arguments)
    except Exception as exc:
        await _audit_mcp_invocation(
            decision=decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error=str(exc),
        )
        raise

    await _audit_mcp_invocation(
        decision=decision,
        endpoint=endpoint,
        transport=transport,
        ok=True,
        error=None,
    )
    return {
        "content": [{"type": "text", "text": json.dumps(result, default=str)}],
        "isError": False,
    }


async def _audit_mcp_invocation(
    *,
    decision: PolicyDecision,
    endpoint: str,
    transport: str,
    ok: bool,
    error: str | None,
) -> None:
    record_audit(
        "mcp.invoke",
        tool=decision.tool_name,
        wallet_id=decision.wallet_id,
        transport=transport,
        auth_source=decision.auth_source,
        key_id=decision.key_id,
        policy_decision_id=decision.decision_id,
        request_id=decision.request_id,
        ok=ok,
        error=error,
    )
    await record_audit_event(
        event="mcp.invoke",
        wallet_id=decision.wallet_id,
        tool=decision.tool_name,
        endpoint=endpoint,
        auth_source=decision.auth_source,
        key_id=decision.key_id,
        policy_decision_id=decision.decision_id,
        request_id=decision.request_id,
        ok=ok,
        error=error,
        metadata={
            "transport": transport,
            "estimated_cost": decision.estimated_cost,
            "policy_reason": decision.reason,
        },
    )


async def _handle_tools_call(
    params: dict,
    *,
    auth: AuthContext,
    money: AgentMoney,
    transport: str,
    endpoint: str,
    request_id: str | None,
) -> dict:
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    mcp_context = params.get("mcpContext", {})
    wallet_id = mcp_context.get("wallet_id")
    return await _execute_registered_tool(
        tool_name=tool_name,
        arguments=arguments,
        wallet_id=wallet_id,
        auth=auth,
        money=money,
        transport=transport,
        endpoint=endpoint,
        request_id=request_id,
    )
```

- [ ] **Step 6: Map permission errors to JSON-RPC forbidden errors**

In the `tools/call` exception branch inside `handle_messages`, add this before the generic `except Exception as e` branch:

```python
        except PermissionError as e:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32003,
                        "message": str(e),
                    },
                }
            )
```

- [ ] **Step 7: Route `/mcp/tools/{service_id}/invoke` through the same helper**

Change the `invoke_tool` signature to inject the same billing service used by `/mcp/messages`:

```python
async def invoke_tool(
    service_id: str,
    request: ToolCallRequest,
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
) -> ToolCallResponse:
```

Replace the body after wallet resolution in `invoke_tool` with:

```python
    if not mcp_context.wallet_id:
        raise HTTPException(status_code=400, detail="Missing wallet_id")

    try:
        result = await _execute_registered_tool(
            tool_name=service_id,
            arguments=request.arguments,
            wallet_id=mcp_context.wallet_id,
            auth=auth,
            money=money,
            transport="http",
            endpoint=f"/mcp/tools/{service_id}/invoke",
            request_id=None,
        )
        return ToolCallResponse(**result)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        message = str(exc)
        if message == "insufficient_funds":
            raise HTTPException(status_code=402, detail=message)
        if message.startswith("Tool not found"):
            raise HTTPException(status_code=404, detail=message)
        if message.startswith("Tool not executable"):
            raise HTTPException(status_code=501, detail=message)
        raise HTTPException(status_code=400, detail=message)
    except Exception as exc:
        logger.error(f"Tool invocation failed: {exc}")
        return ToolCallResponse(
            content=[{"type": "text", "text": f"Error: {str(exc)}"}],
            isError=True,
        )
```

- [ ] **Step 8: Run the MCP route tests**

Run:

```bash
pytest tests/test_mcp_generator.py::TestMcpInvokeRoute -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/routers/mcp.py tests/test_mcp_generator.py
git commit -m "feat: unify MCP invocation controls"
```

---

### Task 5: Prove The Scoped-Key Golden Path Through MCP Invocation

**Files:**
- Modify: `tests/test_golden_path.py`
- Test: `tests/test_golden_path.py`

- [ ] **Step 1: Extend the golden-path test with a billable MCP tool call**

In `tests/test_golden_path.py`, add imports:

```python
from app.schemas.billing import ServiceCategory
from app.services.service_registry import get_service_registry
```

Inside `test_wallet_scoped_agent_golden_path`, before the `mcp_resp = await client.get("/mcp/tools.json", headers=agent_headers)` block, register a local test tool:

```python
    registry = get_service_registry()

    def golden_path_echo(message: str = "ok") -> dict:
        return {"message": message}

    registry.register_local(
        service_id="golden-path-echo",
        name="Golden Path Echo",
        description="Echo tool for golden path MCP invocation",
        category=ServiceCategory.AGENT_COMMS,
        func=golden_path_echo,
        credits_per_unit=2.0,
        unit_name="call",
    )
```

After the `mcp_resp` assertions, add the JSON-RPC invocation:

```python
    try:
        invoke_resp = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": "golden-call-1",
                "method": "tools/call",
                "params": {
                    "name": "golden-path-echo",
                    "arguments": {"message": "hello"},
                    "mcpContext": {
                        "wallet_id": agent_wallet_id,
                        "request_path": "POST /mcp/messages",
                    },
                },
            },
            headers=agent_headers,
        )
        assert invoke_resp.status_code == 200
        invoke_payload = invoke_resp.json()
        assert "result" in invoke_payload
        assert invoke_payload["result"]["isError"] is False
    finally:
        registry.unregister_local("golden-path-echo")
```

After the existing ledger call, assert the MCP charge was committed:

```python
    ledger_entries = ledger_resp.json()["entries"]
    assert any(
        entry["service_category"] == "agent_comms"
        and "golden-path-echo" in entry.get("description", "")
        for entry in ledger_entries
    )
```

Then inspect audit events with the bootstrap key:

```python
    audit_resp = await client.get(
        f"/v1/audit/events?wallet_id={agent_wallet_id}&tool=golden-path-echo",
        headers=bootstrap_headers,
    )
    assert audit_resp.status_code == 200
    audit_events = audit_resp.json()["events"]
    assert len(audit_events) == 1
    assert audit_events[0]["policy_decision_id"].startswith("pol-")
    assert audit_events[0]["metadata"]["transport"] == "jsonrpc"
```

- [ ] **Step 2: Run the golden-path test to verify it passes**

Run:

```bash
pytest tests/test_golden_path.py -q
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_path.py
git commit -m "test: prove scoped MCP golden path"
```

---

### Task 6: Add Discovery Drift Contract Tests

**Files:**
- Create: `tests/test_discovery_drift.py`
- Test: `tests/test_discovery_drift.py`

- [ ] **Step 1: Write discovery drift tests**

Create `tests/test_discovery_drift.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_agent_manifest_points_to_canonical_control_plane_surfaces(client):
    response = await client.get("/.well-known/agent.json")

    assert response.status_code == 200
    data = response.json()
    endpoints = data["endpoints"]
    agent_first = data["agent_first"]

    assert endpoints["billing"] == "/v1/billing"
    assert endpoints["mcp"] == "/mcp"
    assert endpoints["health"] == "/health"
    assert endpoints["agent_manifest"] == "/.well-known/agent.json"
    assert endpoints["llm_docs"] == "/llm.txt"
    assert "/mcp/tools.json" in agent_first["bootstrap_sequence"]
    assert agent_first["simulation_and_dependency_truth"] == "/health/dependencies"


@pytest.mark.anyio
async def test_discover_and_agent_manifest_share_agent_first_contract(client):
    agent_response = await client.get("/.well-known/agent.json")
    discover_response = await client.get("/v1/discover")

    assert agent_response.status_code == 200
    assert discover_response.status_code == 200
    assert agent_response.json()["agent_first"] == discover_response.json()["agent_first"]


@pytest.mark.anyio
async def test_openapi_contains_core_control_plane_routes(client):
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/mcp/messages" in paths
    assert "/mcp/tools/{service_id}/invoke" in paths
    assert "/v1/billing/charge" in paths
    assert "/v1/audit/events" in paths
    assert "/v1/planner/optimize" in paths


@pytest.mark.anyio
async def test_mcp_manifest_tools_include_pricing_and_simulation_truth(client):
    response = await client.get("/mcp/tools.json")

    assert response.status_code == 200
    tools = response.json()["tools"]
    assert tools
    for tool in tools:
        annotations = tool["annotations"]
        assert "creditsPerCall" in annotations
        assert "unitName" in annotations
        assert "simulation" in annotations
        assert "integrationStatus" in annotations
```

- [ ] **Step 2: Run discovery drift tests**

Run:

```bash
pytest tests/test_discovery_drift.py -q
```

Expected: PASS after the audit route from Task 3 is registered.

- [ ] **Step 3: Commit**

```bash
git add tests/test_discovery_drift.py
git commit -m "test: add discovery drift contracts"
```

---

### Task 7: Return Policy Reasons From Planner Responses

**Files:**
- Modify: `app/optimizer/planner.py`
- Modify: `app/schemas/optimizer.py`
- Modify: `tests/test_planner_constraints.py`
- Modify: `docs/openapi.json`

- [ ] **Step 1: Add failing planner policy reason assertions**

In `tests/test_planner_constraints.py`, update `test_risk_budget_enforced_by_tier`:

```python
def test_risk_budget_enforced_by_tier():
    state = _state(tier="low")
    req = OptimizerRequest(state=state)
    candidates = [
        {"id": "safe", "service": "svc1", "credit_cost": 1, "latency_ms": 10, "risk_score": 0.02, "expected_value": 1, "reliability": 1.0},
        {"id": "risky", "service": "svc1", "credit_cost": 1, "latency_ms": 10, "risk_score": 0.2, "expected_value": 10, "reliability": 1.0},
    ]
    out = planner.optimize_action_set(state, candidates, req)
    ids = {x["id"] for x in out["selected_actions"]}
    assert "risky" not in ids
    rejected = {x["id"]: x["reason"] for x in out["rejected_actions"]}
    assert rejected["risky"] == "risk_budget_exceeded"
```

- [ ] **Step 2: Run planner tests to verify failure**

Run:

```bash
pytest tests/test_planner_constraints.py -q
```

Expected: FAIL because the greedy/solver constraint rejection is not currently included in `rejected_actions`.

- [ ] **Step 3: Add policy reason schema field**

In `app/schemas/optimizer.py`, add a new field to `OptimizerResponse`:

```python
    policy_reasons: Dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 4: Track planner policy reasons**

In `app/optimizer/planner.py`, update `_pack_response` signature:

```python
def _pack_response(
    status: str,
    selected: list[dict],
    rejected: list[dict],
    state: OptimizerState,
    risk_budget: float,
    lambdas: dict[str, float],
    policy_reasons: dict[str, str] | None = None,
) -> dict:
```

Add to returned dict:

```python
        "policy_reasons": policy_reasons or {},
```

Add a helper:

```python
def _constraint_rejections(
    candidates: list[dict],
    selected: list[dict],
    state: OptimizerState,
    risk_budget: float,
) -> list[dict]:
    selected_ids = {a.get("id") for a in selected}
    rejected: list[dict] = []
    for action in candidates:
        if action.get("id") in selected_ids:
            continue
        if action.get("credit_cost", 0.0) > state.remaining_budget:
            rejected.append({"id": action.get("id"), "reason": "budget_exceeded"})
        elif action.get("latency_ms", 0.0) > state.slo_window_seconds * 1000:
            rejected.append({"id": action.get("id"), "reason": "latency_budget_exceeded"})
        elif action.get("risk_score", 0.0) > risk_budget:
            rejected.append({"id": action.get("id"), "reason": "risk_budget_exceeded"})
    return rejected
```

Before each successful `_pack_response`, merge constraint rejections:

```python
                constraint_rejected = _constraint_rejections(
                    admissible,
                    selected,
                    state,
                    risk_budget,
                )
                all_rejected = rejected + constraint_rejected
                policy_reasons = {
                    item["id"]: item["reason"]
                    for item in all_rejected
                    if item.get("id")
                }
                return _pack_response(
                    "Optimal",
                    selected,
                    all_rejected,
                    state,
                    risk_budget,
                    lambdas,
                    policy_reasons,
                )
```

Do the same for the greedy fallback path:

```python
    constraint_rejected = _constraint_rejections(admissible, selected, state, risk_budget)
    all_rejected = rejected + constraint_rejected
    policy_reasons = {
        item["id"]: item["reason"]
        for item in all_rejected
        if item.get("id")
    }
    status = "HeuristicFallback" if selected else "Infeasible"
    return _pack_response(status, selected, all_rejected, state, risk_budget, lambdas, policy_reasons)
```

For the no-admissible path, pass policy reasons from existing rejected actions:

```python
        return _pack_response(
            "Infeasible",
            [],
            rejected,
            state,
            risk_budget,
            lambdas,
            {item["id"]: item["reason"] for item in rejected if item.get("id")},
        )
```

- [ ] **Step 5: Run planner tests**

Run:

```bash
pytest tests/test_planner_constraints.py tests/test_planner_optimize.py -q
```

Expected: PASS.

- [ ] **Step 6: Regenerate OpenAPI**

Run:

```bash
python3 scripts/export_openapi.py
```

Expected: `docs/openapi.json` updates with `policy_reasons`.

- [ ] **Step 7: Commit**

```bash
git add app/optimizer/planner.py app/schemas/optimizer.py tests/test_planner_constraints.py docs/openapi.json
git commit -m "feat: return planner policy reasons"
```

---

### Task 8: Final Verification And Documentation Touches

**Files:**
- Modify: `README.md`
- Modify: `docs/golden-path.md`
- Test: full suite

- [ ] **Step 1: Update README control-plane language**

In `README.md`, add one sentence near the core loop section:

```markdown
The MCP invocation path now records a policy decision, charges the wallet, writes a ledger entry, and persists a control-plane audit event for operator inspection.
```

- [ ] **Step 2: Update golden path docs**

In `docs/golden-path.md`, add a section after the MCP/tool call step:

````markdown
### Inspect the operation record

After a scoped agent invokes a tool, operators can inspect the control-plane record:

```bash
curl "http://localhost:8000/v1/audit/events?wallet_id=$AGENT_WALLET_ID" \
  -H "X-API-Key: $BOOTSTRAP_API_KEY"
```

Each event includes the wallet, credential source, tool, endpoint, policy decision ID, request ID, success flag, error, and metadata such as transport and estimated cost.
````

- [ ] **Step 3: Run targeted tests**

Run:

```bash
pytest tests/test_policy_decisions.py tests/test_audit_log.py tests/test_audit_routes.py tests/test_mcp_generator.py::TestMcpInvokeRoute tests/test_golden_path.py tests/test_discovery_drift.py tests/test_planner_constraints.py tests/test_planner_optimize.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full tests**

Run:

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 5: Review diff**

Run:

```bash
git status --short
git diff --stat HEAD
```

Expected: only planned files changed.

- [ ] **Step 6: Commit docs and final verification**

```bash
git add README.md docs/golden-path.md
git commit -m "docs: document control plane audit path"
```

---

## Self-Review Checklist

- Spec coverage: This plan implements the first shippable slice from the North Star spec: golden path, unified MCP invocation, policy decision primitives, durable audit, operator inspection, discovery drift checks, and planner policy reasons.
- Scope control: A2A, OpenAI Apps SDK, broad dashboard work, compliance claims, and marketplace expansion remain outside this plan.
- Type consistency: `PolicyDecision.decision_id`, `policy_decision_id`, `wallet_id`, `tool`, `request_id`, and `metadata` are used consistently across policy, audit, MCP, and tests.
- Test strategy: Every implementation task begins with a failing test and ends with targeted verification and a commit.
