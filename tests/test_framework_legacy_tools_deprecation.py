"""Legacy framework factories must warn toward the governed path.

``framework_integrations.tools`` offers ungoverned helpers (no permit
check, no signed receipt) next to the governed middleware. Each factory
that returns such helpers must emit a ``DeprecationWarning`` that names
the governed alternative, so convenience does not silently bypass
governance.
"""

from __future__ import annotations

import sys
import types
import warnings

import pytest

from framework_integrations import (
    B2AClient,
    get_autogen_tools,
    get_crewai_tools,
    get_langgraph_tools,
    get_llamaindex_tools,
)


def _stub_module(monkeypatch: pytest.MonkeyPatch, dotted: str, **attrs) -> None:
    parts = dotted.split(".")
    for depth in range(1, len(parts) + 1):
        name = ".".join(parts[:depth])
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    for attr, value in attrs.items():
        setattr(sys.modules[dotted], attr, value)


class _StubFunctionTool:
    def __init__(self, fn=None, async_fn=None, name=None) -> None:
        self.fn = fn
        self.async_fn = async_fn
        self.name = name

    @classmethod
    def from_defaults(cls, fn=None, name=None, async_fn=None, **_: object):
        return cls(fn, async_fn, name)


def _client() -> B2AClient:
    return B2AClient(api_url="http://b2a.test", api_key="k", wallet_id="w")


def test_langgraph_factory_warns_toward_governed_tools(monkeypatch) -> None:
    _stub_module(monkeypatch, "langchain_core.tools", tool=lambda fn: fn)
    with pytest.warns(DeprecationWarning, match="governed"):
        tools = get_langgraph_tools(_client())
    assert len(tools) == 6
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        get_langgraph_tools(_client())
    messages = [
        str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert any("LangGraphGovernedTools" in m for m in messages)


def test_autogen_factory_warns_toward_governed_tools() -> None:
    with pytest.warns(DeprecationWarning, match="governed"):
        tools = get_autogen_tools(_client())
    assert set(tools) == {
        "emit_telemetry",
        "get_balance",
        "send_message",
        "ai_decide",
        "self_heal",
        "create_awi_session",
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        get_autogen_tools(_client())
    messages = [
        str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert any("governed" in m for m in messages)


def test_llamaindex_factory_warns_toward_governed_tools(monkeypatch) -> None:
    _stub_module(monkeypatch, "llama_index.core.tools", FunctionTool=_StubFunctionTool)
    with pytest.warns(DeprecationWarning, match="governed"):
        tools = get_llamaindex_tools(_client())
    assert len(tools) == 6


def test_crewai_factory_still_points_at_governed_wrappers() -> None:
    with pytest.raises(NotImplementedError, match="governed|Governed"):
        get_crewai_tools(_client())
