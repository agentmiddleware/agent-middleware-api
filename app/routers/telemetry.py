"""
Autonomous Product Manager / Telemetry Router
----------------------------------------------
Ingests raw telemetry, detects anomalies, generates autonomous PRs.
Wired to AutonomousPM service via FastAPI dependency injection.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
import uuid

from ..core.auth import verify_api_key
from ..core.dependencies import get_autonomous_pm
from ..services.telemetry_pm import AutonomousPM
from ..schemas.telemetry import (
    TelemetryEvent,
    TelemetryBatch,
    TelemetryBatchResponse,
    AnomalyReport,
    AnomalyListResponse,
    AutoPRRequest,
    AutoPRResponse,
    Severity,
    TelemetryEventType,
)

router = APIRouter(
    prefix="/v1/telemetry",
    tags=["Autonomous Product Manager"],
    dependencies=[Depends(verify_api_key)],
    responses={
        401: {"description": "Missing API key"},
        403: {"description": "Invalid API key"},
    },
)


@router.post(
    "/events",
    response_model=TelemetryBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest telemetry events",
    description=(
        "Submit a batch of telemetry events for anomaly detection. "
        "Events are processed asynchronously. The Autonomous PM will "
        "analyze patterns across events to identify error spikes, "
        "latency regressions, and missing feature patterns."
    ),
)
async def ingest_events(
    batch: TelemetryBatch,
    pm: AutonomousPM = Depends(get_autonomous_pm),
):
    batch_id = str(uuid.uuid4())
    ingested, errors = await pm.event_store.ingest(batch.events, batch_id)

    return TelemetryBatchResponse(
        ingested=ingested,
        failed=len(errors),
        batch_id=batch_id,
        errors=errors,
    )


@router.post(
    "/events/single",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a single telemetry event",
    description="Convenience endpoint for submitting one event at a time.",
)
async def ingest_single_event(
    event: TelemetryEvent,
    pm: AutonomousPM = Depends(get_autonomous_pm),
):
    batch_id = str(uuid.uuid4())
    ingested, errors = await pm.event_store.ingest([event], batch_id)
    return TelemetryBatchResponse(
        ingested=ingested,
        failed=len(errors),
        batch_id=batch_id,
        errors=errors,
    )


@router.get(
    "/anomalies",
    response_model=AnomalyListResponse,
    summary="List detected anomalies",
    description=(
        "Retrieve anomalies detected by the Autonomous PM. "
        "Anomalies are classified by severity and category, with "
        "optional LLM-generated fix suggestions and auto-PR links."
    ),
)
async def list_anomalies(
    severity: Severity | None = Query(None, description="Filter by severity level"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    pm: AutonomousPM = Depends(get_autonomous_pm),
):
    anomalies, total = await pm.detector.get_anomalies(severity, page, per_page)
    return AnomalyListResponse(
        anomalies=anomalies,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/anomalies/{anomaly_id}",
    response_model=AnomalyReport,
    summary="Get anomaly details",
    description=(
        "Retrieve detailed information about a specific anomaly, "
        "including suggested fixes."
    ),
)
async def get_anomaly(
    anomaly_id: str,
    pm: AutonomousPM = Depends(get_autonomous_pm),
):
    anomaly = await pm.detector.get_anomaly(anomaly_id)
    if not anomaly:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "anomaly_not_found",
                "message": f"Anomaly '{anomaly_id}' not found.",
            },
        )
    return anomaly


@router.post(
    "/anomalies/{anomaly_id}/auto-pr",
    response_model=AutoPRResponse,
    summary="Generate an autonomous pull request",
    description=(
        "Instruct the Autonomous PM to generate a code fix for the given anomaly "
        "and optionally push it as a pull request. Use dry_run=true to preview "
        "the proposed diff without committing."
    ),
)
async def generate_auto_pr(
    anomaly_id: str,
    request: AutoPRRequest,
    pm: AutonomousPM = Depends(get_autonomous_pm),
):
    anomaly = await pm.detector.get_anomaly(anomaly_id)
    if not anomaly:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "anomaly_not_found",
                "message": f"Anomaly '{anomaly_id}' not found.",
            },
        )

    related = await pm.event_store.query(event_type=TelemetryEventType.ERROR, limit=20)

    result = await pm.pr_generator.generate_fix(
        anomaly=anomaly,
        related_events=related,
        dry_run=request.dry_run,
    )

    return AutoPRResponse(
        anomaly_id=anomaly_id,
        pr_url=result.get("pr_url"),
        diff=result["diff"],
        files_changed=result["files_changed"],
        tests_passed=result.get("tests_passed"),
        status=result["status"],
    )


@router.get(
    "/stats",
    summary="Get telemetry statistics",
    description=(
        "Aggregate statistics across all ingested telemetry events. "
        "Useful for agents monitoring system health at a glance."
    ),
)
async def get_stats(
    pm: AutonomousPM = Depends(get_autonomous_pm),
):
    event_stats = await pm.event_store.stats()
    _, total_anomalies = await pm.detector.get_anomalies()

    return {
        "total_events": event_stats["total"],
        "events_by_type": event_stats["by_type"],
        "events_by_severity": event_stats["by_severity"],
        "events_by_source": event_stats["by_source"],
        "total_anomalies": total_anomalies,
    }
