"""
Tests for MCP Server Generator
===============================

Tests for:
- Service registry registration and discovery
- MCP manifest generation
- Standalone server generation
- Tool invocation
"""

import asyncio
import json
import tempfile
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.service_registry import (
    ServiceRegistry,
    get_service_registry,
    pydantic_to_mcp_schema,
    extract_schema_from_callable,
)
from app.services.mcp_generator import McpGenerator, get_mcp_generator
from app.schemas.billing import ServiceCategory
from pydantic import BaseModel


class TestSchemaExtraction:
    """Test Pydantic to MCP schema conversion."""

    def test_simple_model(self):
        class InputModel(BaseModel):
            name: str
            count: int
            enabled: bool = False

        schema = pydantic_to_mcp_schema(InputModel)

        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert "count" in schema["properties"]
        assert "enabled" in schema["properties"]
        assert "required" in schema
        assert "name" in schema["required"]
        assert "count" in schema["required"]
        assert "enabled" not in schema["required"]

    def test_nested_model(self):
        class Inner(BaseModel):
            value: str

        class Outer(BaseModel):
            inner: Inner
            count: int

        schema = pydantic_to_mcp_schema(Outer)

        assert schema["type"] == "object"
        assert "inner" in schema["properties"]
        assert "count" in schema["properties"]
        assert "inner" in schema["required"]

    def test_none_model(self):
        assert pydantic_to_mcp_schema(None) is None

    def test_extract_from_callable_sync(self):
        def simple_func(name: str, count: int) -> dict:
            return {"name": name, "count": count}

        input_schema, output_schema = extract_schema_from_callable(simple_func)

        assert input_schema is not None
        assert input_schema["type"] == "object"
        assert "name" in input_schema["properties"]
        assert "count" in input_schema["properties"]
        assert "name" in input_schema["required"]
        assert "count" in input_schema["required"]

    def test_extract_from_callable_async(self):
        async def async_func(url: str, style: str = "default") -> str:
            return f"generated: {url}"

        input_schema, output_schema = extract_schema_from_callable(async_func)

        assert input_schema is not None
        assert "url" in input_schema["required"]
        assert "style" not in input_schema["required"]


class TestServiceRegistry:
    """Test service registry operations."""

    @pytest.fixture
    def registry(self):
        return ServiceRegistry()

    def test_register_local_service(self, registry):
        async def dummy_service(url: str, style: str = "default") -> dict:
            return {"result": "ok"}

        result = registry.register_local(
            service_id="test-service",
            name="Test Service",
            description="A test service",
            category=ServiceCategory.CONTENT_FACTORY,
            func=dummy_service,
            credits_per_unit=10.0,
            unit_name="call",
        )

        assert result["service_id"] == "test-service"
        assert result["name"] == "Test Service"
        assert result["credits_per_unit"] == 10.0
        assert result["is_local"] is True
        assert result["input_schema"] is not None

    def test_get_local_service(self, registry):
        async def dummy_service(name: str) -> str:
            return name

        registry.register_local(
            service_id="get-test",
            name="Get Test",
            description="Test get",
            category=ServiceCategory.AGENT_COMMS,
            func=dummy_service,
        )

        service = registry.get_local("get-test")
        assert service is not None
        assert service["service_id"] == "get-test"
        assert service["name"] == "Get Test"

    def test_get_local_func(self, registry):
        async def my_service(x: int) -> int:
            return x * 2

        registry.register_local(
            service_id="func-test",
            name="Func Test",
            description="Test func",
            category=ServiceCategory.IOT_BRIDGE,
            func=my_service,
        )

        func = registry.get_local_func("func-test")
        assert func is my_service

    def test_get_nonexistent_service(self, registry):
        assert registry.get_local("nonexistent") is None
        assert registry.get_local_func("nonexistent") is None

    def test_unregister_local(self, registry):
        async def service1():
            pass

        registry.register_local(
            service_id="unreg-test",
            name="Unreg Test",
            description="Test unreg",
            category=ServiceCategory.PLATFORM_FEE,
            func=service1,
        )

        assert registry.unregister_local("unreg-test") is True
        assert registry.get_local("unreg-test") is None
        assert registry.unregister_local("nonexistent") is False

    def test_list_local_services(self, registry):
        async def service_a():
            pass

        async def service_b():
            pass

        registry.register_local(
            service_id="list-a",
            name="List A",
            description="A",
            category=ServiceCategory.IOT_BRIDGE,
            func=service_a,
        )
        registry.register_local(
            service_id="list-b",
            name="List B",
            description="B",
            category=ServiceCategory.TELEMETRY_PM,
            func=service_b,
        )

        services = asyncio.get_event_loop().run_until_complete(registry.list_local())
        assert len(services) == 2
        assert all(s["is_local"] for s in services)


