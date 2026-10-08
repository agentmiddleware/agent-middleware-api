"""Regression tests: idempotency keys on legacy unpermitted MCP calls.

A client-supplied ``Idempotency-Key`` passes validation on every
``tools/call`` request, so the legacy unpermitted path must honor it too.
Previously the key was validated and then dropped: a retried request
executed and charged again, and a reused key with different arguments ran
without conflict. These tests pin the enforced behavior, including the
failure exits that must free the key rather than bricking it.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db.database import get_session_factory
from app.db.models import LedgerEntryModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.mcp_dispatch_attempts import (
    DispatchAttemptError,
    _assert_origin,
)
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


def _register_counter(
    service_id: str, *, credits_per_unit: float = 1.0, fail_first: bool = False
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _effect(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        if fail_first and len(calls) == 1:
            raise RuntimeError("transient tool boom")
        return {"echo": kwargs}

    get_service_registry().register_local(
        service_id=service_id,
        name=f"Probe {service_id}",
        description="break-it regression probe",
        category=ServiceCategory.AGENT_COMMS,
        func=_effect,
        credits_per_unit=credits_per_unit,
        unit_name="call",
    )
    return calls


def _call_body(tool: str, wallet_id: str, request_id: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": tool,
            "arguments": {"a": 1},
            "mcpContext": {"wallet_id": wallet_id},
        },
    }


async def _ledger_rows(wallet_id: str) -> int:
    async with get_session_factory()() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(LedgerEntryModel)
                .where(LedgerEntryModel.wallet_id == wallet_id)
            )
            or 0
        )


@pytest.mark.anyio
async def test_legacy_unpermitted_key_retry_executes_and_charges_once(
    client: AsyncClient, clean_database
) -> None:
    """Same key, same arguments: one execution, one debit, replay after."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    calls = _register_counter("probe.legacy.once")
    headers = {**provisioned["agent_headers"], "Idempotency-Key": "probe-once-key"}
    before = await _ledger_rows(wallet_id)

    first = await client.post(
        "/mcp/messages",
        json=_call_body("probe.legacy.once", wallet_id, 1),
        headers=headers,
    )
    mid = await _ledger_rows(wallet_id)
    second = await client.post(
        "/mcp/messages",
        json=_call_body("probe.legacy.once", wallet_id, 2),
        headers=headers,
    )
    after = await _ledger_rows(wallet_id)

    assert "result" in first.json()
    assert second.json()["result"] == first.json()["result"]
    assert len(calls) == 1
    assert mid - before == 1
    assert after == mid


@pytest.mark.anyio
async def test_legacy_unpermitted_same_key_different_arguments_conflicts(
    client: AsyncClient, clean_database
) -> None:
    """Same key, different arguments: refused, never executed."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    calls = _register_counter("probe.legacy.conflict")
    headers = {**provisioned["agent_headers"], "Idempotency-Key": "probe-clash-key"}

    first = await client.post(
        "/mcp/messages",
        json=_call_body("probe.legacy.conflict", wallet_id, 1),
        headers=headers,
    )
    assert "result" in first.json()

    other = _call_body("probe.legacy.conflict", wallet_id, 2)
    other["params"]["arguments"] = {"a": 2}
    second = await client.post("/mcp/messages", json=other, headers=headers)

    assert len(calls) == 1
    assert second.json()["error"]["code"] == -32603
    assert second.json()["error"]["message"] == "idempotency_key_reused"


@pytest.mark.anyio
async def test_legacy_unpermitted_tool_failure_frees_key_for_retry(
    client: AsyncClient, clean_database
) -> None:
    """A failed call abandons its record so the invited retry can run."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    calls = _register_counter("probe.legacy.flaky", fail_first=True)
    headers = {**provisioned["agent_headers"], "Idempotency-Key": "probe-flaky-key"}

    first = await client.post(
        "/mcp/messages",
        json=_call_body("probe.legacy.flaky", wallet_id, 1),
        headers=headers,
    )
    assert first.json()["error"]["code"] == -32603

    second = await client.post(
        "/mcp/messages",
        json=_call_body("probe.legacy.flaky", wallet_id, 2),
        headers=headers,
    )
    assert "result" in second.json()
    assert len(calls) == 2


