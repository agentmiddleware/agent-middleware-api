"""
Static Files Router
====================
Serves static discovery docs for agents (llm.txt + advertised markdown).
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pathlib import Path

from ..core.config import get_settings

router = APIRouter(tags=["Static"])

_PUBLIC_URL_PLACEHOLDER = "{{PUBLIC_URL}}"
_LOCAL_EXAMPLE = "http://localhost:8000"
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Paths advertised in /.well-known/agent.json documentation (must 200).
_MARKDOWN_DOCS: dict[str, Path] = {
    "/WEDGE.md": _REPO_ROOT / "WEDGE.md",
    "/SECURITY_LIMITATIONS.md": _REPO_ROOT / "SECURITY_LIMITATIONS.md",
    "/DESIGN_PARTNER_GUIDE.md": _REPO_ROOT / "DESIGN_PARTNER_GUIDE.md",
    "/docs/partner-api-key-bootstrap.md": (
        _REPO_ROOT / "docs" / "partner-api-key-bootstrap.md"
    ),
}


def _serve_markdown(path: str) -> PlainTextResponse:
    file_path = _MARKDOWN_DOCS.get(path)
    if file_path is None or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"{path} not found")
    return PlainTextResponse(
        file_path.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
    )


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
    llm_path = _REPO_ROOT / "static" / "llm.txt"
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


@router.get(
    "/WEDGE.md",
    summary="Product wedge",
    description="Exactly-once MCP permits wedge definition.",
    response_class=PlainTextResponse,
)
async def get_wedge_md():
    return _serve_markdown("/WEDGE.md")


@router.get(
    "/SECURITY_LIMITATIONS.md",
    summary="Security limitations",
    description="Honest non-claims and production posture requirements.",
    response_class=PlainTextResponse,
)
async def get_security_limitations_md():
    return _serve_markdown("/SECURITY_LIMITATIONS.md")


@router.get(
    "/DESIGN_PARTNER_GUIDE.md",
    summary="Design partner guide",
    description="Trust-plane demo and dogfood path for design partners.",
    response_class=PlainTextResponse,
)
async def get_design_partner_guide_md():
    return _serve_markdown("/DESIGN_PARTNER_GUIDE.md")


@router.get(
    "/docs/partner-api-key-bootstrap.md",
    summary="Partner API key bootstrap",
    description="Gated operator flow to provision wallet-scoped agent API keys.",
    response_class=PlainTextResponse,
)
async def get_partner_api_key_bootstrap_md():
    return _serve_markdown("/docs/partner-api-key-bootstrap.md")
