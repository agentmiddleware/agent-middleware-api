"""Malformed legacy JSON-RPC envelopes get a controlled error, never a 500.

Regression target for the adversarial review finding against
``POST /mcp/messages``: the handler assumed the parsed body and its ``params``
were objects before checking, so an authenticated request carrying an array,
null, string, or number body — or ``tools/call`` with array ``params`` — hit
an attribute error and surfaced as HTTP 500. The same route also let a
malformed ``mcpContext.idempotency_key`` flow into the governed pipeline
untyped.

The contract pinned here: every envelope- or params-shape defect is a JSON-RPC
error (``-32600`` Invalid Request for a non-object body, ``-32602`` Invalid
params for a malformed field) on an HTTP 200, with nothing executed and
nothing charged. The Python SDK reads the ``error`` member of the envelope,
so this shape is what existing clients already handle.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.idempotency import MAX_IDEMPOTENCY_KEY_LENGTH
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    create_tool_permit,
    provision_agent_wallet,
)

TOOL = "legacy-envelope-counted"
JSON_HEADERS = {"Content-Type": "application/json"}


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def counted_tool():
    calls: list[dict[str, Any]] = []

    def _run(message: str = "ok") -> dict[str, Any]:
        calls.append({"message": message})
        return {"message": message}

    registry = get_service_registry()
    registry.register_local(
        service_id=TOOL,
        name="Legacy Envelope Counted Tool",
        description="Counts executions so tests can prove nothing ran",
        category=ServiceCategory.AGENT_COMMS,
        func=_run,
        credits_per_unit=1.0,
        unit_name="call",
    )
    try:
        yield calls
    finally:
        registry.unregister_local(TOOL)


async def _post_raw(client: AsyncClient, body: Any, headers: dict | None = None):
    """POST an arbitrary JSON document (httpx's ``json=None`` would send no body)."""
    return await client.post(
        "/mcp/messages",
        content=json.dumps(body),
        headers={**BOOTSTRAP_HEADERS, **JSON_HEADERS, **(headers or {})},
    )


def _rpc(method: str, params: Any, request_id: Any = "req-1") -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


# --- envelope shape ----------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "body",
    [
        [],
        [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}],  # a batch
        None,
        "tools/list",
        42,
        True,
    ],
    ids=["empty-array", "batch", "null", "string", "number", "bool"],
)
async def test_non_object_body_is_invalid_request_not_500(client, body):
    resp = await _post_raw(client, body)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] is None
    assert payload["error"]["code"] == -32600
    assert payload["error"]["message"].startswith("Invalid Request")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "raw",
    [
        b'{"jsonrpc":"2.0","id":1,"method":"tools/list","x":"\xff"}',
        b"\xff\xfe",
    ],
    ids=["invalid-utf8-in-string", "invalid-utf8-body"],
)
async def test_non_utf8_body_is_bad_request_not_500(client, raw):
    """A non-UTF-8 body raised UnicodeDecodeError past the JSONDecodeError catch."""
    resp = await client.post(
        "/mcp/messages", content=raw, headers={**BOOTSTRAP_HEADERS, **JSON_HEADERS}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "Invalid JSON"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "raw",
    [
        b"[" * 100_000 + b"]" * 100_000,
        b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"category":'
        + b"[" * 100_000
        + b"]" * 100_000
        + b"}}",
    ],
    ids=["bare", "inside-params"],
)
async def test_deeply_nested_body_is_bad_request_not_500(client, raw):
    """The standard endpoint pre-screens nesting depth; the legacy route did not."""
    resp = await client.post(
        "/mcp/messages", content=raw, headers={**BOOTSTRAP_HEADERS, **JSON_HEADERS}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"].startswith("Invalid JSON")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "request_id",
    [{"a": 1}, ["a"], True, False],
    ids=["object", "array", "true", "false"],
)
async def test_non_scalar_id_is_invalid_request(client, request_id):
    resp = await _post_raw(client, _rpc("tools/list", {}, request_id=request_id))
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["id"] is None
    assert payload["error"]["code"] == -32600
    assert payload["error"]["message"].startswith("Invalid Request: id")


