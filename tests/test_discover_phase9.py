"""
Tests for Phase 9.1 Agent Discoverability
==========================================

Verifies that all discovery surfaces include Phase 9 features:
- /.well-known/agent.json
- /v1/discover
- /mcp/tools.json
- /llm.txt
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestWellKnownAgentJson:
    """Test the agent.json manifest includes Phase 9 capabilities."""

    def test_well_known_agent_json_has_phase9_capabilities(self):
        """Verify agent.json includes passkey_auth, dom_bridge, rag_memory."""
        from app.routers.well_known import _build_agent_manifest

        manifest = _build_agent_manifest()
        data = manifest.model_dump()

        assert "capabilities" in data
        phase9_capabilities = ["passkey_auth", "dom_bridge", "rag_memory"]
        for cap in phase9_capabilities:
            assert cap in data["capabilities"], f"Missing Phase 9 capability: {cap}"

    def test_well_known_agent_json_has_phase9_endpoints(self):
        """Verify agent.json endpoints include Phase 9 routes."""
        from app.routers.well_known import _build_agent_manifest

        manifest = _build_agent_manifest()
        data = manifest.model_dump()

        assert "endpoints" in data
        phase9_endpoints = ["awi_passkey", "awi_dom", "awi_rag"]
        for endpoint in phase9_endpoints:
            assert endpoint in data["endpoints"], (
                f"Missing Phase 9 endpoint: {endpoint}"
            )

    def test_well_known_agent_json_has_phase9_docs(self):
        """Verify agent.json documentation includes Phase 9 links."""
        from app.routers.well_known import _build_agent_manifest

        manifest = _build_agent_manifest()
        data = manifest.model_dump()

        assert "documentation" in data
        phase9_docs = ["phase9_passkey", "phase9_dom_bridge", "phase9_rag"]
        for doc in phase9_docs:
            assert doc in data["documentation"], f"Missing Phase 9 doc link: {doc}"


class TestDiscoverEndpoint:
    """Test /v1/discover includes Phase 9."""

    def test_discover_has_phase9_capabilities(self):
        """Verify discover endpoint includes Phase 9 capabilities."""
        from app.routers.discover import _build_capabilities

        capabilities = _build_capabilities()
        cap_names = [c.name for c in capabilities]
        phase9_caps = ["passkey", "dom_bridge", "rag_memory"]
        for cap in phase9_caps:
            assert cap in cap_names, f"Missing Phase 9 capability: {cap}"

    def test_discover_has_phase9_mcp_tools(self):
        """Verify discover endpoint includes Phase 9 MCP tools."""
        from app.routers.discover import _build_mcp_tools

        tools = _build_mcp_tools()
        tool_names = [t.name for t in tools]

        phase9_tools = [
            "create_passkey_challenge",
            "verify_passkey",
            "create_dom_session",
            "sync_dom_action",
            "query_memories",
        ]
        for tool in phase9_tools:
            assert tool in tool_names, f"Missing Phase 9 MCP tool: {tool}"

    def test_discover_has_phase9_awi_endpoints(self):
        """Verify discover endpoint includes Phase 9 AWI endpoints."""
        from app.routers.discover import _build_awi_endpoints

        endpoints = _build_awi_endpoints()
        endpoint_paths = [e.path for e in endpoints]

        phase9_endpoints = [
            "/v1/awi/passkey/challenge",
            "/v1/awi/dom/sync",
            "/v1/awi/rag/query",
        ]
        for endpoint in phase9_endpoints:
            assert endpoint in endpoint_paths, f"Missing Phase 9 endpoint: {endpoint}"


class TestMcpToolsManifest:
    """Test MCP generator includes Phase 9 tools."""

    def test_mcp_generator_has_phase9_tools(self):
        """Verify MCP generator includes Phase 9 tools."""
        from app.services.mcp_phase9_tools import (
            ensure_phase9_registered,
            MCP_PHASE9_TOOLS,
        )

        ensure_phase9_registered()

        phase9_tool_ids = [t["service_id"] for t in MCP_PHASE9_TOOLS]
        expected = [
            "awi_passkey_challenge",
            "awi_passkey_verify",
            "awi_dom_bridge_session",
            "awi_dom_sync",
            "awi_dom_state",
            "awi_dom_action_preview",
            "awi_memory_index",
            "awi_rag_query",
            "awi_session_context",
        ]
        for tool in expected:
            assert tool in phase9_tool_ids, f"Missing Phase 9 tool: {tool}"

    def test_mcp_phase9_tools_have_pricing(self):
        """Verify Phase 9 MCP tools have proper pricing annotations."""
        from app.services.mcp_phase9_tools import MCP_PHASE9_TOOLS

        for tool in MCP_PHASE9_TOOLS:
            assert "credits_per_unit" in tool
            assert "unit_name" in tool
            assert tool["credits_per_unit"] > 0


class TestLlmTxt:
    """Test /llm.txt includes Phase 9 documentation."""

    def test_llm_txt_has_phase9_section(self):
        """Verify llm.txt includes Phase 9 documentation."""
        with open("static/llm.txt", "r") as f:
            content = f.read()

        assert "Passkey" in content, "Missing passkey documentation"
        assert "DOM Bridge" in content, "Missing DOM bridge documentation"
        assert "RAG Memory" in content, "Missing RAG memory documentation"

    def test_llm_txt_has_phase9_endpoints(self):
        """Verify llm.txt includes Phase 9 endpoint examples."""
        with open("static/llm.txt", "r") as f:
            content = f.read()

        phase9_endpoints = [
            "/v1/awi/passkey/register",
            "/v1/awi/passkey/challenge",
            "/v1/awi/dom/snapshot",
            "/v1/awi/dom/element_at",
            "/v1/awi/rag/ingest",
            "/v1/awi/rag/search",
        ]
        for endpoint in phase9_endpoints:
            assert endpoint in content, f"Missing Phase 9 endpoint example: {endpoint}"


class TestPhase9ToolsRegistration:
    """Test Phase 9 tools are properly registered."""

    def test_phase9_tools_registered_in_service_registry(self):
        """Verify Phase 9 tools appear in the service registry."""
        from app.services.mcp_phase9_tools import ensure_phase9_registered
        from app.services.service_registry import get_service_registry

        ensure_phase9_registered()
        registry = get_service_registry()

        expected_tools = [
            "awi_passkey_challenge",
            "awi_passkey_verify",
            "awi_dom_bridge_session",
            "awi_dom_sync",
            "awi_dom_state",
            "awi_dom_action_preview",
            "awi_memory_index",
            "awi_rag_query",
            "awi_session_context",
        ]

        for tool_id in expected_tools:
            service = registry.get_local(tool_id)
            assert service is not None, f"Phase 9 tool not registered: {tool_id}"

    def test_phase9_tools_in_mcp_manifest(self):
        """Verify Phase 9 tools appear in MCP tools manifest."""
        from app.services.mcp_phase9_tools import ensure_phase9_registered
        from app.services.mcp_generator import get_mcp_generator

        ensure_phase9_registered()
        generator = get_mcp_generator()

        manifest = generator.generate_tools_json(include_persistent=False)
        tool_names = [t["name"] for t in manifest["tools"]]

        expected_tools = [
            "awi_passkey_challenge",
            "awi_passkey_verify",
            "awi_dom_bridge_session",
            "awi_dom_sync",
            "awi_memory_index",
            "awi_rag_query",
        ]
        for tool in expected_tools:
            assert tool in tool_names, f"Phase 9 tool not in manifest: {tool}"
