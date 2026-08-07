"""Focused security and transport tests for the single upstream MCP adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
import logging
from typing import Any

import httpx
import pytest
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from app.core.config import Settings
from app.db.database import get_session_factory
from app.db.models import WalletModel
from app.schemas.billing import ServiceCategory
from app.services.service_registry import ServiceRegistry
from app.services.upstream_mcp import (
    DiscoveredUpstreamTool,
    UpstreamMcpAdapter,
    UpstreamMcpConfiguration,
    UpstreamMcpConfigurationError,
    UpstreamMcpDeliveryUncertainError,
    UpstreamMcpPreDispatchError,
    UpstreamMcpResponseRejectedError,
    UpstreamMcpReturnedError,
    get_upstream_mcp_metrics_snapshot,
    register_configured_upstream_mcp,
    validate_upstream_url,
)
import app.services.upstream_mcp as upstream_mcp_module


async def _global_resolver(_host: str, _port: int | None) -> Sequence[str]:
    return ("93.184.216.34",)


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "ENVIRONMENT": "local",
        "MCP_UPSTREAM_ENABLED": True,
        "MCP_UPSTREAM_URL": "http://localhost:9000/mcp",
        "MCP_UPSTREAM_TOOL_NAME": "partner.write",
        "MCP_UPSTREAM_PUBLIC_TOOL_ID": "partner.notes.write",
        "MCP_UPSTREAM_BEARER_TOKEN": "secret-partner-token",
        "MCP_UPSTREAM_CREDITS_PER_CALL": "7.5",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _configuration(**overrides: Any) -> UpstreamMcpConfiguration:
    return UpstreamMcpConfiguration.from_settings(_settings(**overrides))


class FakeSession:
    def __init__(
        self,
        *,
        tools: list[Tool] | None = None,
        result: Any | None = None,
        initialize_error: Exception | None = None,
        call_error: Exception | None = None,
    ) -> None:
        self.tools = tools or []
        self.result = result or CallToolResult(
            content=[TextContent(type="text", text="ok")],
            structuredContent={"z": 1, "a": 2},
            isError=False,
        )
        self.initialize_error = initialize_error
        self.call_error = call_error
        self.events: list[str] = []
        self.call_arguments: dict[str, Any] | None = None
        self.call_meta: dict[str, Any] | None = None

    async def initialize(self) -> None:
        self.events.append("initialize")
        if self.initialize_error:
            raise self.initialize_error

    async def list_tools(self, cursor: str | None = None) -> ListToolsResult:
        del cursor
        self.events.append("list_tools")
        return ListToolsResult(tools=self.tools)

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: Any | None = None,
        *,
        meta: dict[str, Any] | None = None,
    ) -> Any:
        del read_timeout_seconds
        self.events.append("call_tool")
        self.call_arguments = {"name": name, "arguments": arguments}
        self.call_meta = meta
        if self.call_error:
            raise self.call_error
        return self.result


def _bind_session(
    adapter: UpstreamMcpAdapter,
    session: FakeSession,
    *,
    cleanup_error: Exception | None = None,
) -> None:
    @asynccontextmanager
    async def session_context() -> AsyncIterator[FakeSession]:
        yield session
        if cleanup_error:
            raise cleanup_error

    adapter._session = session_context  # type: ignore[method-assign]


def _mark_discovered(adapter: UpstreamMcpAdapter) -> None:
    adapter._discovered_tool = DiscoveredUpstreamTool(
        name="partner.write",
        description="Partner write",
        input_schema={"type": "object", "properties": {}},
        output_schema=None,
    )


def test_configuration_requires_every_partner_value_and_redacts_bearer() -> None:
    with pytest.raises(UpstreamMcpConfigurationError) as exc_info:
        UpstreamMcpConfiguration.from_settings(
            _settings(
                MCP_UPSTREAM_URL="",
                MCP_UPSTREAM_BEARER_TOKEN="",
                MCP_UPSTREAM_CREDITS_PER_CALL="0",
            )
        )
    assert exc_info.value.dispatch_started is False
    assert "MCP_UPSTREAM_URL" in exc_info.value.detail
    assert "MCP_UPSTREAM_BEARER_TOKEN" in exc_info.value.detail

    configuration = _configuration()
    assert "secret-partner-token" not in repr(configuration)


def test_configuration_uses_mcp_recommended_tool_name_characters() -> None:
    accepted = _configuration(
        MCP_UPSTREAM_TOOL_NAME="Partner_tool-name.v2",
        MCP_UPSTREAM_PUBLIC_TOOL_ID="public.partner_tool-v2",
    )
    assert accepted.tool_name == "Partner_tool-name.v2"

    for tool_name in ("partner/write", "partner:write", "partner write"):
        with pytest.raises(UpstreamMcpConfigurationError):
            _configuration(MCP_UPSTREAM_TOOL_NAME=tool_name)

    with pytest.raises(UpstreamMcpConfigurationError) as exc_info:
        _configuration(
            MCP_UPSTREAM_TOOL_NAME="secret-partner-token",
        )
    assert "secret-partner-token" not in exc_info.value.detail


@pytest.mark.parametrize(
    ("url", "environment"),
    [
        ("https://user:pass@example.com/mcp", "production"),
        ("https://example.com/mcp?tenant=a", "production"),
        ("https://example.com/mcp#fragment", "production"),
        ("ftp://example.com/mcp", "production"),
    ],
)
def test_configuration_rejects_unsafe_url_shapes(url: str, environment: str) -> None:
    with pytest.raises(UpstreamMcpConfigurationError):
        _configuration(MCP_UPSTREAM_URL=url, ENVIRONMENT=environment)


@pytest.mark.anyio
async def test_url_guard_allows_only_public_https_or_local_loopback_http() -> None:
    await validate_upstream_url(_configuration())
    await validate_upstream_url(
        _configuration(
            MCP_UPSTREAM_URL="https://partner.example/mcp",
            ENVIRONMENT="production",
        ),
        resolver=_global_resolver,
    )

    unsafe = [
        _configuration(
            MCP_UPSTREAM_URL="http://partner.example/mcp",
            ENVIRONMENT="production",
        ),
        _configuration(
            MCP_UPSTREAM_URL="https://127.0.0.1/mcp",
            ENVIRONMENT="production",
        ),
        _configuration(MCP_UPSTREAM_URL="http://10.0.0.5/mcp"),
        _configuration(MCP_UPSTREAM_URL="https://169.254.169.254/latest/meta-data"),
        _configuration(MCP_UPSTREAM_URL="https://metadata.google.internal/mcp"),
    ]
    for configuration in unsafe:
        with pytest.raises(UpstreamMcpConfigurationError):
            await validate_upstream_url(
                configuration,
                resolver=_global_resolver,
            )


@pytest.mark.anyio
async def test_url_guard_rejects_dns_to_private_link_local_and_reserved() -> None:
    async def resolver(_host: str, _port: int | None) -> Sequence[str]:
        return ("10.0.0.2", "169.254.169.254", "192.0.2.1")

    configuration = _configuration(
        MCP_UPSTREAM_URL="https://partner.example/mcp",
        ENVIRONMENT="production",
    )
    with pytest.raises(UpstreamMcpConfigurationError):
        await validate_upstream_url(configuration, resolver=resolver)

    async def failed_resolver(_host: str, _port: int | None) -> Sequence[str]:
        raise OSError("resolver unavailable")

    with pytest.raises(UpstreamMcpConfigurationError) as exc_info:
        await validate_upstream_url(configuration, resolver=failed_resolver)
    assert exc_info.value.detail == "MCP_UPSTREAM_URL host could not be resolved"


@pytest.mark.anyio
async def test_default_http_client_disables_redirects_and_redacts_auth() -> None:
    adapter = UpstreamMcpAdapter(_configuration())
    async with adapter._http_client() as client:
        assert client.follow_redirects is False
        assert client.headers["Authorization"] == "Bearer secret-partner-token"
        assert "secret-partner-token" not in repr(adapter.configuration)


@pytest.mark.anyio
async def test_injected_http_client_is_used_without_being_closed() -> None:
    injected = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: None),
        headers={"Authorization": "Bearer secret-partner-token"},
    )
    adapter = UpstreamMcpAdapter(_configuration(), http_client=injected)
    async with adapter._http_client() as selected:
        assert selected is injected
    assert not injected.is_closed
    await injected.aclose()

    redirecting = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: None),
        headers={"Authorization": "Bearer secret-partner-token"},
        follow_redirects=True,
    )
    adapter = UpstreamMcpAdapter(_configuration(), http_client=redirecting)
    with pytest.raises(UpstreamMcpConfigurationError):
        async with adapter._http_client():
            pass
    await redirecting.aclose()

    missing_credential = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: None),
    )
    adapter = UpstreamMcpAdapter(_configuration(), http_client=missing_credential)
    with pytest.raises(UpstreamMcpConfigurationError) as exc_info:
        async with adapter._http_client():
            pass
    assert "secret-partner-token" not in exc_info.value.detail
    await missing_credential.aclose()


@pytest.mark.anyio
async def test_discovery_initializes_and_caches_exact_tool_schema() -> None:
    session = FakeSession(
        tools=[
            Tool(
                name="partner.write",
                description="Write a partner note",
                inputSchema={
                    "type": "object",
                    "properties": {"note": {"type": "string"}},
                    "required": ["note"],
                },
                outputSchema={"type": "object"},
            )
        ]
    )
    adapter = UpstreamMcpAdapter(_configuration())
    _bind_session(adapter, session)

    discovered = await adapter.discover_tool()

    assert session.events == ["initialize", "list_tools"]
    assert discovered.name == "partner.write"
    assert discovered.description == (
        "Governed remote MCP tool dispatched through the Agent Middleware trust plane."
    )
    assert "Write a partner note" not in discovered.description
    assert discovered.input_schema["required"] == ["note"]
    assert adapter.discovered_tool is discovered


@pytest.mark.parametrize(
    "tool",
    [
        Tool(
            name="partner.write",
            description="credential=secret-partner-token",
            inputSchema={"type": "object"},
        ),
        Tool(
            name="partner.write",
            inputSchema={
                "type": "object",
                "description": "secret-partner-token",
            },
        ),
        Tool(
            name="partner.write",
            inputSchema={"type": "object"},
            outputSchema={
                "type": "object",
                "description": "secret-partner-token",
            },
        ),
    ],
)
@pytest.mark.anyio
async def test_discovery_rejects_bearer_token_echo_without_exposing_it(
    tool: Tool,
) -> None:
    adapter = UpstreamMcpAdapter(_configuration())
    _bind_session(adapter, FakeSession(tools=[tool]))

    with pytest.raises(UpstreamMcpConfigurationError) as exc_info:
        await adapter.discover_tool()

    assert exc_info.value.detail == "upstream MCP discovery metadata is unsafe"
    assert "secret-partner-token" not in str(exc_info.value)
    assert "secret-partner-token" not in repr(exc_info.value)


@pytest.mark.anyio
async def test_discovery_requires_object_input_schema_or_absent_type() -> None:
    adapter = UpstreamMcpAdapter(_configuration())
    _bind_session(
        adapter,
        FakeSession(tools=[Tool(name="partner.write", inputSchema={"type": "string"})]),
    )
    with pytest.raises(UpstreamMcpConfigurationError) as exc_info:
        await adapter.discover_tool()
    assert "must describe an object" in exc_info.value.detail

    adapter = UpstreamMcpAdapter(_configuration())
    _bind_session(
        adapter,
        FakeSession(tools=[Tool(name="partner.write", inputSchema={})]),
    )
    assert (await adapter.discover_tool()).input_schema == {}


@pytest.mark.anyio
async def test_discovery_bounds_page_metadata_and_selected_schema() -> None:
    for tool in (
        Tool(
            name="partner.write",
            description="x" * 2_000,
            inputSchema={"type": "object"},
        ),
        Tool(
            name="partner.write",
            inputSchema={
                "type": "object",
                "description": "x" * 2_000,
            },
        ),
        Tool(
            name="partner.write",
            inputSchema={"type": "object"},
            _meta={"opaque": "x" * 2_000},
        ),
    ):
        adapter = UpstreamMcpAdapter(
            _configuration(MCP_UPSTREAM_MAX_RESPONSE_BYTES=512)
        )
        _bind_session(adapter, FakeSession(tools=[tool]))
        with pytest.raises(UpstreamMcpConfigurationError) as exc_info:
            await adapter.discover_tool()
        assert "configured size limit" in exc_info.value.detail


@pytest.mark.anyio
async def test_discovery_bounds_total_tool_count(monkeypatch) -> None:
    monkeypatch.setattr(upstream_mcp_module, "_MAX_DISCOVERY_TOOLS", 1)
    adapter = UpstreamMcpAdapter(_configuration())
    _bind_session(
        adapter,
        FakeSession(
            tools=[
                Tool(name="partner.write", inputSchema={"type": "object"}),
                Tool(name="other", inputSchema={"type": "object"}),
            ]
        ),
    )
    with pytest.raises(UpstreamMcpConfigurationError) as exc_info:
        await adapter.discover_tool()
    assert exc_info.value.detail == (
        "upstream tools/list exceeded the discovery tool limit"
    )


@pytest.mark.anyio
async def test_discovery_fails_closed_when_exact_tool_is_absent() -> None:
    adapter = UpstreamMcpAdapter(_configuration())
    _bind_session(
        adapter,
        FakeSession(tools=[Tool(name="other", inputSchema={"type": "object"})]),
    )
    with pytest.raises(UpstreamMcpConfigurationError) as exc_info:
        await adapter.discover_tool()
    assert exc_info.value.dispatch_started is False


@pytest.mark.anyio
async def test_call_tool_commits_dispatch_boundary_and_forwards_metadata() -> None:
    session = FakeSession()
    adapter = UpstreamMcpAdapter(_configuration())
    _mark_discovered(adapter)
    _bind_session(adapter, session)

    async def before_dispatch() -> None:
        session.events.append("before_dispatch")

    result = await adapter.call_tool(
        {"note": "hello"},
        invocation_id="inv-123",
        idempotency_key="idem-123",
        before_dispatch=before_dispatch,
    )

    assert session.events == ["initialize", "before_dispatch", "call_tool"]
    assert session.call_arguments == {
        "name": "partner.write",
        "arguments": {"note": "hello"},
    }
    assert session.call_meta == {
        "io.agentmiddleware/invocation_id": "inv-123",
        "io.agentmiddleware/idempotency_key": "idem-123",
    }
    assert result.payload == {
        "content": [{"type": "text", "text": "ok"}],
        "isError": False,
        "structuredContent": {"a": 2, "z": 1},
    }
    assert result.canonical_json == (
        '{"content":[{"text":"ok","type":"text"}],"isError":false,'
        '"structuredContent":{"a":2,"z":1}}'
    )
    assert len(result.response_hash) == 64
    assert result.size_bytes == len(result.canonical_json.encode("utf-8"))


@pytest.mark.anyio
async def test_call_metrics_are_bounded_and_contain_no_partner_data() -> None:
    adapter = UpstreamMcpAdapter(_configuration())
    _mark_discovered(adapter)
    _bind_session(adapter, FakeSession())
    before = get_upstream_mcp_metrics_snapshot()

    async def before_dispatch() -> None:
        return None

    await adapter.call_tool(
        {"private_payload": "must-not-appear"},
        invocation_id="private-invocation-id",
        idempotency_key="private-idempotency-key",
        before_dispatch=before_dispatch,
    )
    after = get_upstream_mcp_metrics_snapshot()

    assert after["calls_total"] == before["calls_total"] + 1
    assert after["outcomes"]["succeeded"] == (before["outcomes"]["succeeded"] + 1)
    assert after["latency_seconds_total"] >= before["latency_seconds_total"]
    serialized = repr(after)
    for private_value in (
        "must-not-appear",
        "private-invocation-id",
        "private-idempotency-key",
        "secret-partner-token",
    ):
        assert private_value not in serialized


@pytest.mark.anyio
async def test_initialize_and_checkpoint_failures_are_pre_dispatch() -> None:
    adapter = UpstreamMcpAdapter(_configuration())
    _mark_discovered(adapter)
    session = FakeSession(initialize_error=RuntimeError("connect failed"))
    _bind_session(adapter, session)
    callback_called = False

    async def before_dispatch() -> None:
        nonlocal callback_called
        callback_called = True

    with pytest.raises(UpstreamMcpPreDispatchError) as initialize_error:
        await adapter.call_tool(
            {},
            invocation_id="inv",
            idempotency_key="idem",
            before_dispatch=before_dispatch,
        )
    assert initialize_error.value.dispatch_started is False
    assert callback_called is False

    session = FakeSession()
    _bind_session(adapter, session)

    async def failed_checkpoint() -> None:
        raise RuntimeError("commit failed")

    with pytest.raises(UpstreamMcpPreDispatchError) as checkpoint_error:
        await adapter.call_tool(
            {},
            invocation_id="inv",
            idempotency_key="idem",
            before_dispatch=failed_checkpoint,
        )
    assert checkpoint_error.value.code == "upstream_dispatch_checkpoint_failed"
    assert checkpoint_error.value.dispatch_started is False
    assert "call_tool" not in session.events


@pytest.mark.anyio
async def test_transport_failure_after_callback_is_delivery_uncertain() -> None:
    adapter = UpstreamMcpAdapter(_configuration())
    _mark_discovered(adapter)
    session = FakeSession(call_error=httpx.ReadTimeout("secret-partner-token"))
    _bind_session(adapter, session)

    async def before_dispatch() -> None:
        return None

    with pytest.raises(UpstreamMcpDeliveryUncertainError) as exc_info:
        await adapter.call_tool(
            {},
            invocation_id="inv",
            idempotency_key="idem",
            before_dispatch=before_dispatch,
        )
    assert exc_info.value.dispatch_started is True
    assert "secret-partner-token" not in str(exc_info.value)


@pytest.mark.anyio
async def test_valid_tool_error_is_typed_and_carries_canonical_result() -> None:
    result = CallToolResult(
        content=[TextContent(type="text", text="partner rejected request")],
        isError=True,
    )
    adapter = UpstreamMcpAdapter(_configuration())
    _mark_discovered(adapter)
    _bind_session(adapter, FakeSession(result=result))

    async def before_dispatch() -> None:
        return None

    with pytest.raises(UpstreamMcpReturnedError) as exc_info:
        await adapter.call_tool(
            {},
            invocation_id="inv",
            idempotency_key="idem",
            before_dispatch=before_dispatch,
        )
    assert exc_info.value.dispatch_started is True
    assert exc_info.value.result.is_error is True
    assert exc_info.value.result.payload["isError"] is True


@pytest.mark.parametrize(
    "result",
    [
        CallToolResult(
            content=[TextContent(type="text", text="secret-partner-token")],
            isError=False,
        ),
        CallToolResult(
            content=[TextContent(type="text", text="safe")],
            structuredContent={"nested": ["secret-partner-token"]},
            isError=False,
        ),
    ],
)
@pytest.mark.anyio
async def test_call_rejects_bearer_token_echo_without_returning_or_logging_it(
    result: CallToolResult,
    caplog,
) -> None:
    adapter = UpstreamMcpAdapter(_configuration())
    _mark_discovered(adapter)
    _bind_session(adapter, FakeSession(result=result))

    async def before_dispatch() -> None:
        return None

    with pytest.raises(UpstreamMcpResponseRejectedError) as exc_info:
        await adapter.call_tool(
            {},
            invocation_id="inv",
            idempotency_key="idem",
            before_dispatch=before_dispatch,
        )

    assert exc_info.value.code == "upstream_response_rejected"
    assert "secret-partner-token" not in str(exc_info.value)
    assert "secret-partner-token" not in repr(exc_info.value)
    assert "secret-partner-token" not in caplog.text


@pytest.mark.anyio
async def test_oversized_or_invalid_response_is_rejected_after_dispatch() -> None:
    oversized = CallToolResult(
        content=[TextContent(type="text", text="x" * 200)],
        isError=False,
    )
    adapter = UpstreamMcpAdapter(_configuration(MCP_UPSTREAM_MAX_RESPONSE_BYTES=80))
    _mark_discovered(adapter)
    _bind_session(adapter, FakeSession(result=oversized))

    async def before_dispatch() -> None:
        return None

    with pytest.raises(UpstreamMcpResponseRejectedError) as oversized_error:
        await adapter.call_tool(
            {},
            invocation_id="inv",
            idempotency_key="idem",
            before_dispatch=before_dispatch,
        )
    assert oversized_error.value.code == "upstream_response_too_large"
    assert oversized_error.value.dispatch_started is True

    adapter = UpstreamMcpAdapter(_configuration())
    _mark_discovered(adapter)
    _bind_session(adapter, FakeSession(result={"not": "an MCP result"}))
    with pytest.raises(UpstreamMcpResponseRejectedError) as invalid_error:
        await adapter.call_tool(
            {},
            invocation_id="inv",
            idempotency_key="idem",
            before_dispatch=before_dispatch,
        )
    assert invalid_error.value.code == "upstream_response_invalid"


@pytest.mark.anyio
async def test_cleanup_failure_does_not_replace_confirmed_response() -> None:
    adapter = UpstreamMcpAdapter(_configuration())
    _mark_discovered(adapter)
    _bind_session(
        adapter,
        FakeSession(),
        cleanup_error=RuntimeError("secret-partner-token"),
    )

    async def before_dispatch() -> None:
        return None

    target = logging.getLogger("app.services.upstream_mcp")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    prior_level = target.level
    prior_disabled = target.disabled
    target.addHandler(handler)
    target.setLevel(logging.WARNING)
    target.disabled = False
    try:
        result = await adapter.call_tool(
            {},
            invocation_id="inv",
            idempotency_key="idem",
            before_dispatch=before_dispatch,
        )
    finally:
        target.removeHandler(handler)
        target.setLevel(prior_level)
        target.disabled = prior_disabled
    assert result.is_error is False
    rendered = "\n".join(record.getMessage() for record in records)
    assert "upstream_mcp_session_cleanup_failed" in rendered
    assert "secret-partner-token" not in rendered


@pytest.mark.anyio
async def test_real_streamable_http_lifecycle_forwards_auth_and_request_metadata() -> (
    None
):
    received: dict[str, Any] = {}
    server = FastMCP(
        "partner-test",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=["localhost:9000"],
        ),
    )

    @server.tool(name="partner.write", description="Untrusted partner description")
    async def partner_write(note: str, ctx: Context) -> dict[str, str]:
        meta = ctx.request_context.meta
        received["meta"] = (
            meta.model_dump(mode="json", by_alias=True, exclude_none=True)
            if meta is not None
            else {}
        )
        return {"echo": note}

    mcp_app = server.streamable_http_app()

    class CaptureHttpSemantics:
        def __init__(self, app: Any) -> None:
            self.app = app
            self.authorization_headers: list[str | None] = []
            self.status_codes: list[int] = []

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            headers = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in scope["headers"]
            }
            self.authorization_headers.append(headers.get("authorization"))

            async def capture_send(message: Any) -> None:
                if message["type"] == "http.response.start":
                    self.status_codes.append(message["status"])
                await send(message)

            await self.app(scope, receive, capture_send)

    captured_app = CaptureHttpSemantics(mcp_app)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=captured_app),
        base_url="http://localhost",
        headers={"Authorization": "Bearer secret-partner-token"},
        follow_redirects=False,
    )
    adapter = UpstreamMcpAdapter(_configuration(), http_client=client)

    async def before_dispatch() -> None:
        received["dispatch_committed"] = True

    async with mcp_app.router.lifespan_context(mcp_app):
        discovered = await adapter.discover_tool()
        result = await adapter.call_tool(
            {"note": "hello over streamable HTTP"},
            invocation_id="inv-real-123",
            idempotency_key="idem-real-123",
            before_dispatch=before_dispatch,
        )
    await client.aclose()

    assert discovered.description == (
        "Governed remote MCP tool dispatched through the Agent Middleware trust plane."
    )
    assert result.is_error is False
    assert result.payload["structuredContent"] == {"echo": "hello over streamable HTTP"}
    assert received["dispatch_committed"] is True
    assert received["meta"] == {
        "io.agentmiddleware/idempotency_key": "idem-real-123",
        "io.agentmiddleware/invocation_id": "inv-real-123",
    }
    assert captured_app.authorization_headers
    assert set(captured_app.authorization_headers) == {"Bearer secret-partner-token"}
    assert client.follow_redirects is False
    assert not any(300 <= status < 400 for status in captured_app.status_codes)


def test_registry_distinguishes_local_upstream_and_metadata_only_services() -> None:
    registry = ServiceRegistry()

    def local_tool() -> None:
        return None

    registry.register_local(
        service_id="local-tool",
        name="Local tool",
        description="Local",
        category=ServiceCategory.PLATFORM_FEE,
        func=local_tool,
    )
    executor = object()
    upstream = registry.register_upstream(
        service_id="partner.notes.write",
        name="partner.write",
        description="Partner write",
        category=ServiceCategory.PLATFORM_FEE,
        executor=executor,
        input_schema={"type": "object"},
        output_schema=None,
        credits_per_unit=7.5,
        upstream_tool_name="partner.write",
        upstream_origin="https://partner.example",
    )

    assert registry.get_local("local-tool")["execution_backend"] == "local"
    assert upstream["execution_backend"] == "upstream_mcp"
    assert upstream["is_executable"] is True
    assert upstream["external"] is True
    assert registry.get_executor("partner.notes.write") is executor


@pytest.mark.anyio
async def test_persistent_services_are_metadata_only_and_not_executable(
    clean_database,
) -> None:
    del clean_database
    registry = ServiceRegistry()
    async with get_session_factory()() as session:
        session.add(
            WalletModel(
                wallet_id="wallet-catalog",
                wallet_type="agent",
                owner_name="Catalog owner",
            )
        )
        await session.commit()
    persistent = await registry.register_persistent(
        name="Catalog metadata",
        description="No runtime executor",
        category=ServiceCategory.PLATFORM_FEE,
        credits_per_unit=1,
        owner_wallet_id="wallet-catalog",
    )
    fetched = await registry.get_persistent(persistent["service_id"])
    executable = await registry.list_executable()

    assert fetched is not None
    assert fetched["execution_backend"] == "metadata_only"
    assert fetched["is_executable"] is False
    assert all(item["service_id"] != persistent["service_id"] for item in executable)


@pytest.mark.anyio
async def test_startup_helper_registers_cached_upstream_executor(monkeypatch) -> None:
    discovered = DiscoveredUpstreamTool(
        name="partner.write",
        description="Partner write",
        input_schema={"type": "object"},
        output_schema=None,
    )

    async def fake_discover(self: UpstreamMcpAdapter) -> DiscoveredUpstreamTool:
        self._discovered_tool = discovered
        return discovered

    monkeypatch.setattr(UpstreamMcpAdapter, "discover_tool", fake_discover)
    registry = ServiceRegistry()
    registered = await register_configured_upstream_mcp(
        settings=_settings(),
        registry=registry,
    )

    assert registered is not None
    assert registered["service_id"] == "partner.notes.write"
    assert registered["execution_backend"] == "upstream_mcp"
    assert isinstance(
        registry.get_executor("partner.notes.write"),
        UpstreamMcpAdapter,
    )


@pytest.mark.anyio
async def test_disabled_startup_helper_unregisters_previous_upstream() -> None:
    registry = ServiceRegistry()
    registry.register_upstream(
        service_id="partner.notes.write",
        name="partner.write",
        description="Partner write",
        category=ServiceCategory.PLATFORM_FEE,
        executor=object(),
        input_schema={"type": "object"},
        output_schema=None,
        credits_per_unit=7.5,
        upstream_tool_name="partner.write",
        upstream_origin="https://partner.example",
    )
    result = await register_configured_upstream_mcp(
        settings=_settings(MCP_UPSTREAM_ENABLED=False),
        registry=registry,
    )
    assert result is None
    assert registry.get_local("partner.notes.write") is None