@pytest.mark.anyio
async def test_object_body_without_method_is_method_not_found(client):
    resp = await _post_raw(client, {"jsonrpc": "2.0", "id": 7})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["id"] == 7
    assert payload["error"]["code"] == -32601


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["tools/list", "tools/call"])
@pytest.mark.parametrize(
    "params",
    [[], [{"name": TOOL}], "params", 5, False],
    ids=["empty-array", "array-of-objects", "string", "number", "bool"],
)
async def test_non_object_params_is_invalid_params(client, counted_tool, method, params):
    resp = await _post_raw(client, _rpc(method, params))
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["id"] == "req-1"
    assert payload["error"]["code"] == -32602
    assert payload["error"]["message"] == "Invalid params: params must be an object"
    assert counted_tool == []


@pytest.mark.anyio
async def test_null_params_is_tolerated_as_empty(client):
    """JSON-RPC lets ``params`` be omitted; an explicit null is read the same way."""
    listed = await _post_raw(client, _rpc("tools/list", None))
    assert listed.status_code == 200
    assert isinstance(listed.json()["result"]["tools"], list)

    called = await _post_raw(client, _rpc("tools/call", None))
    assert called.status_code == 200
    error = called.json()["error"]
    assert error["code"] == -32602
    assert error["message"] == "Missing tool name"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"name": TOOL, "mcpContext": ["w1"]}, "Invalid params: mcpContext must be an object"),
        ({"name": TOOL, "mcpContext": "w1"}, "Invalid params: mcpContext must be an object"),
        ({"name": 123, "mcpContext": {"wallet_id": "w1"}}, "Invalid params: name must be a string"),
        ({"name": ["a"], "mcpContext": {"wallet_id": "w1"}}, "Invalid params: name must be a string"),
        (
            {"name": TOOL, "arguments": ["hi"], "mcpContext": {"wallet_id": "w1"}},
            "Invalid params: arguments must be an object",
        ),
        (
            {"name": TOOL, "arguments": "hi", "mcpContext": {"wallet_id": "w1"}},
            "Invalid params: arguments must be an object",
        ),
    ],
    ids=[
        "mcpContext-array",
        "mcpContext-string",
        "name-number",
        "name-array",
        "arguments-array",
        "arguments-string",
    ],
)
async def test_malformed_tools_call_fields_are_invalid_params(
    client, counted_tool, params, message
):
    resp = await _post_raw(client, _rpc("tools/call", params))
    assert resp.status_code == 200, resp.text
    error = resp.json()["error"]
    assert error["code"] == -32602
    assert error["message"] == message
    assert counted_tool == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("wallet_id", ["w1"]),
        ("wallet_id", {"id": "w1"}),
        ("permit_id", {"id": "p1"}),
        ("permit_id", 7),
        ("quote_id", ["q1"]),
        ("quote_id", 3.5),
    ],
)
async def test_non_string_mcp_context_identifiers_are_invalid_params(
    client, counted_tool, field, value
):
    """A list or object here used to reach the SQL driver and echo its error text."""
    context: dict[str, Any] = {"wallet_id": "w1", field: value}
    resp = await _post_raw(client, _rpc("tools/call", {"name": TOOL, "mcpContext": context}))
    assert resp.status_code == 200, resp.text
    error = resp.json()["error"]
    assert error["code"] == -32602
    assert error["message"] == f"Invalid params: mcpContext.{field} must be a string"
    assert "SELECT" not in error["message"]
    assert counted_tool == []


