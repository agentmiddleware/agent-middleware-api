"""
Agent Oracle Infiltration Router
----------------------------------
Crawl agent directories, index external API capabilities,
register our API for inbound traffic, and monitor visibility.

This is SEO for the agentic web. If agents can't find you, you don't exist.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..core.auth import verify_api_key
from ..core.dependencies import get_agent_oracle
from ..services.oracle import AgentOracle
from ..schemas.oracle import (
    CrawlTargetRequest,
    IndexedAPI,
    IndexedAPIListResponse,
    CompatibilityTier,
    DirectoryType,
    RegistrationRequest,
    RegistrationResponse,
    OracleStatus,
    VisibilityScore,
    NetworkGraphResponse,
)

router = APIRouter(
    prefix="/v1/oracle",
    tags=["Agent Oracle & Network Infiltration"],
    responses={
        401: {"description": "Missing API key"},
        403: {"description": "Invalid API key or access denied"},
    },
)


# --- Crawling ---

@router.post(
    "/crawl",
    response_model=IndexedAPI,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Crawl and index an external API",
    description=(
        "Submit a URL for the Oracle to crawl. It will attempt to discover "
        "the API's capabilities via /.well-known/agent.json, /llm.txt, or "
        "OpenAPI specs, then compute a compatibility score indicating how "
        "well it integrates with our middleware."
    ),
)
async def crawl_target(
    request: CrawlTargetRequest,
    api_key: str = Depends(verify_api_key),
    oracle: AgentOracle = Depends(get_agent_oracle),
):
    result = await oracle.crawl(
        url=request.url,
        directory_type=request.directory_type,
        tags=request.tags,
        priority=request.priority,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "crawl_failed",
                "message": f"Failed to crawl {request.url}",
            },
        )
    return result


@router.post(
    "/crawl/batch",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Batch crawl multiple URLs",
    description="Submit multiple URLs for concurrent crawling and indexing.",
)
async def batch_crawl(
    urls: list[str],
    api_key: str = Depends(verify_api_key),
    oracle: AgentOracle = Depends(get_agent_oracle),
):
    results = await oracle.batch_crawl(urls)
    return {
        "crawled": len(results),
        "submitted": len(urls),
        "apis": [
            {
                "api_id": r.api_id,
                "name": r.name,
                "url": r.url,
                "compatibility_tier": r.compatibility_tier.value,
                "compatibility_score": r.compatibility_score,
            }
            for r in results
        ],
    }


# --- Indexed API Directory ---

@router.get(
    "/index",
    response_model=IndexedAPIListResponse,
    summary="List indexed APIs",
    description=(
        "Browse the Oracle's index of external APIs. Filter by compatibility tier "
        "or directory type. Sorted by compatibility score (highest first)."
    ),
)
async def list_indexed(
    tier: CompatibilityTier | None = Query(
        None, description="Filter by compatibility tier"
    ),
    directory_type: DirectoryType | None = Query(
        None, description="Filter by directory type"
    ),
    api_key: str = Depends(verify_api_key),
    oracle: AgentOracle = Depends(get_agent_oracle),
):
    apis = await oracle.store.list_indexed(tier=tier, directory_type=directory_type)
    filters = {}
    if tier:
        filters["tier"] = tier.value
    if directory_type:
        filters["directory_type"] = directory_type.value

    return IndexedAPIListResponse(
        apis=apis,
        total=len(apis),
        filters_applied=filters,
    )


@router.get(
    "/index/{api_id}",
    response_model=IndexedAPI,
    summary="Get indexed API details",
    description="Retrieve full details for a specific indexed API.",
)
async def get_indexed_api(
    api_id: str,
    api_key: str = Depends(verify_api_key),
    oracle: AgentOracle = Depends(get_agent_oracle),
):
    api = await oracle.store.get_indexed(api_id)
    if not api:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "api_not_found"},
        )
    return api


# --- Registration ---

@router.post(
    "/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Register in external agent directories",
    description=(
        "Push our API profile into external agent directories and registries. "
        "This is how agents find us — by being listed in the directories they "
        "already crawl. Supports /.well-known, MCP server listings, plugin stores, "
        "and centralized agent registries."
    ),
)
async def register_in_directories(
    request: RegistrationRequest,
    api_key: str = Depends(verify_api_key),
    oracle: AgentOracle = Depends(get_agent_oracle),
):
    targets = [
        {
            "directory_url": t.directory_url,
            "directory_type": t.directory_type.value,
            "registration_payload": t.registration_payload,
        }
        for t in request.targets
    ]
    results = await oracle.register_in_directories(
        targets=targets,
        profile_overrides=request.profile if request.profile else None,
    )

    registered = sum(1 for r in results if r.status == OracleStatus.REGISTERED)
    failed = sum(1 for r in results if r.status == OracleStatus.FAILED)

    return RegistrationResponse(
        results=results,
        total_attempted=len(results),
        total_registered=registered,
        total_failed=failed,
    )


@router.get(
    "/registrations",
    summary="List all registrations",
    description="View all directories where our API has been registered.",
)
async def list_registrations(
    api_key: str = Depends(verify_api_key),
    oracle: AgentOracle = Depends(get_agent_oracle),
):
    regs = await oracle.store.get_registrations()
    return {
        "registrations": [
            {
                "directory_url": r.directory_url,
                "directory_type": r.directory_type.value,
                "status": r.status.value,
                "registration_id": r.registration_id,
            }
            for r in regs
        ],
        "total": len(regs),
    }


# --- Visibility & Analytics ---

@router.get(
    "/visibility",
    response_model=VisibilityScore,
    summary="Get visibility score",
    description=(
        "Compute our API's overall visibility across agent networks. "
        "Includes registration count, discovery hit rate, compatibility "
        "distribution, and actionable recommendations."
    ),
)
async def get_visibility(
    api_key: str = Depends(verify_api_key),
    oracle: AgentOracle = Depends(get_agent_oracle),
):
    return await oracle.compute_visibility()


@router.get(
    "/network",
    response_model=NetworkGraphResponse,
    summary="Get agent network graph",
    description=(
        "Returns the agent network graph centered on our API. "
        "Shows all indexed APIs, registered directories, and their "
        "compatibility relationships. Use this to visualize our position "
        "in the agent ecosystem."
    ),
)
async def get_network_graph(
    api_key: str = Depends(verify_api_key),
    oracle: AgentOracle = Depends(get_agent_oracle),
):
    return await oracle.get_network_graph()


@router.post(
    "/discovery",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Record inbound discovery hit",
    description=(
        "Called when an external agent discovers our API. "
        "Tracks referrer for analytics. This endpoint should be called "
        "by our middleware whenever an agent first hits / or /.well-known/agent.json."
    ),
)
async def record_discovery(
    referrer: str = Query(default="direct", description="Referring directory URL"),
    api_key: str = Depends(verify_api_key),
    oracle: AgentOracle = Depends(get_agent_oracle),
):
    await oracle.record_discovery(referrer)
