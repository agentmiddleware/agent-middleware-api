"""
MCP Phase 9 Tools Registration
==============================

Registers Phase 9 enhanced capabilities (passkey auth, DOM bridge, RAG memory)
as discoverable MCP tools.

These tools are automatically included in /mcp/tools.json and /v1/discover responses.

Note: These are HTTP-based services exposed via /v1/awi/* endpoints.
Wrapper functions provide schema information for MCP discovery.
"""

import logging
from typing import Any

from .service_registry import get_service_registry
from ..schemas.billing import ServiceCategory
from ..schemas.awi_enhanced import (
    PasskeyChallengeRequest,
    PasskeyVerifyRequest,
    DOMBridgeSessionRequest,
    DOMSyncRequest,
    DOMStateRequest,
    DOMActionPreviewRequest,
    MemoryIndexRequest,
    RAGQueryRequest,
    SessionContextRequest,
)

logger = logging.getLogger(__name__)


async def awi_passkey_challenge(session_id: str, action: str) -> dict[str, Any]:
    """Wrapper for passkey challenge generation."""
    return {
        "endpoint": "/v1/awi/passkey/challenge",
        "method": "POST",
        "requires": ["session_id", "action"],
    }


async def awi_passkey_verify(challenge_id: str, credential: dict) -> dict[str, Any]:
    """Wrapper for passkey verification."""
    return {
        "endpoint": "/v1/awi/passkey/verify",
        "method": "POST",
        "requires": ["challenge_id", "credential"],
    }


async def awi_dom_bridge_session(
    target_url: str, headless: bool = True, **kwargs
) -> dict[str, Any]:
    """Wrapper for DOM bridge session creation."""
    return {
        "endpoint": "/v1/awi/dom/session",
        "method": "POST",
        "requires": ["target_url"],
    }


async def awi_dom_sync(
    session_id: str, action: str, parameters: dict = None, **kwargs
) -> dict[str, Any]:
    """Wrapper for DOM sync execution."""
    return {
        "endpoint": "/v1/awi/dom/sync",
        "method": "POST",
        "requires": ["session_id", "action"],
    }


async def awi_dom_state(
    session_id: str, representation_type: str = "summary", **kwargs
) -> dict[str, Any]:
    """Wrapper for DOM state retrieval."""
    return {
        "endpoint": "/v1/awi/dom/state",
        "method": "GET",
        "requires": ["session_id"],
    }


async def awi_dom_action_preview(
    session_id: str, action: str, parameters: dict = None, **kwargs
) -> dict[str, Any]:
    """Wrapper for DOM action preview."""
    return {
        "endpoint": "/v1/awi/dom/preview",
        "method": "POST",
        "requires": ["session_id", "action"],
    }


async def awi_memory_index(
    session_id: str, session_type: str, action_history: list = None, **kwargs
) -> dict[str, Any]:
    """Wrapper for memory indexing."""
    return {
        "endpoint": "/v1/awi/rag/index",
        "method": "POST",
        "requires": ["session_id", "session_type"],
    }


async def awi_rag_query(query: str, top_k: int = 5, **kwargs) -> dict[str, Any]:
    """Wrapper for RAG semantic search."""
    return {"endpoint": "/v1/awi/rag/search", "method": "POST", "requires": ["query"]}


async def awi_session_context(
    current_session_id: str, current_state: dict = None, **kwargs
) -> dict[str, Any]:
    """Wrapper for session context retrieval."""
    return {
        "endpoint": "/v1/awi/rag/context",
        "method": "POST",
        "requires": ["current_session_id"],
    }


MCP_PHASE9_TOOLS = [
    {
        "service_id": "awi_passkey_challenge",
        "name": "AWI Passkey Challenge",
        "description": "Generate a passkey challenge for high-risk action verification using FIDO2/WebAuthn.",
        "category": ServiceCategory.AGENT_COMMS,
        "credits_per_unit": 1.0,
        "unit_name": "challenge",
        "func": awi_passkey_challenge,
        "input_model": PasskeyChallengeRequest,
    },
    {
        "service_id": "awi_passkey_verify",
        "name": "AWI Passkey Verify",
        "description": "Verify a passkey assertion response from the client authenticator.",
        "category": ServiceCategory.AGENT_COMMS,
        "credits_per_unit": 2.0,
        "unit_name": "verification",
        "func": awi_passkey_verify,
        "input_model": PasskeyVerifyRequest,
    },
    {
        "service_id": "awi_dom_bridge_session",
        "name": "AWI DOM Bridge Session",
        "description": "Create a new Playwright bridge session for real browser automation.",
        "category": ServiceCategory.AGENT_COMMS,
        "credits_per_unit": 5.0,
        "unit_name": "session",
        "func": awi_dom_bridge_session,
        "input_model": DOMBridgeSessionRequest,
    },
    {
        "service_id": "awi_dom_sync",
        "name": "AWI DOM Sync",
        "description": "Execute an AWI action against real browser DOM and return state representation.",
        "category": ServiceCategory.AGENT_COMMS,
        "credits_per_unit": 3.0,
        "unit_name": "execution",
        "func": awi_dom_sync,
        "input_model": DOMSyncRequest,
    },
    {
        "service_id": "awi_dom_state",
        "name": "AWI DOM State",
        "description": "Get current DOM state as AWI representation (summary, accessibility tree, etc.).",
        "category": ServiceCategory.AGENT_COMMS,
        "credits_per_unit": 2.0,
        "unit_name": "query",
        "func": awi_dom_state,
        "input_model": DOMStateRequest,
    },
    {
        "service_id": "awi_dom_action_preview",
        "name": "AWI DOM Action Preview",
        "description": "Preview what Playwright commands will be generated for an AWI action.",
        "category": ServiceCategory.AGENT_COMMS,
        "credits_per_unit": 2.0,
        "unit_name": "preview",
        "func": awi_dom_action_preview,
        "input_model": DOMActionPreviewRequest,
    },
    {
        "service_id": "awi_memory_index",
        "name": "AWI Memory Index",
        "description": "Index a completed AWI session for semantic search over session history.",
        "category": ServiceCategory.AGENT_COMMS,
        "credits_per_unit": 5.0,
        "unit_name": "indexing",
        "func": awi_memory_index,
        "input_model": MemoryIndexRequest,
    },
    {
        "service_id": "awi_rag_query",
        "name": "AWI RAG Query",
        "description": "Semantic search query over session memories using vector similarity.",
        "category": ServiceCategory.AGENT_COMMS,
        "credits_per_unit": 3.0,
        "unit_name": "search",
        "func": awi_rag_query,
        "input_model": RAGQueryRequest,
    },
    {
        "service_id": "awi_session_context",
        "name": "AWI Session Context",
        "description": "Get relevant context from past sessions for the current session.",
        "category": ServiceCategory.AGENT_COMMS,
        "credits_per_unit": 2.0,
        "unit_name": "context",
        "func": awi_session_context,
        "input_model": SessionContextRequest,
    },
]


def register_phase9_tools():
    """Register all Phase 9 tools with the service registry."""
    registry = get_service_registry()

    for tool in MCP_PHASE9_TOOLS:
        func = tool.pop("func")
        input_model = tool.pop("input_model", None)

        registry.register_local(func=func, input_model=input_model, **tool)
        logger.info(f"Registered Phase 9 MCP tool: {tool['service_id']}")


_registered = False


def ensure_phase9_registered():
    """Ensure Phase 9 tools are registered exactly once."""
    global _registered
    if not _registered:
        register_phase9_tools()
        _registered = True


_default_services_registered = False


async def default_service_placeholder(**kwargs) -> dict[str, Any]:
    """Placeholder for default services."""
    return {"status": "service_available", "message": "This is a default MCP service"}


def register_default_mcp_services():
    """Register default MCP services for the marketplace."""
    global _default_services_registered
    if _default_services_registered:
        return

    registry = get_service_registry()

    default_services = [
        {
            "service_id": "data-indexer",
            "name": "Data Indexer",
            "description": "Fast vector indexing for documents and content. Enables semantic search capabilities for AI agents.",
            "category": ServiceCategory.PROTOCOL_GEN,
            "credits_per_unit": 10.0,
            "unit_name": "document",
            "input_model": None,
            "output_model": None,
        },
        {
            "service_id": "content-generator",
            "name": "Content Generator",
            "description": "Generate marketing copy, product descriptions, and social media content using AI.",
            "category": ServiceCategory.CONTENT_FACTORY,
            "credits_per_unit": 25.0,
            "unit_name": "piece",
            "input_model": None,
            "output_model": None,
        },
        {
            "service_id": "telemetry-processor",
            "name": "Telemetry Processor",
            "description": "Process and analyze agent telemetry data for anomaly detection and monitoring.",
            "category": ServiceCategory.TELEMETRY_PM,
            "credits_per_unit": 5.0,
            "unit_name": "event",
            "input_model": None,
            "output_model": None,
        },
        {
            "service_id": "semantic-search",
            "name": "Semantic Search",
            "description": "Natural language search across indexed content using embeddings.",
            "category": ServiceCategory.PROTOCOL_GEN,
            "credits_per_unit": 15.0,
            "unit_name": "query",
            "input_model": None,
            "output_model": None,
        },
    ]

    for service_def in default_services:
        try:
            registry.register_local(func=default_service_placeholder, **service_def)
            logger.info(f"Registered default MCP service: {service_def['service_id']}")
        except Exception as e:
            logger.warning(
                f"Failed to register default service {service_def['service_id']}: {e}"
            )

    _default_services_registered = True
