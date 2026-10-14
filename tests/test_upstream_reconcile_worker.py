"""Backlog #7: provider lookup handles on receipts + optional reconcile worker.

Pins three properties:
- the forwarded idempotency key (and provider request id when the upstream
  reports one) is signed onto upstream receipts, outside the response hash;
- the reconcile worker probes parked ``delivery_uncertain`` calls on a
  backoff and records a durable, idempotent resolution audit event;
- neither ageing nor any provider answer moves money: wallet balance, ledger
  and permit ``spent_credits`` are unchanged by the worker.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.types import CallToolResult, TextContent
from pydantic import SecretStr
from sqlalchemy import update as sa_update

from app.core.config import get_settings
from app.core.time import to_naive_utc
from app.db.database import get_session_factory
from app.db.models import (
    ControlPlaneAuditEventModel,
    McpDispatchAttemptModel,
    PermitModel,
    ReceiptModel,
)
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.agent_money import get_agent_money
from app.services.receipts import get_receipt_service
from app.services.service_registry import get_service_registry
from app.services.upstream_mcp import (
    UpstreamMcpAdapter,
    UpstreamMcpDeliveryUncertainError,
    UpstreamMcpResult,
    extract_provider_request_id,
)
from app.services.upstream_reconcile import (
    DeliveryUncertainReconcileWorker,
    ParkedCall,
    ProviderLookup,
    ProviderOutcome,
    parse_backoff_seconds,
    resolution_event_id,
)
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

PROVIDER_META_KEY = "io.agentmiddleware/provider_request_id"


def _upstream_result(
    payload: dict[str, Any], provider_request_id: str | None = None
) -> UpstreamMcpResult:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return UpstreamMcpResult(
        payload=payload,
        canonical_json=canonical,
        response_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        size_bytes=len(canonical.encode()),
        is_error=False,
        provider_request_id=provider_request_id,
    )


@dataclass
class ScriptedExecutor:
    """Upstream double: delivery_uncertain, or success with a provider id."""

    mode: str = "uncertain"
    provider_request_id: str | None = None
    forwarded_keys: list[str] = field(default_factory=list)

    async def call_tool(
        self,
        arguments: dict[str, Any],
        *,
        invocation_id: str,
        idempotency_key: str,
        before_dispatch: Callable[[], Awaitable[None]],
    ) -> UpstreamMcpResult:
        self.forwarded_keys.append(idempotency_key)
        await before_dispatch()
        if self.mode == "uncertain":
            raise UpstreamMcpDeliveryUncertainError()
        return _upstream_result(
            {"content": [{"type": "text", "text": "ok"}], "isError": False},
            self.provider_request_id,
        )


@dataclass
class FakeProbe:
    outcome: ProviderOutcome = ProviderOutcome.UNKNOWN
    provider_request_id: str | None = None
    raise_error: bool = False
    seen: list[ParkedCall] = field(default_factory=list)

    async def lookup(self, call: ParkedCall) -> ProviderLookup:
        self.seen.append(call)
        if self.raise_error:
            raise RuntimeError("provider down")
        return ProviderLookup(self.outcome, self.provider_request_id)


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


async def _invoke(
    client: AsyncClient,
    executor: ScriptedExecutor,
    *,
    tool_name: str,
    idem_key: str,
) -> dict[str, Any]:
    registry = get_service_registry()
    registry.register_upstream(
        service_id=tool_name,
        name="Reconcile Worker Test Tool",
        description="Test tool",
        category=ServiceCategory.AGENT_COMMS,
        executor=executor,
        input_schema={"type": "object", "properties": {"test": {"type": "string"}}},
        output_schema=None,
        credits_per_unit=2.0,
        upstream_tool_name=tool_name,
        upstream_origin="https://test.example.com",
    )
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool_name,
        idem_key=f"{idem_key}-permit",
    )
    response = await client.post(
        "/mcp/messages",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": {"test": "value"},
                "mcpContext": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": idem_key,
                },
            },
        },
        headers=provisioned["agent_headers"],
    )
    assert response.status_code == 200
    return {
        "body": response.json(),
        "wallet_id": provisioned["agent_wallet_id"],
        "permit_id": permit["permit_id"],
    }


async def _money_snapshot(wallet_id: str, permit_id: str) -> tuple[Any, ...]:
    wallet = await get_agent_money().get_wallet(wallet_id)
    async with get_session_factory()() as session:
        permit = await session.get(PermitModel, permit_id)
        assert permit is not None
        return wallet.balance, permit.spent_credits


async def _parked_attempt(wallet_id: str) -> McpDispatchAttemptModel:
    worker = DeliveryUncertainReconcileWorker(
        FakeProbe(), backoff_seconds=[30], alert_age_seconds=3600
    )
    calls = [
        c for c in await worker.list_parked_calls(limit=50) if c.wallet_id == wallet_id
    ]
    assert len(calls) == 1
    async with get_session_factory()() as session:
        attempt = await session.get(McpDispatchAttemptModel, calls[0].attempt_id)
        assert attempt is not None
        return attempt


# --- receipt fields -------------------------------------------------------


@pytest.mark.anyio
async def test_delivery_uncertain_receipt_signs_forwarded_key(
    client: AsyncClient, clean_database
) -> None:
    executor = ScriptedExecutor(mode="uncertain")
    tool = "reconcile-uncertain-receipt"
    try:
        result = await _invoke(client, executor, tool_name=tool, idem_key="bl7-u-1")
    finally:
        get_service_registry().unregister_local(tool)

    receipt = result["body"]["error"]["data"]["receipt"]
    assert receipt["outcome"] == "delivery_uncertain"
    evidence = receipt["constraints_evaluated"]["upstream_dispatch"]
    # Exactly the value the upstream received in _meta.
    assert executor.forwarded_keys == [evidence["forwarded_idempotency_key"]]
    assert "provider_request_id" not in evidence  # no response, so none

    receipts = get_receipt_service()
    valid, reason, _ = await receipts.verify_receipt(receipt["receipt_id"])
    assert valid, reason

    # Negative: the field is covered by the signature.
    async with get_session_factory()() as session:
        await session.execute(
            sa_update(ReceiptModel)
            .where(ReceiptModel.receipt_id == receipt["receipt_id"])
            .values(
                constraints_evaluated_json=json.dumps(
                    {"upstream_dispatch": {"forwarded_idempotency_key": "forged"}}
                )
            )
        )
        await session.commit()
    valid, reason, _ = await receipts.verify_receipt(receipt["receipt_id"])
    assert not valid
    assert reason == "receipt_signature_invalid"


@pytest.mark.anyio
async def test_success_receipt_signs_provider_request_id_outside_response_hash(
    client: AsyncClient, clean_database
) -> None:
    executor = ScriptedExecutor(mode="success", provider_request_id="req_abc-123")
    tool = "reconcile-success-receipt"
    try:
        result = await _invoke(client, executor, tool_name=tool, idem_key="bl7-s-1")
    finally:
        get_service_registry().unregister_local(tool)

    receipt = result["body"]["result"]["receipt"]
    evidence = receipt["constraints_evaluated"]["upstream_dispatch"]
    assert evidence == {
        "forwarded_idempotency_key": executor.forwarded_keys[0],
        "provider_request_id": "req_abc-123",
    }
    # Response hash is over the canonical payload only.
    expected = _upstream_result(
        {"content": [{"type": "text", "text": "ok"}], "isError": False}
    )
    assert receipt["response_hash"] == expected.response_hash
    valid, reason, _ = await get_receipt_service().verify_receipt(receipt["receipt_id"])
    assert valid, reason


@pytest.mark.parametrize(
    ("meta", "expected"),
    [
        ({PROVIDER_META_KEY: "req_1"}, "req_1"),
        ({PROVIDER_META_KEY: "x" * 128}, "x" * 128),
        ({PROVIDER_META_KEY: "x" * 129}, None),
        ({PROVIDER_META_KEY: "has space"}, None),
        ({PROVIDER_META_KEY: "line\nbreak"}, None),
        ({PROVIDER_META_KEY: 123}, None),
        ({PROVIDER_META_KEY: ""}, None),
        ({"other": "req_1"}, None),
        (None, None),
        ("not-a-dict", None),
    ],
)
def test_extract_provider_request_id_is_bounded(
    meta: Any, expected: str | None
) -> None:
    assert extract_provider_request_id(meta, PROVIDER_META_KEY) == expected


def test_canonicalize_result_reads_provider_id_from_meta_without_hashing_it() -> None:
    adapter_like = SimpleNamespace(
        configuration=SimpleNamespace(
            bearer_token=SecretStr("upstream-secret"), max_response_bytes=1_048_576
        )
    )
    content = [TextContent(type="text", text="ok")]
    with_meta = CallToolResult(
        content=content, isError=False, _meta={PROVIDER_META_KEY: "req_9"}
    )
    without_meta = CallToolResult(content=content, isError=False)

    a = UpstreamMcpAdapter._canonicalize_result(adapter_like, with_meta)  # type: ignore[arg-type]
    b = UpstreamMcpAdapter._canonicalize_result(adapter_like, without_meta)  # type: ignore[arg-type]
    assert a.provider_request_id == "req_9"
    assert b.provider_request_id is None
    assert a.response_hash == b.response_hash
    assert "_meta" not in a.payload


# --- worker ---------------------------------------------------------------


def test_worker_is_off_by_default_and_backoff_validates() -> None:
    settings = get_settings()
    assert settings.UPSTREAM_RECONCILE_WORKER_ENABLED is False
    assert parse_backoff_seconds("30, 120,600") == (30, 120, 600)
    for bad in ("", "0", "30,-1", ","):
        with pytest.raises(ValueError, match="upstream_reconcile_backoff_invalid"):
            parse_backoff_seconds(bad)


@pytest.mark.anyio
async def test_worker_backoff_and_age_alert_never_release_budget(
    client: AsyncClient, clean_database, caplog: pytest.LogCaptureFixture
) -> None:
    tool = "reconcile-worker-backoff"
    try:
        result = await _invoke(
            client,
            ScriptedExecutor(mode="uncertain"),
            tool_name=tool,
            idem_key="bl7-w-1",
        )
    finally:
        get_service_registry().unregister_local(tool)
    attempt = await _parked_attempt(result["wallet_id"])
    completed = to_naive_utc(attempt.completed_at)
    before = await _money_snapshot(result["wallet_id"], result["permit_id"])
    assert before[1] == Decimal("2")  # reservation consumed by the uncertain call

    clock = {"now": completed + timedelta(seconds=10)}
    probe = FakeProbe(ProviderOutcome.UNKNOWN)
    worker = DeliveryUncertainReconcileWorker(
        probe,
        backoff_seconds=[30, 120],
        alert_age_seconds=600,
        now=lambda: clock["now"],
    )

    # Not due before the first backoff step.
    assert (await worker.run_once()).probed == 0

    clock["now"] = completed + timedelta(seconds=31)
    sweep = await worker.run_once()
    assert (sweep.probed, sweep.still_unknown, sweep.aged_alerts) == (1, 1, 0)
    # Next probe is 120s after the first one.
    clock["now"] = completed + timedelta(seconds=100)
    assert (await worker.run_once()).probed == 0
    clock["now"] = completed + timedelta(seconds=152)
    assert (await worker.run_once()).probed == 1

    # Age past threshold: alert exactly once, budget untouched.
    clock["now"] = completed + timedelta(seconds=601)
    with caplog.at_level("WARNING", logger="app.services.upstream_reconcile"):
        sweep = await worker.run_once()
    assert sweep.aged_alerts == 1
    assert any(r.message == "mcp_delivery_uncertain_aged" for r in caplog.records)
    clock["now"] = completed + timedelta(seconds=5000)
    assert (await worker.run_once()).aged_alerts == 0

    assert await _money_snapshot(result["wallet_id"], result["permit_id"]) == before
    async with get_session_factory()() as session:
        fresh = await session.get(McpDispatchAttemptModel, attempt.attempt_id)
        assert fresh is not None and fresh.state == "delivery_uncertain"
        assert fresh.budget_released_at is None
        assert (
            await session.get(
                ControlPlaneAuditEventModel, resolution_event_id(attempt.attempt_id)
            )
            is None
        )
    # The probe saw the signed forwarded key and the invocation id.
    assert probe.seen[0].forwarded_idempotency_key == "bl7-w-1"
    assert probe.seen[0].invocation_id == attempt.idempotency_record_id


@pytest.mark.anyio
@pytest.mark.parametrize(
    "outcome", [ProviderOutcome.EXECUTED, ProviderOutcome.NOT_EXECUTED]
)
async def test_worker_resolution_is_durable_idempotent_and_moves_no_money(
    client: AsyncClient, clean_database, outcome: ProviderOutcome
) -> None:
    tool = f"reconcile-worker-{outcome.value}"
    try:
        result = await _invoke(
            client,
            ScriptedExecutor(mode="uncertain"),
            tool_name=tool,
            idem_key=f"bl7-r-{outcome.value}",
        )
    finally:
        get_service_registry().unregister_local(tool)
    attempt = await _parked_attempt(result["wallet_id"])
    before = await _money_snapshot(result["wallet_id"], result["permit_id"])
    ledger_before = (
        await client.get(
            f"/v1/billing/ledger/{result['wallet_id']}",
            headers={"X-API-Key": "test-key"},
        )
    ).json()["entries"]

    worker = DeliveryUncertainReconcileWorker(
        FakeProbe(outcome, provider_request_id="prov-77"),
        backoff_seconds=[1],
        alert_age_seconds=3600,
        now=lambda: to_naive_utc(attempt.completed_at) + timedelta(seconds=5),
    )
    sweep = await worker.run_once()
    if outcome is ProviderOutcome.EXECUTED:
        assert sweep.resolved_executed == 1
    else:
        assert sweep.resolved_not_executed == 1

    async with get_session_factory()() as session:
        event = await session.get(
            ControlPlaneAuditEventModel, resolution_event_id(attempt.attempt_id)
        )
        assert event is not None
        metadata = json.loads(event.metadata_json or "{}")
    assert metadata["provider_outcome"] == outcome.value
    assert metadata["provider_request_id"] == "prov-77"
    assert metadata["budget_action"] == "none"
    assert metadata["refund_candidate"] is (outcome is ProviderOutcome.NOT_EXECUTED)

    # Closed: no longer listed, a second sweep (or a fresh worker) is a no-op.
    assert await worker.list_parked_calls(limit=50) == []
    assert (await worker.run_once()).probed == 0

    # No refund, no release, no new ledger entry -- even for not_executed.
    assert await _money_snapshot(result["wallet_id"], result["permit_id"]) == before
    ledger_after = (
        await client.get(
            f"/v1/billing/ledger/{result['wallet_id']}",
            headers={"X-API-Key": "test-key"},
        )
    ).json()["entries"]
    assert ledger_after == ledger_before


@pytest.mark.anyio
async def test_worker_probe_failure_records_nothing(
    client: AsyncClient, clean_database
) -> None:
    tool = "reconcile-worker-probe-error"
    try:
        result = await _invoke(
            client,
            ScriptedExecutor(mode="uncertain"),
            tool_name=tool,
            idem_key="bl7-e-1",
        )
    finally:
        get_service_registry().unregister_local(tool)
    attempt = await _parked_attempt(result["wallet_id"])
    worker = DeliveryUncertainReconcileWorker(
        FakeProbe(raise_error=True),
        backoff_seconds=[1],
        alert_age_seconds=3600,
        now=lambda: to_naive_utc(attempt.completed_at) + timedelta(seconds=5),
    )
    sweep = await worker.run_once()
    assert (sweep.probed, sweep.probe_errors) == (1, 1)
    assert len(await worker.list_parked_calls(limit=50)) == 1
