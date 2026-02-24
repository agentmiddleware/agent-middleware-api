"""
Red-Team-as-a-Service (RTaaS) — Pillar 12
============================================
Multi-tenant security scanning for agent-built tools.

When an agent builds a tool, it can hire our Red Team swarm to
attack its endpoints before deployment. The RTaaS layer wraps the
internal Red Team with tenant isolation, job tracking, and
structured vulnerability reports.

Architecture:
  External Agent → POST /v1/rtaas/jobs → RTaaS Engine
    → Spawns scan against EXTERNAL endpoints
    → Returns structured vulnerability JSON
    → Agent patches → re-scans → deploys

Unlike the internal /v1/security endpoints (which attack our own API),
RTaaS attacks *external* services specified by the requesting agent.
"""

import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..schemas.red_team import AttackCategory, Severity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RTaaS Job Model
# ---------------------------------------------------------------------------

@dataclass
class RTaaSTarget:
    """An external endpoint to attack."""
    url: str
    method: str = "GET"
    auth_header: str | None = None
    description: str = ""


@dataclass
class RTaaSVulnerability:
    """A vulnerability found during external scanning."""
    vuln_id: str
    severity: Severity
    category: AttackCategory
    target_url: str
    title: str
    description: str
    evidence: str = ""
    cwe_id: str | None = None
    remediation: str = ""


@dataclass
class RTaaSJob:
    """A multi-tenant Red Team scanning job."""
    job_id: str
    tenant_id: str  # The agent/wallet requesting the scan
    targets: list[RTaaSTarget]
    attack_categories: list[AttackCategory]
    intensity: str = "standard"  # "quick", "standard", "thorough"
    status: str = "pending"      # "pending", "running", "completed", "failed"
    vulnerabilities: list[RTaaSVulnerability] = field(default_factory=list)
    total_tests_run: int = 0
    security_score: float = 0.0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# RTaaS Engine
# ---------------------------------------------------------------------------

