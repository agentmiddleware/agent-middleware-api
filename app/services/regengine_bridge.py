"""RegEngine governed MCP bridge tools.

These tools are intentionally narrow external adapters. They do not accept a
caller-supplied base URL; the operator configures the target RegEngine service
through environment variables, while the MCP trust plane owns authorization,
metering, receipts, replay protection, and audit.
"""

from __future__ import annotations

import os
from threading import Lock
from typing import Any, Literal
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, Field

from ..schemas.billing import ServiceCategory
from .service_registry import get_service_registry


REGENGINE_AGENT_REVIEWS_TOOL = "regengine.agent_reviews.list"
DEFAULT_REGENGINE_API_URL = "https://regengine-production.up.railway.app"


class RegEngineAgentReviewsListRequest(BaseModel):
    """Read-only RegEngine operator review query exposed as a governed tool."""

    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum agent review items to fetch.",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Pagination offset.",
    )
    tenant_id: str | None = Field(
        default=None,
        description="Optional tenant filter accepted by RegEngine.",
    )
    ingestion_run_id: str | None = Field(
        default=None,
        description="Optional ingestion run filter accepted by RegEngine.",
    )
    artifact_id: str | None = Field(
        default=None,
        description="Optional artifact filter accepted by RegEngine.",
    )
    review_status: Literal["pending", "accepted", "rejected", "needs_more_evidence"] | None = Field(
        default=None,
        description="Optional operator review status filter.",
    )
    min_risk_score: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Optional minimum risk score filter.",
    )


async def list_regengine_agent_reviews(**kwargs: Any) -> dict[str, Any]:
    """Fetch RegEngine agent review items through an operator-configured API."""

    request = RegEngineAgentReviewsListRequest.model_validate(kwargs)
    payload = await _fetch_regengine_agent_reviews(request)
    return {
        "source": "regengine",
        "tool": REGENGINE_AGENT_REVIEWS_TOOL,
        "endpoint": "/v1/agent-reviews/items",
        "items": payload.get("items", []),
        "total": payload.get("total"),
        "limit": request.limit,
        "offset": request.offset,
        "raw": payload,
    }


async def _fetch_regengine_agent_reviews(
    request: RegEngineAgentReviewsListRequest,
) -> dict[str, Any]:
    base_url = _regengine_api_url()
    url = urljoin(f"{base_url}/", "v1/agent-reviews/items")
    headers = {"Accept": "application/json"}
    api_key = os.environ.get("REGENGINE_API_KEY", "").strip()
    if api_key:
        headers["X-API-Key"] = api_key

    params = request.model_dump(exclude_none=True)
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError("regengine_response_not_object")
    return data


def _regengine_api_url() -> str:
    base_url = os.environ.get("REGENGINE_API_URL", DEFAULT_REGENGINE_API_URL).strip()
    if not base_url:
        base_url = DEFAULT_REGENGINE_API_URL
    if not base_url.startswith(("https://", "http://")):
        raise RuntimeError("regengine_api_url_must_be_http")
    return base_url.rstrip("/")


_registered = False
_registration_lock = Lock()


def register_regengine_bridge_tools() -> None:
    registry = get_service_registry()
    registry.register_local(
        service_id=REGENGINE_AGENT_REVIEWS_TOOL,
        name="RegEngine Agent Reviews List",
        description=(
            "Read RegEngine agent-review operator items through the MCP trust "
            "plane. Requires a signed permit before any RegEngine API request."
        ),
        category=ServiceCategory.PLATFORM_FEE,
        func=list_regengine_agent_reviews,
        input_model=RegEngineAgentReviewsListRequest,
        credits_per_unit=1.0,
        unit_name="query",
        requires_permit=True,
    )


def ensure_regengine_bridge_registered() -> None:
    global _registered
    if _registered:
        return

    with _registration_lock:
        if not _registered:
            register_regengine_bridge_tools()
            _registered = True

