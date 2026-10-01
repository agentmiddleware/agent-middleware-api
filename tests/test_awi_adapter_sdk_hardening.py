"""Regression tests for the AWI adoption kit, AWI SDK clients and embeddings.

Frozen proof surface (unmounted by default, refused in production-like
boots). Security and correctness fixes only:

  - AWIExternalAdapter.execute_action_for_external ran the website's
    side-effecting internal call *before* the governed POST /v1/awi/execute,
    and sent internal calls through the client that carries the middleware
    X-API-Key, so an absolute URL in route_mapping received the key.
  - AWIFallbackAdapter swallowed every exception without a log line and
    fabricated a ``fallback-<wallet>`` session id no proxy backs.
  - ProgressiveRepresentationEngine._generate_embedding returned all zeros
    (``hash(chunk) % 1.0``) and depended on per-process hash salting.
  - AWIRAGEngine._generate_embedding silently fell back to the hash mock on
    any OpenAI error.
  - ManifestGenerator._route_to_action escaped "/" so no action_map entry
    could ever match a real route.
  - AWI SDK execute() (and B2AEdgeClient.execute_awi_action) could not send
    the X-Permit-Id / Idempotency-Key the governed route requires, and the
    AWI SDK config printed the API key in its repr.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import app.services.awi_external_adapter as adapter_module
from app.core.config import get_settings
from app.main import app
from app.schemas.awi import AWIRepresentationType, AWIStandardAction
from app.services.awi_external_adapter import AWIExternalAdapter, AWIFallbackAdapter
from app.services.awi_rag_engine import AWIRAGEngine
from app.services.awi_representation import ProgressiveRepresentationEngine
from app.tools.awi_manifest_generator import ManifestGenerator
from b2a_sdk.edge_client import B2AEdgeClient
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

pytestmark = pytest.mark.proof

REPO_ROOT = Path(__file__).resolve().parents[1]
MIDDLEWARE_KEY = "mw-secret-key"
ADAPTER_LOGGER = "app.services.awi_external_adapter"
RAG_LOGGER = "app.services.awi_rag_engine"


def _awi_sdk() -> ModuleType:
    """Import the unpackaged AWI Python SDK from the checkout."""
    sdk_path = str(REPO_ROOT / "awi_sdk" / "python")
    if sdk_path not in sys.path:
        sys.path.insert(0, sdk_path)
    import awi_sdk

    return awi_sdk


# --------------------------------------------------------------------------
# AWIExternalAdapter: authorize before invoke, never leak the middleware key
# --------------------------------------------------------------------------


class _Wire:
    """Records every request the adapter's HTTP clients send."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.governed_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/v1/awi/execute":
            if self.governed_status != 200:
                return httpx.Response(
                    self.governed_status,
                    json={"detail": {"error": "permit_required"}},
                )
            return httpx.Response(200, json={"status": "success", "receipt": {}})
        return httpx.Response(200, json={"internal": "done"})

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


@pytest.fixture
def wire(monkeypatch) -> _Wire:
    """Route every AsyncClient the adapter module builds through a MockTransport."""
    recorder = _Wire()
    real_async_client = httpx.AsyncClient

    def _client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(recorder)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(adapter_module.httpx, "AsyncClient", _client)
    return recorder


def _adapter() -> AWIExternalAdapter:
    return AWIExternalAdapter(
        middleware_url="http://middleware.test", api_key=MIDDLEWARE_KEY
    )


@pytest.mark.anyio
async def test_adapter_governance_denial_never_reaches_internal_route(wire):
    """A refused governed call must leave the website's side effect unrun."""
    wire.governed_status = 403
    adapter = _adapter()
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.execute_action_for_external(
                session_id="sess-1",
                action=AWIStandardAction.ADD_TO_CART,
                parameters={"sku": "laptop-1"},
                route_mapping={"add_to_cart": "/cart/add"},
            )
    finally:
        await adapter.close()

    assert wire.paths() == ["/v1/awi/execute"], (
        "the internal side-effecting route ran even though the governed "
        "call was refused"
    )


