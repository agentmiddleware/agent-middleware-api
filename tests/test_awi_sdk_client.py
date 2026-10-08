"""Unit tests for the AWI Python SDK client (packaging-adjacent behavior).

These cover what the proof-surface hardening suite does not: retry
behavior, typed errors, typed model constructors, and the packaging
metadata that makes the SDK pip-installable. All transport is synthetic
(httpx.MockTransport); no server needed.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_PATH = str(REPO_ROOT / "awi_sdk" / "python")
if SDK_PATH not in sys.path:
    sys.path.insert(0, SDK_PATH)

from awi_sdk import (  # noqa: E402
    AWIActionDefinition,
    AWIClient,
    AWIClientConfig,
    AWIExecutionResponse,
    AuthenticationError,
    AuthorizationError,
    IdempotencyConflictError,
    PermitDeniedError,
)
from awi_sdk import errors as sdk_errors  # noqa: E402

pytestmark = pytest.mark.proof


def _client(handler, **kwargs) -> AWIClient:
    kwargs.setdefault("base_url", "http://middleware.test")
    kwargs.setdefault("api_key", "sk-live")
    client = AWIClient(**kwargs)
    client._client._transport = httpx.MockTransport(handler)
    return client


async def _close(client: AWIClient) -> None:
    await client.close()


def _vocab_entry(**overrides):
    entry = {
        "action": "search_and_sort",
        "category": "search",
        "description": "Search for items",
        "parameters": {"query": {"type": "string", "required": True}},
        "required_preconditions": ["page_loaded"],
        "postconditions": ["results_displayed"],
        "estimated_cost": 0.002,
        "tier": "semantic",
        "status": "stable",
        "risk_level": "low",
        "sensitive_parameters": [],
    }
    entry.update(overrides)
    return entry


@pytest.mark.anyio
async def test_negative_max_retries_rejected():
    with pytest.raises(ValueError):
        AWIClientConfig(max_retries=-1)


@pytest.mark.anyio
async def test_retry_succeeds_after_transient_503():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) < 3:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"status": "success"})

    client = _client(handler, max_retries=3)
    try:
        result = await client.get_queue_status()
    finally:
        await _close(client)
    assert result == {"status": "success"}
    assert len(seen) == 3


@pytest.mark.anyio
async def test_retry_gives_up_and_raises_last_error():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(503, json={"error": "busy"})

    client = _client(handler, max_retries=2)
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await client.get_queue_status()
    finally:
        await _close(client)
    assert len(seen) == 3  # first attempt plus two retries
    assert exc.value.response.status_code == 503


@pytest.mark.anyio
async def test_client_errors_are_never_retried():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(400, json={"error": "bad_request"})

    client = _client(handler, max_retries=3)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_queue_status()
    finally:
        await _close(client)
    assert len(seen) == 1


@pytest.mark.anyio
async def test_transport_failure_retries_then_succeeds():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            raise httpx.ConnectError("synthetic outage")
        return httpx.Response(200, json={"status": "success"})

    client = _client(handler, max_retries=1)
    try:
        result = await client.get_queue_status()
    finally:
        await _close(client)
    assert result == {"status": "success"}
    assert len(seen) == 2


@pytest.mark.anyio
async def test_execute_retry_reuses_idempotency_key():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"status": "success"})

    client = _client(handler, max_retries=1)
    try:
        await client.execute(
            "sess-1",
            "add_to_cart",
            {"sku": "x"},
            permit_id="permit-1",
            idempotency_key="same-key",
        )
    finally:
        await _close(client)
    assert len(seen) == 2
    assert [r.headers["Idempotency-Key"] for r in seen] == ["same-key", "same-key"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "body", "error_type"),
    [
        (401, {"error": "unauthorized"}, AuthenticationError),
        (403, {"error": "permit_denied", "message": "refused"}, PermitDeniedError),
        (403, {"error": "permit_required"}, PermitDeniedError),
        (403, {"error": "forbidden"}, AuthorizationError),
        (
            409,
            {"error": "idempotency_conflict", "message": "reused"},
            IdempotencyConflictError,
        ),
    ],
)
async def test_typed_errors_for_governed_failures(status, body, error_type):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    client = _client(handler, max_retries=0)
    try:
        with pytest.raises(error_type) as exc:
            await client.execute(
                "sess-1",
                "add_to_cart",
                {},
                permit_id="permit-1",
                idempotency_key="k-1",
            )
    finally:
        await _close(client)
    # Still catchable as the httpx error older callers expect.
    assert isinstance(exc.value, httpx.HTTPStatusError)
    assert exc.value.response.status_code == status


@pytest.mark.anyio
async def test_unmapped_error_stays_plain_http_status_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "bad input"})

    client = _client(handler, max_retries=0)
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await client.execute(
                "sess-1", "add_to_cart", {}, permit_id="p", idempotency_key="k"
            )
    finally:
        await _close(client)
    assert not isinstance(exc.value, sdk_errors.AWIError)
    assert exc.value.response.status_code == 422


def test_action_definition_from_dict_round_trip():
    definition = AWIActionDefinition.from_dict(_vocab_entry())
    assert definition.action == "search_and_sort"
    assert definition.tier.value == "semantic"
    assert definition.status.value == "stable"
    assert definition.risk_level.value == "low"


def test_action_definition_from_dict_tolerates_unknown_values():
    definition = AWIActionDefinition.from_dict(
        _vocab_entry(tier="future-tier", status="odd", risk_level="extreme")
    )
    assert definition.tier.value == "semantic"
    assert definition.status.value == "stable"
    assert definition.risk_level.value == "low"


def test_action_definition_from_dict_rejects_non_dict():
    with pytest.raises(ValueError):
        AWIActionDefinition.from_dict(["not", "a", "dict"])


def test_execution_response_from_dict_keeps_typed_view():
    response = AWIExecutionResponse.from_dict(
        {
            "execution_id": "exec-1",
            "session_id": "sess-1",
            "action": "navigate_to",
            "status": "success",
            "result": {"url": "https://example.com"},
            "receipt": {"permit_id": "permit-1"},
        }
    )
    assert response.execution_id == "exec-1"
    assert response.status == "success"
    assert response.result == {"url": "https://example.com"}


@pytest.mark.anyio
async def test_list_action_definitions_returns_typed_models():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"actions": [_vocab_entry()], "categories": ["search"]}
        )

    client = _client(handler)
    try:
        definitions = await client.list_action_definitions()
    finally:
        await _close(client)
    assert len(definitions) == 1
    assert isinstance(definitions[0], AWIActionDefinition)
    assert definitions[0].action == "search_and_sort"


@pytest.mark.anyio
async def test_execute_typed_returns_response_model():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "execution_id": "exec-1",
                "session_id": "sess-1",
                "action": "add_to_cart",
                "status": "success",
            },
        )

    client = _client(handler)
    try:
        typed = await client.execute_typed(
            "sess-1",
            "add_to_cart",
            {"sku": "x"},
            permit_id="permit-1",
            idempotency_key="k-1",
        )
    finally:
        await _close(client)
    assert isinstance(typed, AWIExecutionResponse)
    assert typed.execution_id == "exec-1"
    assert typed.status == "success"


def test_python_package_is_pip_installable():
    pyproject = REPO_ROOT / "awi_sdk" / "python" / "pyproject.toml"
    assert pyproject.is_file(), "pyproject.toml missing: SDK not installable"
    with open(pyproject, "rb") as handle:
        metadata = tomllib.load(handle)
    project = metadata["project"]
    assert project["name"] == "awi-sdk"
    assert any(dep.startswith("httpx") for dep in project["dependencies"])
    assert (REPO_ROOT / "awi_sdk" / "python" / "README.md").is_file()
    assert (REPO_ROOT / "awi_sdk" / "python" / "LICENSE").is_file()
