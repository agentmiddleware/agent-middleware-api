"""The legacy serve path loads on mcp 1.x and 2.x, and fails cleanly with neither."""

import sys
import types

import pytest

from b2a_sdk import mcp as mcp_module


def _install_fake_mcp(monkeypatch, *, fastmcp_cls="missing", mcpserver_cls="missing"):
    """Fake the mcp package tree so no real mcp install is needed.

    A value of "missing" installs ``None`` for that leaf, which makes the
    corresponding ``from ... import ...`` raise ImportError.
    """
    top = types.ModuleType("mcp")
    server = types.ModuleType("mcp.server")
    top.server = server
    monkeypatch.setitem(sys.modules, "mcp", top)
    monkeypatch.setitem(sys.modules, "mcp.server", server)
    if fastmcp_cls == "missing":
        monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)
    else:
        leaf = types.ModuleType("mcp.server.fastmcp")
        leaf.FastMCP = fastmcp_cls
        server.fastmcp = leaf
        monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", leaf)
    if mcpserver_cls == "missing":
        monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", None)
    else:
        leaf = types.ModuleType("mcp.server.mcpserver")
        leaf.MCPServer = mcpserver_cls
        server.mcpserver = leaf
        monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", leaf)


def test_load_server_class_prefers_v1(monkeypatch):
    v1 = type("FastMCP", (), {})
    v2 = type("MCPServer", (), {})
    _install_fake_mcp(monkeypatch, fastmcp_cls=v1, mcpserver_cls=v2)
    assert mcp_module._load_server_class() == (v1, "v1")


def test_load_server_class_falls_back_to_v2(monkeypatch):
    v2 = type("MCPServer", (), {})
    _install_fake_mcp(monkeypatch, mcpserver_cls=v2)
    assert mcp_module._load_server_class() == (v2, "v2")


def test_load_server_class_returns_none_without_mcp(monkeypatch):
    _install_fake_mcp(monkeypatch)
    assert mcp_module._load_server_class() == (None, None)


class _FakeServer:
    instances: list = []

    def __init__(self, name):
        self.name = name
        self.added = []
        self.ran = None
        _FakeServer.instances.append(self)

    def add_tool(self, *args, **kwargs):
        self.added.append((args, kwargs))

    def run(self, transport="stdio", port=8001):
        self.ran = {"transport": transport, "port": port}


def _manifest():
    return {
        "tools": [
            {"name": "data-processor", "description": "Process data"},
            {"name": "url-summarizer", "description": "Summarize a URL"},
        ]
    }


@pytest.mark.asyncio
async def test_serve_registers_tools_through_v1_api(monkeypatch):
    monkeypatch.setattr(_FakeServer, "instances", [])
    monkeypatch.setattr(mcp_module, "_load_server_class", lambda: (_FakeServer, "v1"))
    monkeypatch.setattr(
        mcp_module, "generate_manifest", lambda api_url=None, category=None: _manifest()
    )
    await mcp_module.serve_async(api_url="http://unused.invalid")

    (server,) = _FakeServer.instances
    assert [args[0] for args, _ in server.added] == ["data-processor", "url-summarizer"]
    expected = _manifest()["tools"]
    assert len(server.added) == len(expected)
    for (args, kwargs), tool in zip(server.added, expected, strict=True):
        assert args[0] == tool["name"]
        assert args[1] == tool["description"]
        assert callable(args[2])
        assert kwargs == {}
    assert server.ran == {"transport": "stdio", "port": 8001}


@pytest.mark.asyncio
async def test_serve_registers_tools_through_v2_api(monkeypatch):
    monkeypatch.setattr(_FakeServer, "instances", [])
    monkeypatch.setattr(mcp_module, "_load_server_class", lambda: (_FakeServer, "v2"))
    monkeypatch.setattr(
        mcp_module, "generate_manifest", lambda api_url=None, category=None: _manifest()
    )
    await mcp_module.serve_async(api_url="http://unused.invalid")

    (server,) = _FakeServer.instances
    assert [kwargs["name"] for _, kwargs in server.added] == [
        "data-processor",
        "url-summarizer",
    ]
    expected = _manifest()["tools"]
    assert len(server.added) == len(expected)
    for (args, kwargs), tool in zip(server.added, expected, strict=True):
        assert args == ()
        assert kwargs["name"] == tool["name"]
        assert kwargs["description"] == tool["description"]
        assert callable(kwargs["fn"])
    assert server.ran == {"transport": "stdio", "port": 8001}


@pytest.mark.asyncio
async def test_serve_without_mcp_prints_hint_and_sends_nothing(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("serve without mcp must not discover tools")

    monkeypatch.setattr(mcp_module, "_load_server_class", lambda: (None, None))
    monkeypatch.setattr(mcp_module, "generate_manifest", forbidden)
    assert await mcp_module.serve_async(api_url="https://unused.invalid") is None
    assert "mcp package required" in capsys.readouterr().out
