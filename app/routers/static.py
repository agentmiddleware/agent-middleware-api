"""
Static Files Router
====================
Serves static files for agent discovery.
"""

from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse
from pathlib import Path

router = APIRouter(tags=["Static"])


@router.get(
    "/llm.txt",
    summary="LLM-Readable Documentation",
    description="Plain-text documentation optimized for LLM agents to understand this API.",
    response_class=PlainTextResponse,
)
async def get_llm_txt():
    """
    Serve the LLM-readable documentation.

    This file is optimized for language models to understand:
    - What services are available
    - How to authenticate
    - How to use MCP tools
    - How to integrate with frameworks
    """
    llm_path = Path(__file__).parent.parent.parent / "static" / "llm.txt"
    if llm_path.exists():
        return FileResponse(llm_path, media_type="text/plain")

    fallback_content = """# Agent-Native Middleware API

**Version:** 0.4.1
**Base URL:** http://localhost:8000

## Quick Start

1. GET /v1/discover — Discover all capabilities
2. Use X-API-Key header for authentication
3. Create wallet at POST /v1/billing/wallets/agent
4. Use services: /v1/telemetry, /v1/comms, /v1/ai, /v1/awi

## MCP Tools
GET /mcp/tools.json — List available tools

## Documentation
/docs — Interactive API docs
/openapi.json — OpenAPI spec
"""
    return PlainTextResponse(content=fallback_content)
