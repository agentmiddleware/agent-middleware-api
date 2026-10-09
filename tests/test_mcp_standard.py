"""Focused unit coverage for app/routers/mcp_standard.py pure helpers.

Tests only; no production code changes. Everything here is synchronous and
has no database, network, or external service dependency.
"""

from __future__ import annotations

from decimal import Decimal

import mcp.types as mcp_types
import pytest
from fastapi import HTTPException
from mcp.shared.exceptions import McpError
from starlette.requests import Request

from app.core.config import get_settings
from app.routers import mcp_standard as std
from app.routers.mcp import GovernedToolError
from app.services.permits import PermitError

META_KEY = "io.agentmiddleware/idempotency_key"


def make_params(
    name: str = "tool",
    arguments: dict | None = None,
    meta: dict | None = None,
    extra: dict | None = None,
) -> mcp_types.CallToolRequestParams:
    payload: dict = {"name": name, "arguments": arguments or {}}
    if meta is not None:
        payload["_meta"] = meta
    if extra:
        payload.update(extra)
    return mcp_types.CallToolRequestParams.model_validate(payload)


def make_request(
    url: str = "http://test/mcp",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "server": ("test", 80),
        "path": "/mcp",
        "query_string": b"",
        "headers": headers or [],
    }
    return Request(scope)


# _tool_call_budget ------------------------------------------------------


def test_tool_call_budget_uses_exact_cost() -> None:
    assert std._tool_call_budget({"credits_per_unit_exact": "2.5"}) == Decimal("2.5")


def test_tool_call_budget_falls_back_to_unit_cost() -> None:
    assert std._tool_call_budget({"credits_per_unit": 3.0}) == Decimal("3.0")


def test_tool_call_budget_defaults_to_one() -> None:
    assert std._tool_call_budget({}) == Decimal("1")


def test_tool_call_budget_floors_zero_cost_at_one() -> None:
    assert std._tool_call_budget({"credits_per_unit": 0.0}) == Decimal("1")


def test_tool_call_budget_invalid_exact_falls_back() -> None:
    assert std._tool_call_budget(
        {"credits_per_unit_exact": "not-a-number", "credits_per_unit": 4.0}
    ) == Decimal("4.0")


# _permit_error ------------------------------------------------------------


def test_permit_error_budget_maps_to_fund_wallet_remediation() -> None:
    exc = PermitError("permit_budget_exceeds_wallet_balance")
    err = std._permit_error(
        exc, tool_name="notes.write", record={"credits_per_unit": 2.0}
    )
    assert isinstance(err, McpError)
    assert err.error.code == -32004
    assert err.error.message == "permit_budget_exceeds_wallet_balance"
    assert err.error.data["remediation"]["type"] == "fund_wallet_or_request_authority"
    assert err.error.data["requested"]["tool"] == "notes.write"


def test_permit_error_other_reason_maps_to_generic_denial() -> None:
    err = std._permit_error(PermitError("permit_expired"))
    assert isinstance(err, McpError)
    assert err.error.code == -32003
    assert err.error.message == "permit_expired"


# _meta_idempotency_key_source ----------------------------------------------


def test_meta_source_absent_returns_none() -> None:
    assert std._meta_idempotency_key_source(make_params()) is None


def test_meta_source_null_reads_as_absent() -> None:
    assert std._meta_idempotency_key_source(make_params(meta={META_KEY: None})) is None


def test_meta_source_present_returns_source_tuple() -> None:
    source = std._meta_idempotency_key_source(make_params(meta={META_KEY: "abc"}))
    assert source == (std._META_KEY_SOURCE, "abc")


# _action_permit_reference --------------------------------------------------


def test_permit_reference_absent_returns_none() -> None:
    assert std._action_permit_reference(make_params()) is None


def test_permit_reference_single_value_returned() -> None:
    params = make_params(meta={"io.agentmiddleware/permit_id": "p-1"})
    assert std._action_permit_reference(params) == "p-1"


def test_permit_reference_conflict_raises_invalid_params() -> None:
    params = make_params(
        meta={"io.agentmiddleware/permit_id": "p-1"},
        extra={"mcpContext": {"permit_id": "p-2"}},
    )
    with pytest.raises(McpError) as exc_info:
        std._action_permit_reference(params)
    assert exc_info.value.error.code == -32602


