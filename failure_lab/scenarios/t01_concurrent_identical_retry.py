"""Test 1 -- Concurrent identical retry."""

from __future__ import annotations

import asyncio
from collections import Counter as StatusTally
from typing import Any

from failure_lab.configurations import (
    ALL_CONFIGURATIONS,
    AttemptOutcome,
    Configuration,
    Target,
)
from failure_lab.identity import OperationIdentity
from failure_lab.scenarios.base import (
    ConfigurationResult,
    EventLog,
    Measurements,
    Scenario,
    Verdict,
)

#: Statuses a healthy run of this workload produces when the agent talks to the
#: downstream tool directly. Anything else is an unexpected *product* status and
#: is reported, never smoothed over.
DIRECT_EXPECTED_STATUSES = frozenset({"succeeded", "replayed"})

#: Statuses a healthy run produces through the gateway: the holder of the
#: idempotency key completes, and every other caller is either served the stored
#: envelope or told the key is still in flight.
GATEWAY_EXPECTED_STATUSES = frozenset({"success", "in_progress"})

#: Statuses that can mean the harness itself, rather than the product, buckled
#: under the requested concurrency (in-process asyncio over SQLite).
HARNESS_STRAIN_STATUSES = frozenset({"timeout", "transport_error"})

#: Client patience, in seconds. Deliberately far above the gateway's own call
#: timeout and above its bounded idempotency wait, so what this test records is
#: the gateway's classification of the storm and not the harness's impatience.
DEFAULT_TIMEOUT_SECONDS = 30.0

#: Minor units per refund, mirroring :meth:`Scenario.refund`'s default.
AMOUNT_MINOR_UNITS = 5000


def _tally(attempts: list[AttemptOutcome]) -> dict[str, int]:
    return dict(sorted(StatusTally(a.status for a in attempts).items()))


def _visible_tally(attempts: list[AttemptOutcome]) -> dict[str, int]:
    return dict(sorted(StatusTally(a.client_visible_state for a in attempts).items()))


