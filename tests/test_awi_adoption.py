"""
Tests for AWI Adoption Kit — Phase 8
====================================
Tests for the External AWI Adoption Kit components.
"""

import pytest

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.tools.awi_manifest_generator import ManifestGenerator


class TestAWIManifestGenerator:
    """Test AWI manifest generator."""

    def test_generator_init(self):
        """Test manifest generator initialization."""
        gen = ManifestGenerator(framework="fastapi")
        assert gen.framework == "fastapi"
        assert gen.actions == []

    def test_generate_empty_manifest(self):
        """Test generating a manifest from a FastAPI app with no routes."""
        from fastapi import FastAPI

        gen = ManifestGenerator()
        empty_app = FastAPI(title="Test API", version="1.0.0")
        manifest = gen.scan_fastapi_app(empty_app)

        assert manifest["name"] == "Test API"
        assert manifest["awi_version"] == "1.0.0"
        assert manifest["framework"] == "fastapi"
        assert manifest["actions"] == []

    def test_generate_from_openapi(self):
        """Test generating manifest from OpenAPI spec."""
        gen = ManifestGenerator(framework="openapi")
        spec = {
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {
                "/search": {
                    "post": {"summary": "Search items", "description": "Search"}
                },
                "/cart/add": {"post": {"summary": "Add to cart"}},
            },
        }

        manifest = gen.generate_from_openapi(spec)

        assert manifest["name"] == "Test API"
        assert manifest["framework"] == "openapi"
        assert "endpoints" in manifest

    def test_openapi_endpoint_extraction(self):
        """Test that endpoints are extracted from OpenAPI spec."""
        gen = ManifestGenerator(framework="openapi")
        spec = {
            "info": {"title": "API", "version": "1.0.0"},
            "paths": {
                "/products": {"get": {"summary": "List products"}},
                "/products/{id}": {"get": {"summary": "Get product"}},
            },
        }

        manifest = gen.generate_from_openapi(spec)

        assert len(manifest["endpoints"]) == 2

    def test_openapi_servers_extraction(self):
        """Test that servers URL is extracted."""
        gen = ManifestGenerator(framework="openapi")
        spec = {
            "info": {"title": "API", "version": "1.0.0"},
            "servers": [{"url": "https://api.example.com"}],
            "paths": {},
        }

        manifest = gen.generate_from_openapi(spec)

        assert manifest["base_url"] == "https://api.example.com"

    def test_action_mapping_logic(self):
        """Test action mapping returns valid action for POST routes."""
        gen = ManifestGenerator()

        class MockRoute:
            path = "/custom/action"
            methods = ["POST"]
            name = "custom"

        route = MockRoute()
        action = gen._route_to_action(route)

        assert action is not None
        assert "awi_action" in action
        assert action["method"] == "POST"


class TestAWIClientSDK:
    """Test AWI Python SDK models (defined locally for standalone testing)."""

    def test_awi_action_enum(self):
        """Test AWI action enum values."""
        from enum import Enum

        class AWIStandardAction(str, Enum):
            SEARCH_AND_SORT = "search_and_sort"
            ADD_TO_CART = "add_to_cart"
            CHECKOUT = "checkout"
            FILL_FORM = "fill_form"
            LOGIN = "login"
            LOGOUT = "logout"
            NAVIGATE_TO = "navigate_to"

        assert AWIStandardAction.SEARCH_AND_SORT == "search_and_sort"
        assert AWIStandardAction.ADD_TO_CART == "add_to_cart"
        assert AWIStandardAction.CHECKOUT == "checkout"

    def test_awi_representation_enum(self):
        """Test AWI representation type enum values."""
        from enum import Enum

        class AWIRepresentationType(str, Enum):
            FULL_DOM = "full_dom"
            SUMMARY = "summary"
            EMBEDDING = "embedding"
            LOW_RES_SCREENSHOT = "low_res_screenshot"

        assert AWIRepresentationType.SUMMARY == "summary"
        assert AWIRepresentationType.EMBEDDING == "embedding"

    def test_awi_session_dataclass(self):
        """Test AWISession dataclass structure."""
        from dataclasses import dataclass
        from datetime import datetime

        @dataclass
        class AWISession:
            session_id: str
            target_url: str
            status: str
            created_at: datetime
            max_steps: int = 100

        session = AWISession(
            session_id="test-123",
            target_url="https://example.com",
            status="created",
            created_at=datetime.now(),
        )

        assert session.session_id == "test-123"
        assert session.target_url == "https://example.com"
        assert session.max_steps == 100

    def test_awi_execution_response_dataclass(self):
        """Test AWIExecutionResponse dataclass structure."""
        from dataclasses import dataclass

        @dataclass
        class AWIExecutionResponse:
            execution_id: str
            session_id: str
            action: str
            status: str
            result: dict | None = None
            error: str | None = None

        response = AWIExecutionResponse(
            execution_id="exec-123",
            session_id="test-123",
            action="search_and_sort",
            status="success",
        )

        assert response.execution_id == "exec-123"
        assert response.action == "search_and_sort"


