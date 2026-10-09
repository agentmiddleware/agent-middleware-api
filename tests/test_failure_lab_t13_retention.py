"""T13 must not pass a retention run that never injected its faults.

The aged-record case, the effect-free release, and the simulated purge each
claim to have done something to the idempotency record. A verdict that ignores
whether that write landed reports PASS for a sweep of a fresh row, a retry of
a key that was never released, or a retry of a record the purge left in place.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from app.core.time import utc_now
from failure_lab.configurations import Configuration
from failure_lab.scenarios.base import Counters, EventLog, Measurements, Verdict
from failure_lab.scenarios.t13_retention_expiration import (
    DEFAULT_AGE_SECONDS,
    RetentionExpiration,
)


def _measurements() -> Measurements:
    return Measurements(
        counters=Counters(
            gateway_dispatches=3,
            downstream_executions=3,
            gateway_debits=2,
            gateway_refunds=0,
            gateway_net_debits=2,
            receipts=2,
        ),
        gateway=None,
        snapshot=SimpleNamespace(wallet_balance="90"),
        effects=[],
        crossings=[],
        receipts=[],
    )


def _cases(*, now, age_seconds: int):
    """Three cases in which every injection the scenario narrates did happen."""
    stale = (now - timedelta(seconds=age_seconds)).isoformat()
    aged = {
        "record_ids": ["rec-aged"],
        "rows_aged": {
            "idempotency_records": 1,
            "dispatch_attempts": 1,
            "receipts": 1,
        },
        "record_created_at_after_aging": [stale],
        "first_call_status": "success",
        "dispatches_after_first_call": 1,
        "executions_after_first_call": 1,
        "record_survived_sweep": True,
        "age_days": round(age_seconds / 86_400, 1),
        "replay_status": "success",
        "replay_returned_original_receipt": True,
        "replay_receipt_id": "rcpt-aged",
        "first_call_receipt_id": "rcpt-aged",
        "replay_dispatched": False,
        "replay_produced_new_execution": False,
        "record_expires_at_before_aging": [None],
        "record_expires_at_after_sweep": [None],
        "reconciliation": {"idempotency_repaired": 0},
        "dispatches_after_replay": 1,
        "executions_after_replay": 1,
    }
    release = {
        "record_ids": ["rec-release"],
        "rows_aged": {"idempotency_records": 1},
        "record_released_by_sweep": True,
        "crash_fired": True,
        "crash_status": "gateway_process_died",
        "crash_left_an_effect_to_compensate": False,
        "attempt_rows_left_by_crash": 0,
        "debits_left_by_crash": 0,
        "receipts_left_by_crash": 0,
        "dispatches_at_crash": 0,
        "executions_at_crash": 0,
        "executions_total_for_operation": 1,
        "retry_status": "success",
        "retry_dispatched": True,
        "boundary_description": "idempotency record created; nothing else",
    }
    removed = {
        "record_ids": ["rec-removed"],
        "record_gone_after_purge": True,
        "purge": {
            "records_deleted": 1,
            "direct_delete_succeeded": True,
            "steps": [{"step": "delete_idempotency_record", "ok": True}],
        },
        "retry_status": "success",
        "retry_dispatched": True,
        "second_downstream_effect": True,
        "new_debits_from_retry": ["debit-2"],
        "new_receipts_from_retry": ["rcpt-2"],
        "receipts_surviving_purge": ["rcpt-1"],
    }
    return aged, release, removed


def _verdict_for(aged, release, removed, *, age_seconds: int):
    scenario = RetentionExpiration()
    target = SimpleNamespace(configuration=Configuration.GATEWAY_NAIVE)
    return scenario._verdict(
        target,
        EventLog(),
        aged=aged,
        release=release,
        removed=removed,
        attempts=[],
        measurements=_measurements(),
        age_seconds=age_seconds,
    )


def test_pass_names_a_run_that_aged_released_and_purged():
    now = utc_now()
    aged, release, removed = _cases(now=now, age_seconds=DEFAULT_AGE_SECONDS)
    result = _verdict_for(aged, release, removed, age_seconds=DEFAULT_AGE_SECONDS)
    assert result.verdict == Verdict.PASS
    assert result.extra["verdict_failures"] == []


def test_a_second_effect_after_a_real_purge_is_not_a_failure():
    """The purge's consequence is descriptive. Only a missing purge fails."""
    now = utc_now()
    aged, release, removed = _cases(now=now, age_seconds=DEFAULT_AGE_SECONDS)
    removed["second_downstream_effect"] = True
    removed["retry_dispatched"] = True
    result = _verdict_for(aged, release, removed, age_seconds=DEFAULT_AGE_SECONDS)
    assert result.verdict == Verdict.PASS


def test_fail_when_the_aged_record_clock_never_moved():
    now = utc_now()
    aged, release, removed = _cases(now=now, age_seconds=DEFAULT_AGE_SECONDS)
    aged["rows_aged"]["idempotency_records"] = 0
    aged["record_created_at_after_aging"] = [now.isoformat()]
    result = _verdict_for(aged, release, removed, age_seconds=DEFAULT_AGE_SECONDS)
    assert result.verdict == Verdict.FAIL
    assert any(
        "aged_record" in item and "not backdated" in item
        for item in result.extra["verdict_failures"]
    )


def test_fail_when_the_effect_free_record_was_not_released():
    now = utc_now()
    aged, release, removed = _cases(now=now, age_seconds=DEFAULT_AGE_SECONDS)
    # One execution with the record still present used to pass: the retry
    # looks like a normal success, and nothing checks that a key was released.
    release["record_released_by_sweep"] = False
    release["rows_aged"] = {"idempotency_records": 0}
    result = _verdict_for(aged, release, removed, age_seconds=DEFAULT_AGE_SECONDS)
    assert result.verdict == Verdict.FAIL
    text = " ".join(result.extra["verdict_failures"])
    assert "effect_free_release" in text
    assert "did not release" in text


def test_fail_when_the_simulated_purge_left_the_record_in_place():
    now = utc_now()
    aged, release, removed = _cases(now=now, age_seconds=DEFAULT_AGE_SECONDS)
    removed["record_gone_after_purge"] = False
    removed["purge"]["records_deleted"] = 0
    result = _verdict_for(aged, release, removed, age_seconds=DEFAULT_AGE_SECONDS)
    assert result.verdict == Verdict.FAIL
    assert any(
        item.startswith("record_removed:") for item in result.extra["verdict_failures"]
    )
    risks = " ".join(result.remaining_risks)
    assert "did not remove the idempotency record" in risks
