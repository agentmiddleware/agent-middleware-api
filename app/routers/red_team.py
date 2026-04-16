"""
Red Team Security Swarm Router
-------------------------------
Endpoints for triggering, monitoring, and reviewing automated
security scans against all API services.

The swarm runs 7 attack categories across all 33+ endpoints:
ACL bypass, auth probes, injection, rate limit evasion,
privilege escalation, schema abuse, and enumeration.

All findings are machine-readable so the Autonomous PM
can auto-generate fix PRs.
"""

from fastapi import APIRouter, Depends, HTTPException

from ..core.auth import verify_api_key
from ..core.dependencies import get_red_team_swarm
from ..services.red_team import RedTeamSwarm
from ..schemas.red_team import (
    ScanRequest,
    ScanResponse,
    ScanReport,
    ScanListResponse,
    VulnerabilityListResponse,
    Severity,
)

router = APIRouter(
    prefix="/v1/security",
    tags=["Red Team Security Swarm"],
    dependencies=[Depends(verify_api_key)],
)


@router.post(
    "/scans",
    response_model=ScanResponse,
    status_code=202,
    summary="Launch Red Team scan",
    description=(
        "Deploy the security swarm to attack specified services with selected "
        "attack categories. Returns immediately with scan ID; the swarm runs "
        "asynchronously. Default: full scan of all services with all vectors."
    ),
)
async def launch_scan(
    request: ScanRequest,
    swarm: RedTeamSwarm = Depends(get_red_team_swarm),
):
    report = await swarm.run_scan(
        target_services=request.target_services,
        attack_categories=request.attack_categories,
        intensity=request.intensity,
        auto_remediate=request.auto_remediate,
    )
    return ScanResponse(
        scan_id=report.scan_id,
        status=report.status,
        target_services=report.target_services,
        attack_categories=report.attack_categories,
        intensity=report.intensity,
        estimated_duration_seconds=int(report.duration_seconds or 0),
        total_attack_vectors=report.total_tests_run,
    )


@router.get(
    "/scans",
    response_model=ScanListResponse,
    summary="List all security scans",
    description="Returns all historical scan reports, newest first.",
)
async def list_scans(
    swarm: RedTeamSwarm = Depends(get_red_team_swarm),
):
    scans = await swarm.list_scans()
    scans.sort(key=lambda s: s.started_at, reverse=True)
    return ScanListResponse(scans=scans, total=len(scans))


@router.get(
    "/scans/{scan_id}",
    response_model=ScanReport,
    summary="Get scan report",
    description=(
        "Returns the full security scan report including all discovered "
        "vulnerabilities, severity breakdown, security score, and "
        "prioritized remediation recommendations."
    ),
)
async def get_scan_report(
    scan_id: str,
    swarm: RedTeamSwarm = Depends(get_red_team_swarm),
):
    report = await swarm.get_scan(scan_id)
    if not report:
        raise HTTPException(status_code=404, detail="Scan not found")
    return report


@router.get(
    "/scans/{scan_id}/vulnerabilities",
    response_model=VulnerabilityListResponse,
    summary="Get vulnerabilities from a scan",
    description=(
        "Returns just the vulnerabilities from a scan, optionally filtered "
        "by severity. Machine-readable format for the Autonomous PM "
        "to auto-generate fix PRs."
    ),
)
async def get_vulnerabilities(
    scan_id: str,
    severity: Severity | None = None,
    swarm: RedTeamSwarm = Depends(get_red_team_swarm),
):
    report = await swarm.get_scan(scan_id)
    if not report:
        raise HTTPException(status_code=404, detail="Scan not found")

    vulns = report.vulnerabilities
    if severity:
        vulns = [v for v in vulns if v.severity == severity]

    return VulnerabilityListResponse(
        vulnerabilities=vulns,
        total=len(vulns),
        critical_count=sum(1 for v in vulns if v.severity == Severity.CRITICAL),
        high_count=sum(1 for v in vulns if v.severity == Severity.HIGH),
    )


@router.post(
    "/scans/quick",
    response_model=ScanReport,
    summary="Quick security check",
    description=(
        "Runs a fast, surface-level scan focused on CRITICAL and HIGH severity "
        "vectors only (ACL bypass, auth probes, privilege escalation). "
        "Returns the full report synchronously — use for CI/CD gates."
    ),
)
async def quick_scan(
    swarm: RedTeamSwarm = Depends(get_red_team_swarm),
):
    from ..schemas.red_team import AttackCategory
    report = await swarm.run_scan(
        target_services=["iot", "telemetry", "media", "comms", "factory"],
        attack_categories=[
            AttackCategory.ACL_BYPASS,
            AttackCategory.AUTH_PROBE,
            AttackCategory.PRIVILEGE_ESCALATION,
        ],
        intensity="quick",
    )
    return report
