"""GTM-27 slice: simulated markers on scan reports and planner provenance.

Red-team and RTaaS findings are modeled, and planner candidates come
from the caller. These tests pin the payload-level labels so an
exported report or plan cannot be mistaken for live security testing
or for server-side tool discovery.
"""

import pytest
from pydantic import ValidationError

from app.optimizer.candidates import get_candidate_actions
from app.optimizer.planner import optimize_action_set
from app.routers.rtaas import _job_to_response
from app.schemas.optimizer import OptimizerRequest, OptimizerResponse, OptimizerState
from app.schemas.red_team import (
    ScanReport,
    ScanResponse,
    ScanStatus,
    VulnerabilityListResponse,
)
from app.services.rtaas import RTaaSJob


def _scan_kwargs(**overrides):
    base = dict(
        scan_id="scan-1",
        status=ScanStatus.COMPLETED,
        started_at="2026-01-01T00:00:00+00:00",
        target_services=["iot"],
        attack_categories=["acl_bypass"],
        intensity="quick",
        total_tests_run=8,
        total_passed=8,
        total_failed=0,
        vulnerabilities_found=0,
        score=100.0,
    )
    base.update(overrides)
    return base


def test_scan_report_is_marked_simulated_by_default():
    report = ScanReport(**_scan_kwargs())
    assert report.simulated is True
    assert report.model_dump()["simulated"] is True


def test_scan_report_rejects_non_simulated_flag():
    with pytest.raises(ValidationError):
        ScanReport(**_scan_kwargs(simulated=False))


def test_scan_response_and_vuln_list_are_marked_simulated():
    resp = ScanResponse(
        scan_id="scan-1",
        status=ScanStatus.COMPLETED,
        target_services=["iot"],
        attack_categories=["acl_bypass"],
        intensity="quick",
        estimated_duration_seconds=0,
        total_attack_vectors=8,
    )
    assert resp.model_dump()["simulated"] is True
    listing = VulnerabilityListResponse(
        vulnerabilities=[], total=0, critical_count=0, high_count=0
    )
    assert listing.model_dump()["simulated"] is True


def test_rtaas_job_response_is_marked_simulated():
    job = RTaaSJob(
        job_id="job-1",
        tenant_id="wallet-1",
        targets=[],
        attack_categories=[],
    )
    response = _job_to_response(job)
    assert response.simulated is True
    assert response.model_dump()["simulated"] is True


def test_get_candidate_actions_drops_unusable_entries():
    state = OptimizerState(
        wallet_id="w1",
        agent_id="a1",
        task_id="t1",
        request_id="r1",
        wallet_balance=100,
        daily_spend_used=0,
        daily_limit=100,
        rate_limit_headroom=1.0,
        service_health={"svc1": "healthy"},
        simulation_flags={},
        auth_scope=["invoke"],
        task_context={
            "candidate_actions": [
                {"id": "good", "service": "svc1"},
                {"service": "svc1"},
                "not-a-dict",
                {"id": ""},
                None,
            ]
        },
        remaining_budget=10,
        slo_window_seconds=5,
    )
    assert get_candidate_actions(state) == [{"id": "good", "service": "svc1"}]


def test_get_candidate_actions_handles_non_list():
    state = OptimizerState(
        wallet_id="w1",
        agent_id="a1",
        task_id="t1",
        request_id="r1",
        wallet_balance=100,
        daily_spend_used=0,
        daily_limit=100,
        rate_limit_headroom=1.0,
        service_health={},
        simulation_flags={},
        auth_scope=["invoke"],
        task_context={"candidate_actions": {"id": "nope"}},
        remaining_budget=10,
        slo_window_seconds=5,
    )
    assert get_candidate_actions(state) == []


def test_planner_response_names_caller_supplied_candidates():
    state = OptimizerState(
        wallet_id="w1",
        agent_id="a1",
        task_id="t1",
        request_id="r1",
        wallet_balance=100,
        daily_spend_used=0,
        daily_limit=100,
        rate_limit_headroom=1.0,
        service_health={"svc1": "healthy"},
        simulation_flags={},
        auth_scope=["invoke"],
        task_context={"tier": "medium"},
        remaining_budget=10,
        slo_window_seconds=5,
    )
    req = OptimizerRequest(state=state)
    out = optimize_action_set(
        state,
        [
            {
                "id": "a",
                "service": "svc1",
                "expected_value": 5,
                "reliability": 1.0,
                "credit_cost": 1,
                "latency_ms": 100,
                "risk_score": 0.01,
            }
        ],
        req,
    )
    assert out["candidate_source"] == "caller_supplied"
    parsed = OptimizerResponse(**out)
    assert parsed.candidate_source == "caller_supplied"
