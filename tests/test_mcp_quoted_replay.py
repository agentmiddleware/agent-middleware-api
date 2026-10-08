"""Consumed quotes recover only already-completed governed invocations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import (
    IdempotencyRecordModel,
    LedgerEntryModel,
    PermitModel,
    QuoteModel,
)
from app.main import app
from app.routers import mcp as mcp_router
from app.schemas.billing import ServiceCategory
from app.services.idempotency import (
    GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
    get_idempotency_service,
)
from app.services.permits import get_permit_service
from app.services.quotes import get_quote_service
from app.services.service_registry import get_service_registry
from tests.test_mcp_upstream_governed import (
    FakeUpstreamExecutor,
    _call_body,
    _register_upstream,
    _rest_call_body,
)
from tests.test_trust_helpers import BOOTSTRAP_HEADERS, provision_agent_wallet


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


@dataclass
class QuotedCase:
    client: AsyncClient
    transport: str
    backend: str
    agent: dict[str, Any]
    tool: str
    key: str
    permit: dict[str, Any]
    quote: dict[str, Any]
    body: dict[str, Any]
    executor: FakeUpstreamExecutor
    local_calls: list[str]

    @property
    def path(self) -> str:
        return (
            "/mcp/messages"
            if self.transport == "jsonrpc"
            else f"/mcp/tools/{self.tool}/invoke"
        )

    @property
    def context(self) -> dict[str, Any]:
        return (
            self.body["params"]["mcpContext"]
            if self.transport == "jsonrpc"
            else self.body["mcp_context"]
        )

    @property
    def wire(self) -> bytes:
        return json.dumps(self.body, sort_keys=True, separators=(",", ":")).encode()

    async def call(
        self, *, content: bytes | None = None, headers: dict | None = None
    ) -> Response:
        return await self.client.post(
            self.path,
            content=self.wire if content is None else content,
            headers={
                **(headers or self.agent["agent_headers"]),
                "Content-Type": "application/json",
            },
        )

    def result(self, response: Response) -> dict[str, Any]:
        body = response.json()
        return body["result"] if self.transport == "jsonrpc" else body

    async def complete(self) -> Response:
        response = await self.call()
        assert response.status_code == 200, response.text
        assert self.result(response)["isError"] is False
        return response

    async def snapshot(self) -> dict[str, Any]:
        async with get_session_factory()() as session:
            permit = await session.get(PermitModel, self.permit["permit_id"])
            quote = await session.get(QuoteModel, self.quote["quote_id"])
            debits = (
                (
                    await session.execute(
                        select(LedgerEntryModel).where(
                            LedgerEntryModel.wallet_id == self.agent["agent_wallet_id"],
                            LedgerEntryModel.action == "debit",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert permit is not None and quote is not None
            return {
                "debit_ids": [row.entry_id for row in debits],
                "debit_amount": sum((row.amount for row in debits), Decimal(0)),
                "spent": permit.spent_credits,
                "counts": permit.tool_call_counts_json,
                "max_credits": permit.max_credits,
                "max_calls": permit.max_calls_per_tool_json,
                "quote_status": quote.status,
                "quote_key": quote.consumed_by_idempotency_key,
                "quote_consumed_at": quote.consumed_at,
            }

    def assert_one_execution(self) -> None:
        if self.backend == "upstream":
            assert len(self.executor.calls) == self.executor.dispatch_count == 1
        else:
            assert self.local_calls == ["hello"]

    def error(self, response: Response) -> str:
        payload = response.json()
        if self.transport == "jsonrpc":
            assert "result" not in payload
            return payload["error"]["message"]
        assert response.status_code >= 400
        detail = payload["detail"]
        return detail["error"] if isinstance(detail, dict) else detail

    async def record(self):
        return await get_idempotency_service().get_governed_mcp_record(
            wallet_id=self.agent["agent_wallet_id"], idempotency_key=self.key
        )


@pytest.fixture
async def quoted_case(client, clean_database, request):
    transport, backend = request.param
    agent = await provision_agent_wallet(client)
    tool = f"quoted-replay-{backend}-{transport}"
    executor = FakeUpstreamExecutor("success")
    local_calls = []
    registry = get_service_registry()
    if backend == "upstream":
        _register_upstream(tool, executor)
    else:

        def echo(message: str) -> dict:
            local_calls.append(message)
            return {"message": message}

        registry.register_local(
            service_id=tool,
            name="Quoted replay test",
            description="Local fixture",
            category=ServiceCategory.AGENT_COMMS,
            func=echo,
            credits_per_unit=2,
            unit_name="call",
        )
    try:
        permit_response = await client.post(
            "/v1/permits",
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": tool + "-permit"},
            json={
                "issuer_wallet_id": agent["agent_wallet_id"],
                "subject_wallet_id": agent["agent_wallet_id"],
                "subject_key_id": agent["key_id"],
                "allowed_tools": [tool],
                "scopes": [f"tool:{tool}:invoke", "billing:charge"],
                "max_credits": 2,
                "max_calls_per_tool": {tool: 1},
                "expires_at": (utc_now() + timedelta(minutes=30)).isoformat(),
            },
        )
        assert permit_response.status_code == 201, permit_response.text
        permit = permit_response.json()
        quote_response = await client.post(
            "/v1/quotes",
            headers=agent["agent_headers"],
            json={"wallet_id": agent["agent_wallet_id"], "tool": tool},
        )
        assert quote_response.status_code == 201, quote_response.text
        quote = quote_response.json()
        key = tool + "-operation"
        builder = _call_body if transport == "jsonrpc" else _rest_call_body
        body = builder(
            tool_name=tool,
            wallet_id=agent["agent_wallet_id"],
            permit_id=permit["permit_id"],
            idempotency_key=key,
        )
        case = QuotedCase(
            client,
            transport,
            backend,
            agent,
            tool,
            key,
            permit,
            quote,
            body,
            executor,
            local_calls,
        )
        case.context["quote_id"] = quote["quote_id"]
        yield case
    finally:
        registry.unregister_local(tool)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "quoted_case",
    [
        (transport, backend)
        for transport in ("jsonrpc", "rest")
        for backend in ("upstream", "local")
    ],
    indirect=True,
)
async def test_completed_quoted_replay_preserves_result_dispatch_debit_and_caps(
    quoted_case,
):
    case = quoted_case
    wire = case.wire
    first = await case.complete()
    before = await case.snapshot()
    assert len(before["debit_ids"]) == 1 and before["debit_amount"] == Decimal("-2")
    assert before["spent"] == before["max_credits"] == Decimal("2")
    assert json.loads(before["max_calls"]) == {case.tool: 1}
    assert before["quote_status"] == "consumed" and before["quote_key"] == case.key
    for _ in range(2):
        replay = await case.call(content=wire)
        assert replay.status_code == 200, replay.text
        assert replay.content == first.content
    assert await case.snapshot() == before
    case.assert_one_execution()


UPSTREAM_TRANSPORTS = [("jsonrpc", "upstream"), ("rest", "upstream")]


@pytest.mark.anyio
@pytest.mark.parametrize("quoted_case", UPSTREAM_TRANSPORTS, indirect=True)
@pytest.mark.parametrize(
    "change", ["payload", "fresh_key", "second_key", "wrong_wallet", "foreign_caller"]
)
async def test_completed_quote_keeps_existing_conflict_and_identity_checks(
    quoted_case, change
):
    case = quoted_case
    await case.complete()
    before = await case.snapshot()
    headers = case.agent["agent_headers"]
    if change == "payload":
        arguments = (
            case.body["params"]["arguments"]
            if case.transport == "jsonrpc"
            else case.body["arguments"]
        )
        arguments["message"] = "changed"
        expected = "idempotency_key_reused"
    elif change == "fresh_key":
        case.context["idempotency_key"] = case.key + "-fresh"
        expected = "quote_already_consumed"
    elif change == "second_key":
        key_response = await case.client.post(
            "/v1/api-keys",
            headers=BOOTSTRAP_HEADERS,
            json={
                "wallet_id": case.agent["agent_wallet_id"],
                "key_name": "quoted-replay-second-key",
                "expires_in_days": 30,
            },
        )
        assert key_response.status_code == 201
        headers = {"X-API-Key": key_response.json()["api_key"]}
        expected = "permit_key_mismatch"
    else:
        other_agent = await provision_agent_wallet(case.client)
        headers = other_agent["agent_headers"]
        if change == "wrong_wallet":
            case.context["wallet_id"] = other_agent["agent_wallet_id"]
            expected = "quote_wallet_mismatch"
        else:
            expected = "wallet_access_denied"
    response = await case.call(headers=headers)
    assert case.error(response) == expected
    assert await case.snapshot() == before
    case.assert_one_execution()
    if change == "fresh_key":
        assert (
            await get_idempotency_service().get_governed_mcp_record(
                wallet_id=case.agent["agent_wallet_id"],
                idempotency_key=case.key + "-fresh",
            )
            is None
        )


@pytest.mark.anyio
@pytest.mark.parametrize("quoted_case", UPSTREAM_TRANSPORTS, indirect=True)
@pytest.mark.parametrize("constraint", ["revoked", "expired"])
async def test_completed_quoted_evidence_replays_after_execution_authority_ends(
    quoted_case, monkeypatch, constraint
):
    case = quoted_case
    first = await case.complete()
    before = await case.snapshot()
    if constraint == "revoked":
        revoked = await get_permit_service().revoke_permit(case.permit["permit_id"])
        assert revoked.status == "revoked"
    else:
        # Move the permit service clock past its signed expiry without altering
        # the signed permit or weakening verification of the existing receipt.
        import app.services.permits as permits_module

        future = utc_now() + timedelta(hours=1)
        monkeypatch.setattr(permits_module, "utc_now", lambda: future)
    admission = await get_permit_service().validate_for_action(
        permit_id=case.permit["permit_id"],
        wallet_id=case.agent["agent_wallet_id"],
        tool_name=case.tool,
        estimated_credits=Decimal(0),
        key_id=case.agent["key_id"],
    )
    assert admission.allowed is False
    assert admission.reason == f"permit_{constraint}"
    replay = await case.call()
    assert replay.status_code == 200, replay.text
    assert replay.content == first.content
    assert await case.snapshot() == before
    case.assert_one_execution()


async def seed_consumed_quote(case, *, state="missing", endpoint=None):
    consumed = await get_quote_service().consume(
        case.quote["quote_id"], idempotency_key=case.key
    )
    assert consumed is True
    if state == "missing":
        return
    logical = {
        "tool_name": case.tool,
        "arguments": {"message": "hello"},
        "wallet_id": case.agent["agent_wallet_id"],
        "permit_id": case.permit["permit_id"],
    }
    idem = get_idempotency_service()
    endpoint = endpoint or GOVERNED_MCP_IDEMPOTENCY_ENDPOINT
    await idem.begin_with_record(
        wallet_id=case.agent["agent_wallet_id"],
        endpoint=endpoint,
        idempotency_key=case.key,
        request_payload=logical
        if endpoint == GOVERNED_MCP_IDEMPOTENCY_ENDPOINT
        else case.body,
        operation_kind="upstream_mcp",
    )
    if state in {"completed", "empty"}:
        response = (
            {}
            if state == "empty"
            else {
                "isError": False,
                "content": [],
                "receipt": {"receipt_id": "rcpt-quoted-fixture"},
            }
        )
        await idem.complete(
            wallet_id=case.agent["agent_wallet_id"],
            endpoint=endpoint,
            idempotency_key=case.key,
            response_reference="rcpt-quoted-fixture",
            response_json=response,
            status_code=200,
        )


@pytest.mark.anyio
@pytest.mark.parametrize("quoted_case", UPSTREAM_TRANSPORTS, indirect=True)
@pytest.mark.parametrize("record_state", ["missing", "in_progress", "empty"])
async def test_consumed_quote_without_completed_record_never_starts_work(
    quoted_case, record_state
):
    case = quoted_case
    await seed_consumed_quote(case, state=record_state)
    before = await case.snapshot()
    record_before = await case.record()
    response = await case.call()
    assert case.error(response) == "quote_already_consumed"
    assert await case.snapshot() == before
    assert case.executor.calls == [] and case.executor.dispatch_count == 0
    record_after = await case.record()
    if record_state == "missing":
        assert record_after is None
    else:
        assert record_after.record_id == record_before.record_id
        assert record_after.response_json == record_before.response_json


@pytest.mark.anyio
@pytest.mark.parametrize("quoted_case", UPSTREAM_TRANSPORTS, indirect=True)
@pytest.mark.parametrize("delete_at", ["helper_entry", "record_lookup"])
@pytest.mark.parametrize("identity", ["canonical", "legacy"])
async def test_consumed_quote_record_disappearing_never_creates_a_replacement(
    quoted_case, monkeypatch, delete_at, identity
):
    case = quoted_case
    endpoint = (
        GOVERNED_MCP_IDEMPOTENCY_ENDPOINT if identity == "canonical" else case.path
    )
    await seed_consumed_quote(case, state="completed", endpoint=endpoint)
    before = await case.snapshot()
    record = await case.record()
    assert record is not None
    deleted = False

    async def remove_record():
        nonlocal deleted
        if deleted:
            return
        async with get_session_factory()() as session:
            current = await session.get(IdempotencyRecordModel, record.record_id)
            assert current is not None
            await session.delete(current)
            await session.commit()
        deleted = True

    if delete_at == "helper_entry":
        original = mcp_router._begin_governed_mcp_idempotency

        async def remove_before_helper(**kwargs):
            await remove_record()
            return await original(**kwargs)

        monkeypatch.setattr(
            mcp_router, "_begin_governed_mcp_idempotency", remove_before_helper
        )
    else:
        idem = get_idempotency_service()
        original = idem.begin_with_record

        async def remove_before_lookup(**kwargs):
            await remove_record()
            return await original(**kwargs)

        monkeypatch.setattr(idem, "begin_with_record", remove_before_lookup)
    response = await case.call()
    assert deleted is True
    assert case.error(response) == "quote_already_consumed"
    assert await case.record() is None
    assert await case.snapshot() == before
    assert case.executor.calls == [] and case.executor.dispatch_count == 0
