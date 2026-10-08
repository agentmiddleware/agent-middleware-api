"""Local/upstream registration lifecycle consistency for the service registry.

Replacing or removing a tool registration must not leave stale executor or
action-binding state behind: dispatch and permit paths resolve those maps by
tool id, and a stale entry either raises a registry-mismatch error on a
healthy tool or honors a binding for a tool that no longer exists.
"""

from __future__ import annotations

import pytest

from app.schemas.billing import ServiceCategory
from app.services.action_permits import (
    ActionToolBinding,
    upstream_action_binding_hash,
)
from app.services.service_registry import (
    ServiceRegistry,
    _service_to_mcp_tool,
    extract_schema_from_callable,
    pydantic_to_mcp_schema,
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {"q": {"type": "string"}},
    "required": ["q"],
    "additionalProperties": False,
}
ORIGIN = "https://upstream.example"
REMOTE_TOOL = "remote_tool"


def _binding(service_id: str) -> ActionToolBinding:
    return ActionToolBinding(
        deployment_authority="test-authority",
        public_tool_id=service_id,
        upstream_binding_hash=upstream_action_binding_hash(
            deployment_authority="test-authority",
            public_tool_id=service_id,
            upstream_origin=ORIGIN,
            upstream_tool_name=REMOTE_TOOL,
            schema_id="s1",
            schema_version="v1",
            input_schema=INPUT_SCHEMA,
        ),
        schema_id="s1",
        schema_version="v1",
        input_schema=dict(INPUT_SCHEMA),
    )


def _register_upstream(registry: ServiceRegistry, service_id: str, **kw):
    params = {
        "service_id": service_id,
        "name": service_id,
        "description": "upstream tool",
        "category": ServiceCategory.ORACLE,
        "executor": object(),
        "input_schema": dict(INPUT_SCHEMA),
        "output_schema": None,
        "credits_per_unit": 2.0,
        "upstream_tool_name": REMOTE_TOOL,
        "upstream_origin": ORIGIN,
    }
    params.update(kw)
    return registry.register_upstream(**params)


def _handler(q: str, limit: int = 10) -> str:
    return f"{q}:{limit}"


def _register_local(registry: ServiceRegistry, service_id: str):
    return registry.register_local(
        service_id,
        name=service_id,
        description="local tool",
        category=ServiceCategory.ORACLE,
        func=_handler,
    )


def test_unregister_clears_action_binding():
    registry = ServiceRegistry()
    record = _register_upstream(
        registry, "tool-bind", action_binding=_binding("tool-bind")
    )
    assert registry.get_action_binding(record) is not None
    assert registry.unregister_local("tool-bind") is True
    assert registry.get_action_binding(record) is None


def test_reregister_local_after_unregister_has_no_binding():
    registry = ServiceRegistry()
    _register_upstream(registry, "tool-swap", action_binding=_binding("tool-swap"))
    assert registry.unregister_local("tool-swap") is True
    fresh = _register_local(registry, "tool-swap")
    assert registry.get_action_binding(fresh) is None


def test_register_local_clears_stale_upstream_executor():
    registry = ServiceRegistry()
    sentinel = object()
    _register_upstream(registry, "tool-exec", executor=sentinel)
    assert registry.get_executor("tool-exec") is sentinel
    _register_local(registry, "tool-exec")
    assert registry.get_executor("tool-exec") is None
    assert registry.get_local_func("tool-exec") is _handler


def test_register_upstream_conflicts_with_local_backend():
    registry = ServiceRegistry()
    _register_local(registry, "tool-clash")
    with pytest.raises(ValueError, match="already registered"):
        _register_upstream(registry, "tool-clash")


def test_unregister_unknown_and_backend_sweep():
    registry = ServiceRegistry()
    assert registry.unregister_local("tool-missing") is False
    _register_upstream(registry, "tool-up-a")
    _register_upstream(registry, "tool-up-b")
    _register_local(registry, "tool-local")
    assert registry.unregister_execution_backend("upstream_mcp") == 2
    assert registry.get_local("tool-up-a") is None
    assert registry.get_local("tool-up-b") is None
    assert registry.get_local("tool-local") is not None


async def test_get_serves_local_record_without_database():
    registry = ServiceRegistry()
    _register_local(registry, "tool-get")
    record = await registry.get("tool-get")
    assert record is not None
    assert record["service_id"] == "tool-get"
    assert await registry.get("tool-missing") is None


def test_service_to_mcp_tool_defaults():
    tool = _service_to_mcp_tool({"service_id": "tool-min"})
    assert tool["name"] == "tool-min"
    assert tool["inputSchema"] == {"type": "object", "properties": {}}
    assert tool["annotations"]["creditsPerCall"] == 1.0
    assert "requirePermit" not in tool["annotations"]


def test_extract_schema_from_callable_marks_required():
    input_schema, output_schema = extract_schema_from_callable(_handler)
    assert input_schema is not None
    assert input_schema["required"] == ["q"]
    assert input_schema["properties"]["q"] == {"type": "string"}
    assert input_schema["properties"]["limit"] == {"type": "integer"}
    assert output_schema == {"type": "string"}


def test_pydantic_to_mcp_schema_none_is_none():
    assert pydantic_to_mcp_schema(None) is None