def test_permit_reference_blank_raises_invalid_params() -> None:
    params = make_params(meta={"io.agentmiddleware/permit_id": "  "})
    with pytest.raises(McpError) as exc_info:
        std._action_permit_reference(params)
    assert exc_info.value.error.code == -32602


# _client_idempotency_key ----------------------------------------------------


def test_client_key_absent_returns_none() -> None:
    assert std._client_idempotency_key(None, make_params()) is None


def test_client_key_meta_value_resolves() -> None:
    params = make_params(meta={META_KEY: "key-123"})
    assert std._client_idempotency_key(None, params) == "key-123"


def test_client_key_malformed_meta_is_refused() -> None:
    params = make_params(meta={META_KEY: 12345})
    with pytest.raises(McpError) as exc_info:
        std._client_idempotency_key(None, params)
    assert exc_info.value.error.code == -32602


def test_client_key_meta_and_legacy_context_conflict_refused() -> None:
    params = make_params(
        meta={META_KEY: "key-one"},
        extra={"mcpContext": {"idempotency_key": "key-two"}},
    )
    with pytest.raises(McpError) as exc_info:
        std._client_idempotency_key(None, params)
    assert exc_info.value.error.code == -32602


def test_client_key_same_meta_and_legacy_context_agree() -> None:
    params = make_params(
        meta={META_KEY: "key-same"},
        extra={"mcpContext": {"idempotency_key": "key-same"}},
    )
    assert std._client_idempotency_key(None, params) == "key-same"


# _delivery_uncertain_tool_result ----------------------------------------------


def _uncertain_error() -> GovernedToolError:
    return GovernedToolError(
        "delivery_uncertain",
        receipt={"receipt_id": "r-1"},
        extra_data={"dispatch": {"attempt": 1}},
    )


def test_delivery_uncertain_with_client_key_promises_same_key_replay() -> None:
    payload = std._delivery_uncertain_tool_result(
        _uncertain_error(), client_key_supplied=True
    )
    assert payload["isError"] is True
    assert payload["receipt"] == {"receipt_id": "r-1"}
    outcome = payload["_meta"][std._OUTCOME_META_KEY]
    assert outcome["status"] == "unknown"
    assert outcome["redispatched"] is False
    assert outcome["idempotency_key_supplied"] is True
    assert outcome["dispatch"] == {"attempt": 1}
    text = payload["content"][0]["text"]
    assert "same Idempotency-Key" in text


def test_delivery_uncertain_without_client_key_warns_new_charge() -> None:
    payload = std._delivery_uncertain_tool_result(
        _uncertain_error(), client_key_supplied=False
    )
    assert payload["isError"] is True
    outcome = payload["_meta"][std._OUTCOME_META_KEY]
    assert outcome["idempotency_key_supplied"] is False
    text = payload["content"][0]["text"]
    assert "no Idempotency-Key" in text


def test_delivery_uncertain_without_receipt_omits_receipt_field() -> None:
    error = GovernedToolError("delivery_uncertain")
    payload = std._delivery_uncertain_tool_result(error, client_key_supplied=True)
    assert "receipt" not in payload
    assert payload["isError"] is True


# _require_enabled / _validate_origin -------------------------------------------


def test_require_enabled_refuses_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_STANDARD_MCP_ENDPOINT", "false")
    get_settings.cache_clear()
    try:
        with pytest.raises(HTTPException) as exc_info:
            std._require_enabled()
        assert exc_info.value.status_code == 404
    finally:
        get_settings.cache_clear()


def test_validate_origin_passes_without_origin_header() -> None:
    std._validate_origin(make_request())


def test_validate_origin_refuses_mismatched_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUBLIC_URL", "https://allowed.example")
    get_settings.cache_clear()
    try:
        request = make_request(
            headers=[(b"origin", b"https://evil.example")],
        )
        with pytest.raises(HTTPException) as exc_info:
            std._validate_origin(request)
        assert exc_info.value.status_code == 403
    finally:
        get_settings.cache_clear()