class RTaaSEngine:
    """
    Multi-tenant Red Team scanning engine.

    Operations:
    1. create_job()   — Submit external targets for penetration testing
    2. get_job()      — Check job status and results
    3. list_jobs()    — View all jobs for a tenant
    """

    def __init__(self):
        self._jobs: dict[str, RTaaSJob] = {}

    async def create_job(
        self,
        tenant_id: str,
        targets: list[dict],
        attack_categories: list[str] | None = None,
        intensity: str = "standard",
    ) -> RTaaSJob:
        """Create and execute an RTaaS scanning job against external endpoints."""
        job_id = f"rtaas-{uuid.uuid4().hex[:12]}"

        parsed_targets = [
            RTaaSTarget(
                url=t["url"],
                method=t.get("method", "GET"),
                auth_header=t.get("auth_header"),
                description=t.get("description", ""),
            )
            for t in targets
        ]

        categories = [
            AttackCategory(c) for c in attack_categories
        ] if attack_categories else list(AttackCategory)

        job = RTaaSJob(
            job_id=job_id,
            tenant_id=tenant_id,
            targets=parsed_targets,
            attack_categories=categories,
            intensity=intensity,
            status="running",
            started_at=datetime.now(timezone.utc),
        )

        # Simulate scanning
        vulns, tests_run, score = self._simulate_external_scan(
            parsed_targets, categories, intensity
        )
        job.vulnerabilities = vulns
        job.total_tests_run = tests_run
        job.security_score = score
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)

        self._jobs[job_id] = job
        logger.info(
            f"RTaaS job {job_id}: {len(vulns)} vulns found across "
            f"{len(parsed_targets)} targets ({tests_run} tests)"
        )
        return job

    def _simulate_external_scan(
        self,
        targets: list[RTaaSTarget],
        categories: list[AttackCategory],
        intensity: str,
    ) -> tuple[list[RTaaSVulnerability], int, float]:
        """Simulate scanning external endpoints.

        Production: this would use OWASP ZAP, Nuclei, or custom fuzzers
        against actual HTTP endpoints.
        """
        import hashlib

        vulns = []
        tests_per_target = {"quick": 8, "standard": 15, "thorough": 25}
        num_tests = tests_per_target.get(intensity, 15)
        total_tests = len(targets) * len(categories) * num_tests

        # Deterministic simulation based on target URLs
        for target in targets:
            url_hash = int(hashlib.md5(target.url.encode()).hexdigest()[:8], 16)

            for cat in categories:
                # Simulate finding vulnerabilities probabilistically
                if (url_hash + hash(cat.value)) % 7 == 0:
                    severity = Severity.HIGH if url_hash % 3 == 0 else Severity.MEDIUM
                    vulns.append(RTaaSVulnerability(
                        vuln_id=f"v-{uuid.uuid4().hex[:8]}",
                        severity=severity,
                        category=cat,
                        target_url=target.url,
                        title=f"{cat.value.replace('_', ' ').title()} vulnerability detected",
                        description=f"Potential {cat.value} issue at {target.url}",
                        evidence=f"Simulated attack against {target.method} {target.url}",
                        cwe_id=self._cwe_for_category(cat),
                        remediation=self._remediation_for_category(cat),
                    ))

                if (url_hash + hash(cat.value)) % 11 == 0:
                    vulns.append(RTaaSVulnerability(
                        vuln_id=f"v-{uuid.uuid4().hex[:8]}",
                        severity=Severity.LOW,
                        category=cat,
                        target_url=target.url,
                        title=f"Minor {cat.value.replace('_', ' ')} finding",
                        description=f"Low-risk {cat.value} observation",
                        evidence="Informational finding from automated scan",
                        cwe_id=self._cwe_for_category(cat),
                        remediation="Consider hardening as a best practice.",
                    ))

        # Score: 100 - penalty per vuln
        penalty = sum(
            {"critical": 25, "high": 15, "medium": 8, "low": 3}.get(v.severity.value, 5)
            for v in vulns
        )
        score = max(0, min(100, 100 - penalty))

        return vulns, total_tests, score

    def _cwe_for_category(self, cat: AttackCategory) -> str:
        mapping = {
            AttackCategory.ACL_BYPASS: "CWE-285",
            AttackCategory.AUTH_PROBE: "CWE-287",
            AttackCategory.INJECTION: "CWE-89",
            AttackCategory.RATE_LIMIT_EVASION: "CWE-770",
            AttackCategory.PRIVILEGE_ESCALATION: "CWE-269",
            AttackCategory.SCHEMA_ABUSE: "CWE-20",
            AttackCategory.ENUMERATION: "CWE-200",
            AttackCategory.REPLAY: "CWE-294",
            AttackCategory.DOS_PATTERN: "CWE-400",
        }
        return mapping.get(cat, "CWE-000")

    def _remediation_for_category(self, cat: AttackCategory) -> str:
        mapping = {
            AttackCategory.ACL_BYPASS: "Implement topic-level ACLs. Validate resource ownership per request.",
            AttackCategory.AUTH_PROBE: "Enforce authentication on all endpoints. Validate API keys server-side.",
            AttackCategory.INJECTION: "Sanitize all user inputs. Use parameterized queries.",
            AttackCategory.RATE_LIMIT_EVASION: "Add sliding-window rate limiting per API key.",
            AttackCategory.PRIVILEGE_ESCALATION: "Enforce principle of least privilege. Check role on every request.",
            AttackCategory.SCHEMA_ABUSE: "Validate all input schemas strictly. Reject unexpected types.",
            AttackCategory.ENUMERATION: "Use non-sequential IDs. Audit response payloads for data leaks.",
            AttackCategory.REPLAY: "Add nonce or timestamp validation. Use short-lived tokens.",
            AttackCategory.DOS_PATTERN: "Add request timeouts and resource limits. Cap expensive operations.",
        }
        return mapping.get(cat, "Review and harden the affected endpoint.")

    async def get_job(self, job_id: str) -> RTaaSJob | None:
        return self._jobs.get(job_id)

    async def list_jobs(self, tenant_id: str | None = None) -> list[RTaaSJob]:
        jobs = list(self._jobs.values())
        if tenant_id:
            jobs = [j for j in jobs if j.tenant_id == tenant_id]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)
