"""
Red-Team-as-a-Service Router (Pillar 12)
------------------------------------------
Multi-tenant security scanning for agent-built tools.
Agents hire our Red Team swarm to attack *their* endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from datetime import datetime

from ..core.auth import verify_api_key
from ..core.dependencies import get_rtaas_engine
from ..services.rtaas import RTaaSEngine

router = APIRouter(
    prefix="/v1/rtaas",
    tags=["Red-Team-as-a-Service"],
    dependencies=[Depends(verify_api_key)],
)


# --- Schemas ---

class RTaaSTargetSchema(BaseModel):
    """An external endpoint to attack."""
    url: str = Field(..., description="Full URL of the target endpoint.")
    method: str = Field(default="GET", description="HTTP method.")
    auth_header: str | None = Field(None, description="Optional auth header value for authenticated endpoints.")
    description: str = Field(default="", description="What this endpoint does.")


class CreateJobRequest(BaseModel):
    """Submit external targets for Red Team scanning."""
    tenant_id: str = Field(
        ...,
        description="Your agent or wallet ID (for job tracking).",
    )
    targets: list[RTaaSTargetSchema] = Field(
        ...,
        min_length=1,
        description="List of external endpoints to attack.",
    )
    attack_categories: list[str] | None = Field(
        None,
        description="Attack categories to run. None = all categories.",
    )
    intensity: str = Field(
        default="standard",
        description="Scan intensity: quick, standard, or thorough.",
    )


class VulnerabilitySchema(BaseModel):
    vuln_id: str
    severity: str
    category: str
    target_url: str
    title: str
    description: str
    evidence: str = ""
    cwe_id: str | None = None
    remediation: str = ""


class JobResponse(BaseModel):
    """RTaaS scanning job result."""
    job_id: str
    tenant_id: str
    status: str
    targets_count: int
    total_tests_run: int
    vulnerabilities_found: int
    security_score: float
    vulnerabilities: list[VulnerabilitySchema]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class JobListResponse(BaseModel):
    jobs: list[dict]
    total: int


# --- Endpoints ---

@router.post(
    "/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Red Team scanning job",
    description=(
        "Submit external endpoint URLs for penetration testing. "
        "Our Red Team swarm will attack the specified targets and return "
        "a structured vulnerability report with CWE mappings and remediation steps. "
        "Use this before deploying any agent-built tool to production."
    ),
)
async def create_job(
    request: CreateJobRequest,
    engine: RTaaSEngine = Depends(get_rtaas_engine),
):
    job = await engine.create_job(
        tenant_id=request.tenant_id,
        targets=[t.model_dump() for t in request.targets],
        attack_categories=request.attack_categories,
        intensity=request.intensity,
    )
    return _job_to_response(job)


@router.get(
    "/jobs",
    response_model=JobListResponse,
    summary="List scanning jobs",
    description="View all RTaaS jobs, optionally filtered by tenant.",
)
async def list_jobs(
    tenant_id: str | None = Query(None),
    engine: RTaaSEngine = Depends(get_rtaas_engine),
):
    jobs = await engine.list_jobs(tenant_id)
    return JobListResponse(
        jobs=[
            {
                "job_id": j.job_id,
                "tenant_id": j.tenant_id,
                "status": j.status,
                "targets_count": len(j.targets),
                "vulnerabilities_found": len(j.vulnerabilities),
                "security_score": j.security_score,
                "created_at": j.created_at,
            }
            for j in jobs
        ],
        total=len(jobs),
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="Get job details",
    description="Retrieve the full vulnerability report for an RTaaS job.",
)
async def get_job(
    job_id: str,
    engine: RTaaSEngine = Depends(get_rtaas_engine),
):
    job = await engine.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "job_not_found"},
        )
    return _job_to_response(job)


@router.get(
    "/jobs/{job_id}/vulnerabilities",
    summary="Get vulnerabilities for a job",
    description="Retrieve just the vulnerability list with remediation steps.",
)
async def get_vulnerabilities(
    job_id: str,
    severity: str | None = Query(None, description="Filter by severity"),
    engine: RTaaSEngine = Depends(get_rtaas_engine),
):
    job = await engine.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "job_not_found"},
        )

    vulns = job.vulnerabilities
    if severity:
        vulns = [v for v in vulns if v.severity.value == severity]

    return {
        "job_id": job_id,
        "total": len(vulns),
        "vulnerabilities": [
            {
                "vuln_id": v.vuln_id,
                "severity": v.severity.value,
                "category": v.category.value,
                "target_url": v.target_url,
                "title": v.title,
                "description": v.description,
                "evidence": v.evidence,
                "cwe_id": v.cwe_id,
                "remediation": v.remediation,
            }
            for v in vulns
        ],
    }


def _job_to_response(job) -> JobResponse:
    return JobResponse(
        job_id=job.job_id,
        tenant_id=job.tenant_id,
        status=job.status,
        targets_count=len(job.targets),
        total_tests_run=job.total_tests_run,
        vulnerabilities_found=len(job.vulnerabilities),
        security_score=job.security_score,
        vulnerabilities=[
            VulnerabilitySchema(
                vuln_id=v.vuln_id,
                severity=v.severity.value,
                category=v.category.value,
                target_url=v.target_url,
                title=v.title,
                description=v.description,
                evidence=v.evidence,
                cwe_id=v.cwe_id,
                remediation=v.remediation,
            )
            for v in job.vulnerabilities
        ],
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )
