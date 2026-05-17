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

    fallback_content = """# Agent-Native Middleware API — LLM-Readable Documentation

**Agent-first:** Intended reader = autonomous agents. Fetch GET /.well-known/agent.json first; use GET /health/dependencies (simulation_modes) before assuming real side effects.

**Version:** from GET /.well-known/agent.json
**Base URL:** operator-supplied (e.g. http://localhost:8000)
**Auth:** X-API-Key on protected routes

## Quick Start

1. GET /.well-known/agent.json — Bootstrap manifest (includes agent_first.bootstrap_sequence)
2. GET /llm.txt — Full prose (if this fallback appears, static/llm.txt is missing on disk)
3. GET /mcp/tools.json — MCP tools
4. GET /openapi.json — API contract

## MCP Tools
GET /mcp/tools.json — List available tools
"""
    return PlainTextResponse(content=fallback_content)
