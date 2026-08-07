"""Tests for ENABLE_PROOF_SURFACES router mounting."""

from __future__ import annotations

from fastapi import FastAPI

from app.main import CORE_TRUST_ROUTERS, PROOF_SURFACE_ROUTERS
from tests.conftest import iter_routes


def _paths(app: FastAPI) -> set[str]:
    return {getattr(route, "path", "") for route in iter_routes(app.routes)}


def test_core_trust_routers_include_mcp_and_permits():
    names = {mod.__name__.split(".")[-1] for mod in CORE_TRUST_ROUTERS}
    assert "mcp" in names
    assert "permits" in names
    assert "receipts" in names
    assert "audit" in names
    assert "docs" in names
    assert "static" in names


def test_proof_surface_routers_include_awi_and_media():
    names = {mod.__name__.split(".")[-1] for mod in PROOF_SURFACE_ROUTERS}
    assert "awi" in names
    assert "media" in names
    assert "oracle" in names
    assert "docs" not in names


def test_proof_surfaces_can_be_omitted_from_mount_set():
    """When ENABLE_PROOF_SURFACES is false, only core trust routers mount.

    Rebuild a minimal FastAPI app the same way main.py does, without
    re-importing the process-global app. Proof-marked tests opt in explicitly;
    the ordinary test-suite import keeps ENABLE_PROOF_SURFACES=false.
    """
    app = FastAPI()
    for router_module in CORE_TRUST_ROUTERS:
        app.include_router(router_module.router)

    core_only = _paths(app)
    assert "/mcp/tools" in core_only
    assert "/v1/permits" in core_only
    assert "/v1/receipts" in core_only
    assert "/docs/index" in core_only
    assert "/WEDGE.md" in core_only
    assert not any(p.startswith("/v1/media") for p in core_only)
    assert not any(p.startswith("/v1/awi/") for p in core_only)

    for router_module in PROOF_SURFACE_ROUTERS:
        app.include_router(router_module.router)

    with_proof = _paths(app)
    assert with_proof > core_only
    assert any(p.startswith("/v1/media") for p in with_proof)
    assert any(p.startswith("/v1/awi/") for p in with_proof)
