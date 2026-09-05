"""A present-but-invalid idempotency key is refused, never defaulted.

Regression target for the adversarial review finding against the standard
MCP endpoint (``POST /mcp``): a malformed
``params._meta["io.agentmiddleware/idempotency_key"]`` — empty string,
integer, array, object, or over-long string — failed the extractor's checks,
came back as "no key", and was replaced by a generated per-call key. Two
identical retries carrying the same bad key therefore executed the tool twice
and debited the wallet twice, while the valid-key control replayed correctly.

The contract pinned here:

* an absent key keeps the documented default (a generated key per call);
* a supplied key must be a non-empty string no longer than the idempotency
  store can persist;
* the header and ``_meta`` must agree when both are present;
* anything else is ``-32602 invalid_idempotency_key`` before any permit is
  minted, tool executed, or wallet charged.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.db.models import IdempotencyRecordModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.idempotency import (
    MAX_IDEMPOTENCY_KEY_LENGTH,
    InvalidIdempotencyKeyError,
    resolve_client_idempotency_key,
    validate_idempotency_key,
)
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import provision_agent_wallet

META_KEY = "io.agentmiddleware/idempotency_key"
TOOL = "idempotency-validation-counted"
TOOL_COST = Decimal("2")

# The SDK's streamable HTTP transport requires an explicit Accept header.
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def standard_mcp_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_STANDARD_MCP_ENDPOINT", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.setenv("ENABLE_STANDARD_MCP_ENDPOINT", "false")
    get_settings.cache_clear()


@pytest.fixture
def counted_tool():
    """A priced local tool that counts how many times it really executed."""
    calls: list[dict[str, Any]] = []

    def _run(message: str = "ok") -> dict[str, Any]:
        calls.append({"message": message})
        return {"message": message, "count": len(calls)}

    registry = get_service_registry()
    registry.register_local(
        service_id=TOOL,
        name="Idempotency Validation Counted Tool",
        description="Counts executions so tests can prove nothing ran",
        category=ServiceCategory.AGENT_COMMS,
        func=_run,
        credits_per_unit=float(TOOL_COST),
        unit_name="call",
    )
    try:
        yield calls
    finally:
        registry.unregister_local(TOOL)


def _tools_call(meta: dict[str, Any] | None = None, request_id: int = 1) -> dict:
    params: dict[str, Any] = {"name": TOOL, "arguments": {"message": "hi"}}
    if meta is not None:
        params["_meta"] = meta
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": params}


async def _balance(client: AsyncClient, agent: dict[str, Any]) -> Decimal:
    resp = await client.get(
        f"/v1/billing/wallets/{agent['agent_wallet_id']}",
        headers=agent["agent_headers"],
    )
    assert resp.status_code == 200
    return Decimal(str(resp.json()["balance"]))


async def _tool_debits(client: AsyncClient, agent: dict[str, Any]) -> list[dict]:
    resp = await client.get(
        f"/v1/billing/ledger/{agent['agent_wallet_id']}",
        headers=agent["agent_headers"],
    )
    assert resp.status_code == 200
    return [e for e in resp.json()["entries"] if TOOL in e["description"]]


def _assert_invalid_key(payload: dict, *, reason_code: str, sources: list[str]) -> None:
    error = payload["error"]
    assert error["code"] == -32602
    assert error["message"] == "invalid_idempotency_key"
    data = error["data"]
    assert data["error"] == "invalid_idempotency_key"
    assert data["reason_code"] == reason_code
    assert data["sources"] == sources
    assert data["remediation"]["type"] == "retry_with_valid_idempotency_key"
    assert "Nothing was charged" in data["remediation"]["detail"]
    assert "receipt" not in data


# --- pure contract ----------------------------------------------------------


def test_max_key_length_matches_the_idempotency_store_column():
    """The boundary refuses exactly what the store could not persist.

    A longer cap would let Postgres reject the row mid-pipeline (500, or
    worse, a charge with no replay record); a shorter one would refuse keys
    the store handles fine.
    """
    column = IdempotencyRecordModel.__table__.c.idempotency_key  # type: ignore[attr-defined]
    assert column.type.length == MAX_IDEMPOTENCY_KEY_LENGTH == 128


@pytest.mark.parametrize(
    ("value", "reason_code"),
    [
        ("", "idempotency_key_empty"),
        ("   ", "idempotency_key_empty"),
        (123, "idempotency_key_not_a_string"),
        (0, "idempotency_key_not_a_string"),
        (True, "idempotency_key_not_a_string"),
        (["k"], "idempotency_key_not_a_string"),
        ({"k": "v"}, "idempotency_key_not_a_string"),
        ("x" * (MAX_IDEMPOTENCY_KEY_LENGTH + 1), "idempotency_key_too_long"),
        # A JSON "\ud800" escape decodes to a lone surrogate: a str that
        # cannot be utf-8 encoded for the mint-record hash.
        ("\ud800", "idempotency_key_invalid_characters"),
        ("retry\ud800", "idempotency_key_invalid_characters"),
        # NUL is refused by Postgres text columns; other control characters
        # are never a legitimate opaque token.
        ("\x00retry", "idempotency_key_invalid_characters"),
        ("retry\nagain", "idempotency_key_invalid_characters"),
        ("retry\x7f", "idempotency_key_invalid_characters"),
    ],
)
def test_validate_rejects_every_malformed_class(value, reason_code):
    with pytest.raises(InvalidIdempotencyKeyError) as excinfo:
        validate_idempotency_key(value, source="_meta")
    assert str(excinfo.value) == "invalid_idempotency_key"
    assert excinfo.value.reason_code == reason_code
    assert excinfo.value.sources == ("_meta",)


@pytest.mark.parametrize(
    "value",
    ["k", "x" * MAX_IDEMPOTENCY_KEY_LENGTH, "retry key", "clé-№1", "\U0001f511" * 128],
    ids=["one-char", "at-limit", "interior-space", "non-ascii", "astral-at-limit"],
)
def test_validate_accepts_keys_up_to_the_store_limit(value):
    """Opaque tokens stay opaque: spaces and any printable unicode are fine."""
    assert validate_idempotency_key(value, source="header") == value


def test_resolve_treats_no_candidates_and_explicit_null_as_absent():
    assert resolve_client_idempotency_key([]) is None
    assert resolve_client_idempotency_key([("mcpContext", None)]) is None


def test_resolve_requires_agreement_across_sources():
    assert resolve_client_idempotency_key([("header", "k"), ("_meta", "k")]) == "k"
    with pytest.raises(InvalidIdempotencyKeyError) as excinfo:
        resolve_client_idempotency_key([("header", "a"), ("header", "b")])
    assert excinfo.value.reason_code == "idempotency_key_conflict"
    assert excinfo.value.sources == ("header",)
    with pytest.raises(InvalidIdempotencyKeyError) as excinfo:
        resolve_client_idempotency_key([("header", "a"), ("_meta", "b")])
    assert excinfo.value.sources == ("header", "_meta")


def test_resolve_validates_before_comparing():
    """A malformed value never survives just because another source agrees."""
    with pytest.raises(InvalidIdempotencyKeyError) as excinfo:
        resolve_client_idempotency_key([("header", "k"), ("_meta", "")])
    assert excinfo.value.reason_code == "idempotency_key_empty"
    assert excinfo.value.sources == ("_meta",)


# --- the reproduced attack, over the real endpoint -------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("bad_key", "reason_code"),
    [
        ("", "idempotency_key_empty"),
        (123, "idempotency_key_not_a_string"),
        (["retry-1"], "idempotency_key_not_a_string"),
        ({"key": "retry-1"}, "idempotency_key_not_a_string"),
        ("x" * (MAX_IDEMPOTENCY_KEY_LENGTH + 1), "idempotency_key_too_long"),
        # Before this check the lone surrogate escaped the -32602 contract:
        # utf-8 encoding failed inside the permit mint and the SDK catch-all
        # answered code 0 with the raw exception text.
        ("\ud800", "idempotency_key_invalid_characters"),
        ("\x00retry-1", "idempotency_key_invalid_characters"),
    ],
)
async def test_malformed_meta_key_is_refused_before_any_effect(
    client, standard_mcp_enabled, clean_database, counted_tool, bad_key, reason_code
):
    """The exact attack: two identical requests, one malformed key, zero effects.

    Before the fix each request executed the tool and debited two credits.
    """
    agent = await provision_agent_wallet(client)
    headers = {**agent["agent_headers"], **MCP_HEADERS}
    before = await _balance(client, agent)

    for attempt in (1, 2):
        # Pre-serialized with ASCII escapes: this is the wire form a real
        # client sends (a lone surrogate travels as the "\ud800" escape, which
        # httpx's own json= path cannot utf-8 encode).
        resp = await client.post(
            "/mcp",
            content=json.dumps(_tools_call({META_KEY: bad_key}, request_id=attempt)),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["id"] == attempt
        assert "result" not in payload
        _assert_invalid_key(payload, reason_code=reason_code, sources=["_meta"])

    assert counted_tool == [], "malformed key must not execute the tool"
    assert await _balance(client, agent) == before
    assert await _tool_debits(client, agent) == []
    permits = await client.get("/v1/permits", headers=agent["agent_headers"])
    assert permits.status_code == 200
    assert permits.json()["permits"] == [], "no permit is minted for a refused call"


@pytest.mark.anyio
@pytest.mark.parametrize("good_key", ["retry-control-1", "x" * MAX_IDEMPOTENCY_KEY_LENGTH])
async def test_valid_meta_key_replays_without_a_second_charge(
    client, standard_mcp_enabled, clean_database, counted_tool, good_key
):
    """The control the review ran: a well-formed key replays to one receipt."""
    agent = await provision_agent_wallet(client)
    headers = {**agent["agent_headers"], **MCP_HEADERS}
    before = await _balance(client, agent)

    first = await client.post("/mcp", json=_tools_call({META_KEY: good_key}), headers=headers)
    assert first.status_code == 200, first.text
    receipt = first.json()["result"]["receipt"]

    second = await client.post("/mcp", json=_tools_call({META_KEY: good_key}), headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["result"]["receipt"]["receipt_id"] == receipt["receipt_id"]

    assert len(counted_tool) == 1
    assert before - await _balance(client, agent) == TOOL_COST
    assert len(await _tool_debits(client, agent)) == 1


@pytest.mark.anyio
async def test_explicit_null_meta_key_is_absent_not_invalid(
    client, standard_mcp_enabled, clean_database, counted_tool
):
    """JSON ``null`` is how an unset optional serializes; it means "no key".

    Documented so the choice is deliberate: a null key behaves exactly like
    omitting ``_meta`` — each call is metered as a new action — and is never
    confused with a malformed key.
    """
    agent = await provision_agent_wallet(client)
    headers = {**agent["agent_headers"], **MCP_HEADERS}

    resp = await client.post("/mcp", json=_tools_call({META_KEY: None}), headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["receipt"]["outcome"] == "success"
    assert len(counted_tool) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("header_value", "reason_code"),
    [
        ("", "idempotency_key_empty"),
        ("x" * (MAX_IDEMPOTENCY_KEY_LENGTH + 1), "idempotency_key_too_long"),
    ],
)
async def test_malformed_header_key_is_refused_before_any_effect(
    client, standard_mcp_enabled, clean_database, counted_tool, header_value, reason_code
):
    """The header path holds the same contract as ``_meta``.

    An empty header used to fall through to a generated key; an over-long one
    used to be accepted verbatim even though the store column is 128 wide.
    """
    agent = await provision_agent_wallet(client)
    headers = {**agent["agent_headers"], **MCP_HEADERS, "Idempotency-Key": header_value}

    for attempt in (1, 2):
        resp = await client.post("/mcp", json=_tools_call(request_id=attempt), headers=headers)
        assert resp.status_code == 200, resp.text
        _assert_invalid_key(resp.json(), reason_code=reason_code, sources=["header"])

    assert counted_tool == []
    assert await _tool_debits(client, agent) == []


@pytest.mark.anyio
async def test_header_at_store_limit_is_accepted_and_replays(
    client, standard_mcp_enabled, clean_database, counted_tool
):
    agent = await provision_agent_wallet(client)
    headers = {
        **agent["agent_headers"],
        **MCP_HEADERS,
        "Idempotency-Key": "h" * MAX_IDEMPOTENCY_KEY_LENGTH,
    }
    first = await client.post("/mcp", json=_tools_call(), headers=headers)
    second = await client.post("/mcp", json=_tools_call(), headers=headers)
    assert first.status_code == 200 and second.status_code == 200
    assert (
        first.json()["result"]["receipt"]["receipt_id"]
        == second.json()["result"]["receipt"]["receipt_id"]
    )
    assert len(counted_tool) == 1


@pytest.mark.anyio
async def test_header_and_meta_keys_must_agree(
    client, standard_mcp_enabled, clean_database, counted_tool
):
    """Two different keys on one request is an ambiguity, not a preference.

    The old code let the header win silently, so a client keying by ``_meta``
    behind a proxy that injected its own header lost its replay identity.
    """
    agent = await provision_agent_wallet(client)
    headers = {**agent["agent_headers"], **MCP_HEADERS, "Idempotency-Key": "header-key"}

    resp = await client.post("/mcp", json=_tools_call({META_KEY: "meta-key"}), headers=headers)
    assert resp.status_code == 200, resp.text
    _assert_invalid_key(
        resp.json(), reason_code="idempotency_key_conflict", sources=["header", "_meta"]
    )
    assert counted_tool == []
    assert await _tool_debits(client, agent) == []

    # The same key on both transports is one identity and replays as one.
    headers["Idempotency-Key"] = "meta-key"
    first = await client.post("/mcp", json=_tools_call({META_KEY: "meta-key"}), headers=headers)
    second = await client.post("/mcp", json=_tools_call({META_KEY: "meta-key"}), headers=headers)
    assert first.status_code == 200 and second.status_code == 200
    assert (
        first.json()["result"]["receipt"]["receipt_id"]
        == second.json()["result"]["receipt"]["receipt_id"]
    )
    assert len(counted_tool) == 1
    assert len(await _tool_debits(client, agent)) == 1


@pytest.mark.anyio
async def test_repeated_header_lines_must_agree(
    client, standard_mcp_enabled, clean_database, counted_tool
):
    agent = await provision_agent_wallet(client)
    headers = [
        *agent["agent_headers"].items(),
        *MCP_HEADERS.items(),
        ("Idempotency-Key", "first"),
        ("Idempotency-Key", "second"),
    ]
    resp = await client.post("/mcp", json=_tools_call(), headers=headers)
    assert resp.status_code == 200, resp.text
    _assert_invalid_key(resp.json(), reason_code="idempotency_key_conflict", sources=["header"])
    assert counted_tool == []


@pytest.mark.anyio
async def test_malformed_key_is_refused_even_for_a_caller_without_a_wallet(
    client, standard_mcp_enabled, clean_database, counted_tool
):
    """Key validation is a transport-boundary check, ahead of wallet checks.

    A bootstrap key gets the input error, not ``wallet_scoped_key_required``:
    the request is malformed regardless of who sent it.
    """
    from tests.test_trust_helpers import BOOTSTRAP_HEADERS

    headers = {**BOOTSTRAP_HEADERS, **MCP_HEADERS}
    resp = await client.post("/mcp", json=_tools_call({META_KEY: 42}), headers=headers)
    assert resp.status_code == 200, resp.text
    _assert_invalid_key(
        resp.json(), reason_code="idempotency_key_not_a_string", sources=["_meta"]
    )
    assert counted_tool == []
