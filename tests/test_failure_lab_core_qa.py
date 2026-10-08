"""QA pass over failure_lab core (runner, evidence, faults, verifier, steps).

Fast, deterministic unit tests for behavior the existing suite does not pin:
bundle integrity verification against malformed input, fault plan validation,
the runner's error and evidence-harvest paths, the web selection gate, the
ledger's reset path, and the verifier's input handling.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from failure_lab.evidence import verify_bundle_integrity
from failure_lab.faults import FaultInjector, FaultMode, FaultPlan


def _write_bundle(tmp_path: Path, manifest: dict, files: dict[str, bytes]) -> Path:
    root = tmp_path / "bundle"
    root.mkdir(exist_ok=True)
    for name, payload in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _manifest_for(files: dict[str, bytes]) -> dict:
    return {
        "files": [
            {"path": name, "sha256": _sha(payload), "bytes": len(payload)}
            for name, payload in files.items()
        ]
    }


class TestVerifyBundleIntegrityMalformedInput:
    def test_clean_bundle_verifies(self, tmp_path):
        files = {"environment.json": b'{"run": 1}\n'}
        root = _write_bundle(tmp_path, _manifest_for(files), files)
        report = verify_bundle_integrity(root)
        assert report.ok
        assert report.checked == 1
        assert report.problems == []

    def test_files_that_is_not_a_list_is_reported_not_raised(self, tmp_path):
        root = _write_bundle(tmp_path, {"files": {"a.json": 1}}, {})
        report = verify_bundle_integrity(root)
        assert not report.ok
        assert report.problems

    def test_non_mapping_entry_is_reported_not_raised(self, tmp_path):
        root = _write_bundle(tmp_path, {"files": ["environment.json"]}, {})
        report = verify_bundle_integrity(root)
        assert not report.ok
        assert report.problems

    def test_non_integer_bytes_is_reported_not_raised(self, tmp_path):
        files = {"environment.json": b"{}\n"}
        manifest = _manifest_for(files)
        manifest["files"][0]["bytes"] = "lots"
        root = _write_bundle(tmp_path, manifest, files)
        report = verify_bundle_integrity(root)
        assert not report.ok
        assert any("environment.json" in problem for problem in report.problems)

    def test_absolute_path_entry_is_not_read(self, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_bytes(b"not part of the bundle")
        manifest = {
            "files": [
                {"path": str(outside), "sha256": "x", "bytes": 1},
            ]
        }
        root = _write_bundle(tmp_path, manifest, {})
        report = verify_bundle_integrity(root)
        assert not report.ok
        assert report.checked == 0
        assert report.problems

    def test_parent_traversal_entry_is_not_read(self, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_bytes(b"not part of the bundle")
        manifest = {
            "files": [
                {"path": "../outside.txt", "sha256": "x", "bytes": 1},
            ]
        }
        root = _write_bundle(tmp_path, manifest, {})
        report = verify_bundle_integrity(root)
        assert not report.ok
        assert report.checked == 0
        assert report.problems


class TestFaultPlanValidation:
    def test_negative_remaining_is_refused(self):
        with pytest.raises(ValueError):
            FaultPlan.from_dict({"mode": "delayed", "remaining": -1})

    def test_negative_delay_is_refused(self):
        with pytest.raises(ValueError):
            FaultPlan.from_dict({"mode": "delayed", "delay_ms": -50})

    def test_negative_hold_is_refused(self):
        with pytest.raises(ValueError):
            FaultPlan.from_dict(
                {"mode": "response_lost_after_execution", "hold_seconds": -1.0}
            )

    def test_zero_values_stay_legal(self):
        plan = FaultPlan.from_dict(
            {"mode": "delayed", "remaining": 0, "delay_ms": 0, "hold_seconds": 0.0}
        )
        assert plan.remaining == 0
        assert plan.delay_ms == 0
        assert plan.hold_seconds == 0.0

    def test_valid_plan_round_trips(self):
        plan = FaultPlan.from_dict(
            {
                "mode": "connection_failure_after_execution",
                "operation_id": "refund:pay_1",
                "remaining": 2,
                "label": "qa",
            }
        )
        assert plan.mode is FaultMode.CONNECTION_FAILURE_AFTER_EXECUTION
        assert plan.operation_id == "refund:pay_1"
        assert plan.remaining == 2
        assert FaultPlan.from_dict(plan.as_dict()).mode is plan.mode


class TestFaultInjectorSelection:
    def test_plan_fires_once_then_passes_through(self):
        injector = FaultInjector()
        injector.arm(FaultPlan(mode=FaultMode.HTTP_ERROR_BEFORE_EXECUTION, remaining=1))
        assert injector._select("tools_call", None) is not None
        assert injector._select("tools_call", None) is None

    def test_operation_scoped_plan_ignores_other_operations(self):
        injector = FaultInjector()
        injector.arm(
            FaultPlan(
                mode=FaultPlan.from_dict({"mode": "http_error_before_execution"}).mode,
                operation_id="refund:pay_1",
                remaining=1,
            )
        )
        assert injector._select("tools_call", "refund:pay_2") is None
        assert injector._select("tools_call", "refund:pay_1") is not None
        assert injector.armed() == []


def _configuration_result(
    configuration: str = "A_direct_naive",
    verdict=None,
    extra=None,
):
    from failure_lab.scenarios.base import (
        ConfigurationResult,
        Counters,
        Verdict,
    )

    return ConfigurationResult(
        configuration=configuration,
        label=configuration,
        verdict=verdict or Verdict.PASS,
        expectation="",
        observation="",
        counters=Counters(),
        extra=dict(extra or {}),
    )


def _scenario_result(configurations, expected=None, test_id="T99"):
    from failure_lab.scenarios.base import ScenarioResult

    return ScenarioResult(
        test_id=test_id,
        title="qa probe",
        claim="probe claim",
        definition_version="test",
        definition_hash="hash",
        started_at="2026-01-01T00:00:00",
        finished_at="2026-01-01T00:00:01",
        configurations=list(configurations),
        limitations=[],
        events=[],
        expected=dict(expected or {}),
    )


class TestExitStatus:
    def test_empty_results_are_not_presented_as_a_pass(self):
        from failure_lab.runner import EXIT_OK, exit_status_for

        assert exit_status_for([]) == EXIT_OK

    def test_error_outranks_divergence(self):
        from failure_lab.runner import EXIT_SCENARIO_ERROR, exit_status_for
        from failure_lab.scenarios.base import Verdict

        errored = _scenario_result(
            [_configuration_result(verdict=Verdict.ERROR)],
            expected={"A_direct_naive": "PASS"},
        )
        assert exit_status_for([errored]) == EXIT_SCENARIO_ERROR

    def test_divergence_is_a_release_blocker(self):
        from failure_lab.runner import EXIT_EXPECTATION_DIVERGED, exit_status_for
        from failure_lab.scenarios.base import Verdict

        diverged = _scenario_result(
            [_configuration_result(verdict=Verdict.FAIL)],
            expected={"A_direct_naive": "PASS"},
        )
        assert exit_status_for([diverged]) == EXIT_EXPECTATION_DIVERGED

    def test_matching_run_is_clean(self):
        from failure_lab.runner import EXIT_OK, exit_status_for
        from failure_lab.scenarios.base import Verdict

        clean = _scenario_result(
            [_configuration_result(verdict=Verdict.PASS)],
            expected={"A_direct_naive": "PASS"},
        )
        assert exit_status_for([clean]) == EXIT_OK


class TestErrorResult:
    def test_crash_becomes_an_error_row_not_a_pass(self):
        from failure_lab.runner import HARNESS_CONFIGURATION, error_result
        from failure_lab.scenarios import get_scenario
        from failure_lab.scenarios.base import Verdict

        scenario = get_scenario("T03")
        result = error_result(
            scenario,
            RuntimeError("boom"),
            started_at="2026-01-01T00:00:00",
            finished_at="2026-01-01T00:00:01",
        )
        assert result.verdict == Verdict.ERROR
        by_configuration = {
            entry.configuration: entry for entry in result.configurations
        }
        for configuration in scenario.configurations:
            assert by_configuration[configuration.value].verdict == Verdict.NOT_RUN
        harness = by_configuration[HARNESS_CONFIGURATION]
        assert harness.verdict == Verdict.ERROR
        assert "boom" in harness.observation


class TestHarvestEvidence:
    def test_unknown_shapes_are_noted_never_dropped_silently(self):
        from failure_lab.runner import harvest_evidence

        result = _scenario_result(
            [
                _configuration_result(
                    extra={
                        "portable_receipts": "not-a-mapping-or-list",
                        "verification_results": {"not": "a-list"},
                        "trust_keys": ["not-a-mapping"],
                    }
                )
            ]
        )
        notes: list[str] = []
        receipts, verifications, keys = harvest_evidence([result], notes)
        assert receipts == {}
        assert verifications == []
        assert keys is None
        assert len(notes) == 3

    def test_mapping_receipts_merge_and_lists_are_keyed(self):
        from failure_lab.runner import harvest_evidence

        result = _scenario_result(
            [
                _configuration_result(
                    extra={"portable_receipts": {"r1": {"receipt_id": "r1"}}}
                ),
                _configuration_result(
                    configuration="B_direct_native_idempotency",
                    extra={"portable_receipts": [{"amount": 1}]},
                ),
            ]
        )
        receipts, _, _ = harvest_evidence([result], [])
        assert set(receipts) == {"r1", "T99-B_direct_native_idempotency-000"}

    def test_a_second_different_key_document_is_recorded(self):
        from failure_lab.runner import harvest_evidence

        first = _scenario_result(
            [_configuration_result(extra={"trust_keys": {"keys": [{"kid": "a"}]}})],
            test_id="T01",
        )
        second = _scenario_result(
            [_configuration_result(extra={"trust_keys": {"keys": [{"kid": "b"}]}})],
            test_id="T02",
        )
        notes: list[str] = []
        _, _, keys = harvest_evidence([first, second], notes)
        assert keys == {"keys": [{"kid": "a"}]}
        assert len(notes) == 1
        assert "T02" in notes[0]


class TestSelectWebScenarios:
    def test_unknown_id_is_refused(self):
        from failure_lab.diagnostic.runs import RunRefused, select_web_scenarios

        with pytest.raises(RunRefused):
            select_web_scenarios(["T99"])

    def test_non_list_selection_is_refused(self):
        from failure_lab.diagnostic.runs import RunRefused, select_web_scenarios

        with pytest.raises(RunRefused):
            select_web_scenarios(42)

    def test_ids_are_case_insensitive_and_deduplicated(self):
        from failure_lab.diagnostic.runs import select_web_scenarios

        assert select_web_scenarios(["t03", "T03"], allowed=("T03",)) == ["T03"]

    def test_too_many_scenarios_are_refused(self):
        from failure_lab.diagnostic.runs import RunRefused, select_web_scenarios

        with pytest.raises(RunRefused):
            select_web_scenarios(
                ["A", "B", "C", "D"], allowed=("A", "B", "C", "D", "E")
            )


class TestEffectLedgerMaintenance:
    def test_reset_clears_effects_and_native_results(self, tmp_path):
        from failure_lab.effect_ledger import EffectLedger

        ledger = EffectLedger(tmp_path / "effects.db")
        common = dict(
            request_id="req_1",
            idempotency_key="k",
            amount=5000,
            currency="USD",
            customer_id="cus",
            payment_id="pay",
            configuration="test",
        )
        ledger.execute(operation_id="refund:pay", native_fingerprint="fp", **common)
        assert ledger.execution_count("refund:pay") == 1
        ledger.reset()
        assert ledger.execution_count("refund:pay") == 0
        assert ledger.snapshot() == []
        replay = ledger.execute(
            operation_id="refund:pay", native_fingerprint="other", **common
        )
        assert replay.replayed is False

    def test_snapshot_carries_the_prd_ledger_shape(self, tmp_path):
        from failure_lab.effect_ledger import EffectLedger

        ledger = EffectLedger(tmp_path / "effects.db")
        ledger.execute(
            operation_id="refund:pay",
            request_id="req_1",
            idempotency_key="k",
            amount=5000,
            currency="USD",
            customer_id="cus",
            payment_id="pay",
            configuration="test",
        )
        (row,) = ledger.snapshot()
        assert row["operation_id"] == "refund:pay"
        assert row["execution_count"] == 1
        assert row["execution_ordinal"] == 1


class TestOperationIdentity:
    def test_restart_bumps_generation_and_keeps_business_operation(self):
        from failure_lab.identity import KeyPolicy, OperationIdentity

        first = OperationIdentity.first_attempt(
            "refund:pay_1", key_policy=KeyPolicy.BUSINESS
        )
        restarted = first.after_restart()
        assert restarted.agent_generation == first.agent_generation + 1
        assert restarted.business_operation_id == first.business_operation_id
        assert restarted.request_id != first.request_id

    def test_new_key_policy_mints_a_fresh_key_on_restart(self):
        from failure_lab.identity import KeyPolicy, OperationIdentity

        first = OperationIdentity.first_attempt(
            "refund:pay_1", key_policy=KeyPolicy.ATTEMPT
        )
        restarted = first.after_restart()
        assert restarted.idempotency_key != first.idempotency_key


class TestStepTranslation:
    def test_unknown_configuration_is_setup(self):
        from failure_lab.diagnostic.steps import PHASE_SETUP, phase_for

        assert phase_for("no-such-configuration") == PHASE_SETUP
        assert phase_for("") == PHASE_SETUP

    def test_unknown_step_renders_its_message(self):
        from failure_lab.diagnostic.steps import translate_all

        (step,) = translate_all(
            [
                {
                    "step": "t99.something_new",
                    "message": "a new line",
                    "at": "2026-01-01T00:00:00",
                    "scenario": "T99",
                    "configuration": "",
                    "data": {},
                }
            ]
        )
        assert step.text == "a new line"
        assert step.source_step == "t99.something_new"

    def test_empty_unknown_step_emits_no_line(self):
        from failure_lab.diagnostic.steps import translate_all

        assert (
            translate_all(
                [
                    {
                        "step": "t99.something_new",
                        "message": "",
                        "at": "2026-01-01T00:00:00",
                        "scenario": "T99",
                        "configuration": "",
                        "data": {},
                    }
                ]
            )
            == []
        )


class TestVerifierInputHandling:
    def test_non_json_bundle_fails_without_raising(self):
        from failure_lab.verifier import ClaimStatus, verify

        report = verify("this is not json", {})
        assert report.signature.status is ClaimStatus.FAILED

    def test_non_object_bundle_fails_without_raising(self):
        from failure_lab.verifier import ClaimStatus, verify

        report = verify([1, 2, 3], {})
        assert report.signature.status is ClaimStatus.FAILED


class TestLabTelemetry:
    def test_human_customer_is_unreachable_by_detection(self):
        from failure_lab.telemetry import TrafficSource, detect_traffic_source

        assert detect_traffic_source({}) is TrafficSource.UNKNOWN
        assert (
            detect_traffic_source({"FAILURE_LAB_INTERNAL_TEST": "1"})
            is TrafficSource.INTERNAL_TEST
        )
        assert (
            detect_traffic_source({"AGENT_HARNESS": "1"}) is TrafficSource.AI_TEST_AGENT
        )
        assert detect_traffic_source({"CI": "true"}) is TrafficSource.CI_RUN
        assert detect_traffic_source({"CI": "true", "AGENT_HARNESS": "1"}) is (
            TrafficSource.CI_RUN
        )

    def test_funnel_counts_humans_and_reports_what_it_dropped(self):
        from failure_lab.telemetry import (
            Event,
            EventName,
            TrafficSource,
            funnel,
        )

        events = [
            Event(
                name=EventName.DIAGNOSTIC_STARTED,
                traffic_source=TrafficSource.HUMAN_CUSTOMER,
                subject="sub_aaa",
            ),
            Event(
                name=EventName.DIAGNOSTIC_STARTED,
                traffic_source=TrafficSource.INTERNAL_TEST,
                subject="sub_bbb",
            ),
        ]
        result = funnel(events)
        assert result.counted_events == 1
        assert result.excluded_events_by_source == {"internal_test": 1}
        assert result.excluded_subjects_by_source == {"internal_test": 1}
        assert result.stages[0].subjects == 1
