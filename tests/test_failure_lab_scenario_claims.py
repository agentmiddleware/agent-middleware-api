"""Claim-exercise guards for the failure-lab scenario suite.

The audit flagged T06, T12 and T13: does each scenario actually exercise the
claim it reports, or does it report PASS over a workload that degenerated?
The scenario modules answer that at runtime with premise checks and controls.
What belongs here is the deterministic half of the same question: the pure
verdict helpers every scenario funnels through, tested without a database,
without sleeps and without network, so a future edit that weakens a verdict
rule fails fast.

Style follows tests/test_failure_lab_scenarios.py: plain pytest, no fixtures
unless a test needs the app.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from failure_lab.scenarios import (
    FAST_SCENARIO_IDS,
    SCENARIO_CLASSES,
    SLOW_SCENARIO_IDS,
    get_scenario,
    select_scenarios,
)
from failure_lab.scenarios.base import (
    REFUSED_STATUSES,
    Counters,
    EventLog,
    ScenarioResult,
    Verdict,
    _jsonable,
    percentile,
)


def _configuration_result(configuration: str, verdict: Verdict):
    from failure_lab.scenarios.base import ConfigurationResult

    return ConfigurationResult(
        configuration=configuration,
        label=configuration,
        verdict=verdict,
        expectation="",
        observation="measured",
        counters=Counters(),
    )


def _result_with_verdicts(*verdicts: Verdict) -> ScenarioResult:
    return ScenarioResult(
        test_id="TX",
        title="synthetic",
        claim="synthetic claim for verdict aggregation",
        definition_version="test",
        definition_hash="0" * 64,
        started_at="",
        finished_at="",
        configurations=[
            _configuration_result(f"C{i}", verdict)
            for i, verdict in enumerate(verdicts)
        ],
        limitations=[],
        events=[],
        expected={},
    )


# -- base.percentile ------------------------------------------------------


def test_percentile_empty_is_none():
    assert percentile([], 0.5) is None


def test_percentile_single_value():
    assert percentile([4.0], 0.95) == 4.0


def test_percentile_median_interpolates():
    assert percentile([1.0, 3.0], 0.5) == 2.0


def test_percentile_p95_stays_within_sample_range():
    values = [float(v) for v in range(1, 21)]
    result = percentile(values, 0.95)
    assert result is not None
    assert min(values) <= result <= max(values)
    assert result == round(values[0] + 0.95 * (values[-1] - values[0]), 3)


# -- base._jsonable --------------------------------------------------------


def test_jsonable_passes_plain_scalars_through():
    assert _jsonable({"a": 1, "b": "x", "c": None, "d": True}) == {
        "a": 1,
        "b": "x",
        "c": None,
        "d": True,
    }


def test_jsonable_converts_enums_and_as_dict_objects():
    assert _jsonable(Verdict.PASS) == "PASS"
    assert _jsonable(Counters(downstream_executions=2))["downstream_executions"] == 2


def test_jsonable_falls_back_to_str_for_unknown_types():
    assert _jsonable(object()) != ""


# -- base.EventLog ----------------------------------------------------------


def test_event_log_sequences_and_records_context():
    log = EventLog()
    first = log.emit("step.one", "hello", scenario="T06", configuration="C")
    second = log.emit("step.two", "world", scenario="T06", configuration="C")
    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert first["step"] == "step.one"
    assert first["scenario"] == "T06"
    assert len(log.events) == 2


# -- base.ScenarioResult verdict aggregation --------------------------------


def test_scenario_verdict_reports_the_worst_configuration():
    assert _result_with_verdicts(Verdict.PASS).verdict is Verdict.PASS
    assert _result_with_verdicts(Verdict.PASS, Verdict.OBSERVED).verdict is Verdict.PASS
    assert _result_with_verdicts(Verdict.PASS, Verdict.FAIL).verdict is Verdict.FAIL
    assert _result_with_verdicts(Verdict.FAIL, Verdict.ERROR).verdict is Verdict.ERROR
    assert (
        _result_with_verdicts(Verdict.OBSERVED, Verdict.NOT_APPLICABLE).verdict
        is Verdict.OBSERVED
    )


def test_matches_expectation_and_mismatches_agree():
    result = _result_with_verdicts(Verdict.PASS, Verdict.FAIL)
    result.expected = {"C0": "PASS", "C1": "FAIL"}
    assert result.matches_expectation
    assert result.mismatches() == []
    result.expected = {"C0": "PASS", "C1": "PASS"}
    assert not result.matches_expectation
    assert result.mismatches() == [("C1", "PASS", "FAIL")]


# -- scenario registry -------------------------------------------------------


def test_get_scenario_is_case_insensitive_and_lists_known_ids():
    assert get_scenario("t06").test_id == "T06"
    with pytest.raises(KeyError) as excinfo:
        get_scenario("T99")
    assert "T06" in str(excinfo.value)


def test_select_scenarios_filters_by_tier():
    fast = select_scenarios(tier="fast")
    assert fast
    assert all(scenario.tier == "fast" for scenario in fast)
    assert {scenario.test_id for scenario in fast} == set(FAST_SCENARIO_IDS)
    slow = select_scenarios(tier="slow")
    assert {scenario.test_id for scenario in slow} == set(SLOW_SCENARIO_IDS)
    assert len(FAST_SCENARIO_IDS) + len(SLOW_SCENARIO_IDS) == len(SCENARIO_CLASSES)


def test_refused_statuses_covers_product_refusals_but_not_success():
    for status in (
        "denied",
        "rejected",
        "conflict",
        "key_conflict",
        "insufficient_funds",
        "invalid_params",
    ):
        assert status in REFUSED_STATUSES
    assert "success" not in REFUSED_STATUSES
    assert "succeeded" not in REFUSED_STATUSES


# -- T01 storm preconditions --------------------------------------------------


def _t01_attempts(statuses):
    from failure_lab.configurations import AttemptOutcome

    return [
        AttemptOutcome(
            configuration="test",
            identity={
                "business_operation_id": "op_t01",
                "idempotency_key": "key_t01",
                "request_id": f"req_{index}",
            },
            status=status,
            client_visible_state="confirmed_success",
            http_status=200,
            latency_ms=1.0,
        )
        for index, status in enumerate(statuses)
    ]


def test_t01_preconditions_hold_for_a_well_formed_storm():
    from failure_lab.scenarios.base import Measurements

    scenario = get_scenario("T01")
    attempts = _t01_attempts(["succeeded"] * 4)
    measurements = Measurements(
        counters=Counters(
            incoming_requests=4, downstream_executions=1, downstream_requests=1
        ),
        gateway=None,
        snapshot=None,
        effects=[],
        crossings=[],
        receipts=[],
    )
    assert (
        scenario._preconditions(
            attempts=attempts,
            concurrency=4,
            distinct_request_ids=4,
            distinct_keys=1,
            distinct_operations=1,
            measurements=measurements,
            ledger_count=1,
            layer_requests=1,
        )
        == []
    )


def test_t01_preconditions_catch_a_storm_that_was_not_a_storm():
    from failure_lab.scenarios.base import Measurements

    scenario = get_scenario("T01")
    attempts = _t01_attempts(["succeeded"] * 4)
    measurements = Measurements(
        counters=Counters(
            incoming_requests=4, downstream_executions=1, downstream_requests=1
        ),
        gateway=None,
        snapshot=None,
        effects=[],
        crossings=[],
        receipts=[],
    )
    unmet = scenario._preconditions(
        attempts=attempts,
        concurrency=4,
        distinct_request_ids=4,
        distinct_keys=2,
        distinct_operations=1,
        measurements=measurements,
        ledger_count=1,
        layer_requests=1,
    )
    assert any("idempotency key" in item for item in unmet)


def test_t01_preconditions_catch_an_instrument_disagreeing_with_itself():
    from failure_lab.scenarios.base import Measurements

    scenario = get_scenario("T01")
    attempts = _t01_attempts(["succeeded"] * 4)
    measurements = Measurements(
        counters=Counters(
            incoming_requests=4, downstream_executions=9, downstream_requests=1
        ),
        gateway=None,
        snapshot=None,
        effects=[],
        crossings=[],
        receipts=[],
    )
    unmet = scenario._preconditions(
        attempts=attempts,
        concurrency=4,
        distinct_request_ids=4,
        distinct_keys=1,
        distinct_operations=1,
        measurements=measurements,
        ledger_count=1,
        layer_requests=1,
    )
    assert any("disagrees with itself" in item for item in unmet)


# -- T02 conflict deltas -------------------------------------------------------


def test_t02_deltas_measures_movement_across_one_request():
    from failure_lab.scenarios.t02_same_key_different_arguments import _deltas

    before = {
        "sent_attempts": 1,
        "debits": 1,
        "refunds": 0,
        "net_debits": 1,
        "receipts": 1,
        "idempotency_records": 1,
    }
    assert _deltas(before, dict(before)) == {
        "sent_attempts": 0,
        "debits": 0,
        "refunds": 0,
        "net_debits": 0,
        "receipts": 0,
        "idempotency_records": 0,
    }
    after = dict(before, debits=2, net_debits=2, receipts=2)
    deltas = _deltas(before, after)
    assert deltas["debits"] == 1
    assert deltas["net_debits"] == 1
    assert deltas["receipts"] == 1


def test_t02_deltas_without_gateway_state_is_empty():
    from failure_lab.scenarios.t02_same_key_different_arguments import _deltas

    assert _deltas(None, None) == {}
    assert _deltas(None, {"debits": 1}) == {}


# -- T03 lost-response premise and control -------------------------------------


def test_t03_premise_requires_both_execution_and_the_injected_fault():
    scenario = get_scenario("T03")
    established = scenario._premise(1, True)
    assert "withheld the response" in established
    assert not established.startswith("PREMISE NOT ESTABLISHED")
    fault_missing = scenario._premise(1, False)
    assert "NOT recorded" in fault_missing
    nothing_ran = scenario._premise(0, False)
    assert nothing_ran.startswith("PREMISE NOT ESTABLISHED")


def test_t03_control_sentence_distinguishes_a_working_path():
    scenario = get_scenario("T03")
    working = {
        "status": "success",
        "downstream_executions": 1,
        "downstream_requests": 1,
        "executed": True,
    }
    assert "not a wedged path" in scenario._control_sentence(
        working, subject="the retry"
    )
    broken = {
        "status": "timeout",
        "downstream_executions": 0,
        "downstream_requests": 0,
        "executed": False,
    }
    sentence = scenario._control_sentence(broken, subject="the retry")
    assert "did NOT execute" in sentence


# -- T05 crash-after-dispatch case failures -------------------------------------


def _t05_passing_case() -> dict:
    return {
        "case": "A",
        "boundary": "after_claim",
        "expected_downstream_executions": 1,
        "crash_fired": True,
        "crash_status": "gateway_process_died",
        "downstream_executions_after_crash": 1,
        "downstream_executions_after_reconcile": 1,
        "downstream_executions_after_retry": 1,
        "gateway_dispatches_after_crash": 1,
        "gateway_dispatches_after_reconcile": 1,
        "gateway_dispatches_after_retry": 1,
        "case_receipt_outcomes": ["delivery_uncertain"],
        "attempt_states": ["delivery_uncertain"],
        "reconciliation_marked_uncertain": 1,
        "case_gateway_net_debits": 1,
        "case_gateway_debits": 1,
        "case_gateway_refunds": 0,
        "retry_status": "delivery_uncertain",
        "retry_client_visible_state": "explicit_uncertain",
        "retry_receipt_outcome": "delivery_uncertain",
        "retry_receipt_id": "rcpt_1",
        "receipt_ids": ["rcpt_1"],
    }


def test_t05_passing_case_has_no_failures():
    scenario = get_scenario("T05")
    assert scenario._case_failures(_t05_passing_case()) == []


def test_t05_unfired_crash_is_a_failure_not_a_pass():
    scenario = get_scenario("T05")
    case = _t05_passing_case()
    case["crash_fired"] = False
    assert scenario._case_failures(case)


def test_t05_success_receipt_for_an_unseen_call_is_overclaiming():
    scenario = get_scenario("T05")
    case = _t05_passing_case()
    case["case_receipt_outcomes"] = ["success"]
    case["retry_receipt_outcome"] = "success"
    failures = scenario._case_failures(case)
    assert any("never saw the end of" in failure for failure in failures)


def test_t05_retry_citing_another_operations_receipt_fails():
    scenario = get_scenario("T05")
    case = _t05_passing_case()
    case["retry_receipt_id"] = "rcpt_someone_else"
    failures = scenario._case_failures(case)
    assert any("not among this operation" in failure for failure in failures)


# -- T06 restart attribution -----------------------------------------------------
# The audit flagged T06: the verdict must name which layer absorbed the
# replanned attempt, and must never credit a layer when there was no duplicate
# to stop. These tests pin that attribution table without running the lab.


def _t06_target(*, uses_gateway: bool):
    return SimpleNamespace(uses_gateway=uses_gateway)


def test_t06_gateway_front_layer_earns_credit_only_when_replan_never_arrived():
    scenario = get_scenario("T06")
    target = _t06_target(uses_gateway=True)
    assert scenario._deduplicated_by(target, 1, 1, 0) == "gateway"
    assert scenario._deduplicated_by(target, 1, 1, 1) == "downstream"


def test_t06_direct_path_has_no_front_layer_to_credit():
    scenario = get_scenario("T06")
    target = _t06_target(uses_gateway=False)
    assert scenario._deduplicated_by(target, 1, 1, 0) == "nothing"
    assert scenario._deduplicated_by(target, 1, 1, 2) == "downstream"


def test_t06_no_credit_without_a_duplicate_to_stop():
    scenario = get_scenario("T06")
    gateway = _t06_target(uses_gateway=True)
    assert scenario._deduplicated_by(gateway, 2, 1, 1) == "nothing"
    assert scenario._deduplicated_by(gateway, 0, 0, 0) == "nothing"
    assert scenario._deduplicated_by(gateway, 1, 0, 1) == "nothing"


def test_t06_first_attempt_premise_comes_from_instruments_not_the_plan():
    scenario = get_scenario("T06")
    assert "withheld the response" in scenario._first_attempt_premise(1, True)
    assert "NOT recorded" in scenario._first_attempt_premise(1, False)
    assert scenario._first_attempt_premise(0, False).startswith(
        "PREMISE NOT ESTABLISHED"
    )


# -- T08 revocation attribution ----------------------------------------------------


def _t08_staged_record(**overrides) -> dict:
    record = {
        "staged": True,
        "staging_note": "",
        "permit_revocation_confirmed": True,
        "permit_final_status": "revoked",
        "dispatches": 0,
        "downstream_executions": 0,
        "receipt_outcomes": ["denied"],
        "net_charge_credits": "0",
        "net_debit_count": 0,
        "status": "denied",
    }
    record.update(overrides)
    return record


def test_t08_unstaged_interleaving_is_not_evidence():
    from failure_lab.scenarios.t08_permit_revocation_race import _evaluate

    record = _t08_staged_record(staged=False, staging_note="call finished first")
    disposition, problems = _evaluate(record)
    assert disposition == "not_staged"
    assert problems


def test_t08_unrevoked_permit_is_not_evidence():
    from failure_lab.scenarios.t08_permit_revocation_race import _evaluate

    record = _t08_staged_record(
        permit_revocation_confirmed=False, permit_final_status="active"
    )
    disposition, _ = _evaluate(record)
    assert disposition == "not_staged"


def test_t08_clean_denial_is_coherent():
    from failure_lab.scenarios.t08_permit_revocation_race import _evaluate

    assert _evaluate(_t08_staged_record()) == ("denied", [])


def test_t08_second_dispatch_is_incoherent():
    from failure_lab.scenarios.t08_permit_revocation_race import _evaluate

    record = _t08_staged_record(
        dispatches=2,
        downstream_executions=1,
        receipt_outcomes=["success"],
        net_charge_credits="5",
        net_debit_count=1,
        status="success",
    )
    disposition, problems = _evaluate(record)
    assert disposition == "incoherent"
    assert any("2 dispatches" in problem for problem in problems)


def test_t08_success_receipt_with_no_effect_is_incoherent():
    from failure_lab.scenarios.t08_permit_revocation_race import _evaluate

    record = _t08_staged_record(
        dispatches=1,
        downstream_executions=0,
        receipt_outcomes=["success"],
        net_charge_credits="5",
        net_debit_count=1,
        status="success",
    )
    disposition, problems = _evaluate(record)
    assert disposition == "incoherent"
    assert any("no downstream execution" in problem for problem in problems)


def test_t08_charge_without_receipt_is_incoherent():
    from failure_lab.scenarios.t08_permit_revocation_race import _evaluate

    record = _t08_staged_record(
        dispatches=1,
        downstream_executions=1,
        receipt_outcomes=[],
        net_charge_credits="5",
        net_debit_count=1,
        status="success",
    )
    disposition, problems = _evaluate(record)
    assert disposition == "incoherent"
    assert any("with no receipt" in problem for problem in problems)


def test_t08_revocation_attribution_ignores_unrelated_refusals():
    from failure_lab.scenarios.t08_permit_revocation_race import (
        _revocation_attributable,
    )

    assert _revocation_attributable("permit_revoked")
    assert _revocation_attributable("denied", ["PERMIT_REVOKED_AT_DISPATCH"])
    assert not _revocation_attributable("insufficient_funds")
    assert not _revocation_attributable("key_conflict")
    assert not _revocation_attributable(None)


# -- T09 permit probe verdicts ------------------------------------------------------


def _t09_control_row(**overrides) -> dict:
    row = {
        "probe": "control",
        "status": "success",
        "reason": None,
        "dispatches": 1,
        "executions": 1,
        "net_charge_credits": "5",
    }
    row.update(overrides)
    return row


def test_t09_sound_control_has_no_problems():
    scenario = get_scenario("T09")
    assert scenario._control_problems(_t09_control_row(), call_cost=Decimal("5")) == []


def test_t09_unadmitted_control_invalidates_the_run():
    scenario = get_scenario("T09")
    problems = scenario._control_problems(
        _t09_control_row(status="denied", reason="permit_revoked"),
        call_cost=Decimal("5"),
    )
    assert any("unattributable" in problem for problem in problems)


def test_t09_control_cost_mismatch_invalidates_the_run():
    scenario = get_scenario("T09")
    problems = scenario._control_problems(
        _t09_control_row(net_charge_credits="0"), call_cost=Decimal("5")
    )
    assert any("kept 0 credits" in problem for problem in problems)


def _t09_probe_row(**overrides) -> dict:
    row = {
        "probe": "probe",
        "refused": True,
        "status": "denied",
        "reason": "permit_tool_not_allowed",
        "dispatches": 0,
        "executions": 0,
        "net_debit": 0,
        "net_charge_credits": "0",
    }
    row.update(overrides)
    return row


def test_t09_clean_refusal_has_no_problems():
    scenario = get_scenario("T09")
    assert scenario._permit_problems(_t09_probe_row()) == []


def test_t09_admitted_probe_breaks_the_claim():
    scenario = get_scenario("T09")
    problems = scenario._permit_problems(
        _t09_probe_row(refused=False, status="success", dispatches=1, executions=1)
    )
    assert any("not refused" in problem for problem in problems)


def test_t09_refusal_after_dispatch_breaks_the_claim():
    scenario = get_scenario("T09")
    problems = scenario._permit_problems(_t09_probe_row(dispatches=1))
    assert any("before dispatch" in problem for problem in problems)


def test_t09_refusal_that_keeps_a_charge_breaks_the_claim():
    scenario = get_scenario("T09")
    problems = scenario._permit_problems(
        _t09_probe_row(net_debit=1, net_charge_credits="5")
    )
    assert any("net charge" in problem for problem in problems)


# -- T10 tamper measurement ----------------------------------------------------------


def test_t10_distinct_guarantees_the_edit_is_an_edit():
    from failure_lab.scenarios.t10_receipt_tampering import _distinct

    assert _distinct("a", "b") == "b"
    assert _distinct("same", "same") != "same"
    assert _distinct(7, 7) != 7


def test_t10_failure_mode_separates_crypto_from_key_lookup():
    from failure_lab.scenarios.t10_receipt_tampering import _failure_mode
    from failure_lab.verifier import ClaimStatus

    def report(status, reason):
        return SimpleNamespace(signature=SimpleNamespace(status=status, reason=reason))

    assert _failure_mode(report(ClaimStatus.ESTABLISHED, "ok")) is None
    assert (
        _failure_mode(report(ClaimStatus.FAILED, "does not verify over signing_input"))
        == "signature_check"
    )
    assert (
        _failure_mode(report(ClaimStatus.FAILED, "names no key for kid x"))
        == "key_resolution"
    )
    assert (
        _failure_mode(report(ClaimStatus.FAILED, "not a 64-byte Ed25519 signature"))
        == "signature_decode"
    )
    assert _failure_mode(report(ClaimStatus.FAILED, "something unexpected")) == "other"


# -- T11 outage damage measures ---------------------------------------------------------


def _t11_failed_closed_case() -> dict:
    return {
        "boundary": None,
        "boundary_reached": False,
        "dispatches_total": 0,
        "executions_total": 0,
        "dispatches_during_outage": 0,
        "outage_status": "transport_error",
        "admitted_records": [],
        "admitted_attempts": [],
        "after_recovery": {
            "unsettled_debit_entry_ids": [],
            "attempt_states": [],
            "receipts": [],
            "receipt_outcomes": [],
        },
        "final_unsettled_debit_entry_ids": [],
        "refused_connections": True,
        "retry_client_visible_state": "confirmed_success",
        "retry_status": "success",
        "retry_dispatches": 1,
        "retry_executions": 1,
    }


def test_t11_failed_closed_case_with_sound_control():
    from failure_lab.scenarios.t11_database_restart import _evaluate

    disposition, problems, measures = _evaluate(_t11_failed_closed_case())
    assert disposition == "failed_closed"
    assert problems == []
    assert measures["duplicate_dispatches"] == 0
    assert measures["lost_accepted_operations"] == 0


def test_t11_failed_closed_case_with_broken_control_is_flagged():
    from failure_lab.scenarios.t11_database_restart import _evaluate

    case = _t11_failed_closed_case()
    case["retry_dispatches"] = 0
    case["retry_executions"] = 0
    disposition, problems, _ = _evaluate(case)
    assert disposition == "failed_closed"
    assert any("control did not hold" in problem for problem in problems)


def test_t11_duplicate_dispatch_counts_as_damage():
    from failure_lab.scenarios.t11_database_restart import _evaluate

    case = _t11_failed_closed_case()
    case["dispatches_total"] = 2
    case["executions_total"] = 2
    case["boundary"] = "after_claim"
    case["boundary_reached"] = True
    case["dispatches_during_outage"] = 1
    case["refused_connections"] = True
    case["admitted_records"] = [{"record_id": "r1"}]
    case["after_recovery"] = {
        "unsettled_debit_entry_ids": [],
        "attempt_states": ["delivery_uncertain"],
        "receipts": [{"receipt_id": "rcpt_1"}],
        "receipt_outcomes": ["delivery_uncertain"],
    }
    case["retry_client_visible_state"] = "explicit_uncertain"
    _, problems, measures = _evaluate(case)
    assert measures["duplicate_dispatches"] == 1
    assert measures["duplicate_downstream_executions"] == 1
    assert any("2 dispatches" in problem for problem in problems)


# -- T12 cache-failure helpers ------------------------------------------------------------
# The audit flagged T12: the verdict must rest on a cache outage that actually
# happened and on governed calls that actually met it. The runtime checks live
# in the scenario; these tests pin the small instruments they are built from.


def test_t12_added_matches_rows_on_key():
    from failure_lab.scenarios.t12_cache_failure import _added

    before = [{"entry_id": "a"}, {"entry_id": "b"}]
    after = [{"entry_id": "a"}, {"entry_id": "b"}, {"entry_id": "c"}]
    assert _added(before, after, "entry_id") == [{"entry_id": "c"}]
    assert _added(before, list(before), "entry_id") == []


def test_t12_credits_signs_debits_negative():
    from failure_lab.scenarios.t12_cache_failure import _credits

    assert _credits([{"amount": "-5"}, {"amount": "5"}]) == Decimal("0")
    assert _credits([{"amount": "-5"}, {}]) == Decimal("-5")


def test_t12_credit_text_has_no_signed_zero_or_exponent():
    from failure_lab.scenarios.t12_cache_failure import _credit_text

    assert _credit_text(Decimal("0")) == "0"
    assert _credit_text(Decimal("-0.00")) == "0"
    assert "E" not in _credit_text(Decimal("5000"))


def test_t12_health_summary_carries_http_status_alongside_body():
    from failure_lab.scenarios.t12_cache_failure import _health_summary

    summary = _health_summary({"status": "ok"}, 200)
    assert summary["http_status"] == 200
    assert summary["status"] == "ok"
    unreadable = _health_summary("not json", 503)
    assert unreadable["http_status"] == 503
    assert "unreadable" in unreadable


def test_t12_closed_loopback_url_names_an_unroutable_redis():
    from failure_lab.scenarios.t12_cache_failure import _closed_loopback_url

    url = _closed_loopback_url()
    assert url.startswith("redis://127.0.0.1:")
    assert url.endswith("/0")
    port = int(url.split(":")[-1].split("/")[0])
    assert 1 <= port <= 65535


def test_t12_live_rate_limiters_walks_the_middleware_stack():
    from failure_lab.scenarios.t12_cache_failure import _live_rate_limiters

    class FakeLimiter:
        def __init__(self, app=None):
            self.app = app

    class Other:
        def __init__(self, app=None):
            self.app = app

    inner = FakeLimiter()
    outer = Other(app=inner)
    root = SimpleNamespace(middleware_stack=outer)
    assert _live_rate_limiters(root, FakeLimiter) == [inner]
    assert _live_rate_limiters(root, Other) == [outer]
    assert _live_rate_limiters(root, str) == []
    assert _live_rate_limiters(None, FakeLimiter) == []