class TestMcpGenerator:
    """Test MCP manifest generation."""

    @pytest.fixture
    def generator(self):
        registry = ServiceRegistry()
        return McpGenerator(registry), registry

    def test_generate_tools_json_empty(self, generator):
        gen, registry = generator
        manifest = gen.generate_tools_json()

        assert manifest["version"] == "1.0"
        assert "tools" in manifest
        assert len(manifest["tools"]) == 0

    def test_generate_tools_json_with_services(self, generator):
        gen, registry = generator

        async def video_service(url: str, style: str = "cinematic") -> dict:
            return {"video_url": f"{url}.mp4"}

        async def data_service(query: str) -> list:
            return [query]

        registry.register_local(
            service_id="video-generator",
            name="Video Generator",
            description="Generate videos from URLs",
            category=ServiceCategory.CONTENT_FACTORY,
            func=video_service,
            credits_per_unit=50.0,
            unit_name="video",
        )

        registry.register_local(
            service_id="data-indexer",
            name="Data Indexer",
            description="Index data for search",
            category=ServiceCategory.ORACLE,
            func=data_service,
            credits_per_unit=5.0,
            unit_name="query",
        )

        manifest = gen.generate_tools_json()

        assert len(manifest["tools"]) == 2

        video_tool = next(t for t in manifest["tools"] if t["name"] == "video-generator")
        assert video_tool["description"] == "Generate videos from URLs"
        assert video_tool["annotations"]["creditsPerCall"] == 50.0
        assert video_tool["annotations"]["unitName"] == "video"

        data_tool = next(t for t in manifest["tools"] if t["name"] == "data-indexer")
        assert data_tool["annotations"]["creditsPerCall"] == 5.0

    def test_generate_tools_json_category_filter(self, generator):
        gen, registry = generator

        async def service1():
            pass

        registry.register_local(
            service_id="iot-service",
            name="IoT Service",
            description="IoT",
            category=ServiceCategory.IOT_BRIDGE,
            func=service1,
        )

        registry.register_local(
            service_id="media-service",
            name="Media Service",
            description="Media",
            category=ServiceCategory.MEDIA_ENGINE,
            func=service1,
        )

        manifest = gen.generate_tools_json(category=ServiceCategory.IOT_BRIDGE)

        assert len(manifest["tools"]) == 1
        assert manifest["tools"][0]["name"] == "iot-service"

    def test_service_to_mcp_tool(self, generator):
        gen, registry = generator

        service = {
            "service_id": "test-tool",
            "name": "Test Tool",
            "description": "A test tool",
            "category": "content_factory",
            "credits_per_unit": 25.0,
            "unit_name": "call",
            "input_schema": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            "owner_wallet_id": "wallet-123",
        }

        tool = gen._service_to_mcp_tool(service)

        assert tool["name"] == "test-tool"
        assert tool["description"] == "A test tool"
        assert tool["inputSchema"]["properties"]["url"]
        assert tool["annotations"]["creditsPerCall"] == 25.0
        assert tool["annotations"]["providerWallet"] == "wallet-123"

    def test_generate_standalone_server(self, generator):
        gen, registry = generator

        async def service1(url: str):
            return {"url": url}

        registry.register_local(
            service_id="my-service",
            name="My Service",
            description="My service description",
            category=ServiceCategory.CONTENT_FACTORY,
            func=service1,
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            output_path = f.name

        try:
            gen.generate_standalone_server(
                output_path=output_path,
                title="Test MCP Server",
            )

            with open(output_path) as f:
                content = f.read()

            assert "Test MCP Server" in content
            assert "@mcp.tool()" in content
            assert "my_service" in content
            assert "call_b2a_service" in content
        finally:
            import os
            os.unlink(output_path)


class TestMcpGeneratorAsync:
    """Test async MCP generator methods."""

    @pytest.fixture
    def generator(self):
        registry = ServiceRegistry()
        return McpGenerator(registry)

    @pytest.mark.asyncio
    async def test_generate_tools_json_async(self, generator):
        manifest = await generator.generate_tools_json_async()
        assert "tools" in manifest
        assert "generated_at" in manifest


class TestGlobalSingletons:
    """Test global singleton getters."""

    def test_get_service_registry(self):
        registry = get_service_registry()
        assert registry is not None
        assert isinstance(registry, ServiceRegistry)

    def test_get_mcp_generator(self):
        generator = get_mcp_generator()
        assert generator is not None
        assert isinstance(generator, McpGenerator)
