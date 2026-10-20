"""Optional OpenTelemetry spans for the governed MCP path."""

from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from mcp.types import CallToolResult
from pydantic import SecretStr

from app.core.config import get_settings
from app.core.tracing import (
    inject_w3c_traceparent,
    install_tracing,
    note,
    otlp_traces_endpoint,
    start_span,
    tracing_enabled,
)
from app.services.mcp_dispatch_attempts import (
    DispatchAttemptError,
    McpDispatchAttemptService,
)
from app.services.permits import PermitService
from app.services.upstream_mcp import (
    DiscoveredUpstreamTool,
    UpstreamMcpAdapter,
    UpstreamMcpConfiguration,
    _PinnedAsyncTransport,
    _ResponseGuardState,
)
from app.trust.adapters import GovernedRequest, McpGovernedAdapter

REPO_ROOT = Path(__file__).resolve().parents[1]
_EXPORTER = None
_SECRET = "super-secret-token"
_WALLET = "agt-aabbccddeeff"
_ARGUMENTS = {"note": "secret-body", "api_key": _SECRET}


def _exporter():
    global _EXPORTER
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    if _EXPORTER is None:
        _EXPORTER = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_EXPORTER))
        trace.set_tracer_provider(provider)
    _EXPORTER.clear()
    return _EXPORTER


@pytest.fixture
def otel_on(monkeypatch):
    monkeypatch.setenv("OTEL_TRACING_ENABLED", "true")
    get_settings.cache_clear()
    exporter = _exporter()
    yield exporter
    get_settings.cache_clear()


def _finished(exporter):
    return list(exporter.get_finished_spans())


def _ancestor_ids(span, by_id):
    found = []
    parent = span.parent
    seen: set[int] = set()
    while parent is not None and parent.span_id not in seen:
        seen.add(parent.span_id)
        found.append(parent.span_id)
        parent_span = by_id.get(parent.span_id)
        if parent_span is None:
            break
        parent = parent_span.parent
    return found


def _ancestor_names(span, by_id):
    return [
        by_id[span_id].name
        for span_id in _ancestor_ids(span, by_id)
        if span_id in by_id
    ]


def _by_name(spans):
    grouped: dict[str, list] = {}
    for span in spans:
        grouped.setdefault(span.name, []).append(span)
    return grouped


def _blob(span) -> str:
    parts = [span.name]
    attributes = span.attributes or {}
    parts.extend(f"{key}={value}" for key, value in attributes.items())
    for event in span.events:
        parts.append(event.name)
        parts.extend(
            f"{key}={value}" for key, value in (event.attributes or {}).items()
        )
    return "\n".join(parts)


def test_runtime_requirements_omit_otel() -> None:
    assert "opentelemetry" not in (REPO_ROOT / "requirements.txt").read_text()


