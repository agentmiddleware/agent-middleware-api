"""Governed-first guards for ``framework_integrations``.

The governed wrappers (LangGraphGovernedTools, PydanticAIGovernedTools, the
CrewAI and OpenAI wrappers) are the path sellers should demo: every call
goes through permit plus idempotency key plus signed receipt. The older
``get_*`` factories skip permits and receipts. These tests pin the guards
that keep a demo on the governed path:

* the legacy factories warn at call time and name the governed alternative
  in their docstrings;
* ``B2AClient`` refuses to send a request when the key or wallet is missing,
  with a message that says what to set instead of a connection error;
* the in-folder CrewAI and OpenAI bridges exist and either build the
  governed helper or explain exactly what to install.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import httpx
import pytest

from framework_integrations import B2AClient
from framework_integrations import tools as legacy_tools


def _stub_module(monkeypatch: pytest.MonkeyPatch, dotted: str, **attrs: Any) -> None:
    parts = dotted.split(".")
    for depth in range(1, len(parts) + 1):
        name = ".".join(parts[:depth])
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    for attr, value in attrs.items():
        setattr(sys.modules[dotted], attr, value)


class _StubFunctionTool:
    def __init__(self, fn: Any, async_fn: Any, name: str | None) -> None:
        self.fn = fn
        self.async_fn = async_fn
        self.name = name

    @classmethod
    def from_defaults(
        cls,
        fn: Any = None,
        name: str | None = None,
        async_fn: Any = None,
        **_: Any,
    ) -> "_StubFunctionTool":
        return cls(fn, async_fn, name)


def _legacy_client() -> B2AClient:
    client = B2AClient(api_url="http://b2a.test", api_key="k", wallet_id="wal-1")
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    )
    return client


@pytest.mark.anyio
async def test_langgraph_factory_warns_and_names_governed_path(monkeypatch):
    _stub_module(monkeypatch, "langchain_core.tools", tool=lambda fn: fn)
    client = _legacy_client()
    try:
        with pytest.warns(DeprecationWarning, match="overned"):
            tools = legacy_tools.get_langgraph_tools(client)
        assert len(tools) == 6
    finally:
        await client.close()


@pytest.mark.anyio
async def test_llamaindex_factory_warns_and_names_governed_path(monkeypatch):
    _stub_module(monkeypatch, "llama_index.core.tools", FunctionTool=_StubFunctionTool)
    client = _legacy_client()
    try:
        with pytest.warns(DeprecationWarning, match="overned"):
            tools = legacy_tools.get_llamaindex_tools(client)
        assert len(tools) == 6
    finally:
        await client.close()


@pytest.mark.anyio
async def test_autogen_factory_warns_and_names_governed_path():
    client = _legacy_client()
    try:
        with pytest.warns(DeprecationWarning, match="overned"):
            function_map = legacy_tools.get_autogen_tools(client)
        assert set(function_map) == {
            "emit_telemetry",
            "get_balance",
            "send_message",
            "ai_decide",
            "self_heal",
            "create_awi_session",
        }
    finally:
        await client.close()


@pytest.mark.parametrize(
    "factory_name",
    ["get_langgraph_tools", "get_llamaindex_tools", "get_autogen_tools"],
)
def test_legacy_docstrings_name_the_governed_alternative(factory_name):
    doc = getattr(legacy_tools, factory_name).__doc__ or ""
    assert "UNGOVERNED" in doc
    assert "governed" in doc.lower()


@pytest.mark.anyio
async def test_blank_api_key_is_refused_before_any_request():
    sent: list[httpx.Request] = []
    client = B2AClient(api_url="http://b2a.test", api_key="", wallet_id="wal-1")
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: sent.append(r) or httpx.Response(200, json={})
        )
    )
    try:
        with pytest.raises(ValueError, match="api_key"):
            await client.get_balance()
    finally:
        await client.close()
    assert sent == []


@pytest.mark.anyio
async def test_blank_wallet_id_is_refused_before_any_request():
    sent: list[httpx.Request] = []
    client = B2AClient(api_url="http://b2a.test", api_key="k", wallet_id="  ")
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: sent.append(r) or httpx.Response(200, json={})
        )
    )
    try:
        with pytest.raises(ValueError, match="wallet_id"):
            await client.get_balance()
    finally:
        await client.close()
    assert sent == []


@pytest.mark.anyio
async def test_discover_still_works_without_a_wallet_id():
    """Wallet validation must not break wallet-free calls."""
    sent: list[httpx.Request] = []
    client = B2AClient(api_url="http://b2a.test", api_key="k")
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: sent.append(r) or httpx.Response(200, json={"tools": []})
        )
    )
    try:
        assert await client.discover() == {"tools": []}
    finally:
        await client.close()
    assert len(sent) == 1


def test_crewai_bridge_points_at_wrapper_install(monkeypatch):
    """Without the CrewAI stack, the bridge explains what to install."""
    from framework_integrations import bridges

    monkeypatch.setitem(sys.modules, "crewai", None)
    monkeypatch.setitem(sys.modules, "crewai_b2a", None)
    monkeypatch.setitem(sys.modules, "crewai_b2a.tool", None)
    with pytest.raises(ImportError, match="crewai-agent-middleware"):
        bridges.get_crewai_governed_tool(api_key="k", wallet_id="w")


def test_openai_bridge_builds_a_governed_runner():
    from framework_integrations import bridges
    from openai_b2a.runner import GovernedToolRunner

    runner = bridges.get_openai_governed_runner(
        api_key="k", wallet_id="wal-1", run_id="run-1"
    )
    assert isinstance(runner, GovernedToolRunner)
    definition = runner.register_tool(
        "notes.write", description="Write a note", parameters={"type": "object"}
    )
    assert definition["function"]["name"] == "notes_write"
