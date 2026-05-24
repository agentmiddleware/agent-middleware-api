from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.trust_mode import is_production_like_environment

TrustReadinessStatus = Literal[
    "verified",
    "partially_verified",
    "demo_only",
    "not_verified",
    "blocked",
]
TrustReadinessSeverity = Literal["critical", "high", "medium", "low", "info"]
TrustReadinessVerdict = Literal["pilot-ready", "needs-work", "blocked"]


class TrustReadinessItem(BaseModel):
    id: str
    area: str
    status: TrustReadinessStatus
    severity: TrustReadinessSeverity
    claim: str
    evidence: list[str] = Field(default_factory=list)
    gap: str | None = None
    recommended_next_step: str


class TrustReadinessReport(BaseModel):
    checked_at: datetime
    verdict: TrustReadinessVerdict
    total_items: int
    by_status: dict[str, int]
    critical_gaps: list[str]
    items: list[TrustReadinessItem]


def _item(
    *,
    id: str,
    area: str,
    status: TrustReadinessStatus,
    severity: TrustReadinessSeverity,
    claim: str,
    evidence: list[str],
    recommended_next_step: str,
    gap: str | None = None,
) -> TrustReadinessItem:
    return TrustReadinessItem(
        id=id,
        area=area,
        status=status,
        severity=severity,
        claim=claim,
        evidence=evidence,
        gap=gap,
        recommended_next_step=recommended_next_step,
    )


def _strict_trust_mode_item(settings: Settings) -> TrustReadinessItem:
    strict_enabled = (
        settings.TRUST_MODE_ENABLED
        and not settings.ALLOW_LEGACY_UNPERMITTED_MCP
        and bool(settings.TRUST_SIGNING_PRIVATE_KEY_B64.strip())
    )
    production_like = is_production_like_environment(settings.ENVIRONMENT)

    if strict_enabled:
        return _item(
            id="strict_trust_mode",
            area="deployment",
            status="verified",
            severity="info",
            claim=(
                "Strict trust mode is configured with permit-required MCP and "
                "signing key material."
            ),
            evidence=[
                "app/core/config.py:51",
                "app/core/trust_mode.py:54",
                "tests/test_trust_mode_guardrails.py:45",
            ],
            recommended_next_step=(
                "Keep TRUST_MODE_ENABLED=true and "
                "ALLOW_LEGACY_UNPERMITTED_MCP=false in production-like deploys."
            ),
        )

    if production_like:
        return _item(
            id="strict_trust_mode",
            area="deployment",
            status="blocked",
            severity="critical",
            claim=(
                "Production-like environments must fail closed on governed MCP "
                "trust mode."
            ),
            evidence=[
                "app/core/trust_mode.py:54",
                "tests/test_trust_mode_guardrails.py:57",
                "TRUST_MODEL.md:32",
            ],
            gap=(
                "Current settings do not satisfy strict trust mode: require "
                "TRUST_MODE_ENABLED=true, ALLOW_LEGACY_UNPERMITTED_MCP=false, "
                "and TRUST_SIGNING_PRIVATE_KEY_B64."
            ),
            recommended_next_step=(
                "Set strict trust-mode environment variables before using this "
                "deployment for a paid pilot."
            ),
        )

    return _item(
        id="strict_trust_mode",
        area="deployment",
        status="partially_verified",
        severity="medium",
        claim=(
            "Strict trust-mode guardrails exist, but this environment is running "
            "local-compatible settings."
        ),
        evidence=[
            "app/core/config.py:51",
            "app/core/trust_mode.py:54",
            "tests/test_trust_mode_guardrails.py:17",
        ],
        gap=(
            "Local defaults allow legacy unpermitted MCP for compatibility; that "
            "is not the production trust posture."
        ),
        recommended_next_step=(
            "Use production-like env settings in the hosted demo and paid-pilot "
            "environment."
        ),
    )