@pytest.mark.anyio
async def test_null_mcp_context_and_arguments_are_tolerated(client, counted_tool):
    """Explicit nulls read as "not supplied", matching the pre-existing ``or {}``."""
    resp = await _post_raw(
        client, _rpc("tools/call", {"name": TOOL, "arguments": None, "mcpContext": None})
    )
    assert resp.status_code == 200
    error = resp.json()["error"]
    assert error["code"] == -32602
    assert error["message"] == "Missing wallet_id in mcpContext"
    assert counted_tool == []


# --- idempotency key on the legacy route -------------------------------------


async def _governed_agent(client: AsyncClient) -> dict[str, Any]:
    """An agent wallet plus a signed permit for TOOL, so calls are governed.

    The legacy route only keys and receipts *governed* calls (a permit is
    present, or trust mode forbids unpermitted MCP); the test environment
    allows unpermitted legacy MCP, so a permit is what puts these requests
    on the metered, replay-protected path the finding is about.
    """
    agent = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=agent["agent_wallet_id"],
        key_id=agent["key_id"],
        tool_name=TOOL,
        max_credits=10,
    )
    return {**agent, "permit_id": permit["permit_id"]}


def _legacy_call(agent: dict[str, Any], **context: Any) -> dict:
    mcp_context: dict[str, Any] = {"wallet_id": agent["agent_wallet_id"], **context}
    if "permit_id" in agent:
        mcp_context["permit_id"] = agent["permit_id"]
    return _rpc("tools/call", {"name": TOOL, "arguments": {"message": "hi"}, "mcpContext": mcp_context})


def _assert_invalid_key(payload: dict, *, reason_code: str, sources: list[str]) -> None:
    error = payload["error"]
    assert error["code"] == -32602
    assert error["message"] == "invalid_idempotency_key"
    assert error["data"]["error"] == "invalid_idempotency_key"
    assert error["data"]["reason_code"] == reason_code
    assert error["data"]["sources"] == sources
    assert error["data"]["remediation"]["type"] == "retry_with_valid_idempotency_key"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("bad_key", "reason_code"),
    [
        ("", "idempotency_key_empty"),
        (123, "idempotency_key_not_a_string"),
        (["k"], "idempotency_key_not_a_string"),
        ({"k": "v"}, "idempotency_key_not_a_string"),
        ("x" * (MAX_IDEMPOTENCY_KEY_LENGTH + 1), "idempotency_key_too_long"),
        ("\ud800", "idempotency_key_invalid_characters"),
        ("\x00k", "idempotency_key_invalid_characters"),
    ],
)
async def test_malformed_mcp_context_key_is_refused_before_execution(
    client, clean_database, counted_tool, bad_key, reason_code
):
    """Same contract as the standard endpoint, on the legacy route's own field."""
    agent = await _governed_agent(client)
    for attempt in (1, 2):
        # Pre-serialized with ASCII escapes so a lone surrogate travels as the
        # "\ud800" escape a real client would send.
        resp = await client.post(
            "/mcp/messages",
            content=json.dumps(_legacy_call(agent, idempotency_key=bad_key)),
            headers={**agent["agent_headers"], **JSON_HEADERS},
        )
        assert resp.status_code == 200, resp.text
        _assert_invalid_key(resp.json(), reason_code=reason_code, sources=["mcpContext"])
    assert counted_tool == []
    ledger = await client.get(
        f"/v1/billing/ledger/{agent['agent_wallet_id']}", headers=agent["agent_headers"]
    )
    assert [e for e in ledger.json()["entries"] if TOOL in e["description"]] == []


@pytest.mark.anyio
async def test_empty_idempotency_header_on_legacy_route_is_refused(
    client, clean_database, counted_tool
):
    agent = await _governed_agent(client)
    resp = await client.post(
        "/mcp/messages",
        json=_legacy_call(agent),
        headers={**agent["agent_headers"], "Idempotency-Key": ""},
    )
    assert resp.status_code == 200, resp.text
    _assert_invalid_key(resp.json(), reason_code="idempotency_key_empty", sources=["header"])
    assert counted_tool == []