def test_tracing_module_does_not_import_otel_at_import_time() -> None:
    tree = ast.parse((REPO_ROOT / "app/core/tracing.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        else:
            continue
        assert all(not name.startswith("opentelemetry") for name in names)


def test_defaults_leave_existing_guards_alone(monkeypatch) -> None:
    for name in (
        "OTEL_TRACING_ENABLED",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_SERVICE_NAME",
        "RETRY_LOOP_ALERT_ENABLED",
        "WALLET_REPLAN_GUARD",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.OTEL_TRACING_ENABLED is False
    assert settings.OTEL_EXPORTER_OTLP_ENDPOINT == ""
    assert settings.OTEL_SERVICE_NAME == "agent-middleware-api"
    assert settings.RETRY_LOOP_ALERT_ENABLED is False
    assert settings.WALLET_REPLAN_GUARD.value == "log_only"
    get_settings.cache_clear()


def test_import_without_otel_packages() -> None:
    code = """
import builtins
real = builtins.__import__

def blocked(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "opentelemetry" or name.startswith("opentelemetry."):
        raise ModuleNotFoundError(name)
    return real(name, globals, locals, fromlist, level)

builtins.__import__ = blocked
from app.core.tracing import otel_packages_available, tracing_enabled
assert otel_packages_available() is False
assert tracing_enabled() is False
"""
    env = os.environ.copy()
    env["OTEL_TRACING_ENABLED"] = "true"
    env["PYTHONPATH"] = str(REPO_ROOT)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_otlp_endpoint_appends_traces_path() -> None:
    assert otlp_traces_endpoint("") is None
    assert (
        otlp_traces_endpoint("http://collector.example:4318")
        == "http://collector.example:4318/v1/traces"
    )
    assert (
        otlp_traces_endpoint("http://collector.example:4318/v1/traces")
        == "http://collector.example:4318/v1/traces"
    )


def test_disabled_emits_nothing_and_adds_no_middleware(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_TRACING_ENABLED", raising=False)
    get_settings.cache_clear()
    exporter = _exporter()
    app = FastAPI()
    before = list(app.user_middleware)
    install_tracing(app)
    assert app.user_middleware == before
    assert tracing_enabled() is False

    class Carrier(dict):
        pass

    carrier = Carrier()

    async def exercise() -> None:
        async with start_span(
            "mcp.invoke",
            tool_name="partner.notes.write",
            wallet_id=_WALLET,
            attempt_id="dsp-0123456789abcdef",
        ):
            inject_w3c_traceparent(carrier)

    import asyncio

    asyncio.run(exercise())
    assert carrier == {}
    assert _finished(exporter) == []
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_spans_nest_and_drop_secrets(otel_on, monkeypatch) -> None:
    exporter = otel_on
    captured: dict[str, str] = {}

    class StubTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured["traceparent"] = request.headers.get("traceparent", "")
            captured["authorization"] = request.headers.get("authorization", "")
            return httpx.Response(204)

    configuration = UpstreamMcpConfiguration(
        url="https://partner.example/mcp",
        origin="https://partner.example",
        tool_name="notes.write",
        public_tool_id="partner.notes.write",
        bearer_token=SecretStr(_SECRET),
        credits_per_call=Decimal("1"),
        connect_timeout_seconds=1.0,
        call_timeout_seconds=1.0,
        max_response_bytes=4096,
        environment="local",
    )
    transport = _PinnedAsyncTransport(
        configuration,
        pinned_address="93.184.216.34",
        response_guard=_ResponseGuardState(),
        transport=StubTransport(),
    )
    adapter = UpstreamMcpAdapter(configuration)
    adapter._discovered_tool = DiscoveredUpstreamTool(
        name="notes.write",
        description="notes",
        input_schema={"type": "object"},
        output_schema=None,
    )

    @asynccontextmanager
    async def fake_session(**kwargs):
        del kwargs

        class Session:
            async def call_tool(
                self, name, arguments, read_timeout_seconds=None, meta=None
            ):
                del name, read_timeout_seconds, meta
                assert arguments == _ARGUMENTS
                upstream = httpx.Request(
                    "POST",
                    "https://partner.example/mcp",
                    headers={
                        "Host": "partner.example",
                        "Authorization": f"Bearer {_SECRET}",
                    },
                )
                await transport.handle_async_request(upstream)
                return CallToolResult(content=[], isError=False)

        yield Session()

    async def noop_init(self, session, *, response_guard):
        del self, session, response_guard

    monkeypatch.setattr(adapter, "_session", fake_session)
    monkeypatch.setattr(UpstreamMcpAdapter, "_initialize_session", noop_init)

    def stop_reserve():
        raise RuntimeError("stop-reserve")

    monkeypatch.setattr("app.services.permits.get_session_factory", stop_reserve)
    monkeypatch.setattr(
        "app.services.mcp_dispatch_attempts.schedule_attempt",
        lambda **kwargs: None,
    )

    async def fake_claim(self, attempt_id):
        del self
        return SimpleNamespace(
            attempt_id=attempt_id,
            public_tool_id="partner.notes.write",
            wallet_id=_WALLET,
            idempotency_record_id="rec-1",
            state="dispatch_claimed",
        )

    monkeypatch.setattr(McpDispatchAttemptService, "_claim_dispatch", fake_claim)

    async def fake_create(**kwargs):
        assert kwargs["request_payload"]["arguments"] == _ARGUMENTS
        return SimpleNamespace(model_dump=lambda mode: {"credits_charged": "0"})

    monkeypatch.setattr(
        "app.routers.mcp.get_receipt_service",
        lambda: SimpleNamespace(create_receipt=fake_create),
    )

    async def fake_execute(**kwargs):
        assert kwargs["arguments"] == _ARGUMENTS
        permits = PermitService()
        with pytest.raises(RuntimeError, match="stop-reserve"):
            await permits.authorize_and_reserve(
                permit_id="permit-1",
                wallet_id=_WALLET,
                tool_name="partner.notes.write",
                estimated_credits=Decimal("1"),
            )
        dispatch = McpDispatchAttemptService()
        with pytest.raises(DispatchAttemptError, match="dispatch_prepare_invalid"):
            await dispatch.authorize_reserve_and_prepare(
                idempotency_record_id="",
                wallet_id=_WALLET,
                permit_id="permit-1",
                key_id=None,
                public_tool_id="partner.notes.write",
                upstream_tool_name="notes.write",
                upstream_origin="https://partner.example",
                request_hash="a" * 64,
                credits_authorized=Decimal("1"),
                arguments=_ARGUMENTS,
            )
        await dispatch.claim_dispatch("dsp-0123456789abcdef")
        await adapter._call_tool_once(
            _ARGUMENTS,
            invocation_id="inv-1",
            idempotency_key="idem-1",
            before_dispatch=_async_noop,
        )
        from app.routers.mcp import _traced_mcp_receipt

        await _traced_mcp_receipt(
            permit_id="permit-1",
            wallet_id=_WALLET,
            key_id=None,
            tool="partner.notes.write",
            request_payload={"arguments": _ARGUMENTS, "api_key": _SECRET},
            response_payload={"content": [], "isError": False},
            ledger_entry_id=None,
            credits_authorized=Decimal("1"),
            credits_charged=Decimal("0"),
            outcome="success",
            dispatch_attempt_id="dsp-0123456789abcdef",
        )
        return {
            "isError": False,
            "receipt": {"outcome": "success", "ledger_entry_id": None},
        }

    monkeypatch.setattr("app.routers.mcp._execute_registered_tool", fake_execute)

    app = FastAPI()
    install_tracing(app)

    @app.post("/invoke")
    async def invoke() -> dict[str, bool]:
        result = await McpGovernedAdapter().invoke(
            GovernedRequest(
                protocol="mcp",
                tool_name="partner.notes.write",
                arguments=_ARGUMENTS,
                wallet_id=_WALLET,
                auth=object(),
                money=object(),
            )
        )
        return {"ok": result.outcome == "success"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/invoke")
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    finished = _finished(exporter)
    spans = _by_name(finished)
    by_id = {span.context.span_id: span for span in finished}
    http_span = spans["http.request"][0]
    invoke_span = spans["mcp.invoke"][0]
    assert "http.request" in _ancestor_names(invoke_span, by_id)
    assert http_span.context.span_id in _ancestor_ids(invoke_span, by_id)
    for name in (
        "mcp.reserve",
        "mcp.dispatch_claim",
        "mcp.upstream_dispatch",
        "mcp.receipt",
    ):
        assert spans[name], name
        for child in spans[name]:
            assert child.parent is not None
            assert child.parent.span_id == invoke_span.context.span_id
    assert len(spans["mcp.reserve"]) == 2

    assert captured["authorization"] == f"Bearer {_SECRET}"
    assert captured["traceparent"].startswith("00-")
    trace_id = format(invoke_span.context.trace_id, "032x")
    assert trace_id in captured["traceparent"]

    allowed = {"tool.name", "outcome.state", "wallet.id_hash", "attempt.id"}
    ours = {
        "http.request",
        "mcp.invoke",
        "mcp.reserve",
        "mcp.dispatch_claim",
        "mcp.upstream_dispatch",
        "mcp.receipt",
    }
    wallet_hash = hashlib.sha256(_WALLET.encode("utf-8")).hexdigest()
    for span in finished:
        blob = _blob(span)
        assert _SECRET not in blob
        assert "secret-body" not in blob
        assert _WALLET not in blob
        if span.name not in ours:
            continue
        attributes = dict(span.attributes or {})
        assert set(attributes).issubset(allowed)
        assert "api_key" not in attributes
        if "wallet.id_hash" in attributes:
            assert attributes["wallet.id_hash"] == wallet_hash


@pytest.mark.asyncio
async def test_secret_attribute_writes_are_dropped(otel_on) -> None:
    exporter = otel_on
    async with start_span("mcp.invoke", tool_name="partner.notes.write") as span:
        span.set_attribute("api_key", _SECRET)
        span.set_attribute("arguments", str(_ARGUMENTS))
        span.set_attribute("tool.name", f"Bearer {_SECRET}")
        span.set_attribute("wallet.id_hash", _WALLET)
        note(span, wallet_id=_WALLET, attempt_id="dsp-0123456789abcdef")
    spans = _finished(exporter)
    assert len(spans) == 1
    attributes = dict(spans[0].attributes or {})
    assert attributes == {
        "tool.name": "partner.notes.write",
        "wallet.id_hash": hashlib.sha256(_WALLET.encode("utf-8")).hexdigest(),
        "attempt.id": "dsp-0123456789abcdef",
    }
    assert _SECRET not in _blob(spans[0])


@pytest.mark.asyncio
async def test_header_injection_skipped_when_client_refuses(otel_on) -> None:
    class Locked:
        def __setitem__(self, key, value):
            raise TypeError("client does not support header injection")

    carrier = Locked()
    async with start_span("mcp.upstream_dispatch", tool_name="partner.notes.write"):
        inject_w3c_traceparent(carrier)
    mutable: dict[str, str] = {}
    inject_w3c_traceparent(mutable)
    assert mutable == {}


async def _async_noop() -> None:
    return None