@pytest.mark.anyio
async def test_adapter_authorizes_first_and_internal_call_carries_no_key(wire):
    adapter = _adapter()
    try:
        result = await adapter.execute_action_for_external(
            session_id="sess-1",
            action=AWIStandardAction.ADD_TO_CART,
            parameters={"sku": "laptop-1"},
            route_mapping={"add_to_cart": "/cart/add"},
        )
    finally:
        await adapter.close()

    assert wire.paths() == ["/v1/awi/execute", "/cart/add"]
    governed, internal = wire.requests
    assert governed.headers["X-API-Key"] == MIDDLEWARE_KEY
    assert "x-api-key" not in internal.headers
    assert MIDDLEWARE_KEY not in str(internal.headers)
    assert result["internal_result"] == {"internal": "done"}
    assert result["awi_response"]["status"] == "success"


@pytest.mark.anyio
async def test_adapter_forwards_permit_headers_only_to_governed_call(wire):
    adapter = _adapter()
    try:
        await adapter.execute_action_for_external(
            session_id="sess-1",
            action="add_to_cart",
            parameters={"sku": "laptop-1"},
            route_mapping={"add_to_cart": "/cart/add"},
            permit_id="permit-123",
            idempotency_key="idem-123",
        )
    finally:
        await adapter.close()

    governed, internal = wire.requests
    assert governed.url.path == "/v1/awi/execute"
    assert governed.headers["X-Permit-Id"] == "permit-123"
    assert governed.headers["Idempotency-Key"] == "idem-123"
    assert "x-permit-id" not in internal.headers
    assert "idempotency-key" not in internal.headers


@pytest.mark.anyio
@pytest.mark.parametrize(
    "route",
    [
        "https://attacker.example/steal",
        "http://attacker.example/steal",
        "//attacker.example/steal",
    ],
)
async def test_adapter_refuses_absolute_route_mapping(wire, route):
    adapter = _adapter()
    try:
        result = await adapter.execute_action_for_external(
            session_id="sess-1",
            action="add_to_cart",
            parameters={"sku": "laptop-1"},
            route_mapping={"add_to_cart": route},
        )
    finally:
        await adapter.close()

    leaked = [
        str(request.url)
        for request in wire.requests
        if request.headers.get("X-API-Key") == MIDDLEWARE_KEY
        and request.url.path != "/v1/awi/execute"
    ]
    assert leaked == [], "the middleware API key was sent to a mapped route"
    # Refused before any network call: nothing was authorized or invoked.
    assert wire.requests == []
    assert result["success"] is False
    assert "relative" in result["error"]


# --------------------------------------------------------------------------
# AWIFallbackAdapter: log, do not fabricate, do not swallow non-HTTP errors
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fallback_discover_logs_http_failure(monkeypatch, caplog):
    adapter = AWIFallbackAdapter("http://middleware.test", MIDDLEWARE_KEY)

    async def _down() -> dict[str, Any]:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(adapter.awi, "discover_manifest", _down)
    caplog.set_level(logging.WARNING, logger=ADAPTER_LOGGER)
    try:
        manifest = await adapter.discover()
    finally:
        await adapter.awi.close()

    assert manifest["name"] == "MCP Fallback"
    warnings = [r for r in caplog.records if r.name == ADAPTER_LOGGER]
    assert warnings, "fallback discover swallowed the failure without a log line"
    assert all(MIDDLEWARE_KEY not in r.getMessage() for r in warnings)


