"""Optional OpenTelemetry spans for the governed MCP path."""

from __future__ import annotations

import ast
import hashlib
import logging
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

import app.core.tracing as tracing_module
from app.core.config import get_settings
from app.core.tracing import (
    TracingMiddleware,
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
from app.services.permits import PermitService, PermitValidation
from app.services.upstream_mcp import (
    DiscoveredUpstreamTool,
    UpstreamMcpAdapter,
    UpstreamMcpConfiguration,
    UpstreamMcpDeliveryUncertainError,
    UpstreamMcpPreDispatchError,
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


def test_broken_otel_import_type_error_fail_open() -> None:
    """A protobuf-style TypeError during import must not abort startup."""
    code = """
import builtins
import logging
from fastapi import FastAPI

real = builtins.__import__

def broken(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "opentelemetry" or name.startswith("opentelemetry."):
        raise TypeError("Descriptors cannot be created directly")
    return real(name, globals, locals, fromlist, level)

builtins.__import__ = broken
logging.basicConfig()
from app.core.tracing import (
    install_tracing,
    otel_packages_available,
    start_span,
    tracing_enabled,
)

assert otel_packages_available() is False
assert tracing_enabled() is False
app = FastAPI()
before = list(app.user_middleware)
install_tracing(app)
assert app.user_middleware == before

import asyncio

runs = {"n": 0}

async def exercise():
    async with start_span("mcp.invoke", tool_name="partner.notes.write"):
        runs["n"] += 1
        return "ok"

assert asyncio.run(exercise()) == "ok"
assert runs["n"] == 1
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


def test_install_tracing_warns_when_packages_unavailable(monkeypatch, caplog) -> None:
    monkeypatch.setenv("OTEL_TRACING_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(tracing_module, "otel_packages_available", lambda: False)
    app = FastAPI()
    before = list(app.user_middleware)
    with caplog.at_level(logging.WARNING, logger="app.core.tracing"):
        install_tracing(app)
    assert app.user_middleware == before
    assert any(record.msg == "otel_tracing_install_failed" for record in caplog.records)
    get_settings.cache_clear()


def test_install_tracing_fail_open_when_enabled_check_raises(
    monkeypatch, caplog
) -> None:
    monkeypatch.setenv("OTEL_TRACING_ENABLED", "true")
    get_settings.cache_clear()

    def boom() -> bool:
        raise TypeError("broken otel import")

    monkeypatch.setattr(tracing_module, "otel_packages_available", boom)
    app = FastAPI()
    before = list(app.user_middleware)
    with caplog.at_level(logging.WARNING, logger="app.core.tracing"):
        install_tracing(app)
    assert app.user_middleware == before
    assert any(record.msg == "otel_tracing_install_failed" for record in caplog.records)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_start_span_runs_body_once_when_enabled_check_raises(
    monkeypatch, caplog
) -> None:
    monkeypatch.setenv("OTEL_TRACING_ENABLED", "true")
    get_settings.cache_clear()

    def boom() -> bool:
        raise TypeError("broken otel import")

    monkeypatch.setattr(tracing_module, "tracing_enabled", boom)
    body_runs = {"n": 0}
    with caplog.at_level(logging.WARNING, logger="app.core.tracing"):
        async with start_span("mcp.invoke", tool_name="partner.notes.write"):
            body_runs["n"] += 1
    assert body_runs["n"] == 1
    assert any(record.msg == "otel_tracing_unavailable" for record in caplog.records)
    get_settings.cache_clear()


def test_fail_open_span_enter_exit_preserve_body_result(caplog) -> None:
    """Processor-style enter/exit failures must not alter the governed result."""
    tracing_module._tracing_failure_logged = False
    caplog.set_level(logging.DEBUG, logger="app.core.tracing")

    class BoomCM:
        def __enter__(self):
            raise RuntimeError("otel-enter")

        def __exit__(self, exc_type, exc, tb):
            raise RuntimeError("otel-exit")

    body_runs = {"n": 0}
    with tracing_module._FailOpenSpan(BoomCM) as span:
        body_runs["n"] += 1
        assert span is tracing_module._NOOP
        result = "governed-ok"
    assert body_runs["n"] == 1
    assert result == "governed-ok"

    class EnterOkExitBoom:
        def __enter__(self):
            return SimpleNamespace(set_attribute=lambda *a, **k: None)

        def __exit__(self, exc_type, exc, tb):
            raise RuntimeError("otel-exit")

    with pytest.raises(_BodyError, match="^governed-body$") as raised:
        with tracing_module._FailOpenSpan(EnterOkExitBoom):
            body_runs["n"] += 1
            raise _BodyError("governed-body")
    assert body_runs["n"] == 2
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert len(_tracing_failure_logs(caplog)) == 1


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


class _BodyError(RuntimeError):
    """Exception raised by governed code, not by the tracer."""


class _RaisingSpanProcessor:
    """Span processor whose start and end hooks both raise."""

    def __init__(self) -> None:
        self.starts = 0
        self.ends = 0
        self.enabled = True
        self.raise_on_start = True
        self.raise_on_end = True

    def on_start(self, span: object, parent_context: object = None) -> None:
        del span, parent_context
        if not self.enabled:
            return
        self.starts += 1
        if self.raise_on_start:
            raise RuntimeError("otel-on-start")

    def on_end(self, span: object) -> None:
        del span
        if not self.enabled:
            return
        self.ends += 1
        if self.raise_on_end:
            raise RuntimeError("otel-on-end")

    def _on_ending(self, span: object) -> None:
        del span

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        del timeout_millis
        return True


def _tracing_failure_logs(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == "app.core.tracing" and record.msg == "otel_tracing_failure"
    ]


@pytest.mark.asyncio
async def test_span_processor_failures_do_not_affect_governed_calls(
    otel_on, monkeypatch, caplog
) -> None:
    """Reserve, dispatch, and receipt finish when span hooks raise.

    ``on_start`` runs during context entry, after ``dispatch_started`` is set
    and before the upstream send. A raising processor must not skip that send
    or mark it ``delivery_uncertain``. ``on_end`` must not replace the body's
    exception or the successful result.
    """
    del otel_on
    from opentelemetry import trace

    processor = _RaisingSpanProcessor()
    trace.get_tracer_provider().add_span_processor(processor)  # type: ignore[arg-type]
    tracing_module._tracing_failure_logged = False
    caplog.set_level(logging.DEBUG, logger="app.core.tracing")
    try:
        reserved = {"n": 0}
        claimed = {"n": 0}
        created = {"n": 0}
        sent = {"n": 0}

        async def fake_retry(self, operation):
            del self, operation
            reserved["n"] += 1
            return PermitValidation(True, None, None)

        monkeypatch.setattr(PermitService, "_run_with_write_retry", fake_retry)
        monkeypatch.setattr(
            "app.services.permits.get_session_factory", lambda: object()
        )

        async def fake_claim(self, attempt_id):
            del self
            claimed["n"] += 1
            assert attempt_id == "dsp-0123456789abcdef"
            return SimpleNamespace(
                attempt_id=attempt_id,
                public_tool_id="partner.notes.write",
                wallet_id=_WALLET,
                idempotency_record_id="rec-1",
                state="dispatch_claimed",
            )

        monkeypatch.setattr(McpDispatchAttemptService, "_claim_dispatch", fake_claim)
        monkeypatch.setattr(
            "app.services.mcp_dispatch_attempts.schedule_attempt",
            lambda **kwargs: None,
        )

        async def fake_create(**kwargs):
            created["n"] += 1
            assert kwargs["outcome"] == "success"
            assert kwargs["tool"] == "partner.notes.write"
            return SimpleNamespace(outcome="success", tool="partner.notes.write")

        monkeypatch.setattr(
            "app.routers.mcp.get_receipt_service",
            lambda: SimpleNamespace(create_receipt=fake_create),
        )

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
                    sent["n"] += 1
                    assert arguments == _ARGUMENTS
                    return CallToolResult(content=[], isError=False)

            yield Session()

        async def noop_init(self, session, *, response_guard):
            del self, session, response_guard

        monkeypatch.setattr(adapter, "_session", fake_session)
        monkeypatch.setattr(UpstreamMcpAdapter, "_initialize_session", noop_init)

        validation = await PermitService().authorize_and_reserve(
            permit_id="permit-1",
            wallet_id=_WALLET,
            tool_name="partner.notes.write",
            estimated_credits=Decimal("1"),
        )
        assert validation.allowed is True
        assert validation.reason is None
        assert reserved["n"] == 1

        attempt = await McpDispatchAttemptService().claim_dispatch(
            "dsp-0123456789abcdef"
        )
        assert attempt.state == "dispatch_claimed"
        assert attempt.attempt_id == "dsp-0123456789abcdef"
        assert claimed["n"] == 1

        result = await adapter._call_tool_once(
            _ARGUMENTS,
            invocation_id="inv-1",
            idempotency_key="idem-1",
            before_dispatch=_async_noop,
        )
        assert result.is_error is False
        assert sent["n"] == 1

        async def never_sent() -> None:
            raise RuntimeError("checkpoint")

        with pytest.raises(
            UpstreamMcpPreDispatchError,
            match="^upstream_dispatch_checkpoint_failed$",
        ) as pre_dispatch:
            await adapter._call_tool_once(
                _ARGUMENTS,
                invocation_id="inv-2",
                idempotency_key="idem-2",
                before_dispatch=never_sent,
            )
        assert sent["n"] == 1
        assert not isinstance(pre_dispatch.value, UpstreamMcpDeliveryUncertainError)

        from app.routers.mcp import _traced_mcp_receipt

        receipt = await _traced_mcp_receipt(
            permit_id="permit-1",
            wallet_id=_WALLET,
            key_id=None,
            tool="partner.notes.write",
            request_payload={"arguments": _ARGUMENTS},
            response_payload={"content": [], "isError": False},
            ledger_entry_id=None,
            credits_authorized=Decimal("1"),
            credits_charged=Decimal("0"),
            outcome="success",
            dispatch_attempt_id="dsp-0123456789abcdef",
        )
        assert receipt.outcome == "success"
        assert receipt.tool == "partner.notes.write"
        assert created["n"] == 1
        assert processor.starts == 4
        assert processor.ends == 0

        body_runs = {"n": 0}

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            del message

        async def ok_app(scope, receive_fn, send_fn):
            del scope, receive_fn
            body_runs["n"] += 1
            await send_fn({"type": "http.response.start", "status": 200, "headers": []})
            await send_fn({"type": "http.response.body", "body": b"ok"})

        await TracingMiddleware(ok_app)({"type": "http"}, receive, send)
        assert body_runs["n"] == 1
        assert len(_tracing_failure_logs(caplog)) == 1
        assert _tracing_failure_logs(caplog)[0].levelno == logging.DEBUG

        processor.raise_on_start = False
        ends_before_exit_failures = processor.ends
        caplog.clear()
        tracing_module._tracing_failure_logged = False

        async with start_span("mcp.invoke", tool_name="partner.notes.write") as span:
            body_runs["n"] += 1

            def boom_attribute(key, value):
                del key, value
                raise RuntimeError("attr-write")

            span._span.set_attribute = boom_attribute
            span.set_attribute("tool.name", "partner.notes.write")
            note(span, outcome_state="success")
        assert body_runs["n"] == 2

        class Locked:
            def __setitem__(self, key, value):
                del key, value
                raise TypeError("client does not support header injection")

        async with start_span("mcp.upstream_dispatch", tool_name="partner.notes.write"):
            inject_w3c_traceparent(Locked())

        with pytest.raises(_BodyError, match="^governed-body$") as body_error:
            async with start_span("mcp.receipt", tool_name="partner.notes.write"):
                body_runs["n"] += 1
                raise _BodyError("governed-body")
        assert body_runs["n"] == 3
        assert body_error.value.__cause__ is None
        assert body_error.value.__context__ is None

        async def failing_app(scope, receive_fn, send_fn):
            del scope, receive_fn, send_fn
            body_runs["n"] += 1
            raise _BodyError("governed-body")

        with pytest.raises(_BodyError, match="^governed-body$") as middleware_error:
            await TracingMiddleware(failing_app)({"type": "http"}, receive, send)
        assert body_runs["n"] == 4
        assert middleware_error.value.__cause__ is None
        assert middleware_error.value.__context__ is None

        ended = await adapter._call_tool_once(
            _ARGUMENTS,
            invocation_id="inv-3",
            idempotency_key="idem-3",
            before_dispatch=_async_noop,
        )
        assert ended.is_error is False
        assert sent["n"] == 2
        receipt_again = await _traced_mcp_receipt(
            permit_id="permit-1",
            wallet_id=_WALLET,
            key_id=None,
            tool="partner.notes.write",
            request_payload={"arguments": _ARGUMENTS},
            response_payload={"content": [], "isError": False},
            ledger_entry_id=None,
            credits_authorized=Decimal("1"),
            credits_charged=Decimal("0"),
            outcome="success",
            dispatch_attempt_id="dsp-0123456789abcdef",
        )
        assert receipt_again.outcome == "success"
        assert created["n"] == 2
        assert reserved["n"] == 1
        assert claimed["n"] == 1
        assert processor.starts == 11
        assert processor.ends == ends_before_exit_failures + 6
        assert len(_tracing_failure_logs(caplog)) == 1
        caplog.clear()
        async with start_span("mcp.invoke", tool_name="partner.notes.write"):
            body_runs["n"] += 1
        assert body_runs["n"] == 5
        assert _tracing_failure_logs(caplog) == []
    finally:
        processor.enabled = False
