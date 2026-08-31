"""Ordinary input-validation regression for explicit MCP replay metadata.

Run only with the repository's test fixtures on an isolated disposable copy.
An absent key may mean a new action; a supplied invalid key must not silently
turn retries into separately charged actions.
"""

# Imported pytest fixtures intentionally share test parameter names.
# ruff: noqa: F811

from __future__ import annotations

import pytest

from app.schemas.billing import ServiceCategory
from app.services.service_registry import get_service_registry
from tests.test_standard_mcp_endpoint import (
    MCP_HEADERS,
    _rpc,
    client as client,
    standard_mcp_enabled as standard_mcp_enabled,
)
from tests.test_trust_helpers import provision_agent_wallet


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("source", "malformed_key", "other_key"),
    [
        pytest.param("metadata", "k" * 257, None, id="metadata-over-old-limit"),
        pytest.param("metadata", "k" * 129, None, id="metadata-over-canonical-limit"),
        pytest.param("metadata", 42, None, id="metadata-wrong-type"),
        pytest.param("metadata", None, None, id="metadata-null"),
        pytest.param("metadata", "", None, id="metadata-empty"),
        pytest.param("metadata", "   ", None, id="metadata-blank"),
        pytest.param("metadata", " padded-key ", None, id="metadata-padded"),
        pytest.param("header", "k" * 129, None, id="header-over-canonical-limit"),
        pytest.param("header", "", None, id="header-empty"),
        pytest.param("header", "   ", None, id="header-blank"),
        pytest.param("header", " padded-key ", None, id="header-padded"),
        pytest.param(
            "metadata", "", "valid-header", id="invalid-metadata-valid-header"
        ),
        pytest.param(
            "header", "", "valid-metadata", id="invalid-header-valid-metadata"
        ),
    ],
)
async def test_explicit_invalid_mcp_key_is_rejected_before_effects(
    client, standard_mcp_enabled, clean_database, source, malformed_key, other_key
):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    registry = get_service_registry()
    tool_name = "integration-key-validation"
    calls = 0

    def counted_tool(message: str = "ok") -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"message": message}

    registry.register_local(
        service_id=tool_name,
        name="Integration Key Validation",
        description="Count local effects for invalid replay metadata",
        category=ServiceCategory.AGENT_COMMS,
        func=counted_tool,
        credits_per_unit=2.0,
        unit_name="call",
    )
    try:
        headers = {**provisioned["agent_headers"], **MCP_HEADERS}
        params = {
            "name": tool_name,
            "arguments": {"message": "same logical action"},
        }
        meta_key = "io.agentmiddleware/idempotency_key"
        if source == "metadata":
            params["_meta"] = {meta_key: malformed_key}
            if other_key is not None:
                headers["Idempotency-Key"] = other_key
        else:
            headers["Idempotency-Key"] = malformed_key
            if other_key is not None:
                params["_meta"] = {meta_key: other_key}
        body = _rpc("tools/call", params=params)
        responses = [
            await client.post("/mcp", json=body, headers=headers) for _ in range(2)
        ]
        ledger = await client.get(
            f"/v1/billing/ledger/{wallet_id}",
            headers=provisioned["agent_headers"],
        )
        assert ledger.status_code == 200
        debits = [
            entry
            for entry in ledger.json()["entries"]
            if tool_name in entry["description"]
        ]
        assert (calls, len(debits)) == (0, 0), (
            "A supplied invalid idempotency key must be refused, not replaced "
            f"with fresh action identities: observed calls={calls}, debits={len(debits)}"
        )
        permits = await client.get(
            "/v1/permits",
            params={"wallet_id": wallet_id},
            headers=provisioned["agent_headers"],
        )
        assert permits.status_code == 200
        assert permits.json()["total"] == 0
        for response in responses:
            assert response.status_code == 200
            payload = response.json()
            assert "result" not in payload
            assert payload["error"]["code"] == -32602
            assert payload["error"]["message"] == "idempotency_key_invalid"
    finally:
        registry.unregister_local(tool_name)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "scenario", ["exact-boundary", "header-precedence", "missing-key"]
)
async def test_valid_or_absent_standard_mcp_keys_preserve_call_identity(
    client, standard_mcp_enabled, clean_database, scenario
):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    registry = get_service_registry()
    tool_name = "integration-key-compatibility"
    calls = 0

    def counted_tool(message: str = "ok") -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"message": message}

    registry.register_local(
        service_id=tool_name,
        name="Integration Key Compatibility",
        description="Count local effects for replay metadata compatibility",
        category=ServiceCategory.AGENT_COMMS,
        func=counted_tool,
        credits_per_unit=2.0,
        unit_name="call",
    )
    try:
        meta_key = "io.agentmiddleware/idempotency_key"
        key = "k" * 128
        if scenario == "exact-boundary":
            # Both aliases accept the canonical 128-character boundary.
            # Changing JSON-RPC ids is only framing.
            inputs = [
                ({meta_key: key}, {}),
                ({}, {"Idempotency-Key": key}),
                ({meta_key: key}, {}),
            ]
            expected_calls = 1
        elif scenario == "header-precedence":
            # Retain existing precedence when both supplied keys are valid.
            inputs = [
                ({meta_key: "metadata-1"}, {"Idempotency-Key": "header-action"}),
                ({meta_key: "metadata-2"}, {"Idempotency-Key": "header-action"}),
                ({meta_key: "header-action"}, {}),
            ]
            expected_calls = 1
        else:
            # An unrelated extension does not count as an explicitly supplied
            # idempotency key; unkeyed calls intentionally remain new actions.
            inputs = [({}, {}), ({"unrelated-extension": "value"}, {})]
            expected_calls = 2

        receipts = []
        for request_id, (metadata, extra_headers) in enumerate(inputs, start=1):
            response = await client.post(
                "/mcp",
                json=_rpc(
                    "tools/call",
                    request_id=request_id,
                    params={
                        "name": tool_name,
                        "arguments": {"message": "same logical input"},
                        "_meta": metadata,
                    },
                ),
                headers={
                    **provisioned["agent_headers"],
                    **MCP_HEADERS,
                    **extra_headers,
                },
            )
            assert response.status_code == 200
            receipts.append(response.json()["result"]["receipt"]["receipt_id"])

        ledger = await client.get(
            f"/v1/billing/ledger/{wallet_id}",
            headers=provisioned["agent_headers"],
        )
        assert ledger.status_code == 200
        debits = [
            entry
            for entry in ledger.json()["entries"]
            if tool_name in entry["description"]
        ]
        assert calls == expected_calls
        assert len(debits) == expected_calls
        assert len(set(receipts)) == expected_calls
    finally:
        registry.unregister_local(tool_name)