def _sandbox_item(settings: Settings) -> TrustReadinessItem:
    if settings.BEHAVIORAL_SANDBOX_PYTHON_BACKEND == "docker":
        return _item(
            id="sandbox_isolation",
            area="tool_execution",
            status="partially_verified",
            severity="medium",
            claim="Behavioral sandbox has a Docker process boundary when enabled.",
            evidence=[
                "app/core/config.py:138",
                "app/routers/sandbox_behavioral.py:8",
                "tests/test_behavioral_sandbox.py",
            ],
            gap=(
                "Docker isolation is stronger than host subprocess execution, but "
                "not yet a full managed sandbox boundary with network policy."
            ),
            recommended_next_step=(
                "Keep arbitrary public code execution disabled until container "
                "network and resource policy are explicit."
            ),
        )

    return _item(
        id="sandbox_isolation",
        area="tool_execution",
        status="partially_verified",
        severity="high",
        claim="Public arbitrary-code execution is not production-ready by default.",
        evidence=[
            "app/core/config.py:138",
            "app/routers/sandbox_behavioral.py:8",
            "docs/threat-model.md:100",
        ],
        gap=(
            "The default sandbox backend is disabled; unsafe host execution is "
            "explicitly not a production boundary."
        ),
        recommended_next_step=(
            "Do not include arbitrary-code execution in the paid-pilot wedge unless "
            "Docker or a stronger sandbox is configured and tested."
        ),
    )


