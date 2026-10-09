"""Focused coverage for the OpenAI runner's public behavior.

Complements test_governed_flow.py (which pins the operation identity and
crash recovery contracts) by exercising the remaining public surface of
openai_b2a.runner: key helpers, both key stores, one happy path run, and
refusal paths that must stay silent on the wire.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from openai_b2a import (
    B2AClient,
    GovernedToolRunner,
    InMemoryOperationKeyStore,
    JsonFileOperationKeyStore,
    OperationRecord,
    PermitRecord,
    normalize_tool_call,
)
from openai_b2a.runner import function_name_for, operation_key_for

TOOL = "partner.notes.write"
WALLET = "wallet-1"


def _permit_payload(permit_id: str = "permit-1") -> dict:
    now = datetime.now(UTC)
    return {
        "permit_id": permit_id,
        "issuer_wallet_id": WALLET,
        "subject_wallet_id": WALLET,
        "subject_key_id": "key-1",
        "scopes": [f"tool:{TOOL}:invoke", "billing:charge"],
        "allowed_tools": [TOOL],
        "max_credits": "100",
        "spent_credits": "0",
        "expires_at": (now + timedelta(minutes=30)).isoformat(),
        "nonce": "nonce-1",
        "status": "active",
        "signature": "sig-permit-1",
        "key_id": "signing-key-1",
        "issued_at": now.isoformat(),
        "revoked_at": None,
    }


def _receipt_payload(idempotency_key: str, receipt_id: str = "rcpt-1") -> dict:
    return {
        "receipt_id": receipt_id,
        "idempotency_record_id": "idem-1",
        "permit_id": "permit-1",
        "wallet_id": WALLET,
        "key_id": "key-1",
        "tool": TOOL,
        "request_hash": "a" * 64,
        "response_hash": "b" * 64,
        "ledger_entry_id": "ledger-1",
        "dispatch_attempt_id": None,
        "credits_authorized": "2",
        "credits_charged": "2",
        "outcome": "success",
        "audit_event_id": "audit-1",
        "created_at": datetime.now(UTC).isoformat(),
        "signature": "sig-receipt-1",
        "signature_key_id": "signing-key-1",
        "idempotency_key": idempotency_key,
    }


class FakeTrustPlane:
    def __init__(self) -> None:
        self.permit_requests: list[httpx.Request] = []
        self.invoke_requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            self.permit_requests.append(request)
            return httpx.Response(201, json=_permit_payload())
        if request.url.path == "/mcp/messages":
            self.invoke_requests.append(request)
            body = json.loads(request.content)
            key = body["params"]["mcpContext"]["idempotency_key"]
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "content": [{"type": "text", "text": "ok"}],
                        "structuredContent": {"ok": True},
                        "isError": False,
                        "receipt": _receipt_payload(key),
                    },
                },
            )
        return httpx.Response(404, json={"detail": "unexpected path"})


def _client(plane: FakeTrustPlane) -> B2AClient:
    return B2AClient(api_key="test-key", base_url="http://trust.test", transport=plane.transport())


def _chat_tool_call(call_id: str = "call_abc123") -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=function_name_for(TOOL), arguments='{"text": "hi"}'),
    )


def _runner(plane: FakeTrustPlane, **kwargs) -> GovernedToolRunner:
    return GovernedToolRunner(_client(plane), wallet_id=WALLET, run_id="run-1", **kwargs)


# -- key helpers -------------------------------------------------------------


def test_normalize_tool_call_accepts_chat_completions_dict():
    call = normalize_tool_call(
        {"id": "call_1", "function": {"name": "f", "arguments": '{"text": "hi"}'}}
    )
    assert call.id == "call_1"
    assert call.name == "f"
    assert call.arguments == {"text": "hi"}


def test_normalize_tool_call_accepts_responses_api_call_id():
    call = normalize_tool_call({"call_id": "call_xyz", "name": "f", "arguments": {"text": "hi"}})
    assert call.id == "call_xyz"
    assert call.arguments == {"text": "hi"}


@pytest.mark.parametrize("bad_id", [None, "", "   "])
def test_normalize_tool_call_refuses_missing_id(bad_id):
    with pytest.raises(ValueError, match="no id"):
        normalize_tool_call({"id": bad_id, "function": {"name": "f", "arguments": "{}"}})


def test_normalize_tool_call_rejects_non_object_arguments():
    with pytest.raises(TypeError):
        normalize_tool_call({"id": "call_1", "function": {"name": "f", "arguments": "[1, 2]"}})


def test_operation_key_for_prefixes_the_call_id():
    assert operation_key_for("call_abc") == "oai-call_abc"


@pytest.mark.parametrize("bad_id", ["", "   ", "c" * 125])
def test_operation_key_for_rejects_unusable_ids(bad_id):
    with pytest.raises(ValueError):
        operation_key_for(bad_id)


def test_function_name_for_sanitizes_and_truncates():
    assert function_name_for("partner.notes.write") == "partner_notes_write"
    assert len(function_name_for("n" * 100)) == 64


# -- stores ------------------------------------------------------------------


def test_in_memory_store_roundtrips_operation_and_permit():
    store = InMemoryOperationKeyStore()
    operation = OperationRecord(
        tool_call_id="call_1",
        tool_name=TOOL,
        idempotency_key="oai-call_1",
        permit_idempotency_key=f"oai-permit-run-1-{TOOL}",
    )
    store.put_operation(operation)
    assert store.get_operation("call_1") == operation
    assert store.get_operation("call_missing") is None

    permit = PermitRecord(
        permit_idempotency_key=f"oai-permit-run-1-{TOOL}",
        tool_name=TOOL,
        expires_at=datetime.now(UTC).isoformat(),
    )
    store.put_permit(permit)
    assert store.get_permit(permit.permit_idempotency_key) == permit


def test_json_file_store_roundtrips_across_instances(tmp_path):
    path = tmp_path / "operations.json"
    first = JsonFileOperationKeyStore(path)
    operation = OperationRecord(
        tool_call_id="call_1",
        tool_name=TOOL,
        idempotency_key="oai-call_1",
        permit_idempotency_key=f"oai-permit-run-1-{TOOL}",
        permit_id="permit-1",
        receipt_id="rcpt-1",
    )
    first.put_operation(operation)

    second = JsonFileOperationKeyStore(path)
    assert second.get_operation("call_1") == operation


def test_json_file_store_rejects_a_non_object_file(tmp_path):
    path = tmp_path / "operations.json"
    path.write_text("[1, 2]")
    with pytest.raises(TypeError):
        JsonFileOperationKeyStore(path).get_operation("call_1")


# -- runner ------------------------------------------------------------------


async def test_run_executes_one_governed_action_and_renders_outputs():
    plane = FakeTrustPlane()
    runner = _runner(plane)
    runner.register_tool(TOOL, description="Append a note")

    result = await runner.run(_chat_tool_call("call_abc123"))

    assert result.tool_call_id == "call_abc123"
    assert result.idempotency_key == "oai-call_abc123"
    assert result.receipt.receipt_id == "rcpt-1"
    assert len(plane.permit_requests) == 1
    assert len(plane.invoke_requests) == 1

    message = result.as_tool_message()
    assert message["role"] == "tool"
    assert message["tool_call_id"] == "call_abc123"
    payload = json.loads(message["content"])
    assert payload["idempotency_key"] == "oai-call_abc123"
    assert payload["receipt"]["receipt_id"] == "rcpt-1"

    item = result.as_function_call_output()
    assert item["type"] == "function_call_output"
    assert json.loads(item["output"]) == payload


async def test_run_all_executes_calls_in_order():
    plane = FakeTrustPlane()
    runner = _runner(plane)
    runner.register_tool(TOOL, description="Append a note")

    results = await runner.run_all([_chat_tool_call("call_1"), _chat_tool_call("call_2")])

    assert [r.idempotency_key for r in results] == ["oai-call_1", "oai-call_2"]
    assert len(plane.permit_requests) == 1


async def test_run_refuses_unregistered_function_without_network_or_persistence(tmp_path):
    plane = FakeTrustPlane()
    store_path = tmp_path / "operations.json"
    runner = GovernedToolRunner(
        _client(plane),
        wallet_id=WALLET,
        run_id="run-1",
        key_store=JsonFileOperationKeyStore(store_path),
    )
    runner.register_tool(TOOL, description="Append a note")
    call = _chat_tool_call()
    call.function.name = "unadvertised_tool"

    with pytest.raises(ValueError, match="not registered"):
        await runner.run(call)

    assert not store_path.exists()
    assert plane.permit_requests == [] and plane.invoke_requests == []


async def test_run_refuses_tool_call_without_id_before_any_network_call():
    plane = FakeTrustPlane()
    runner = _runner(plane)
    runner.register_tool(TOOL, description="Append a note")

    with pytest.raises(ValueError):
        await runner.run(_chat_tool_call("   "))

    assert plane.permit_requests == [] and plane.invoke_requests == []


def test_register_tool_rejects_colliding_function_name():
    runner = _runner(FakeTrustPlane())
    runner.register_tool("a.b", description="x")
    with pytest.raises(ValueError, match="already maps"):
        runner.register_tool("a_b", description="y")


def test_permit_key_is_scoped_to_run_and_tool():
    runner = _runner(FakeTrustPlane())
    assert runner.permit_key_for(TOOL) == f"oai-permit-run-1-{TOOL}"