class ConcurrentIdenticalRetry(Scenario):
    """Send one accepted operation concurrently N times and count everything.

    WHAT TO IMPLEMENT
    -----------------
    1. Build one refund (``self.refund("pay_t01")``) and one identity
       (``OperationIdentity.first_attempt(operation_id)``).
    2. Fire ``self.options.get("concurrency", 100)`` submissions of that
       *identical* identity concurrently via ``asyncio.gather`` on
       ``target.agent.submit(identity.retry(), refund, timeout_seconds=...)``.
       ``identity.retry()`` keeps the idempotency key and the business
       operation id and varies only ``request_id`` -- which is the point:
       100 distinct wire requests, one business operation, one key.
    3. Measure with ``await self.measure(target, attempts, operation_ids=[op])``.
    4. Verdict rules:
       * ``DIRECT_NAIVE``  -> always ``OBSERVED``. Record the duplicate count.
       * ``DIRECT_NATIVE`` -> ``PASS`` iff downstream_executions == 1.
       * gateway configs   -> ``PASS`` iff downstream_executions == 1 AND
         gateway_dispatches == 1 AND gateway_debits == 1 AND receipts == 1 AND
         every non-``in_progress`` attempt that succeeded carries the SAME
         receipt_id. Anything else is ``FAIL``.
    5. The observation string MUST NOT use the words "exactly once" about the
       downstream effect. Say what was counted and by which instrument.

    If the requested concurrency produces harness-level errors (SQLite write
    contention, not a product failure), reduce it until the run is clean,
    record the level actually used in ``extra["concurrency"]``, and add a
    limitation saying so. Do not silence a product failure this way: an
    attempt that returns an unexpected *product* status is a finding.
    """

    test_id = "T01"
    title = "Concurrent identical retry"
    claim = (
        "One accepted idempotency key admits at most one gateway dispatch, "
        "at most one ledger debit, and one receipt, however many identical "
        "requests arrive at once."
    )
    tier = "slow"
    configurations = ALL_CONFIGURATIONS
    expected = {
        Configuration.DIRECT_NAIVE.value: Verdict.OBSERVED.value,
        Configuration.DIRECT_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NAIVE.value: Verdict.PASS.value,
    }
    limitations = (
        "Counts gateway dispatches and downstream executions; does not prove "
        "exactly-once downstream execution in general.",
        "Concurrency is in-process asyncio against SQLite, not a multi-node load test.",
    )

    async def run_configuration(self, target: Target, log: EventLog) -> ConfigurationResult:
        requested = int(self.options.get("concurrency", 100))
        concurrency = max(1, requested)
        timeout_seconds = float(
            self.options.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        )
        operation_id, refund = self.refund("pay_t01")
        identity = OperationIdentity.first_attempt(operation_id)

        log.emit(
            "workload.plan",
            f"{concurrency} concurrent wire requests, one business operation, one key",
            scenario=self.test_id,
            configuration=target.configuration.value,
            concurrency=concurrency,
            concurrency_requested=requested,
            operation_id=operation_id,
            idempotency_key=identity.idempotency_key,
            key_policy=identity.key_policy.value,
            client_timeout_seconds=timeout_seconds,
        )

        submissions = [identity.retry() for _ in range(concurrency)]
        attempts: list[AttemptOutcome] = list(
            await asyncio.gather(
                *(
                    target.agent.submit(one, refund, timeout_seconds=timeout_seconds)
                    for one in submissions
                )
            )
        )

        status_tally = _tally(attempts)
        distinct_request_ids = len({a.identity["request_id"] for a in attempts})
        distinct_keys = len({a.identity["idempotency_key"] for a in attempts})
        log.emit(
            "workload.complete",
            f"{len(attempts)} attempts returned: {status_tally}",
            scenario=self.test_id,
            configuration=target.configuration.value,
            statuses=status_tally,
            client_visible_states=_visible_tally(attempts),
            distinct_request_ids=distinct_request_ids,
            distinct_idempotency_keys=distinct_keys,
        )

        measurements = await self.measure(target, attempts, operation_ids=[operation_id])
        ledger_count = target.ledger.execution_count(operation_id)
        layer_requests = target.injector.dispatch_count(operation_id)
        log.emit(
            "measure.instruments",
            (
                f"effect ledger (independent): {ledger_count} execution(s); "
                f"fault layer (independent): {layer_requests} request(s) into the tool"
            ),
            scenario=self.test_id,
            configuration=target.configuration.value,
            downstream_executions=ledger_count,
            downstream_requests=layer_requests,
            gateway_debits=measurements.counters.gateway_debits,
            gateway_receipts=measurements.counters.receipts,
            gateway_sent_attempts=measurements.counters.gateway_sent_attempts,
        )

        allowed = (
            GATEWAY_EXPECTED_STATUSES if target.uses_gateway else DIRECT_EXPECTED_STATUSES
        )
        unexpected = _tally([a for a in attempts if a.status not in allowed])
        strain = {k: v for k, v in unexpected.items() if k in HARNESS_STRAIN_STATUSES}
        product_anomalies = {k: v for k, v in unexpected.items() if k not in strain}
        if unexpected:
            log.emit(
                "measure.unexpected_statuses",
                f"attempt statuses outside the healthy set: {unexpected}",
                scenario=self.test_id,
                configuration=target.configuration.value,
                unexpected=unexpected,
                possible_harness_strain=strain,
                product_anomalies=product_anomalies,
            )

        extra: dict[str, Any] = {
            "concurrency": concurrency,
            "concurrency_requested": requested,
            "client_timeout_seconds": timeout_seconds,
            "operation_id": operation_id,
            "idempotency_key": identity.idempotency_key,
            "distinct_request_ids": distinct_request_ids,
            "distinct_idempotency_keys": distinct_keys,
            "attempt_statuses": status_tally,
            "client_visible_states": _visible_tally(attempts),
            "unexpected_statuses": unexpected,
            "possible_harness_strain": strain,
            "product_anomalies": product_anomalies,
            "effect_ledger_execution_count": ledger_count,
            "fault_layer_downstream_requests": layer_requests,
        }
        risks: list[str] = []
        if product_anomalies:
            risks.append(
                "Attempt statuses outside the healthy set for this configuration "
                f"were observed and are reported, not discarded: {product_anomalies}."
            )
        if strain:
            risks.append(
                f"{sum(strain.values())} attempt(s) ended in {sorted(strain)} at "
                f"concurrency {concurrency}. The client-side counters below are "
                "therefore a lower bound on what the product resolved; the "
                "independent ledger and fault-layer counts are not affected. "
                "Re-run with --option concurrency=<lower> to separate harness "
                "contention from product behaviour."
            )

        if target.uses_gateway:
            return self._gateway_result(
                target, log, attempts, measurements, extra, risks, ledger_count
            )
        if target.configuration is Configuration.DIRECT_NATIVE:
            return self._direct_native_result(
                target, log, attempts, measurements, extra, risks, ledger_count
            )
        return self._direct_naive_result(
            target, log, attempts, measurements, extra, risks, ledger_count
        )

    # -- per-configuration verdicts --------------------------------------

    def _direct_naive_result(
        self,
        target: Target,
        log: EventLog,
        attempts: list[AttemptOutcome],
        measurements: Measurements,
        extra: dict[str, Any],
        risks: list[str],
        ledger_count: int,
    ) -> ConfigurationResult:
        duplicates = max(0, ledger_count - 1)
        extra["duplicate_executions"] = duplicates
        extra["amount_minor_units_per_execution"] = AMOUNT_MINOR_UNITS
        extra["duplicated_value_minor_units"] = duplicates * AMOUNT_MINOR_UNITS
        observation = (
            f"{len(attempts)} identical concurrent requests for one business "
            f"operation. The independent effect ledger recorded {ledger_count} "
            f"downstream execution(s) and the independent fault layer counted "
            f"{measurements.counters.downstream_requests} request(s) reaching the "
            f"tool, so {duplicates} refund(s) of {AMOUNT_MINOR_UNITS} minor units "
            f"were paid out beyond the one the agent intended "
            f"({duplicates * AMOUNT_MINOR_UNITS} minor units of duplicated value). "
            f"Nothing in this configuration deduplicates, so the count of effects "
            f"tracks the count of requests. Descriptive baseline: there is no "
            f"guarantee here to pass or fail, and the numbers are the point."
        )
        risks.append(
            "A direct naive integration has no replay defence at all: a retry "
            "storm multiplies the business effect one for one."
        )
        log.emit(
            "verdict",
            f"{target.configuration.value} -> OBSERVED ({ledger_count} executions)",
            scenario=self.test_id,
            configuration=target.configuration.value,
            downstream_executions=ledger_count,
            duplicate_executions=duplicates,
        )
        return self.result(
            target,
            verdict=Verdict.OBSERVED,
            observation=observation,
            measurements=measurements,
            attempts=attempts,
            remaining_risks=risks,
            extra=extra,
        )

    def _direct_native_result(
        self,
        target: Target,
        log: EventLog,
        attempts: list[AttemptOutcome],
        measurements: Measurements,
        extra: dict[str, Any],
        risks: list[str],
        ledger_count: int,
    ) -> ConfigurationResult:
        fresh = sum(1 for a in attempts if a.status == "succeeded")
        replayed = sum(1 for a in attempts if a.status == "replayed")
        extra["fresh_responses"] = fresh
        extra["replayed_responses"] = replayed
        held = ledger_count == 1
        verdict = Verdict.PASS if held else Verdict.FAIL
        observation = (
            f"{len(attempts)} identical concurrent requests. The independent "
            f"effect ledger recorded {ledger_count} downstream execution(s) for "
            f"this operation while the independent fault layer counted "
            f"{measurements.counters.downstream_requests} request(s) reaching the "
            f"tool: every request was admitted and the tool itself collapsed them, "
            f"answering {fresh} caller(s) with a fresh execution and {replayed} "
            f"from its stored result. A correctly built downstream needs no "
            f"gateway to hold this line under concurrency."
        )
        if not held:
            observation += (
                f" It did not hold here: {ledger_count} executions were recorded "
                f"where the native idempotency store should have permitted one. "
                f"That is a finding about the baseline, reported as measured."
            )
        risks.append(
            "The native guarantee here is one SQLite transaction in one process; "
            "it says nothing about the same tool sharded across nodes or "
            "databases."
        )
        risks.append(
            "The deduplication is invisible from outside the tool: the caller "
            "gets no signed artifact, and no third party can check after the "
            "fact how many times the operation ran."
        )
        log.emit(
            "verdict",
            f"{target.configuration.value} -> {verdict.value} ({ledger_count} executions)",
            scenario=self.test_id,
            configuration=target.configuration.value,
            downstream_executions=ledger_count,
            fresh_responses=fresh,
            replayed_responses=replayed,
        )
        return self.result(
            target,
            verdict=verdict,
            observation=observation,
            measurements=measurements,
            attempts=attempts,
            remaining_risks=risks,
            extra=extra,
        )

    def _gateway_result(
        self,
        target: Target,
        log: EventLog,
        attempts: list[AttemptOutcome],
        measurements: Measurements,
        extra: dict[str, Any],
        risks: list[str],
        ledger_count: int,
    ) -> ConfigurationResult:
        counters = measurements.counters
        dispatches = counters.gateway_dispatches
        debits = counters.gateway_debits
        receipts = counters.receipts

        answered = [a for a in attempts if a.status == "success"]
        in_progress = [a for a in attempts if a.status == "in_progress"]
        receipt_ids = sorted({a.receipt_id for a in answered if a.receipt_id is not None})
        without_receipt = sum(1 for a in answered if a.receipt_id is None)
        outcomes = measurements.receipt_outcomes()

        extra.update(
            {
                "answered_attempts": len(answered),
                "in_progress_attempts": len(in_progress),
                "distinct_receipt_ids_on_answered": len(receipt_ids),
                "receipt_ids_on_answered": receipt_ids,
                "answered_without_receipt": without_receipt,
                "gateway_dispatches": dispatches,
                "gateway_debits": debits,
                "gateway_refunds": counters.gateway_refunds,
                "gateway_net_debits": counters.gateway_net_debits,
                "gateway_sent_attempts": counters.gateway_sent_attempts,
                "gateway_receipts": receipts,
                "receipt_outcomes": outcomes,
                "wallet_balance": (
                    measurements.snapshot.wallet_balance
                    if measurements.snapshot is not None
                    else None
                ),
            }
        )

        failures: list[str] = []
        if ledger_count != 1:
            failures.append(
                f"downstream executions (independent effect ledger) = {ledger_count}, want 1"
            )
        if dispatches != 1:
            failures.append(
                f"gateway dispatches (independent fault layer) = {dispatches}, want 1"
            )
        if debits != 1:
            failures.append(f"wallet debits (gateway-reported) = {debits}, want 1")
        if receipts != 1:
            failures.append(f"receipts (gateway-reported) = {receipts}, want 1")
        if not answered:
            failures.append(
                "no caller was answered with a completed result, so the storm "
                "left the gateway's own state consistent but told nobody the "
                "outcome"
            )
        elif without_receipt or len(receipt_ids) != 1:
            failures.append(
                f"answered callers did not all cite one receipt id "
                f"(distinct ids={len(receipt_ids)}, answered={len(answered)}, "
                f"answered without a receipt={without_receipt})"
            )

        verdict = Verdict.PASS if not failures else Verdict.FAIL
        extra["verdict_failures"] = failures

        observation = (
            f"{len(attempts)} identical concurrent requests carrying one "
            f"idempotency key ({extra['idempotency_key']}) and "
            f"{extra['distinct_request_ids']} distinct request ids. Independently "
            f"observed: the effect ledger recorded {ledger_count} downstream "
            f"execution(s) and the fault layer counted {dispatches} request(s) "
            f"crossing into the tool. Gateway-reported: {debits} wallet debit(s), "
            f"{counters.gateway_sent_attempts} attempt(s) past the send boundary, "
            f"and {receipts} receipt(s) "
            f"[{', '.join(outcomes) if outcomes else 'none'}]. "
            f"{len(answered)} caller(s) were answered with a completed result "
            f"citing {len(receipt_ids)} distinct receipt id(s); {len(in_progress)} "
            f"were told the key was still in flight. The cost of collapsing the "
            f"storm shows in latency: p50 {counters.latency_p50_ms} ms, p95 "
            f"{counters.latency_p95_ms} ms per caller, against a client patience "
            f"budget of {extra['client_timeout_seconds']} s."
        )
        if failures:
            observation += " Guarantee not met: " + "; ".join(failures) + "."
        log.emit(
            "verdict",
            f"{target.configuration.value} -> {verdict.value}",
            scenario=self.test_id,
            configuration=target.configuration.value,
            downstream_executions=ledger_count,
            gateway_dispatches=dispatches,
            gateway_debits=debits,
            receipts=receipts,
            distinct_receipt_ids=len(receipt_ids),
            answered=len(answered),
            in_progress=len(in_progress),
            failures=failures,
        )

        risks.append(
            "Dispatches and debits were counted for one operation under "
            "in-process concurrency against one gateway database; a partitioned "
            "or multi-node gateway deployment is not exercised here."
        )
        if len(answered) > 1 and ledger_count == 1:
            risks.append(
                f"{len(answered)} callers each received a completed result, but "
                f"only {ledger_count} execution reached the tool. The stored "
                "envelope is served back verbatim, so a caller cannot tell from "
                "its own payload whether it drove the call or was served a copy; "
                "the shared receipt id is the only signal that distinguishes them."
            )
        if in_progress:
            risks.append(
                f"{len(in_progress)} caller(s) got an in-flight answer rather than "
                "a final one. A real agent must then poll or retry to learn the "
                "outcome, and this test does not measure that follow-up."
            )
        if counters.latency_p95_ms is not None and counters.latency_p95_ms >= 1000:
            risks.append(
                f"Collapsing the storm is a blocking wait paid by every caller: "
                f"p95 was {counters.latency_p95_ms} ms at concurrency "
                f"{extra['concurrency']}. A client whose patience is shorter than "
                "that gets no information even though the gateway's own state is "
                "consistent."
            )
        return self.result(
            target,
            verdict=verdict,
            observation=observation,
            measurements=measurements,
            attempts=attempts,
            remaining_risks=risks,
            extra=extra,
        )