class TestAWIExternalAdapter:
    """Test AWI external adapter."""

    def test_external_adapter_init(self):
        """Test external adapter initialization."""
        from app.services.awi_external_adapter import AWIExternalAdapter

        adapter = AWIExternalAdapter(
            middleware_url="http://localhost:8000",
            api_key="test-key",
        )

        assert adapter.middleware_url == "http://localhost:8000"
        assert adapter.api_key == "test-key"

    def test_fallback_adapter_init(self):
        """Test fallback adapter initialization."""
        from app.services.awi_external_adapter import AWIFallbackAdapter

        adapter = AWIFallbackAdapter(
            middleware_url="http://localhost:8000",
            api_key="test-key",
        )

        assert adapter.awi is not None


class TestAWIAdoptionGuide:
    """Test adoption guide content."""

    def test_adoption_guide_exists(self):
        """Test adoption guide was created."""
        import os

        guide_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "docs",
            "awi-adoption-guide.md",
        )
        assert os.path.exists(guide_path)

    def test_adoption_guide_content(self):
        """Test adoption guide has required sections."""
        import os

        guide_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "docs",
            "awi-adoption-guide.md",
        )

        with open(guide_path) as f:
            content = f.read()

        assert "AWI Adoption Guide" in content
        assert "Quick Start" in content
        assert "Security Checklist" in content
        assert "Framework Templates" in content
        assert "arXiv" in content or "arxiv" in content.lower()


class TestManifestGeneratorCliHonesty:
    """The CLI must offer only frameworks it implements (fastapi, openapi)."""

    def test_cli_accepts_implemented_frameworks(self):
        from app.tools.awi_manifest_generator import build_parser

        parser = build_parser()
        assert parser.parse_args(["--framework", "fastapi"]).framework == "fastapi"
        assert parser.parse_args(["--framework", "openapi"]).framework == "openapi"

    @pytest.mark.parametrize("framework", ["django", "express"])
    def test_cli_rejects_unimplemented_frameworks(self, framework):
        from app.tools.awi_manifest_generator import build_parser

        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--framework", framework])


class TestOpenApiActions:
    """OpenAPI generation must yield agent-ready actions, not only endpoints."""

    def test_openapi_maps_known_operations_to_actions(self):
        gen = ManifestGenerator(framework="openapi")
        spec = {
            "info": {"title": "Shop API", "version": "1.0.0"},
            "servers": [{"url": "https://api.example.com"}],
            "paths": {
                "/search": {"post": {"summary": "Search items"}},
                "/cart/add": {"post": {"summary": "Add to cart"}},
                "/products": {"get": {"summary": "List products"}},
            },
        }

        manifest = gen.generate_from_openapi(spec)

        by_action = {a["awi_action"]: a for a in manifest["actions"]}
        assert by_action["search_and_sort"]["route"] == "/search"
        assert by_action["search_and_sort"]["description"] == "Search items"
        assert by_action["add_to_cart"]["route"] == "/cart/add"
        assert manifest["route_mappings"]["search_and_sort"] == "/search"
        assert manifest["route_mappings"]["add_to_cart"] == "/cart/add"
        paths = {e["path"] for e in manifest["endpoints"]}
        assert {"/search", "/cart/add", "/products"} <= paths

    def test_openapi_skips_malformed_operations(self):
        gen = ManifestGenerator(framework="openapi")
        spec = {
            "info": {"title": "API", "version": "1.0.0"},
            "paths": {
                "/ok": {"post": {"summary": "Ok"}},
                "/broken": "not-a-mapping",
                "/empty": {"trace": {"summary": "Unsupported method"}},
            },
        }

        manifest = gen.generate_from_openapi(spec)

        assert [e["path"] for e in manifest["endpoints"]] == ["/ok"]

    def test_scan_sample_shop_app_to_manifest_file(self, tmp_path):
        """Worked example: sample FastAPI shop app scans to a saved manifest."""
        from fastapi import FastAPI

        from app.tools.awi_manifest_generator import ManifestGenerator

        shop = FastAPI(title="Shop", version="2.0.0")

        @shop.get("/")
        async def home() -> dict:
            return {}

        @shop.post("/api/search")
        async def search() -> dict:
            """Search items."""
            return {}

        @shop.post("/api/cart/add")
        async def add() -> dict:
            """Add to cart."""
            return {}

        @shop.post("/checkout")
        async def checkout() -> dict:
            """Complete checkout."""
            return {}

        gen = ManifestGenerator()
        manifest = gen.save_manifest(
            gen.scan_fastapi_app(shop), tmp_path / ".well-known" / "awi.json"
        )

        assert manifest["name"] == "Shop"
        assert manifest["route_mappings"]["navigate_to"] == "/"
        assert manifest["route_mappings"]["search_and_sort"] == "/api/search"
        assert manifest["route_mappings"]["add_to_cart"] == "/api/cart/add"
        assert manifest["route_mappings"]["checkout"] == "/checkout"
        import json

        saved = json.loads((tmp_path / ".well-known" / "awi.json").read_text())
        assert saved["actions"] == manifest["actions"]
        assert len(saved["endpoints"]) >= 4


class TestAWIAdoptionRouter:
    """Test AWI adoption endpoints."""

    @pytest.mark.anyio
    async def test_awi_endpoints_available(self):
        """Test AWI endpoints are accessible."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/v1/awi/vocabulary")
            assert response.status_code == 200
            data = response.json()
            assert "actions" in data
