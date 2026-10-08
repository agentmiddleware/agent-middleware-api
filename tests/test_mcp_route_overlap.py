"""The three /mcp routers must not compete for the same path and method.

``mcp`` (legacy JSON-RPC), ``mcp_standard`` (Streamable HTTP) and
``mcp_public`` (unauthenticated reads) share the ``/mcp`` prefix, so this
test pins what the review could only guess at: no (method, path) pair is
claimed twice, which means router registration order cannot decide which
handler wins. Each transport also keeps exactly one POST handler.
"""

from __future__ import annotations

from app.main import app
from app.routers import mcp, mcp_public, mcp_standard
from tests.conftest import iter_routes

_MCP_ROUTERS = (mcp.router, mcp_standard.router, mcp_public.router)


def _method_path_pairs(routes) -> list[tuple[str, str]]:
    pairs = []
    for route in iter_routes(routes):
        path = getattr(route, "path", "")
        for method in route.methods or set():
            pairs.append((method, path))
    return pairs


def test_mcp_routers_claim_no_shared_method_and_path():
    seen: dict[tuple[str, str], str] = {}
    for router in _MCP_ROUTERS:
        owner = router.prefix
        for pair in _method_path_pairs(router.routes):
            assert pair not in seen, (
                f"{pair} claimed by both {seen[pair]} and {owner}: "
                "registration order would decide the handler"
            )
            seen[pair] = owner


def test_each_mcp_transport_keeps_one_post_handler():
    posts = sorted(
        pair
        for pair in _method_path_pairs(app.routes)
        if pair[0] == "POST" and pair[1] in ("/mcp", "/mcp/messages", "/mcp/public")
    )
    assert posts == [
        ("POST", "/mcp"),
        ("POST", "/mcp/messages"),
        ("POST", "/mcp/public"),
    ]