@pytest.mark.anyio
async def test_fallback_create_session_does_not_fabricate_session_id(
    monkeypatch, caplog
):
    adapter = AWIFallbackAdapter("http://middleware.test", MIDDLEWARE_KEY)

    async def _down(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(adapter.awi, "create_external_session", _down)
    caplog.set_level(logging.WARNING, logger=ADAPTER_LOGGER)
    try:
        session = await adapter.create_session("https://shop.example", "wallet-a")
    finally:
        await adapter.awi.close()

    assert session["session_id"] is None
    assert session["status"] == "unavailable"
    assert "wallet-a" not in str(session)
    assert [r for r in caplog.records if r.name == ADAPTER_LOGGER]


@pytest.mark.anyio
async def test_fallback_does_not_swallow_programming_errors(monkeypatch):
    adapter = AWIFallbackAdapter("http://middleware.test", MIDDLEWARE_KEY)

    async def _broken(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ValueError("bug, not an outage")

    monkeypatch.setattr(adapter.awi, "discover_manifest", _broken)
    monkeypatch.setattr(adapter.awi, "create_external_session", _broken)
    try:
        with pytest.raises(ValueError):
            await adapter.discover()
        with pytest.raises(ValueError):
            await adapter.create_session("https://shop.example", "wallet-a")
    finally:
        await adapter.awi.close()


# --------------------------------------------------------------------------
# Progressive representation embedding (simulation, but not all zeros)
# --------------------------------------------------------------------------


async def _embed(engine: ProgressiveRepresentationEngine, text: str) -> dict:
    result = await engine.generate_representation(
        "sess-embed",
        AWIRepresentationType.EMBEDDING,
        {"html": f"<html><body>{text}</body></html>"},
        {},
    )
    return result["content"]


@pytest.mark.anyio
async def test_representation_embedding_is_non_zero_deterministic_and_labelled():
    engine = ProgressiveRepresentationEngine()
    text_a = "Laptops on sale today with free shipping and easy returns"
    text_b = "Garden tools, outdoor furniture and seasonal plants for spring"

    first = await _embed(engine, text_a)
    again = await _embed(engine, text_a)
    other = await _embed(engine, text_b)

    vector = first["vector"]
    assert vector, "embedding vector is empty"
    assert any(value != 0.0 for value in vector), "embedding is all zeros"
    assert all(0.0 <= value < 1.0 for value in vector)
    assert len(set(vector)) > 1
    assert again["vector"] == vector
    assert other["vector"] != vector
    assert first["dimension"] == len(vector)
    assert first["simulated"] is True


# --------------------------------------------------------------------------
# AWI RAG embedding fallback is logged, and skipped quietly without a key
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_rag_embedding_fallback_is_logged_without_payload(monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "LLM_API_KEY", "sk-test-not-real")
    engine = AWIRAGEngine()

    async def _boom(text: str) -> list[float]:
        raise RuntimeError("upstream said: secret-query-text")

    monkeypatch.setattr(engine, "_generate_openai_embedding", _boom)
    caplog.set_level(logging.WARNING, logger=RAG_LOGGER)

    vector = await engine._generate_embedding("secret-query-text")

    assert vector == engine._generate_mock_embedding("secret-query-text")
    records = [r for r in caplog.records if r.name == RAG_LOGGER]
    messages = " ".join(r.getMessage() for r in records)
    assert "awi_rag_embedding_fallback" in messages
    assert "RuntimeError" in messages
    assert "secret-query-text" not in messages


@pytest.mark.anyio
async def test_rag_embedding_without_key_skips_openai(monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "LLM_API_KEY", "")
    engine = AWIRAGEngine()
    calls: list[str] = []

    async def _record(text: str) -> list[float]:
        calls.append(text)
        raise AssertionError("OpenAI must not be attempted without a key")

    monkeypatch.setattr(engine, "_generate_openai_embedding", _record)
    caplog.set_level(logging.WARNING, logger=RAG_LOGGER)

    vector = await engine._generate_embedding("hello")

    assert calls == []
    assert vector == engine._generate_mock_embedding("hello")
    assert not [r for r in caplog.records if r.name == RAG_LOGGER]


# --------------------------------------------------------------------------
# Manifest generator action mapping
# --------------------------------------------------------------------------


class _Route:
    def __init__(self, method: str, path: str) -> None:
        self.path = path
        self.methods = {method}
        self.name = path


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("POST", "/search", "search_and_sort"),
        ("POST", "/api/search", "search_and_sort"),
        ("POST", "/api/search/", "search_and_sort"),
        ("POST", "/api/cart/add", "add_to_cart"),
        ("POST", "/checkout", "checkout"),
        ("POST", "/login", "login"),
        ("POST", "/logout", "logout"),
        ("POST", "/form", "fill_form"),
        ("GET", "/", "navigate_to"),
        ("GET", "/items", None),
        ("GET", "/search", None),
        ("POST", "/format", "custom_action"),
        ("POST", "/research", "custom_action"),
        ("POST", "/search/history", "custom_action"),
    ],
)
def test_manifest_route_to_action_matches_real_paths(method, path, expected):
    action = ManifestGenerator()._route_to_action(_Route(method, path))
    if expected is None:
        assert action is None
    else:
        assert action is not None
        assert action["awi_action"] == expected
        assert action["route"] == path