@pytest.mark.anyio
async def test_legacy_unpermitted_insufficient_funds_frees_key_for_retry(
    client: AsyncClient, clean_database
) -> None:
    """A denial leaves no in-progress record behind to brick the key."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    _register_counter("probe.legacy.pricey", credits_per_unit=1_000_000.0)
    headers = {**provisioned["agent_headers"], "Idempotency-Key": "probe-poor-key"}

    first = await client.post(
        "/mcp/messages",
        json=_call_body("probe.legacy.pricey", wallet_id, 1),
        headers=headers,
    )
    assert first.json()["error"]["code"] == -32004

    second = await client.post(
        "/mcp/messages",
        json=_call_body("probe.legacy.pricey", wallet_id, 2),
        headers=headers,
    )
    assert second.json()["error"]["code"] == -32004
    assert "idempotency_in_progress" not in second.json()["error"]["message"]


@pytest.mark.anyio
async def test_legacy_unpermitted_upstream_still_requires_permit(
    client: AsyncClient, clean_database
) -> None:
    """Upstream dispatch without a permit is a clean denial, not a 500."""
    from tests.test_mcp_upstream_governed import FakeUpstreamExecutor

    provisioned = await provision_agent_wallet(client)
    get_service_registry().register_upstream(
        service_id="probe.legacy.upstream",
        name="probe-legacy-upstream",
        description="break-it regression probe",
        category=ServiceCategory.AGENT_COMMS,
        executor=FakeUpstreamExecutor(mode="success"),
        input_schema={"type": "object"},
        output_schema=None,
        credits_per_unit=2.0,
        upstream_tool_name="partner.write",
        upstream_origin="https://partner.example",
    )
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "probe.legacy.upstream",
            "arguments": {},
            "mcpContext": {"wallet_id": provisioned["agent_wallet_id"]},
        },
    }
    headers = {**provisioned["agent_headers"], "Idempotency-Key": "probe-up-key"}
    response = await client.post("/mcp/messages", json=body, headers=headers)
    assert response.json()["error"]["code"] == -32003


@pytest.mark.anyio
async def test_unknown_governed_tool_charges_nothing(
    client: AsyncClient, clean_database
) -> None:
    """A tool name outside the catalog is denied before any debit."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    permit = await create_tool_permit(
        client,
        wallet_id=wallet_id,
        key_id=provisioned["key_id"],
        tool_name="probe.unknown.permit",
        idem_key="probe-unknown-permit",
    )
    before = await _ledger_rows(wallet_id)
    body = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "no.such.tool",
            "arguments": {},
            "mcpContext": {
                "wallet_id": wallet_id,
                "permit_id": permit["permit_id"],
                "idempotency_key": "probe-unknown-key",
            },
        },
    }
    response = await client.post(
        "/mcp/messages", json=body, headers=provisioned["agent_headers"]
    )
    assert response.json()["error"]["code"] == -32001
    assert await _ledger_rows(wallet_id) == before


@pytest.mark.parametrize(
    "origin",
    [
        "https://partner.example ",
        " https://partner.example",
        "https://partner.example\n",
        "",
    ],
)
def test_dispatch_origin_rejects_surrounding_whitespace(origin: str) -> None:
    """The dispatch origin check refuses padded or empty values outright."""
    with pytest.raises(DispatchAttemptError):
        _assert_origin(origin)


@pytest.mark.parametrize(
    "origin",
    [
        "https://partner.example",
        "http://localhost:9000",
        "https://[::1]:9000",
    ],
)
def test_dispatch_origin_accepts_clean_shapes(origin: str) -> None:
    assert _assert_origin(origin) == origin
