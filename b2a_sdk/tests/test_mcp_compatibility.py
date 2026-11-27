"""The optional MCP dependency must provide the legacy serving import."""

import importlib.util
import sys

import pytest

from b2a_sdk import mcp


@pytest.mark.skipif(importlib.util.find_spec("mcp") is None, reason="mcp extra not installed")
def test_installed_mcp_supports_fastmcp():
    # A present but incompatible package must fail, not skip this check.
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("b2a-sdk-compatibility")
    assert server.name == "b2a-sdk-compatibility"


@pytest.mark.skipif(importlib.util.find_spec("mcp") is None, reason="mcp extra not installed")
def test_serve_cli_imports_mcp_before_discovery(monkeypatch):
    class DiscoveryReachedError(Exception):
        pass

    def stop_at_discovery(*, api_url):
        assert api_url == "https://unused.invalid"
        raise DiscoveryReachedError

    monkeypatch.setattr(mcp, "generate_manifest", stop_at_discovery)
    monkeypatch.setattr(sys, "argv", ["mcp", "serve", "--api-url", "https://unused.invalid"])
    with pytest.raises(DiscoveryReachedError):
        mcp.main()


def test_serve_without_fastmcp_refuses_before_discovery(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("missing MCP dependency must not trigger discovery")

    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)
    monkeypatch.setattr(mcp, "generate_manifest", forbidden)
    monkeypatch.setattr(sys, "argv", ["mcp", "serve"])

    mcp.main()

    assert 'pip install "b2a-sdk[mcp]"' in capsys.readouterr().out