def _static_items() -> list[TrustReadinessItem]:
    return [
        _item(
            id="product_boundary",
            area="positioning",
            status="verified",
            severity="info",
            claim="The credible product wedge is a governed MCP trust plane.",
            evidence=["WEDGE.md:4", "AGENTS.md:8", "docs/related-work.md:18"],
            recommended_next_step=(
                "Keep AWI and broad platform claims subordinate to the trust-plane "
                "wedge."
            ),
        ),
        _item(
            id="machine_readable_discovery",
            area="discovery",
            status="verified",
            severity="info",
            claim="Agents can discover manifests, MCP tools, OpenAPI, and llm.txt.",
            evidence=[
                "app/routers/well_known.py:24",
                "app/routers/mcp.py:150",
                "tests/test_discovery_drift.py:48",
            ],
            recommended_next_step=(
                "Keep discovery drift tests in the release gate."
            ),
        ),
        _item(
            id="signed_permits",
            area="authorization",
            status="verified",
            severity="info",
            claim=(
                "Signed permits bind wallet, key, tool scope, budget, expiry, and "
                "nonce."
            ),
            evidence=[
                "app/services/permits.py:116",
                "app/services/permits.py:193",
                "tests/test_permits.py",
            ],
            recommended_next_step=(
                "Add partner-facing examples for permit issuance and revocation."
            ),
        ),
        _item(
            id="governed_mcp_replay",
            area="invoke",
            status="verified",
            severity="info",
            claim=(
                "Governed MCP enforces permits and idempotency, and replay returns "
                "the original result."
            ),
            evidence=[
                "app/routers/mcp.py:336",
                "app/services/idempotency.py:30",
                "tests/test_mcp_trust_mode.py",
                "tests/test_demo_trust_plane.py:29",
            ],
            recommended_next_step=(
                "Keep agent-comms-send as the canonical paid-pilot governed MCP "
                "tool until partner feedback forces another slice."
            ),
        ),
        _item(
            id="metered_ledger",
            area="metering",
            status="verified",
            severity="info",
            claim="Successful governed invokes debit wallet credits and write ledger entries.",
            evidence=[
                "app/services/agent_money.py:744",
                "app/routers/mcp.py:605",
                "tests/test_demo_trust_plane.py:25",
            ],
            recommended_next_step=(
                "Keep settlement language separate from internal credit metering."
            ),
        ),
        _item(
            id="signed_receipts_evidence",
            area="receipt",
            status="verified",
            severity="info",
            claim=(
                "Receipts are signed and can be linked to permit, ledger, audit, "
                "and request-hash evidence."
            ),
            evidence=[
                "app/services/receipts.py:42",
                "app/trust/evidence.py:199",
                "app/routers/evidence.py:17",
                "tests/test_receipts.py:133",
            ],
            recommended_next_step=(
                "Make the evidence bundle the main buyer-facing demo artifact."
            ),
        ),
        _item(
            id="audit_chain",
            area="audit",
            status="verified",
            severity="info",
            claim="Wallet audit events are signed and hash-linked.",
            evidence=[
                "app/services/audit_chain.py:128",
                "app/services/audit_chain.py:214",
                "tests/test_audit_chain.py:97",
            ],
            recommended_next_step=(
                "Keep tamper-detection tests in the trust release gate."
            ),
        ),
        _item(
            id="wallet_scoped_inspection",
            area="tenant_isolation",
            status="verified",
            severity="info",
            claim="Wallet keys can inspect only their own trust ledger records.",
            evidence=[
                "app/routers/me.py:21",
                "app/trust/evidence.py:175",
                "tests/test_me_trust_ledger.py:116",
            ],
            recommended_next_step=(
                "Add this as a standard enterprise trust talking point."
            ),
        ),
        _item(
            id="paid_pilot_real_tool",
            area="pilot",
            status="verified",
            severity="info",
            claim=(
                "The paid-pilot proof has one real internal tool behind the "
                "governed MCP path."
            ),
            evidence=[
                "app/services/paid_pilot_mcp_tools.py",
                "tests/test_paid_pilot_agent_comms_mcp.py",
                "scripts/demo_trust_plane.py",
            ],
            recommended_next_step=(
                "Run the design-partner demo with Agent Comms real mode enabled "
                "and keep the proof scoped to this tool until partner feedback."
            ),
        ),
        _item(
            id="awi_full_paper",
            area="awi",
            status="partially_verified",
            severity="medium",
            claim="The repo has AWI draft surfaces, not the full AWI paper outcome.",
            evidence=[
                "app/routers/awi.py:59",
                "app/services/awi_session.py:124",
                "app/routers/well_known.py:193",
                "tests/test_awi.py",
            ],
            gap=(
                "AWI is a proof surface and draft profile; external standardization "
                "and real website adoption are not verified."
            ),
            recommended_next_step=(
                "Keep AWI out of the core paid-pilot promise until a live workflow "
                "uses the same trust primitives end to end."
            ),
        ),
        _item(
            id="production_settlement",
            area="billing",
            status="not_verified",
            severity="high",
            claim="Production-ready payments or settlement are not claimable yet.",
            evidence=["WEDGE.md:64", "docs/related-work.md:59"],
            gap=(
                "Internal credit metering is verified; external settlement safety is "
                "not verified."
            ),
            recommended_next_step=(
                "Use internal metering language for pilots; keep Stripe settlement "
                "as a separate hardening milestone."
            ),
        ),
        _item(
            id="compliance_grade_ledger",
            area="compliance",
            status="not_verified",
            severity="high",
            claim="Compliance-grade ledger storage is not claimable yet.",
            evidence=["WEDGE.md:65", "docs/related-work.md:60"],
            gap=(
                "The ledger is useful for audit evidence, but compliance-grade "
                "retention, external audit, and controls are not verified."
            ),
            recommended_next_step=(
                "Define compliance requirements only after the paid-pilot trust loop "
                "is proven with a real tool."
            ),
        ),
        _item(
            id="proof_surface_governance",
            area="scope_control",
            status="demo_only",
            severity="medium",
            claim=(
                "AWI, media, IoT, oracle, red-team, sandbox, and content surfaces "
                "are proof surfaces, not the product spine."
            ),
            evidence=["WEDGE.md:50", "README.md:145"],
            gap=(
                "Not every proof surface consumes permit, receipt, idempotency, and "
                "audit primitives as its governing boundary."
            ),
            recommended_next_step=(
                "Freeze broad surface expansion; govern one real tool first."
            ),
        ),
    ]


def _verdict(items: list[TrustReadinessItem]) -> TrustReadinessVerdict:
    if any(item.status == "blocked" and item.severity == "critical" for item in items):
        return "blocked"
    unresolved = {"partially_verified", "demo_only", "not_verified", "blocked"}
    if any(item.status in unresolved and item.severity in {"critical", "high"} for item in items):
        return "needs-work"
    return "pilot-ready"


def build_trust_readiness_report(
    *,
    settings: Settings | None = None,
) -> TrustReadinessReport:
    current_settings = settings or get_settings()
    items = [
        *_static_items(),
        _strict_trust_mode_item(current_settings),
        _sandbox_item(current_settings),
    ]
    by_status = Counter(item.status for item in items)
    critical_gaps = [
        item.id
        for item in items
        if item.status != "verified" and item.severity == "critical"
    ]

    return TrustReadinessReport(
        checked_at=datetime.now(timezone.utc),
        verdict=_verdict(items),
        total_items=len(items),
        by_status=dict(sorted(by_status.items())),
        critical_gaps=critical_gaps,
        items=items,
    )


__all__ = [
    "TrustReadinessItem",
    "TrustReadinessReport",
    "build_trust_readiness_report",
]
