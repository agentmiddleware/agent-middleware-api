"""
Telemetry Scoping Router (Pillar 14)
--------------------------------------
Multi-tenant autonomous PM for agent-built tools.
Each builder-agent gets its own telemetry pipeline with
anomaly detection and auto-PR generation.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from datetime import datetime

from ..core.auth import verify_api_key
from ..core.dependencies import get_telemetry_scope
from ..services.telemetry_scope import TelemetryScope

router = APIRouter(
    prefix="/v1/telemetry-scope",
    tags=["Telemetry Scoping"],
    dependencies=[Depends(verify_api_key)],
)


# --- Schemas ---

class CreatePipelineRequest(BaseModel):
    """Create a tenant-scoped telemetry pipeline."""
    tenant_id: str = Field(..., description="Your agent or wallet ID.")
    service_name: str = Field(..., description="Name of the tool being monitored.")
    git_repo_url: str = Field(default="", description="Git repo for auto-PR generation.")
    webhook_url: str = Field(default="", description="Webhook for anomaly notifications.")


class PipelineResponse(BaseModel):
    pipeline_id: str
    tenant_id: str
    service_name: str
    git_repo_url: str = ""
    webhook_url: str = ""
    total_events: int = 0
    anomalies_detected: int = 0
    auto_prs_generated: int = 0
    status: str
    created_at: datetime


class IngestRequest(BaseModel):
    """Ingest telemetry events into a scoped pipeline."""
    events: list[dict] = Field(
        ...,
        min_length=1,
        description="Telemetry events from the monitored tool.",
    )


class IngestResponse(BaseModel):
    pipeline_id: str
    events_ingested: int
    total_events: int
    anomalies_detected: int


class AutoPrRequest(BaseModel):
    anomaly_id: str = Field(..., description="ID of the anomaly to auto-fix.")


class PipelineStatsResponse(BaseModel):
    pipeline_id: str
    service_name: str
    total_events: int
    error_events: int
    error_rate: float
    avg_latency_ms: float
    max_latency_ms: float
    anomalies_detected: int
    auto_prs_generated: int
    status: str


class PipelineListResponse(BaseModel):
    pipelines: list[dict]
    total: int


# --- Endpoints ---

@router.post(
    "/pipelines",
    response_model=PipelineResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a telemetry pipeline",
    description=(
        "Create an isolated telemetry pipeline for monitoring an agent-built tool. "
        "Events ingested into this pipeline are analyzed independently, with "
        "per-tenant anomaly detection and optional auto-PR generation."
    ),
)
async def create_pipeline(
    request: CreatePipelineRequest,
    scope: TelemetryScope = Depends(get_telemetry_scope),
):
    pipeline = await scope.create_pipeline(
        tenant_id=request.tenant_id,
        service_name=request.service_name,
        git_repo_url=request.git_repo_url,
        webhook_url=request.webhook_url,
    )
    return _pipeline_to_response(pipeline)


@router.post(
    "/pipelines/{pipeline_id}/events",
    response_model=IngestResponse,
    summary="Ingest telemetry events",
    description=(
        "Route telemetry events from your tool into its scoped pipeline. "
        "Anomaly detection runs automatically on each batch."
    ),
)
async def ingest_events(
    pipeline_id: str,
    request: IngestRequest,
    scope: TelemetryScope = Depends(get_telemetry_scope),
):
    try:
        result = await scope.ingest_events(pipeline_id, request.events)
        return IngestResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "pipeline_not_found", "message": str(e)},
        )


@router.get(
    "/pipelines/{pipeline_id}/anomalies",
    summary="Get pipeline anomalies",
    description="Retrieve all anomalies detected in a telemetry pipeline.",
)
async def get_anomalies(
    pipeline_id: str,
    scope: TelemetryScope = Depends(get_telemetry_scope),
):
    try:
        anomalies = await scope.get_anomalies(pipeline_id)
        return {"pipeline_id": pipeline_id, "anomalies": anomalies, "total": len(anomalies)}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "pipeline_not_found", "message": str(e)},
        )


@router.post(
    "/pipelines/{pipeline_id}/auto-pr",
    summary="Generate auto-fix PR",
    description=(
        "Auto-generate a pull request to fix a detected anomaly. "
        "Targets the git repo configured on the pipeline."
    ),
)
async def generate_auto_pr(
    pipeline_id: str,
    request: AutoPrRequest,
    scope: TelemetryScope = Depends(get_telemetry_scope),
):
    try:
        pr = await scope.generate_auto_pr(pipeline_id, request.anomaly_id)
        return pr
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": str(e)},
        )


@router.get(
    "/pipelines/{pipeline_id}/stats",
    response_model=PipelineStatsResponse,
    summary="Get pipeline statistics",
    description="Aggregated telemetry stats: error rates, latencies, anomaly counts.",
)
async def get_stats(
    pipeline_id: str,
    scope: TelemetryScope = Depends(get_telemetry_scope),
):
    try:
        stats = await scope.get_pipeline_stats(pipeline_id)
        return PipelineStatsResponse(**stats)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "pipeline_not_found", "message": str(e)},
        )


@router.get(
    "/pipelines/{pipeline_id}",
    response_model=PipelineResponse,
    summary="Get pipeline details",
)
async def get_pipeline(
    pipeline_id: str,
    scope: TelemetryScope = Depends(get_telemetry_scope),
):
    pipeline = await scope.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "pipeline_not_found"},
        )
    return _pipeline_to_response(pipeline)


@router.get(
    "/pipelines",
    response_model=PipelineListResponse,
    summary="List pipelines",
)
async def list_pipelines(
    tenant_id: str | None = Query(None),
    scope: TelemetryScope = Depends(get_telemetry_scope),
):
    pipelines = await scope.list_pipelines(tenant_id)
    return PipelineListResponse(
        pipelines=[
            {
                "pipeline_id": p.pipeline_id,
                "tenant_id": p.tenant_id,
                "service_name": p.service_name,
                "total_events": len(p.events),
                "anomalies": len(p.anomalies),
                "status": p.status,
                "created_at": p.created_at,
            }
            for p in pipelines
        ],
        total=len(pipelines),
    )


def _pipeline_to_response(p) -> PipelineResponse:
    return PipelineResponse(
        pipeline_id=p.pipeline_id,
        tenant_id=p.tenant_id,
        service_name=p.service_name,
        git_repo_url=p.git_repo_url,
        webhook_url=p.webhook_url,
        total_events=len(p.events),
        anomalies_detected=len(p.anomalies),
        auto_prs_generated=len(p.auto_prs),
        status=p.status,
        created_at=p.created_at,
    )