@pytest.mark.anyio
async def test_legacy_header_and_mcp_context_keys_must_agree(
    client, clean_database, counted_tool
):
    """The old code let mcpContext win silently over a differing header."""
    agent = await _governed_agent(client)
    resp = await client.post(
        "/mcp/messages",
        json=_legacy_call(agent, idempotency_key="body-key"),
        headers={**agent["agent_headers"], "Idempotency-Key": "header-key"},
    )
    assert resp.status_code == 200, resp.text
    _assert_invalid_key(
        resp.json(),
        reason_code="idempotency_key_conflict",
        sources=["header", "mcpContext"],
    )
    assert counted_tool == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "template",
    [
        '{"jsonrpc":"2.0","id":NaN,"method":"tools/call","params":%s}',
        '{"jsonrpc":"2.0","id":Infinity,"method":"tools/call","params":%s}',
        '{"jsonrpc":"2.0","id":-Infinity,"method":"tools/call","params":%s}',
        '{"jsonrpc":"2.0","id":1e400,"method":"tools/call","params":%s}',
    ],
    ids=["NaN-id", "Infinity-id", "-Infinity-id", "overflow-id"],
)
async def test_non_finite_id_is_refused_before_execution(
    client, clean_database, counted_tool, template
):
    """The worst of the envelope 500s: the tool ran and the wallet was charged,
    then echoing a non-finite ``id`` blew up response serialization, so the
    caller saw HTTP 500 for a call that had happened. A retry with the same
    key 500'd again on the replay. Non-finite numbers are now a parse error.
    """
    agent = await _governed_agent(client)
    params = json.dumps(_legacy_call(agent, idempotency_key="nonfinite-1")["params"])
    for _ in (1, 2):
        resp = await client.post(
            "/mcp/messages",
            content=(template % params).encode(),
            headers={**agent["agent_headers"], **JSON_HEADERS},
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"] == "Invalid JSON"
    assert counted_tool == []
    ledger = await client.get(
        f"/v1/billing/ledger/{agent['agent_wallet_id']}", headers=agent["agent_headers"]
    )
    assert [e for e in ledger.json()["entries"] if TOOL in e["description"]] == []


@pytest.mark.anyio
async def test_non_finite_argument_is_refused_before_execution(
    client, clean_database, counted_tool
):
    """Same class inside ``arguments``: an echoed NaN would 500 after the charge."""
    agent = await _governed_agent(client)
    body = _legacy_call(agent, idempotency_key="nonfinite-arg-1")
    body["params"]["arguments"] = {"message": "__NAN__"}
    raw = json.dumps(body).replace('"__NAN__"', "NaN")
    resp = await client.post(
        "/mcp/messages", content=raw.encode(), headers={**agent["agent_headers"], **JSON_HEADERS}
    )
    assert resp.status_code == 400, resp.text
    assert counted_tool == []


@pytest.mark.anyio
async def test_finite_float_id_is_still_echoed(client):
    """Only non-finite numbers are refused; an ordinary numeric id round-trips."""
    resp = await _post_raw(client, _rpc("tools/list", {}, request_id=2.5))
    assert resp.status_code == 200
    assert resp.json()["id"] == 2.5
    assert "result" in resp.json()


# --- the deprecated REST route holds the same contract -----------------------


def _rest_body(agent: dict[str, Any], **context: Any) -> dict:
    mcp_context: dict[str, Any] = {"wallet_id": agent["agent_wallet_id"], **context}
    if "permit_id" in agent:
        mcp_context["permit_id"] = agent["permit_id"]
    return {"name": TOOL, "arguments": {"message": "hi"}, "mcp_context": mcp_context}


def _assert_rest_invalid_key(resp, *, reason_code: str, sources: list[str]) -> None:
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "invalid_idempotency_key"
    assert detail["reason_code"] == reason_code
    assert detail["sources"] == sources
    assert detail["remediation"]["type"] == "retry_with_valid_idempotency_key"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("bad_key", "reason_code"),
    [
        ("", "idempotency_key_empty"),
        ("   ", "idempotency_key_empty"),
        ("x" * (MAX_IDEMPOTENCY_KEY_LENGTH + 1), "idempotency_key_too_long"),
        ("\x00k", "idempotency_key_invalid_characters"),
    ],
)
async def test_rest_invoke_refuses_malformed_body_key(
    client, clean_database, counted_tool, bad_key, reason_code
):
    """``POST /mcp/tools/{id}/invoke`` used to pass the body key through a bare
    ``or``: an empty key fell through to the header, a whitespace-only or
    over-long key reached the store verbatim. Pydantic already rejects
    non-string keys (422); this pins the rest of the contract.
    """
    agent = await _governed_agent(client)
    for _ in (1, 2):
        resp = await client.post(
            f"/mcp/tools/{TOOL}/invoke",
            json=_rest_body(agent, idempotency_key=bad_key),
            headers=agent["agent_headers"],
        )
        _assert_rest_invalid_key(resp, reason_code=reason_code, sources=["mcpContext"])
    assert counted_tool == []


