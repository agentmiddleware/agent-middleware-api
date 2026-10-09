"""Focused coverage for app/services/service_registry.py.

In-memory behavior only: local registration, upstream registration,
schema helpers, MCP tool conversion, and unregister paths. No database,
no network.
"""

import pytest
from pydantic import BaseModel

from app.schemas.billing import ServiceCategory
from app.services.service_registry import (
    ServiceRegistry,
    extract_schema_from_callable,
    get_service_registry,
    pydantic_to_mcp_schema,
)


class _Input(BaseModel):
    name: str
    count: int = 0


class _Output(BaseModel):
    ok: bool


def _sample_func(name: str, count: int = 0) -> bool:
    return bool(name) and count >= 0


def _make_registry() -> ServiceRegistry:
    return ServiceRegistry()


def test_pydantic_to_mcp_schema_none_returns_none():
    assert pydantic_to_mcp_schema(None) is None


def test_pydantic_to_mcp_schema_model_shape():
    schema = pydantic_to_mcp_schema(_Input)

    assert schema is not None
    assert schema["type"] == "object"
    assert "name" in schema["properties"]
    assert "count" in schema["properties"]
    assert "name" in schema["required"]
    assert "count" not in schema["required"]
    assert schema["additionalProperties"] is False


def test_extract_schema_marks_required_and_optional():
    input_schema, output_schema = extract_schema_from_callable(_sample_func)

    assert input_schema is not None
    assert set(input_schema["properties"]) == {"name", "count"}
    assert input_schema["required"] == ["name"]
    assert output_schema == {"type": "boolean"}


def test_extract_schema_untyped_callable_has_no_input_schema():
    def _untyped(*args, **kwargs):
        pass

    input_schema, output_schema = extract_schema_from_callable(_untyped)

    assert input_schema is None
    assert output_schema is None


async def test_register_local_roundtrip_and_pricing():
    registry = _make_registry()
    record = registry.register_local(
        service_id="local.echo",
        name="Echo",
        description="Echo fixture",
        category=ServiceCategory.AGENT_COMMS,
        func=_sample_func,
        input_model=_Input,
        output_model=_Output,
        credits_per_unit=2.5,
        unit_name="call",
    )

    assert record["service_id"] == "local.echo"
    assert record["is_local"] is True
    assert record["is_executable"] is True
    assert registry.get_local("local.echo") is record
    assert registry.get_local_func("local.echo") is _sample_func
    assert await registry.get("local.echo") is record
    assert await registry.get_pricing("local.echo") == (2.5, "call")

    tool = registry.to_mcp_tool(record)
    assert tool["name"] == "local.echo"
    assert tool["inputSchema"]["properties"]["name"] == {
        "title": "Name",
        "type": "string",
    }
    assert tool["annotations"]["category"] == ServiceCategory.AGENT_COMMS.value

    listed = await registry.list_local()
    assert any(s["service_id"] == "local.echo" for s in listed)
    assert all("func" not in s for s in listed)
    executable = await registry.list_executable()
    assert any(s["service_id"] == "local.echo" for s in executable)

    assert registry.unregister_local("local.echo") is True
    assert registry.get_local("local.echo") is None
    assert registry.get_local_func("local.echo") is None


def test_register_local_output_model_only_still_derives_input():
    registry = _make_registry()
    record = registry.register_local(
        service_id="local.typed",
        name="Typed",
        description="Typed fixture",
        category=ServiceCategory.AGENT_COMMS,
        func=_sample_func,
        output_model=_Output,
    )

    assert record["input_schema"] is not None
    assert set(record["input_schema"]["properties"]) == {"name", "count"}


def test_unregister_unknown_returns_false_and_lookup_is_none():
    registry = _make_registry()

    assert registry.unregister_local("no.such.tool") is False
    assert registry.get_local("no.such.tool") is None
    assert registry.get_local_func("no.such.tool") is None
    assert registry.get_executor("no.such.tool") is None


def test_to_mcp_tool_defaults_missing_input_schema():
    registry = _make_registry()
    tool = registry.to_mcp_tool({"service_id": "bare.tool"})

    assert tool["inputSchema"] == {"type": "object", "properties": {}}
    assert tool["annotations"]["creditsPerCall"] == 1.0


async def test_register_upstream_roundtrip_and_backend_removal():
    registry = _make_registry()
    executor = object()
    record = registry.register_upstream(
        service_id="partner.tool",
        name="Partner tool",
        description="Upstream fixture",
        category=ServiceCategory.AGENT_COMMS,
        executor=executor,
        input_schema={"type": "object", "properties": {}},
        output_schema=None,
        credits_per_unit=1.0,
        upstream_tool_name="tool",
        upstream_origin="https://fixture.invalid",
    )

    assert record["execution_backend"] == "upstream_mcp"
    assert record["require_permit"] is True
    assert registry.get_executor("partner.tool") is executor
    assert registry.get_action_binding(record) is None
    assert await registry.get("partner.tool") is record

    tool = registry.to_mcp_tool(record)
    assert tool["annotations"]["external"] is True

    assert registry.unregister_execution_backend("upstream_mcp") == 1
    assert registry.get_local("partner.tool") is None


def test_register_upstream_conflicts_with_local_service_id():
    registry = _make_registry()
    registry.register_local(
        service_id="dup.tool",
        name="Dup",
        description="Dup fixture",
        category=ServiceCategory.AGENT_COMMS,
        func=_sample_func,
    )

    with pytest.raises(ValueError, match="already registered"):
        registry.register_upstream(
            service_id="dup.tool",
            name="Dup upstream",
            description="Dup fixture",
            category=ServiceCategory.AGENT_COMMS,
            executor=object(),
            input_schema={"type": "object", "properties": {}},
            output_schema=None,
            credits_per_unit=1.0,
            upstream_tool_name="tool",
            upstream_origin="https://fixture.invalid",
        )


def test_get_service_registry_is_singleton():
    assert get_service_registry() is get_service_registry()
