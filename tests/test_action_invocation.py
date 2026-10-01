from dataclasses import replace

import pytest

from app.services import action_permits
from tests.test_action_permits import BINDING
from tests.test_permit_signing_input_snapshot import _base_model


def action_permit(**changes):
    fields = dict(
        action_contract_version=1,
        action_payload_hash="a" * 64,
        action_schema_id=BINDING.schema_id,
        action_schema_version=BINDING.schema_version,
        action_public_tool_id=BINDING.public_tool_id,
        action_upstream_binding_hash=BINDING.upstream_binding_hash,
        allowed_tools_json='["partner.pay"]',
        max_calls_per_tool_json='{"partner.pay":1}',
    )
    fields.update(changes)
    return _base_model().model_copy(update=fields)


def test_identity_is_stable_across_signing_and_transport_keys():
    permit = action_permit()
    first = action_permits.action_execution_identity(permit, BINDING)
    rotated = permit.model_copy(
        update={"key_id": "rotated", "signature": "new", "subject_key_id": "fresh"}
    )
    assert action_permits.action_execution_identity(rotated, BINDING) == first
    assert first.endpoint == "/mcp/action/v1"
    assert first.idempotency_key.startswith("act1-")
    assert len(first.idempotency_key) == 69
    assert first.request_payload["action_payload_hash"] == "a" * 64
    assert (
        action_permits.action_execution_identity(
            permit.model_copy(update={"permit_id": "another"}), BINDING
        )
        != first
    )
    assert (
        action_permits.action_execution_identity(
            permit.model_copy(update={"subject_wallet_id": "another"}), BINDING
        )
        != first
    )
    other = replace(BINDING, public_tool_id="other")
    changed = action_permit(
        action_public_tool_id="other",
        allowed_tools_json='["other"]',
        max_calls_per_tool_json='{"other":1}',
    )
    assert action_permits.action_execution_identity(changed, other) != first
    other = replace(BINDING, upstream_binding_hash="b" * 64)
    assert (
        action_permits.action_execution_identity(
            action_permit(action_upstream_binding_hash="b" * 64), other
        )
        != first
    )
    other = replace(BINDING, deployment_authority="another")
    assert (
        action_permits.action_execution_identity(permit, other).native_idempotency_key
        != first.native_idempotency_key
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"action_contract_version": 2},
        {"action_contract_version": None},
        {"action_payload_hash": None},
        {"action_payload_hash": "bad"},
        {"action_schema_id": "wrong"},
        {"action_schema_version": "wrong"},
        {"action_public_tool_id": "wrong"},
        {"action_upstream_binding_hash": "wrong"},
        {"allowed_tools_json": '["partner.pay","other"]'},
        {"max_calls_per_tool_json": '{"partner.pay":2}'},
    ],
)
def test_identity_refuses_unsupported_or_mismatched_permit(changes):
    with pytest.raises(ValueError):
        action_permits.action_execution_identity(action_permit(**changes), BINDING)


def test_identity_refuses_incomplete_binding():
    with pytest.raises(ValueError):
        action_permits.action_execution_identity(
            action_permit(), replace(BINDING, deployment_authority="")
        )


@pytest.mark.anyio
async def test_http_transport_cannot_select_action_namespace(monkeypatch):
    from unittest.mock import AsyncMock
    from starlette.requests import Request
    from app.routers import mcp

    normalize = AsyncMock(return_value=object())
    monkeypatch.setattr(mcp._mcp_adapter, "normalize_request", normalize)
    monkeypatch.setattr(mcp._mcp_adapter, "invoke", AsyncMock(return_value=object()))
    monkeypatch.setattr(
        mcp._mcp_adapter, "normalize_response", AsyncMock(return_value={"content": []})
    )
    request = mcp.ToolCallRequest.model_validate(
        {
            "name": "partner.pay",
            "arguments": {},
            "endpoint": "/mcp/action/v1",
            "mcp_context": {
                "wallet_id": "fixture",
                "request_path": "/mcp/action/v1",
                "endpoint": "/mcp/action/v1",
                "idempotency_key": "act1-" + "a" * 64,
            },
        }
    )
    await mcp.invoke_tool(
        "partner.pay",
        request,
        Request({"type": "http", "headers": []}),
        auth=object(),
        money=object(),
    )
    assert normalize.call_args.kwargs["endpoint"] == "/mcp/tools/partner.pay/invoke"