@pytest.mark.anyio
async def test_rest_invoke_refuses_disagreeing_header_and_body_keys(
    client, clean_database, counted_tool
):
    agent = await _governed_agent(client)
    resp = await client.post(
        f"/mcp/tools/{TOOL}/invoke",
        json=_rest_body(agent, idempotency_key="body-key"),
        headers={**agent["agent_headers"], "Idempotency-Key": "header-key"},
    )
    _assert_rest_invalid_key(
        resp, reason_code="idempotency_key_conflict", sources=["header", "mcpContext"]
    )
    assert counted_tool == []


@pytest.mark.anyio
async def test_rest_invoke_matching_keys_replay_as_one_action(
    client, clean_database, counted_tool
):
    agent = await _governed_agent(client)
    headers = {**agent["agent_headers"], "Idempotency-Key": "rest-same-key"}
    first = await client.post(
        f"/mcp/tools/{TOOL}/invoke",
        json=_rest_body(agent, idempotency_key="rest-same-key"),
        headers=headers,
    )
    second = await client.post(
        f"/mcp/tools/{TOOL}/invoke",
        json=_rest_body(agent, idempotency_key="rest-same-key"),
        headers=headers,
    )
    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    assert first.json()["receipt"]["receipt_id"] == second.json()["receipt"]["receipt_id"]
    assert len(counted_tool) == 1


@pytest.mark.anyio
async def test_rest_invoke_header_only_key_still_works(client, clean_database, counted_tool):
    """A header with no body key is the documented single-source path."""
    agent = await _governed_agent(client)
    headers = {**agent["agent_headers"], "Idempotency-Key": "rest-header-only"}
    first = await client.post(
        f"/mcp/tools/{TOOL}/invoke", json=_rest_body(agent), headers=headers
    )
    second = await client.post(
        f"/mcp/tools/{TOOL}/invoke", json=_rest_body(agent), headers=headers
    )
    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    assert first.json()["receipt"]["receipt_id"] == second.json()["receipt"]["receipt_id"]
    assert len(counted_tool) == 1


@pytest.mark.anyio
async def test_legacy_matching_keys_replay_as_one_action(client, clean_database, counted_tool):
    """Control: the SDK sends the same key in both places and must keep working."""
    agent = await _governed_agent(client)
    headers = {**agent["agent_headers"], "Idempotency-Key": "same-key"}
    first = await client.post(
        "/mcp/messages", json=_legacy_call(agent, idempotency_key="same-key"), headers=headers
    )
    second = await client.post(
        "/mcp/messages", json=_legacy_call(agent, idempotency_key="same-key"), headers=headers
    )
    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    assert (
        first.json()["result"]["receipt"]["receipt_id"]
        == second.json()["result"]["receipt"]["receipt_id"]
    )
    assert len(counted_tool) == 1
