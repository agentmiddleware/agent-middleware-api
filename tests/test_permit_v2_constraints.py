"""Adversarial tests for permit schema v2 constraints.

One test per constraint type, proving both denial and correct metering.
"""

from __future__ import annotations

import json
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


# --- forbidden_fields regression coverage (upstream path + nesting) ---


@pytest.mark.anyio
async def test_forbidden_fields_denies_on_upstream_path(client, clean_database):
    """forbidden_fields must be enforced for upstream_mcp calls, not just local.

    Regression: the upstream authorization path did not forward the invocation
    arguments to permit validation, so forbidden_fields was silently skipped
    for the higher-risk external-dispatch path.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "v2-test-forbidden-upstream"
    executor = _FakeUpstreamExecutor()

    _register_upstream_tool(tool_name, executor, origin="https://partner.example")
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
                # Match the registered upstream origin so recipient_domain
                # does not deny first — we want forbidden_fields to be the gate.
                "recipient_domain": "partner.example",
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=30)
                ).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "fu-permit-1"},
        )
        assert permit_resp.status_code == 201
        permit_id = permit_resp.json()["permit_id"]

        r = await _invoke_governed(
            client,
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool_name=tool_name,
            arguments={"secret_token": "leak"},
            idem_key="fu-1",
            headers=agent_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" in body
        assert "permit_forbidden_field" in body["error"]["message"]

        # Upstream executor must never run, and no budget consumed.
        assert executor.calls == []
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(PermitModel, permit_id)
            assert model is not None
            assert model.spent_credits == Decimal("0")
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_forbidden_fields_denies_nested_key(client, clean_database):
    """A forbidden key nested below the top level must still be denied."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "v2-test-forbidden-nested"
    _register_test_tool(tool_name)
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
                "forbidden_fields": ["ssn"],
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=30)
                ).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "fn-permit-1"},
        )
        assert permit_resp.status_code == 201
        permit_id = permit_resp.json()["permit_id"]

        # Forbidden key nested inside a dict.
        r = await _invoke_governed(
            client,
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool_name=tool_name,
            arguments={"profile": {"contact": {"ssn": "123-45-6789"}}},
            idem_key="fn-1",
            headers=agent_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" in body
        assert "permit_forbidden_field" in body["error"]["message"]

        # Forbidden key nested inside a list element must also be denied.
        r_list = await _invoke_governed(
            client,
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool_name=tool_name,
            arguments={"profiles": [{"ssn": "123-45-6789"}]},
            idem_key="fn-2",
            headers=agent_headers,
        )
        assert r_list.status_code == 200
        body_list = r_list.json()
        assert "error" in body_list
        assert "permit_forbidden_field" in body_list["error"]["message"]
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_max_calls_fractional_limit_fails_closed(client, clean_database):
    """A non-integer max_calls limit is malformed and must fail closed.

    int(2.5) would coerce to 2 and silently permit calls; a stored fractional
    limit must instead deny with permit_max_calls_exceeded.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "v2-test-frac-limit"
    _register_test_tool(tool_name)
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
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=30)
                ).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "frac-permit-1"},
        )
        assert permit_resp.status_code == 201
        permit_id = permit_resp.json()["permit_id"]

        # The API coerces max_calls to dict[str, int], so inject a fractional
        # limit directly at the storage layer to exercise the enforcement guard
        # against a malformed row (migration/ops-written value).
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(PermitModel, permit_id)
            assert model is not None
            model.max_calls_per_tool_json = json.dumps({tool_name: 2.5})
            session.add(model)
            await session.commit()

        r = await _invoke_governed(
            client,
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool_name=tool_name,
            arguments={"input": "hello"},
            idem_key="frac-1",
            headers=agent_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" in body
        assert "permit_max_calls_exceeded" in body["error"]["message"]

        # No budget consumed on the fail-closed denial.
        async with factory() as session:
            model = await session.get(PermitModel, permit_id)
            assert model is not None
            assert model.spent_credits == Decimal("0")
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_reconciler_constraints_snapshot_matches_live_path(client, clean_database):
    """A crash-recovered receipt must sign byte-identical constraints.

    The live invoke path normalizes `aggregate_value_cap`
    (`Decimal("10.50")` -> `"10.5"`); the reconciler previously used
    `str(...)`, so a receipt minted during crash recovery could hash a
    different `constraints_evaluated` than a live receipt for the same permit.
    Both now delegate to `permit_constraints_snapshot`.
    """

    from app.routers.mcp import _permit_constraints_snapshot as live_snapshot
    from app.services.mcp_dispatch_reconciliation import (
        get_mcp_dispatch_reconciliation_service,
    )
    from app.services.permits import permit_constraints_snapshot

    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]

    permit_resp = await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": wallet_id,
            "subject_wallet_id": wallet_id,
            "subject_key_id": key_id,
            "allowed_tools": ["example.tool"],
            "scopes": ["tool:example.tool:invoke", "billing:charge"],
            "max_credits": 50,
            "max_calls_per_tool": {"example.tool": 5},
            "aggregate_value_cap": "10.50",
            "forbidden_fields": ["secret_token"],
            "recipient_domain": "allowed.example.com",
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=30)
            ).isoformat(),
        },
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "snapshot-parity-1"},
    )
    assert permit_resp.status_code == 201
    permit_id = permit_resp.json()["permit_id"]

    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(PermitModel, permit_id)
        assert model is not None
        live = live_snapshot(model)
        shared = permit_constraints_snapshot(model)

    reconciler = get_mcp_dispatch_reconciliation_service()
    recovered = await reconciler._permit_constraints_snapshot(permit_id)

    assert live == shared == recovered
    # The normalized form, regardless of how the column stores the scale.
    assert recovered["aggregate_value_cap"] == "10.5"


@pytest.mark.anyio
async def test_reconciler_constraints_snapshot_absent_permit_is_none(clean_database):
    from app.services.mcp_dispatch_reconciliation import (
        get_mcp_dispatch_reconciliation_service,
    )

    reconciler = get_mcp_dispatch_reconciliation_service()
    assert await reconciler._permit_constraints_snapshot("permit-missing") is None
