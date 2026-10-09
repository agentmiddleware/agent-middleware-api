"""Unit tests for app.services.mcp_phase9_tools (pure, no network or DB)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.core.config import get_settings
from app.services import mcp_phase9_tools
from app.services.mcp_phase9_tools import (
    ALWAYS_GOVERNED_AWI_TOOLS,
    DEFAULT_MCP_STUB_SERVICE_IDS,
    MCP_PHASE9_TOOLS,
    PROOF_SURFACE_MCP_STUB_IDS,
    _make_default_service_handler,
    ensure_phase9_registered,
    register_default_mcp_services,
    register_phase9_tools,
    sync_proof_surface_mcp_registration,
    unregister_proof_surface_mcp_stubs,
)
from app.services.service_registry import get_service_registry


@pytest.fixture
def isolated_registry(monkeypatch):
    """Snapshot the global registry and module flags, restore after the test."""
    registry = get_service_registry()
    saved_local = dict(registry._local_registry)
    saved_func = dict(registry._func_registry)
    saved_exec = dict(registry._executor_registry)
    saved_registered = mcp_phase9_tools._registered
    saved_defaults = mcp_phase9_tools._default_services_registered
    mcp_phase9_tools._registered = False
    mcp_phase9_tools._default_services_registered = False
    try:
        yield registry
    finally:
        registry._local_registry.clear()
        registry._local_registry.update(saved_local)
        registry._func_registry.clear()
        registry._func_registry.update(saved_func)
        registry._executor_registry.clear()
        registry._executor_registry.update(saved_exec)
        mcp_phase9_tools._registered = saved_registered
        mcp_phase9_tools._default_services_registered = saved_defaults


def _flag(monkeypatch, value: bool):
    monkeypatch.setattr(get_settings(), "ENABLE_PROOF_SURFACES", value)


def test_phase9_tool_table_is_always_governed():
    assert len(MCP_PHASE9_TOOLS) == 9
    assert {t["service_id"] for t in MCP_PHASE9_TOOLS} == set(ALWAYS_GOVERNED_AWI_TOOLS)
    for tool in MCP_PHASE9_TOOLS:
        assert tool["require_permit"] is True
        assert callable(tool["func"])
        assert isinstance(tool["input_model"], type)
        assert issubclass(tool["input_model"], BaseModel)


def test_proof_surface_stub_ids_cover_phase9_and_defaults():
    assert PROOF_SURFACE_MCP_STUB_IDS == (
        ALWAYS_GOVERNED_AWI_TOOLS | DEFAULT_MCP_STUB_SERVICE_IDS
    )
    assert len(DEFAULT_MCP_STUB_SERVICE_IDS) == 4


async def test_wrapper_tools_point_at_wallet_scoped_http_routes():
    cases = [
        (mcp_phase9_tools.awi_passkey_verify, ("x", {}), "/v1/awi/passkey/verify"),
        (
            mcp_phase9_tools.awi_dom_bridge_session,
            ("https://example.com",),
            "/v1/awi/dom/session",
        ),
        (
            mcp_phase9_tools.awi_dom_sync,
            ("s1", "click"),
            "/v1/awi/dom/sync",
        ),
        (mcp_phase9_tools.awi_dom_state, ("s1",), "/v1/awi/dom/state"),
        (
            mcp_phase9_tools.awi_dom_action_preview,
            ("s1", "click"),
            "/v1/awi/dom/preview",
        ),
        (
            mcp_phase9_tools.awi_memory_index,
            ("s1", "shopping"),
            "/v1/awi/rag/index",
        ),
        (mcp_phase9_tools.awi_rag_query, ("laptops",), "/v1/awi/rag/query"),
        (
            mcp_phase9_tools.awi_session_context,
            ("s1",),
            "/v1/awi/rag/context",
        ),
    ]
    for func, args, endpoint in cases:
        result = await func(*args)
        assert result["endpoint"] == endpoint
        assert result["method"] in ("GET", "POST")
        assert isinstance(result["requires"], list) and result["requires"]


async def test_wrappers_ignore_extra_kwargs_and_rag_query_returns_no_memories():
    result = await mcp_phase9_tools.awi_rag_query(
        "victim-widget", top_k=5, unexpected="ignored"
    )
    assert result["endpoint"] == "/v1/awi/rag/query"
    assert "memories" not in result
    assert "victim-widget" not in str(result)

    state = await mcp_phase9_tools.awi_dom_state(
        "s1", representation_type="summary", unexpected="ignored"
    )
    assert state["endpoint"] == "/v1/awi/dom/state"


async def test_passkey_challenge_delegates_to_provider(monkeypatch):
    class FakeProvider:
        async def create_challenge(self, session_id, action):
            return {
                "challenge_id": "ch-1",
                "session_id": session_id,
                "action": action,
            }

    monkeypatch.setattr(
        "app.services.webauthn_provider.get_webauthn_provider",
        lambda: FakeProvider(),
    )
    result = await mcp_phase9_tools.awi_passkey_challenge("sess-1", "checkout")
    assert result["status"] == "ok"
    assert result["governed"] is True
    assert result["tool"] == "awi_passkey_challenge"
    assert result["challenge_id"] == "ch-1"
    assert result["session_id"] == "sess-1"


async def test_passkey_challenge_propagates_provider_error(monkeypatch):
    class FailingProvider:
        async def create_challenge(self, session_id, action):
            raise RuntimeError("provider down")

    monkeypatch.setattr(
        "app.services.webauthn_provider.get_webauthn_provider",
        lambda: FailingProvider(),
    )
    with pytest.raises(RuntimeError, match="provider down"):
        await mcp_phase9_tools.awi_passkey_challenge("sess-1", "checkout")


async def test_default_service_handler_is_deterministic_preview():
    service_def = {
        "service_id": "data-indexer",
        "name": "Data Indexer",
        "category": mcp_phase9_tools.MCP_PHASE9_TOOLS[0]["category"],
        "unit_name": "document",
    }
    handler = _make_default_service_handler(service_def)
    first = await handler(alpha=1, beta=2)
    second = await handler(beta=2, alpha=1)
    assert first == second
    assert first["status"] == "preview_available"
    assert first["service_id"] == "data-indexer"
    assert first["input_keys"] == ["alpha", "beta"]
    assert (await handler())["input_keys"] == []


def test_register_phase9_tools_registers_all_governed(isolated_registry):
    register_phase9_tools()
    for tool in MCP_PHASE9_TOOLS:
        record = isolated_registry.get_local(tool["service_id"])
        assert record is not None
        assert record["require_permit"] is True


def test_ensure_registered_noop_when_flag_off(monkeypatch, isolated_registry):
    _flag(monkeypatch, False)
    ensure_phase9_registered()
    assert mcp_phase9_tools._registered is False
    assert isolated_registry.get_local("awi_rag_query") is None


def test_ensure_registered_registers_once_when_on(monkeypatch, isolated_registry):
    _flag(monkeypatch, True)
    ensure_phase9_registered()
    ensure_phase9_registered()
    assert mcp_phase9_tools._registered is True
    assert isolated_registry.get_local("awi_rag_query") is not None


def test_register_default_services_gated_by_flag(monkeypatch, isolated_registry):
    _flag(monkeypatch, False)
    register_default_mcp_services()
    assert isolated_registry.get_local("data-indexer") is None

    _flag(monkeypatch, True)
    register_default_mcp_services()
    register_default_mcp_services()
    assert isolated_registry.get_local("data-indexer") is not None


def test_sync_registration_unregisters_stubs_when_flag_off(
    monkeypatch, isolated_registry
):
    _flag(monkeypatch, True)
    sync_proof_surface_mcp_registration()
    assert isolated_registry.get_local("awi_rag_query") is not None
    assert isolated_registry.get_local("data-indexer") is not None

    _flag(monkeypatch, False)
    sync_proof_surface_mcp_registration()
    assert isolated_registry.get_local("awi_rag_query") is None
    assert isolated_registry.get_local("data-indexer") is None


def test_unregister_stubs_is_idempotent(isolated_registry):
    unregister_proof_surface_mcp_stubs()
    unregister_proof_surface_mcp_stubs()
    assert mcp_phase9_tools._registered is False
