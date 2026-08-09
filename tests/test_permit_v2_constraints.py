"""Adversarial tests for permit schema v2 constraints.

One test per constraint type, proving both denial and correct metering.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from app.db.models import PermitModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    create_tool_permit,
    provision_agent_wallet,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _register_test_tool(tool_name: str, credits: float = 1.0):
    """Register a simple echo tool for testing."""
    registry = get_service_registry()

    def test_echo(input: str = "ok") -> dict:
        return {"message": input}

    registry.register_local(
        service_id=tool_name,
        name="Test Echo",
        description="Test tool for permit v2 constraints",
        category=ServiceCategory.AGENT_COMMS,
        func=test_echo,
        credits_per_unit=credits,
        unit_name="call",
    )
    return registry


async def _invoke_governed(
    client: AsyncClient,
    *,
    wallet_id: str,
    permit_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    idem_key: str = "invoke-1",
    headers: dict[str, str] | None = None,
) -> Any:
    """Invoke a tool under a governed permit via JSON-RPC."""
    resp = await client.post(
        "/mcp/messages",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
                "mcpContext": {
                    "wallet_id": wallet_id,
                    "permit_id": permit_id,
                    "idempotency_key": idem_key,
                },
            },
        },
        headers=headers or BOOTSTRAP_HEADERS,
    )
    return resp


@pytest.mark.anyio
async def test_max_calls_per_tool_denies_after_limit(client, clean_database):
    """Permit with max_calls_per_tool denies after limit exceeded."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "v2-test-echo"

    _register_test_tool(tool_name, credits=1.0)
    try:
        permit_resp = await client.post(
            "/v1/permits",
            json={
                "issuer_wallet_id": wallet_id,
                "subject_wallet_id": wallet_id,
                "subject_key_id": key_id,
                "allowed_tools": [tool_name],
                "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
                "max_credits": 50,
                "max_calls_per_tool": {tool_name: 2},
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=30)
                ).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "max-calls-permit-1"},
        )
        assert permit_resp.status_code == 201
        permit = permit_resp.json()
        permit_id = permit["permit_id"]

        # First call succeeds
        r1 = await _invoke_governed(
            client,
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool_name=tool_name,
            arguments={"input": "hello1"},
            idem_key="max-call-1",
            headers=agent_headers,
        )
        assert r1.status_code == 200
        body1 = r1.json()
        assert "result" in body1
        assert "receipt" in body1["result"]

        # Second call succeeds
        r2 = await _invoke_governed(
            client,
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool_name=tool_name,
            arguments={"input": "hello2"},
            idem_key="max-call-2",
            headers=agent_headers,
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert "result" in body2

        # Third call fails with permit_max_calls_exceeded
        r3 = await _invoke_governed(
            client,
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool_name=tool_name,
            arguments={"input": "hello3"},
            idem_key="max-call-3",
            headers=agent_headers,
        )
        assert r3.status_code == 200
        body3 = r3.json()
        assert "error" in body3
        assert body3["error"]["code"] == -32003
        assert "permit_max_calls_exceeded" in body3["error"]["message"]

        # Verify spent_credits == 2 (two successful calls at 1 credit each)
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(PermitModel, permit_id)
            assert model is not None
            assert model.spent_credits == Decimal("2")
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_aggregate_value_cap_denies_over_total(client, clean_database):
    """Permit with aggregate_value_cap denies when total would exceed cap."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "v2-test-agg"

    _register_test_tool(tool_name, credits=1.0)
    try:
        permit_resp = await client.post(
            "/v1/permits",
            json={
                "issuer_wallet_id": wallet_id,
                "subject_wallet_id": wallet_id,
                "subject_key_id": key_id,
                "allowed_tools": [tool_name],
                "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
                "max_credits": 100,
                "aggregate_value_cap": 10,
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=30)
                ).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "agg-cap-permit-1"},
        )
        assert permit_resp.status_code == 201
        permit = permit_resp.json()
        permit_id = permit["permit_id"]

        # 10 calls at 1 credit each succeed
        for i in range(1, 11):
            ri = await _invoke_governed(
                client,
                wallet_id=wallet_id,
                permit_id=permit_id,
                tool_name=tool_name,
                arguments={"input": f"call{i}"},
                idem_key=f"agg-{i}",
                headers=agent_headers,
            )
            assert ri.status_code == 200
            body = ri.json()
            assert "error" not in body, f"Call {i} should succeed"

        # 11th call fails: total would be 11 > cap of 10
        r11 = await _invoke_governed(
            client,
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool_name=tool_name,
            arguments={"input": "call11"},
            idem_key="agg-11",
            headers=agent_headers,
        )
        assert r11.status_code == 200
        body11 = r11.json()
        assert "error" in body11
        assert body11["error"]["code"] == -32003
        assert "permit_aggregate_value_cap_exceeded" in body11["error"]["message"]

        # Verify total charged == 10
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(PermitModel, permit_id)
            assert model is not None
            assert model.spent_credits == Decimal("10")
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_forbidden_fields_denies_matching_arg(client, clean_database):
    """Permit with forbidden_fields denies when argument contains forbidden key."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "v2-test-forbidden"

    _register_test_tool(tool_name, credits=1.0)
    try:
        permit_resp = await client.post(
            "/v1/permits",
            json={
                "issuer_wallet_id": wallet_id,
                "subject_wallet_id": wallet_id,
                "subject_key_id": key_id,
                "allowed_tools": [tool_name],
                "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
                "max_credits": 50,
                "forbidden_fields": ["secret_token"],
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=30)
                ).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "forbidden-permit-1"},
        )
        assert permit_resp.status_code == 201
        permit = permit_resp.json()
        permit_id = permit["permit_id"]

        # Call with forbidden field fails
        r = await _invoke_governed(
            client,
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool_name=tool_name,
            arguments={"input": "hello", "secret_token": "xyz"},
            idem_key="forbidden-1",
            headers=agent_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == -32003
        assert "permit_forbidden_field" in body["error"]["message"]
        assert "secret_token" in body["error"]["message"]

        # Verify no budget consumed (denial before reserve)
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(PermitModel, permit_id)
            assert model is not None
            assert model.spent_credits == Decimal("0")

        # Call without forbidden field succeeds
        r2 = await _invoke_governed(
            client,
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool_name=tool_name,
            arguments={"input": "safe"},
            idem_key="forbidden-2",
            headers=agent_headers,
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert "error" not in body2
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_constraints_evaluated_on_receipt(client, clean_database):
    """Successful invoke produces receipt with constraints_evaluated block."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "v2-test-ce"

    _register_test_tool(tool_name, credits=1.0)
    try:
        permit_resp = await client.post(
            "/v1/permits",
            json={
                "issuer_wallet_id": wallet_id,
                "subject_wallet_id": wallet_id,
                "subject_key_id": key_id,
                "allowed_tools": [tool_name],
                "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
                "max_credits": 50,
                "max_calls_per_tool": {tool_name: 5},
                "aggregate_value_cap": 20,
                "forbidden_fields": ["secret_token"],
                "recipient_domain": "allowed.example.com",
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=30)
                ).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "ce-permit-1"},
        )
        assert permit_resp.status_code == 201
        permit = permit_resp.json()
        permit_id = permit["permit_id"]

        r = await _invoke_governed(
            client,
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool_name=tool_name,
            arguments={"input": "test"},
            idem_key="ce-1",
            headers=agent_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" not in body
        receipt = body["result"]["receipt"]
        assert "constraints_evaluated" in receipt
        ce = receipt["constraints_evaluated"]
        assert ce["max_calls_per_tool"] == {tool_name: 5}
        assert ce["aggregate_value_cap"] == "20"
        assert ce["forbidden_fields"] == ["secret_token"]
        assert ce["recipient_domain"] == "allowed.example.com"
    finally:
        get_service_registry().unregister_local(tool_name)


# --- recipient_domain upstream test ---

class _FakeUpstreamExecutor:
    """Minimal fake executor for recipient_domain denial test."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def call_tool(
        self,
        arguments: dict[str, Any],
        invocation_id: str | None = None,
        idempotency_key: str | None = None,
        before_dispatch: Any | None = None,
    ) -> Any:
        self.calls.append(
            {
                "arguments": arguments,
                "invocation_id": invocation_id,
                "idempotency_key": idempotency_key,
            }
        )
        return None


def _register_upstream_tool(
    tool_name: str,
    executor: _FakeUpstreamExecutor,
    origin: str = "https://partner.example",
) -> None:
    get_service_registry().register_upstream(
        service_id=tool_name,
        name="Partner Tool",
        description="Test upstream tool for permit v2",
        category=ServiceCategory.AGENT_COMMS,
        executor=executor,
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        credits_per_unit=2.0,
        upstream_tool_name="partner.echo",
        upstream_origin=origin,
    )


@pytest.mark.anyio
async def test_recipient_domain_denies_mismatch(client, clean_database):
    """Permit with recipient_domain denies upstream calls to a different origin."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "v2-test-domain"
    executor = _FakeUpstreamExecutor()

    # Register upstream tool at partner.example
    _register_upstream_tool(tool_name, executor, origin="https://partner.example")
    try:
        # Create permit allowing only OTHER origin
        permit_resp = await client.post(
            "/v1/permits",
            json={
                "issuer_wallet_id": wallet_id,
                "subject_wallet_id": wallet_id,
                "subject_key_id": key_id,
                "allowed_tools": [tool_name],
                "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
                "max_credits": 50,
                "recipient_domain": "allowed.example.com",
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=30)
                ).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "domain-permit-1"},
        )
        assert permit_resp.status_code == 201
        permit = permit_resp.json()
        permit_id = permit["permit_id"]

        # Invoke should fail before dispatch with domain mismatch
        r = await _invoke_governed(
            client,
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool_name=tool_name,
            arguments={"message": "hello"},
            idem_key="domain-1",
            headers=agent_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == -32003
        assert "permit_recipient_domain_mismatch" in body["error"]["message"]

        # Executor should never have been called
        assert executor.calls == []

        # Verify no budget consumed (denial before reserve)
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(PermitModel, permit_id)
            assert model is not None
            assert model.spent_credits == Decimal("0")
    finally:
        get_service_registry().unregister_local(tool_name)
