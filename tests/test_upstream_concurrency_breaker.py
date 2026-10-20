"""Per-upstream concurrency limit and circuit breaker (SEL-331).

Defaults stay off. When enabled, a saturated limit or an open breaker
refuses before reservation, debit, or dispatch. delivery_uncertain still
counts as upstream trouble without changing that call.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.config import ReplanGuardMode, Settings, get_settings
from app.core.resilience import CircuitBreaker
from app.db.database import get_session_factory
from app.db.models import McpDispatchAttemptModel, ReceiptModel, WalletModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.idempotency import (
    GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
    get_idempotency_service,
)
from app.services.service_registry import get_service_registry
from app.services.upstream_admission import (
    UpstreamAdmissionRefusal,
    UpstreamAdmissionSlot,
    clear_upstream_admission_state,
    get_upstream_admission_gate,
    upstream_admission_key,
)
from app.services.upstream_mcp import (
    UpstreamMcpDeliveryUncertainError,
    UpstreamMcpPreDispatchError,
    UpstreamMcpResult,
    UpstreamMcpReturnedError,
)
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

_ORIGIN = "https://partner.example"


@pytest.fixture(autouse=True)
def _reset_upstream_admission() -> Any:
    clear_upstream_admission_state()
    yield
    clear_upstream_admission_state()


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


def _result(text: str = "partner response") -> UpstreamMcpResult:
    payload = {
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return UpstreamMcpResult(
        payload=payload,
        canonical_json=canonical,
        response_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        size_bytes=len(canonical.encode()),
        is_error=False,
    )


def _error_result() -> UpstreamMcpResult:
    payload = {
        "content": [{"type": "text", "text": "partner rejected request"}],
        "isError": True,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return UpstreamMcpResult(
        payload=payload,
        canonical_json=canonical,
        response_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        size_bytes=len(canonical.encode()),
        is_error=True,
    )


def _register(tool_name: str, executor: Any, *, origin: str = _ORIGIN) -> None:
    get_service_registry().register_upstream(
        service_id=tool_name,
        name="Design Partner Tool",
        description="Controlled remote MCP test tool",
        category=ServiceCategory.AGENT_COMMS,
        executor=executor,
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        credits_per_unit=2.0,
        upstream_tool_name="partner.echo",
        upstream_origin=origin,
    )


def _body(
    *,
    tool_name: str,
    wallet_id: str,
    permit_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": f"call-{idempotency_key}",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"message": "hello"},
            "mcpContext": {
                "wallet_id": wallet_id,
                "permit_id": permit_id,
                "idempotency_key": idempotency_key,
            },
        },
    }


def _enable(
    monkeypatch: pytest.MonkeyPatch,
    *,
    limit: int = 0,
    breaker: bool = False,
    threshold: int = 5,
    recovery: float = 30.0,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "UPSTREAM_MAX_CONCURRENCY_PER_UPSTREAM", limit)
    monkeypatch.setattr(settings, "UPSTREAM_CIRCUIT_BREAKER_ENABLED", breaker)
    monkeypatch.setattr(
        settings, "UPSTREAM_CIRCUIT_BREAKER_FAILURE_THRESHOLD", threshold
    )
    monkeypatch.setattr(settings, "UPSTREAM_CIRCUIT_BREAKER_RECOVERY_SECONDS", recovery)


async def _balance(wallet_id: str) -> Decimal:
    async with get_session_factory()() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        return wallet.balance


async def _attempt_count() -> int:
    async with get_session_factory()() as session:
        counted = await session.scalar(
            select(func.count()).select_from(McpDispatchAttemptModel)
        )
    return int(counted or 0)


async def _receipt_count(wallet_id: str) -> int:
    async with get_session_factory()() as session:
        counted = await session.scalar(
            select(func.count())
            .select_from(ReceiptModel)
            .where(ReceiptModel.wallet_id == wallet_id)
        )
    return int(counted or 0)


async def _provision(client: AsyncClient, tool_name: str) -> dict[str, Any]:
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool_name,
        idem_key=f"{tool_name}-permit",
    )
    provisioned["permit_id"] = permit["permit_id"]
    return provisioned


async def _post(
    client: AsyncClient,
    provisioned: dict[str, Any],
    *,
    tool_name: str,
    idempotency_key: str,
) -> Any:
    return await client.post(
        "/mcp/messages",
        json=_body(
            tool_name=tool_name,
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=provisioned["permit_id"],
            idempotency_key=idempotency_key,
        ),
        headers=provisioned["agent_headers"],
    )


class _SuccessExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def call_tool(
        self,
        arguments: dict[str, Any],
        *,
        invocation_id: str,
        idempotency_key: str,
        before_dispatch: Any,
    ) -> UpstreamMcpResult:
        del arguments, invocation_id, idempotency_key
        await before_dispatch()
        self.calls += 1
        return _result()


class _BlockingExecutor:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def call_tool(
        self,
        arguments: dict[str, Any],
        *,
        invocation_id: str,
        idempotency_key: str,
        before_dispatch: Any,
    ) -> UpstreamMcpResult:
        del arguments, invocation_id, idempotency_key
        await before_dispatch()
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return _result()


class _TransportFailureExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def call_tool(
        self,
        arguments: dict[str, Any],
        *,
        invocation_id: str,
        idempotency_key: str,
        before_dispatch: Any,
    ) -> UpstreamMcpResult:
        del arguments, invocation_id, idempotency_key, before_dispatch
        self.calls += 1
        raise UpstreamMcpPreDispatchError()


class _BoomThenOk:
    def __init__(self) -> None:
        self.calls = 0

    async def call_tool(
        self,
        arguments: dict[str, Any],
        *,
        invocation_id: str,
        idempotency_key: str,
        before_dispatch: Any,
    ) -> UpstreamMcpResult:
        del arguments, invocation_id, idempotency_key
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("upstream boom")
        await before_dispatch()
        return _result()


class _UncertainExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def call_tool(
        self,
        arguments: dict[str, Any],
        *,
        invocation_id: str,
        idempotency_key: str,
        before_dispatch: Any,
    ) -> UpstreamMcpResult:
        del arguments, invocation_id, idempotency_key
        await before_dispatch()
        self.calls += 1
        raise UpstreamMcpDeliveryUncertainError()


class _ReturnedThenOk:
    def __init__(self) -> None:
        self.calls = 0

    async def call_tool(
        self,
        arguments: dict[str, Any],
        *,
        invocation_id: str,
        idempotency_key: str,
        before_dispatch: Any,
    ) -> UpstreamMcpResult:
        del arguments, invocation_id, idempotency_key
        await before_dispatch()
        self.calls += 1
        if self.calls == 1:
            raise UpstreamMcpReturnedError(_error_result())
        return _result()


class _FailThenSucceed:
    def __init__(self, failures: int) -> None:
        self.calls = 0
        self._failures_left = failures

    async def call_tool(
        self,
        arguments: dict[str, Any],
        *,
        invocation_id: str,
        idempotency_key: str,
        before_dispatch: Any,
    ) -> UpstreamMcpResult:
        del arguments, invocation_id, idempotency_key
        self.calls += 1
        if self._failures_left > 0:
            self._failures_left -= 1
            raise UpstreamMcpPreDispatchError()
        await before_dispatch()
        return _result()


def test_shipped_defaults_match_today() -> None:
    fields = Settings.model_fields
    assert fields["UPSTREAM_MAX_CONCURRENCY_PER_UPSTREAM"].default == 0
    assert fields["UPSTREAM_CIRCUIT_BREAKER_ENABLED"].default is False
    assert fields["UPSTREAM_CIRCUIT_BREAKER_FAILURE_THRESHOLD"].default == 5
    assert fields["UPSTREAM_CIRCUIT_BREAKER_RECOVERY_SECONDS"].default == 30.0
    assert fields["RETRY_LOOP_ALERT_ENABLED"].default is False
    assert fields["WALLET_REPLAN_GUARD"].default is ReplanGuardMode.LOG_ONLY


def test_concurrency_and_recovery_reject_out_of_range_values() -> None:
    with pytest.raises(ValidationError, match="UPSTREAM_MAX_CONCURRENCY_PER_UPSTREAM"):
        Settings(UPSTREAM_MAX_CONCURRENCY_PER_UPSTREAM=-1)
    with pytest.raises(
        ValidationError, match="UPSTREAM_CIRCUIT_BREAKER_FAILURE_THRESHOLD"
    ):
        Settings(UPSTREAM_CIRCUIT_BREAKER_FAILURE_THRESHOLD=0)
    with pytest.raises(
        ValidationError, match="UPSTREAM_CIRCUIT_BREAKER_RECOVERY_SECONDS"
    ):
        Settings(UPSTREAM_CIRCUIT_BREAKER_RECOVERY_SECONDS=0)


def test_admission_key_is_origin_or_server_id() -> None:
    assert (
        upstream_admission_key({"upstream_origin": "https://partner.example/"})
        == "https://partner.example"
    )
    assert upstream_admission_key({"service_id": "partner.echo"}) == "partner.echo"


def test_semaphore_is_per_key_and_releases_after_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, limit=1)
    gate = get_upstream_admission_gate()
    first = gate.try_admit("https://a.example")
    other = gate.try_admit("https://b.example")
    assert isinstance(first, UpstreamAdmissionSlot)
    assert isinstance(other, UpstreamAdmissionSlot)
    saturated = gate.try_admit("https://a.example")
    assert isinstance(saturated, UpstreamAdmissionRefusal)
    assert saturated.reason == "upstream_concurrency_saturated"
    assert saturated.retry_after_seconds == 1
    first.close()
    first.close()
    again = gate.try_admit("https://a.example")
    assert isinstance(again, UpstreamAdmissionSlot)
    again.close()
    other.close()


def test_slot_releases_when_the_holder_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, limit=1)
    gate = get_upstream_admission_gate()
    slot = gate.try_admit("https://partner.example")
    assert isinstance(slot, UpstreamAdmissionSlot)
    with pytest.raises(RuntimeError, match="boom"):
        try:
            raise RuntimeError("boom")
        finally:
            slot.close()
    follow = gate.try_admit("https://partner.example")
    assert isinstance(follow, UpstreamAdmissionSlot)
    follow.close()


@pytest.mark.anyio
async def test_slot_releases_when_the_holder_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, limit=1)
    gate = get_upstream_admission_gate()
    slot = gate.try_admit("https://partner.example")
    assert isinstance(slot, UpstreamAdmissionSlot)

    async def _hold() -> None:
        try:
            await asyncio.sleep(30)
        finally:
            slot.close()

    task = asyncio.create_task(_hold())
    await asyncio.sleep(0)
    task.cancel()
    cancelled = False
    try:
        await task
    except asyncio.CancelledError:
        cancelled = True
    assert cancelled is True
    follow = gate.try_admit("https://partner.example")
    assert isinstance(follow, UpstreamAdmissionSlot)
    follow.close()


def test_breaker_opens_and_half_opens_after_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 1_000.0}
    monkeypatch.setattr("app.core.resilience.time.monotonic", lambda: clock["now"])
    _enable(monkeypatch, breaker=True, threshold=2, recovery=10)
    gate = get_upstream_admission_gate()
    key = "https://partner.example"

    first = gate.try_admit(key)
    assert isinstance(first, UpstreamAdmissionSlot)
    first.observe_failure()
    first.close()
    second = gate.try_admit(key)
    assert isinstance(second, UpstreamAdmissionSlot)
    second.observe_failure()
    second.close()

    opened = gate.try_admit(key)
    assert isinstance(opened, UpstreamAdmissionRefusal)
    assert opened.reason == "upstream_circuit_open"
    assert opened.retry_after_seconds == 10

    clock["now"] = 1_010.0
    probe = gate.try_admit(key)
    assert isinstance(probe, UpstreamAdmissionSlot)
    blocked = gate.try_admit(key)
    assert isinstance(blocked, UpstreamAdmissionRefusal)
    assert blocked.reason == "upstream_circuit_open"
    probe.observe_failure()
    probe.close()

    still_open = gate.try_admit(key)
    assert isinstance(still_open, UpstreamAdmissionRefusal)

    clock["now"] = 1_020.0
    recovered = gate.try_admit(key)
    assert isinstance(recovered, UpstreamAdmissionSlot)
    recovered.observe_success()
    recovered.close()
    breaker = gate._breakers[key]
    assert breaker.state == CircuitBreaker.CLOSED
    follow = gate.try_admit(key)
    assert isinstance(follow, UpstreamAdmissionSlot)
    follow.close()


@pytest.mark.anyio
async def test_defaults_do_not_consult_the_gate(
    client: AsyncClient,
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(self: Any, key: str) -> Any:
        raise AssertionError(f"admission gate ran for {key}")

    monkeypatch.setattr(
        "app.services.upstream_admission.UpstreamAdmissionGate.try_admit",
        _boom,
    )
    tool_name = "partner-upstream-defaults-off"
    executor = _SuccessExecutor()
    _register(tool_name, executor)
    try:
        provisioned = await _provision(client, tool_name)
        wallet_id = provisioned["agent_wallet_id"]
        before = await _balance(wallet_id)
        response = await _post(
            client, provisioned, tool_name=tool_name, idempotency_key="defaults-1"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["result"]["isError"] is False
        assert executor.calls == 1
        assert await _balance(wallet_id) == before - Decimal("2")
        assert await _attempt_count() == 1
        assert await _receipt_count(wallet_id) == 1
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_saturation_rejects_before_debit_and_releases_the_key(
    client: AsyncClient,
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, limit=1)
    tool_name = "partner-upstream-saturated"
    executor = _BlockingExecutor()
    _register(tool_name, executor)
    held: asyncio.Task[Any] | None = None
    try:
        provisioned = await _provision(client, tool_name)
        wallet_id = provisioned["agent_wallet_id"]
        started = await _balance(wallet_id)
        held = asyncio.create_task(
            _post(client, provisioned, tool_name=tool_name, idempotency_key="held-1")
        )
        await asyncio.wait_for(executor.entered.wait(), timeout=5)
        while_held = await _balance(wallet_id)
        assert while_held == started - Decimal("2")
        assert await _attempt_count() == 1

        rejected = await asyncio.wait_for(
            _post(client, provisioned, tool_name=tool_name, idempotency_key="sat-1"),
            timeout=15,
        )
        assert rejected.status_code == 200
        error = rejected.json()["error"]
        assert error["code"] == -32005
        assert error["message"] == "upstream_concurrency_saturated"
        assert error["data"]["retry_after_seconds"] == 1
        assert "receipt" not in error["data"]
        assert await _balance(wallet_id) == while_held
        assert await _attempt_count() == 1
        assert await _receipt_count(wallet_id) == 0
        assert executor.calls == 1
        record = await get_idempotency_service().get_record(
            wallet_id=wallet_id,
            endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
            idempotency_key="sat-1",
        )
        assert record is None

        executor.release.set()
        held_response = await asyncio.wait_for(held, timeout=15)
        assert held_response.status_code == 200
        assert held_response.json()["result"]["isError"] is False

        retried = await _post(
            client, provisioned, tool_name=tool_name, idempotency_key="sat-1"
        )
        assert retried.status_code == 200
        assert retried.json()["result"]["isError"] is False
        assert executor.calls == 2
        assert await _balance(wallet_id) == started - Decimal("4")
    finally:
        executor.release.set()
        if held is not None and not held.done():
            await held
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_breaker_opens_on_transport_failures_and_half_opens(
    client: AsyncClient,
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 5_000.0}
    monkeypatch.setattr("app.core.resilience.time.monotonic", lambda: clock["now"])
    _enable(monkeypatch, breaker=True, threshold=2, recovery=15)
    tool_name = "partner-upstream-breaker-open"
    executor = _FailThenSucceed(failures=2)
    _register(tool_name, executor)
    try:
        provisioned = await _provision(client, tool_name)
        wallet_id = provisioned["agent_wallet_id"]
        started = await _balance(wallet_id)
        first = await _post(
            client, provisioned, tool_name=tool_name, idempotency_key="fail-1"
        )
        second = await _post(
            client, provisioned, tool_name=tool_name, idempotency_key="fail-2"
        )
        assert first.json()["error"]["message"] == "upstream_pre_dispatch_failed"
        assert second.json()["error"]["message"] == "upstream_pre_dispatch_failed"
        assert await _balance(wallet_id) == started
        assert executor.calls == 2

        opened = await _post(
            client, provisioned, tool_name=tool_name, idempotency_key="open-1"
        )
        assert opened.json()["error"]["code"] == -32005
        assert opened.json()["error"]["message"] == "upstream_circuit_open"
        assert opened.json()["error"]["data"]["retry_after_seconds"] == 15
        assert "receipt" not in opened.json()["error"]["data"]
        assert executor.calls == 2
        assert await _balance(wallet_id) == started
        assert await _attempt_count() == 2
        open_record = await get_idempotency_service().get_record(
            wallet_id=wallet_id,
            endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
            idempotency_key="open-1",
        )
        assert open_record is None

        clock["now"] = 5_015.0
        probe = await _post(
            client, provisioned, tool_name=tool_name, idempotency_key="probe-1"
        )
        assert probe.status_code == 200
        assert probe.json()["result"]["isError"] is False
        assert executor.calls == 3
        breaker = get_upstream_admission_gate()._breakers[_ORIGIN]
        assert breaker.state == CircuitBreaker.CLOSED
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_delivery_uncertain_counts_without_changing_the_call(
    client: AsyncClient,
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, breaker=True, threshold=1, recovery=30)
    tool_name = "partner-upstream-uncertain-breaker"
    executor = _UncertainExecutor()
    _register(tool_name, executor)
    try:
        provisioned = await _provision(client, tool_name)
        wallet_id = provisioned["agent_wallet_id"]
        started = await _balance(wallet_id)
        first = await _post(
            client, provisioned, tool_name=tool_name, idempotency_key="uncertain-1"
        )
        error = first.json()["error"]
        assert error["code"] == -32005
        assert error["message"] == "delivery_uncertain"
        receipt = error["data"]["receipt"]
        assert receipt["outcome"] == "delivery_uncertain"
        assert Decimal(receipt["credits_charged"]) == Decimal("2")
        assert await _balance(wallet_id) == started - Decimal("2")
        assert executor.calls == 1

        replay = await _post(
            client, provisioned, tool_name=tool_name, idempotency_key="uncertain-1"
        )
        assert replay.json()["error"] == error
        assert executor.calls == 1

        opened = await _post(
            client, provisioned, tool_name=tool_name, idempotency_key="uncertain-2"
        )
        assert opened.json()["error"]["message"] == "upstream_circuit_open"
        assert "receipt" not in opened.json()["error"]["data"]
        assert executor.calls == 1
        assert await _balance(wallet_id) == started - Decimal("2")
        assert await _receipt_count(wallet_id) == 1
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_tool_error_does_not_open_the_breaker(
    client: AsyncClient,
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, breaker=True, threshold=1, recovery=30)
    tool_name = "partner-upstream-tool-error"
    executor = _ReturnedThenOk()
    _register(tool_name, executor)
    try:
        provisioned = await _provision(client, tool_name)
        failed = await _post(
            client, provisioned, tool_name=tool_name, idempotency_key="tool-err-1"
        )
        assert failed.json()["error"]["message"] == "upstream_returned_error"
        followed = await _post(
            client, provisioned, tool_name=tool_name, idempotency_key="tool-err-2"
        )
        assert followed.json()["result"]["isError"] is False
        assert executor.calls == 2
        breaker = get_upstream_admission_gate()._breakers[_ORIGIN]
        assert breaker.state == CircuitBreaker.CLOSED
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_router_releases_the_slot_on_exception_and_cancellation(
    client: AsyncClient,
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, limit=1)
    tool_name = "partner-upstream-slot-release"
    boom = _BoomThenOk()
    _register(tool_name, boom)
    try:
        provisioned = await _provision(client, tool_name)
        failed = await _post(
            client, provisioned, tool_name=tool_name, idempotency_key="boom-1"
        )
        assert failed.json()["error"]["code"] == -32603
        followed = await _post(
            client, provisioned, tool_name=tool_name, idempotency_key="boom-2"
        )
        assert followed.json()["result"]["isError"] is False
        assert boom.calls == 2
    finally:
        get_service_registry().unregister_local(tool_name)

    blocker = _BlockingExecutor()
    cancel_tool = "partner-upstream-slot-cancel"
    _register(cancel_tool, blocker)
    followed_task: asyncio.Task[Any] | None = None
    try:
        provisioned = await _provision(client, cancel_tool)
        held = asyncio.create_task(
            _post(
                client,
                provisioned,
                tool_name=cancel_tool,
                idempotency_key="cancel-1",
            )
        )
        await asyncio.wait_for(blocker.entered.wait(), timeout=5)
        held.cancel()
        with pytest.raises(asyncio.CancelledError):
            await held
        # Cancellation unwinds the call and releases the slot. The follow-up
        # blocks in the executor only after it has taken that slot.
        blocker.entered.clear()
        followed_task = asyncio.create_task(
            _post(
                client,
                provisioned,
                tool_name=cancel_tool,
                idempotency_key="cancel-2",
            )
        )
        await asyncio.wait_for(blocker.entered.wait(), timeout=5)
        blocker.release.set()
        followed = await followed_task
        assert followed.json()["result"]["isError"] is False
        assert blocker.calls == 2
    finally:
        blocker.release.set()
        if followed_task is not None and not followed_task.done():
            followed_task.cancel()
            try:
                await followed_task
            except asyncio.CancelledError:
                pass
        get_service_registry().unregister_local(cancel_tool)