def test_manifest_scan_maps_standard_actions_from_fastapi_app():
    from fastapi import FastAPI

    site = FastAPI(title="Shop")

    @site.get("/")
    async def home() -> dict:
        return {}

    @site.post("/api/search")
    async def search() -> dict:
        return {}

    @site.post("/api/cart/add")
    async def add() -> dict:
        return {}

    manifest = ManifestGenerator().scan_fastapi_app(site)

    assert manifest["route_mappings"]["navigate_to"] == "/"
    assert manifest["route_mappings"]["search_and_sort"] == "/api/search"
    assert manifest["route_mappings"]["add_to_cart"] == "/api/cart/add"


# --------------------------------------------------------------------------
# AWI Python SDK + B2A edge client: governed headers, key hygiene
# --------------------------------------------------------------------------


def _capturing_transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "success"})

    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_awi_sdk_execute_sends_permit_and_idempotency_headers():
    sdk = _awi_sdk()
    seen: list[httpx.Request] = []
    client = sdk.AWIClient(base_url="http://middleware.test", api_key="sk-live")
    client._client._transport = _capturing_transport(seen)
    try:
        await client.execute(
            "sess-1",
            "add_to_cart",
            {"sku": "laptop-1"},
            permit_id="permit-123",
            idempotency_key="idem-123",
        )
    finally:
        await client.close()

    assert len(seen) == 1
    assert seen[0].url.path == "/v1/awi/execute"
    assert seen[0].headers["X-Permit-Id"] == "permit-123"
    assert seen[0].headers["Idempotency-Key"] == "idem-123"
    assert seen[0].headers["X-API-Key"] == "sk-live"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("permit_id", "idempotency_key"),
    [
        ("", "idem-1"),
        ("   ", "idem-1"),
        ("permit-1", ""),
        ("permit-1", "   "),
        ("permit-1", "k" * 129),
    ],
)
async def test_awi_sdk_execute_rejects_invalid_governance_headers(
    permit_id, idempotency_key
):
    sdk = _awi_sdk()
    seen: list[httpx.Request] = []
    client = sdk.AWIClient(base_url="http://middleware.test", api_key="sk-live")
    client._client._transport = _capturing_transport(seen)
    try:
        with pytest.raises(ValueError):
            await client.execute(
                "sess-1",
                "add_to_cart",
                permit_id=permit_id,
                idempotency_key=idempotency_key,
            )
        with pytest.raises(TypeError):
            await client.execute("sess-1", "add_to_cart")
    finally:
        await client.close()

    assert seen == [], "an invalid governed call still reached the network"


def test_awi_sdk_config_repr_masks_api_key():
    sdk = _awi_sdk()
    config = sdk.AWIClientConfig(api_key="sk-secret-value")
    assert "sk-secret-value" not in repr(config)
    assert "sk-secret-value" not in str(config)


