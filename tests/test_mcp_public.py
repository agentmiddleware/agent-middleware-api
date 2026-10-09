"""Unit coverage for the public MCP router (app/routers/mcp_public.py).

The HTTP-level contract already lives in tests/test_public_mcp_endpoint.py.
These tests pin the module's handler logic directly, with stubbed key and
tool services, so they stay fast and need no database or network.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from mcp.shared.exceptions import McpError

from app.routers import mcp_public
from app.routers.mcp_public import (
    _MAX_SIGNING_INPUT_BYTES,
    _keys_unavailable_result,
    _signing_input_too_large,
)


def _fake_key(kid: str = "kid-1") -> SimpleNamespace:
    return SimpleNamespace(
        key_id=kid,
        alg="Ed25519",
        status="active",
        public_key_b64=base64.b64encode(b"\x01" * 32).decode(),
        created_at=None,
        activated_at=None,
        retired_at=None,
    )


def _fake_signing_service(keys: list) -> SimpleNamespace:
    async def list_public_keys() -> list:
        return list(keys)

    return SimpleNamespace(list_public_keys=list_public_keys)


def _fake_generator(tools: list[dict]) -> SimpleNamespace:
    async def generate_tools_json_async(category=None) -> dict:
        if category is not None:
            wanted = getattr(category, "value", category)
            tools_out = [
                t
                for t in tools
                if (t.get("annotations") or {}).get("category") == wanted
            ]
        else:
            tools_out = list(tools)
        return {"tools": tools_out}

    return SimpleNamespace(generate_tools_json_async=generate_tools_json_async)


def _governed_tool(name: str, category: str = "agent_comms") -> dict:
    return {
        "name": name,
        "description": f"{name} description",
        "annotations": {
            "category": category,
            "creditsPerCall": 2,
            "unitName": "call",
            "requirePermit": True,
        },
    }


class _Status:
    def __init__(self, value: str):
        self.value = value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _Status):
            return self.value == other.value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.value)


class _FakeVerifierStatuses:
    VERIFIED = _Status("verified")
    INVALID = _Status("invalid")
    MALFORMED = _Status("malformed")
    UNKNOWN_KEY = _Status("unknown_key")
    MISMATCH = _Status("mismatch")
    UNSUPPORTED = _Status("unsupported")
    KEYS_UNAVAILABLE = _Status("keys_unavailable")


class _FakeResult:
    def __init__(
        self,
        status: _Status,
        ok: bool = False,
        reason: str = "reason",
        receipt_id: str | None = None,
        key_id: str | None = None,
        claims: dict | None = None,
        is_tampered: bool = False,
    ):
        self.status = status
        self.ok = ok
        self.reason = reason
        self.receipt_id = receipt_id
        self.key_id = key_id
        self.claims = claims or {}
        self.is_tampered = is_tampered


class _FakeVerifier:
    VerificationStatus = _FakeVerifierStatuses

    def __init__(self, results: list[_FakeResult]):
        self._results = list(results)
        self.calls = 0

    def verify_bundle(self, bundle, key_set, expected_issuer=None) -> _FakeResult:
        self.calls += 1
        return self._results[min(self.calls - 1, len(self._results) - 1)]

    def key_set_from_document(self, document: dict) -> dict:
        return {entry["kid"]: b"key" for entry in document.get("keys", [])}


def test_tools_are_exactly_the_read_only_surface() -> None:
    assert [tool.name for tool in mcp_public._TOOLS] == [
        "verify_receipt",
        "get_trust_plane_info",
        "list_governed_tools",
    ]
    for tool in mcp_public._TOOLS:
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.openWorldHint is False
    assert set(mcp_public._TOOL_HANDLERS) == {
        "verify_receipt",
        "get_trust_plane_info",
        "list_governed_tools",
    }


def test_signing_input_size_guard() -> None:
    limit = _MAX_SIGNING_INPUT_BYTES
    assert _signing_input_too_large({"signing_input": "x" * (limit + 1)}) is True
    assert _signing_input_too_large("x" * (limit + 1)) is True
    assert _signing_input_too_large({"signing_input": "small"}) is False
    assert _signing_input_too_large("small") is False
    assert _signing_input_too_large({}) is False
    assert _signing_input_too_large(None) is False
    assert _signing_input_too_large({"signing_input": 123}) is False


def test_keys_unavailable_result_shape() -> None:
    structured, text = _keys_unavailable_result()
    assert structured["ok"] is False
    assert structured["status"] == "keys_unavailable"
    assert structured["receipt_id"] is None
    assert "not invalid" in structured["reason"]
    assert "keys_unavailable" in text


@pytest.mark.anyio
async def test_verify_receipt_requires_a_bundle() -> None:
    with pytest.raises(McpError) as missing:
        await mcp_public._tool_verify_receipt({})
    assert missing.value.error.code == -32602

    with pytest.raises(McpError) as wrong_type:
        await mcp_public._tool_verify_receipt({"bundle": 123})
    assert wrong_type.value.error.code == -32602

    with pytest.raises(McpError) as bad_issuer:
        await mcp_public._tool_verify_receipt(
            {"bundle": {"signing_input": "{}"}, "expected_issuer": 42}
        )
    assert bad_issuer.value.error.code == -32602


@pytest.mark.anyio
async def test_verify_receipt_oversized_bundle_never_touches_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _FakeVerifier([_FakeResult(_FakeVerifierStatuses.VERIFIED, ok=True)])
    monkeypatch.setattr(mcp_public, "_receipt_verifier", verifier)

    async def fail_if_called() -> dict:
        raise AssertionError("oversized bundle reached the key store")

    monkeypatch.setattr(mcp_public, "_published_key_set", fail_if_called)
    big = {"signing_input": "x" * (_MAX_SIGNING_INPUT_BYTES + 1)}

    structured, text = await mcp_public._tool_verify_receipt({"bundle": big})

    assert structured["status"] == "malformed"
    assert structured["ok"] is False
    assert verifier.calls == 0
    assert "malformed" in text.lower()


@pytest.mark.anyio
async def test_verify_receipt_verified_reports_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _FakeResult(
        _FakeVerifierStatuses.VERIFIED,
        ok=True,
        reason="signature holds",
        receipt_id="rcpt-1",
        key_id="kid-1",
        claims={"tool": "portable-echo"},
    )
    monkeypatch.setattr(mcp_public, "_receipt_verifier", _FakeVerifier([result]))

    structured, text = await mcp_public._tool_verify_receipt(
        {"bundle": {"signing_input": "{}"}}
    )

    assert structured["ok"] is True
    assert structured["status"] == "verified"
    assert structured["receipt_id"] == "rcpt-1"
    assert structured["kid"] == "kid-1"
    assert structured["claims"] == {"tool": "portable-echo"}
    assert text.startswith("VERIFIED")


@pytest.mark.anyio
async def test_verify_receipt_tampered_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _FakeResult(
        _FakeVerifierStatuses.INVALID,
        ok=False,
        reason="signature mismatch",
        is_tampered=True,
    )
    monkeypatch.setattr(mcp_public, "_receipt_verifier", _FakeVerifier([result]))

    structured, text = await mcp_public._tool_verify_receipt(
        {"bundle": {"signing_input": "{}"}}
    )

    assert structured["ok"] is False
    assert structured["status"] == "invalid"
    assert structured["claims"] == {}
    assert text.startswith("INVALID")


@pytest.mark.anyio
async def test_verify_receipt_unknown_key_without_published_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight = _FakeResult(_FakeVerifierStatuses.UNKNOWN_KEY, ok=False)
    monkeypatch.setattr(mcp_public, "_receipt_verifier", _FakeVerifier([preflight]))

    async def no_keys() -> None:
        return None

    monkeypatch.setattr(mcp_public, "_published_key_set", no_keys)

    structured, text = await mcp_public._tool_verify_receipt(
        {"bundle": {"signing_input": "{}"}}
    )

    assert structured["status"] == "keys_unavailable"
    assert structured["ok"] is False
    assert "not a verdict" in text.lower()


@pytest.mark.anyio
async def test_verify_receipt_mismatch_is_not_reported_as_tampering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _FakeResult(
        _FakeVerifierStatuses.MISMATCH,
        ok=False,
        reason="envelope kid disagrees",
    )
    monkeypatch.setattr(mcp_public, "_receipt_verifier", _FakeVerifier([result]))

    structured, text = await mcp_public._tool_verify_receipt(
        {"bundle": {"signing_input": "{}"}}
    )

    assert structured["status"] == "mismatch"
    assert structured["ok"] is False
    assert "does not mean the signature failed" in text


@pytest.mark.anyio
async def test_get_trust_plane_info_reports_published_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_public,
        "get_signing_key_service",
        lambda: _fake_signing_service([_fake_key("kid-1")]),
    )

    structured, text = await mcp_public._tool_get_trust_plane_info({})

    assert structured["name"] == mcp_public.PUBLIC_SERVER_NAME
    assert structured["alg"] == "Ed25519"
    assert structured["keys_available"] is True
    assert [key["kid"] for key in structured["keys"]] == ["kid-1"]
    assert all("jwk" not in key for key in structured["keys"])
    assert structured["endpoints"]["trust_keys"] == "/.well-known/trust-keys.json"
    assert "kid-1" in text


@pytest.mark.anyio
async def test_get_trust_plane_info_without_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_public, "get_signing_key_service", lambda: _fake_signing_service([])
    )

    structured, _ = await mcp_public._tool_get_trust_plane_info({})

    assert structured["keys_available"] is False
    assert structured["keys"] == []


@pytest.mark.anyio
async def test_list_governed_tools_rejects_bad_input() -> None:
    with pytest.raises(McpError) as unknown_category:
        await mcp_public._tool_list_governed_tools({"category": "not-a-category"})
    assert unknown_category.value.error.code == -32602
    assert "Valid categories" in unknown_category.value.error.message

    for bad_limit in (0, 201, "50", True):
        with pytest.raises(McpError) as bad:
            await mcp_public._tool_list_governed_tools({"limit": bad_limit})
        assert bad.value.error.code == -32602

    for bad_offset in (-1, "0", False):
        with pytest.raises(McpError) as bad_offset_error:
            await mcp_public._tool_list_governed_tools({"offset": bad_offset})
        assert bad_offset_error.value.error.code == -32602


@pytest.mark.anyio
async def test_list_governed_tools_paginates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = [_governed_tool(f"tool-{index}") for index in range(3)]
    monkeypatch.setattr(mcp_public, "get_mcp_generator", lambda: _fake_generator(tools))

    structured, text = await mcp_public._tool_list_governed_tools(
        {"limit": 2, "offset": 1}
    )

    assert structured["total"] == 3
    assert structured["count"] == 2
    assert [tool["name"] for tool in structured["tools"]] == ["tool-1", "tool-2"]
    assert structured["has_more"] is False
    assert set(structured["tools"][0]) == {
        "name",
        "description",
        "category",
        "credits_per_call",
        "unit_name",
        "requires_permit",
    }
    assert "3 governed tool(s)" in text


@pytest.mark.anyio
async def test_unknown_tool_dispatch_is_rejected() -> None:
    server = mcp_public._build_public_mcp_server()
    handler = server.request_handlers[mcp_public.mcp_types.CallToolRequest]
    request = SimpleNamespace(
        params=SimpleNamespace(name="partner.notes.write", arguments={})
    )

    with pytest.raises(McpError) as error:
        await handler(request)

    assert error.value.error.code == -32602
    assert "read-only" in error.value.error.message


def test_require_enabled_gating(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mcp_public, "is_production_like_environment", lambda environment: False
    )
    monkeypatch.setattr(
        mcp_public,
        "get_settings",
        lambda: SimpleNamespace(ENVIRONMENT="test", ENABLE_PUBLIC_MCP_ENDPOINT=False),
    )
    with pytest.raises(HTTPException) as disabled:
        mcp_public._require_enabled()
    assert disabled.value.status_code == 404

    monkeypatch.setattr(
        mcp_public,
        "get_settings",
        lambda: SimpleNamespace(ENVIRONMENT="prod", ENABLE_PUBLIC_MCP_ENDPOINT=True),
    )
    monkeypatch.setattr(
        mcp_public, "is_production_like_environment", lambda environment: True
    )
    with pytest.raises(HTTPException) as production:
        mcp_public._require_enabled()
    assert production.value.status_code == 404

    monkeypatch.setattr(
        mcp_public,
        "get_settings",
        lambda: SimpleNamespace(ENVIRONMENT="test", ENABLE_PUBLIC_MCP_ENDPOINT=True),
    )
    monkeypatch.setattr(
        mcp_public, "is_production_like_environment", lambda environment: False
    )
    assert mcp_public._require_enabled() is None


@pytest.mark.anyio
async def test_public_mcp_no_stream_answers_405(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_public,
        "get_settings",
        lambda: SimpleNamespace(ENVIRONMENT="test", ENABLE_PUBLIC_MCP_ENDPOINT=True),
    )
    monkeypatch.setattr(
        mcp_public, "is_production_like_environment", lambda environment: False
    )

    response = await mcp_public.public_mcp_no_stream()

    assert response.status_code == 405
    assert response.headers["Allow"] == "POST"
