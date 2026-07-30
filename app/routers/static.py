"""
Static Files Router
====================
Serves static files for agent discovery.
"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pathlib import Path

from ..core.config import get_settings

router = APIRouter(tags=["Static"])

_PUBLIC_URL_PLACEHOLDER = "{{PUBLIC_URL}}"
_LOCAL_EXAMPLE = "http://localhost:8000"


@router.get(
    "/llm.txt",
    summary="LLM-Readable Documentation",
    description="Plain-text documentation optimized for LLM agents to understand this API.",
    response_class=PlainTextResponse,
)
async def get_llm_txt():
    """
    Serve the LLM-readable documentation.

    Substitutes ``{{PUBLIC_URL}}`` from settings so production agents do not
    treat localhost as the deployment base.
    """
    settings = get_settings()
    llm_path = Path(__file__).parent.parent.parent / "static" / "llm.txt"
    if llm_path.exists():
        content = llm_path.read_text(encoding="utf-8")
    else:
        content = f"""# Agent-Native Middleware API — LLM-Readable Documentation

**Agent-first:** Intended reader = autonomous agents. Fetch GET /.well-known/agent.json first (use `capabilities` vs `proof_surfaces`); use GET /health/dependencies (`simulation_modes`, `enable_proof_surfaces`) before assuming real side effects.

**Version:** from GET /.well-known/agent.json
**Base URL:** {_PUBLIC_URL_PLACEHOLDER}
**Auth:** X-API-Key on protected routes

## Quick Start

1. GET /.well-known/agent.json — Bootstrap manifest (product wedge + labeled proof surfaces)
2. GET /llm.txt — Full prose (if this fallback appears, static/llm.txt is missing on disk)
3. GET /mcp/tools.json — MCP tools
4. GET /openapi.json — API contract

## MCP Tools
GET /mcp/tools.json — List available tools
"""

    public = (settings.PUBLIC_URL or "").strip().rstrip("/")
    if public:
        base = public
    else:
        base = f"(configure PUBLIC_URL for this deployment; local example {_LOCAL_EXAMPLE})"
    content = content.replace(_PUBLIC_URL_PLACEHOLDER, base)
    # Never present bare localhost as the production Base URL line.
    if not public and f"**Base URL:** {_LOCAL_EXAMPLE}" in content:
        content = content.replace(
            f"**Base URL:** {_LOCAL_EXAMPLE}",
            f"**Base URL:** {base}",
        )
    return PlainTextResponse(content=content)