@pytest.mark.anyio
async def test_awi_sdk_does_not_follow_cross_host_redirects():
    sdk = _awi_sdk()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            307, headers={"Location": "https://attacker.example/collect"}
        )

    client = sdk.AWIClient(base_url="http://middleware.test", api_key="sk-live")
    client._client._transport = httpx.MockTransport(handler)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.discover()
    finally:
        await client.close()

    assert [request.url.host for request in seen] == ["middleware.test"]


@pytest.mark.anyio
async def test_edge_client_execute_awi_action_sends_governed_headers():
    seen: list[httpx.Request] = []
    edge = B2AEdgeClient(api_url="http://middleware.test", api_key="sk-live")
    edge._client._transport = _capturing_transport(seen)
    try:
        await edge.execute_awi_action(
            "sess-1",
            "add_to_cart",
            {"sku": "laptop-1"},
            permit_id="permit-123",
            idempotency_key="idem-123",
        )
        with pytest.raises(ValueError):
            await edge.execute_awi_action(
                "sess-1",
                "add_to_cart",
                {},
                permit_id="permit-123",
                idempotency_key="k" * 129,
            )
    finally:
        await edge.close()

    assert len(seen) == 1
    assert seen[0].headers["X-Permit-Id"] == "permit-123"
    assert seen[0].headers["Idempotency-Key"] == "idem-123"


@pytest.fixture
async def http_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _sdk_client_for(provisioned: dict[str, Any]):
    sdk = _awi_sdk()
    client = sdk.AWIClient(
        base_url="http://test",
        api_key=provisioned["agent_headers"]["X-API-Key"],
        wallet_id=provisioned["agent_wallet_id"],
    )
    client._client._transport = ASGITransport(app=app)
    return client


@pytest.mark.anyio
async def test_awi_sdk_governed_execute_end_to_end_and_cross_wallet_denied(
    http_client, clean_database
):
    """Owner's SDK call is governed and receipted; another wallet is refused."""
    owner = await provision_agent_wallet(http_client)
    other = await provision_agent_wallet(http_client)
    owner_permit = await create_tool_permit(
        http_client,
        wallet_id=owner["agent_wallet_id"],
        key_id=owner["key_id"],
        tool_name="awi_execute",
        max_credits=50,
        idem_key="permit-sdk-owner",
    )
    other_permit = await create_tool_permit(
        http_client,
        wallet_id=other["agent_wallet_id"],
        key_id=other["key_id"],
        tool_name="awi_execute",
        max_credits=50,
        idem_key="permit-sdk-other",
    )

    owner_sdk = await _sdk_client_for(owner)
    other_sdk = await _sdk_client_for(other)
    try:
        session = await owner_sdk.create_session("https://example.com")
        session_id = session["session_id"]

        # Another wallet, holding its own valid permit, cannot drive the
        # owner's session through the SDK, and learns nothing of its result.
        with pytest.raises(httpx.HTTPStatusError) as denied:
            await other_sdk.execute(
                session_id,
                "navigate_to",
                {"url": "https://example.com/next"},
                permit_id=other_permit["permit_id"],
                idempotency_key="sdk-cross-wallet-1",
            )
        assert denied.value.response.status_code in (403, 404)
        assert "receipt" not in denied.value.response.text
        assert "execution_id" not in denied.value.response.text

        result = await owner_sdk.execute(
            session_id,
            "navigate_to",
            {"url": "https://example.com/next"},
            permit_id=owner_permit["permit_id"],
            idempotency_key="sdk-owner-1",
        )
    finally:
        await owner_sdk.close()
        await other_sdk.close()

    assert result["status"] == "success"
    assert result["receipt"]["permit_id"] == owner_permit["permit_id"]
    assert result["receipt"]["outcome"] == "success"
