"""Test 5 -- Crash after dispatch."""

from __future__ import annotations

from typing import Any

from failure_lab.configurations import (
    GATEWAY_CONFIGURATIONS,
    AttemptOutcome,
    Configuration,
    Target,
)
from failure_lab.gateway import CRASH_BOUNDARY_DESCRIPTIONS
from failure_lab.identity import OperationIdentity
from failure_lab.scenarios.base import (
    ConfigurationResult,
    EventLog,
    Measurements,
    Scenario,
    Verdict,
)

#: How far back attempt rows are aged so the reconciler treats the claim as
#: abandoned rather than live. The real idle window is 11,430 seconds; the lab
#: moves the clock instead of waiting it out, and says so in ``limitations``.
DEFAULT_BACKDATE_SECONDS = 12_000

#: Client patience, comfortably above the gateway's own 2s upstream timeout so
#: what is measured is the gateway dying, not the harness giving up.
DEFAULT_TIMEOUT_SECONDS = 8.0

#: The honest terminal outcome for a claim whose fate the gateway cannot know.
UNCERTAIN_OUTCOME = "delivery_uncertain"

#: A receipt outcome that would assert the gateway knows the call landed. It
#: cannot know that at either of these boundaries.
OVERCLAIMED_OUTCOME = "success"

#: ``(crash boundary, payment id, downstream executions a test observer knows
#: happened)``. Each sub-case gets its own payment id, so its business
#: operation id, idempotency key, gateway attempt row and debit are its own.
CASES: tuple[tuple[str, str, int], ...] = (
    ("after_claim", "pay_t05_a", 0),
    ("after_upstream_response", "pay_t05_b", 1),
)

#: Human labels for the two sub-cases, used in the observation.
CASE_LABELS = {
    "after_claim": "A",
    "after_upstream_response": "B",
}


class CrashAfterDispatch(Scenario):
    """Kill the gateway once the send boundary is crossed. The outcome is unknowable.

    This is the highest-priority crash case in the PRD.

    WHAT TO IMPLEMENT
    -----------------
    Two sub-cases, each with its own payment id and key:

    A. ``after_claim`` -- the durable one-shot claim committed, the network
       send never started. A test observer knows no effect landed
       (downstream_executions == 0 for this operation). A restarted gateway
       cannot know that.
    B. ``after_upstream_response`` -- the downstream executed and answered,
       and the gateway died before recording any terminal state
       (downstream_executions == 1).

    For each: crash, backdate, reconcile, then retry the same key.

    Verdict rules -- ``PASS`` iff for BOTH sub-cases:
      * the attempt terminalizes as ``delivery_uncertain``;
      * the charge is retained (net debit == 1 for that operation);
      * NO redispatch occurs -- gateway_dispatches for the operation is
        unchanged by reconciliation and by the retry;
      * downstream_executions is unchanged by reconciliation and by the retry
        (0 for case A, 1 for case B);
      * the same-key retry returns the ``delivery_uncertain`` disposition
        rather than executing afresh.
    ``FAIL`` on any redispatch, any second downstream effect, or any receipt
    claiming ``success``.

    Case A is the interesting honesty result and the observation must say it
    plainly: the gateway retained a charge for an operation that provably
    never executed, because from inside the gateway that case is
    indistinguishable from case B. Do not present that as a defect and do not
    present it as a virtue -- report it, and note that the caller resolves it
    with the upstream using the forwarded idempotency metadata.

    Record per-case detail in ``extra["cases"]``.
    """

    test_id = "T05"
    title = "Crash after dispatch"
    claim = (
        "Once the one-shot dispatch claim is durable, a crash produces a "
        "receipted uncertain outcome that is never silently redispatched, "
        "whether or not the downstream actually executed."
    )
    tier = "slow"
    configurations = GATEWAY_CONFIGURATIONS
    inapplicable_reason = "a direct integration has no dispatch claim to crash after"
    expected = {
        Configuration.DIRECT_NAIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.DIRECT_NATIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.GATEWAY_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NAIVE.value: Verdict.PASS.value,
    }
    limitations = (
        "Simulated in-process death at an instrumented durable boundary, not "
        "a SIGKILL of a separate OS process.",
        "In case A the charge is retained for an operation that provably did "
        "not execute. That is the documented conservative choice, measured here.",
        "Attempt rows are backdated past the reconciler's idle window.",
    )

    # -- orchestration ----------------------------------------------------

    async def run_configuration(self, target: Target, log: EventLog) -> ConfigurationResult:
        target.require_gateway()
        backdate_seconds = int(
            self.options.get("backdate_seconds", DEFAULT_BACKDATE_SECONDS)
        )
        timeout_seconds = float(
            self.options.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        )

        cases: list[dict[str, Any]] = []
        attempts: list[AttemptOutcome] = []
        operation_ids: list[str] = []
        for boundary, payment_id, expected_executions in CASES:
            case, case_attempts, operation_id = await self._run_case(
                target,
                log,
                boundary=boundary,
                payment_id=payment_id,
                expected_executions=expected_executions,
                backdate_seconds=backdate_seconds,
                timeout_seconds=timeout_seconds,
            )
            cases.append(case)
            attempts.extend(case_attempts)
            operation_ids.append(operation_id)

        measurements = await self.measure(target, attempts, operation_ids=operation_ids)
        for case in cases:
            case.update(self._gateway_rows(measurements.snapshot, case["idempotency_key"]))
            case["failures"] = self._case_failures(case)

        return self._verdict(target, log, cases, attempts, measurements, timeout_seconds)

    # -- one sub-case -----------------------------------------------------

    async def _run_case(
        self,
        target: Target,
        log: EventLog,
        *,
        boundary: str,
        payment_id: str,
        expected_executions: int,
        backdate_seconds: int,
        timeout_seconds: float,
    ) -> tuple[dict[str, Any], list[AttemptOutcome], str]:
        gateway, tenant, _permit = target.require_gateway()
        configuration = target.configuration.value
        label = CASE_LABELS[boundary]
        operation_id, refund = self.refund(payment_id)
        identity = OperationIdentity.first_attempt(operation_id)

        log.emit(
            "case.start",
            (
                f"case {label} ({boundary}): "
                f"{CRASH_BOUNDARY_DESCRIPTIONS[boundary]}"
            ),
            scenario=self.test_id,
            configuration=configuration,
            case=label,
            boundary=boundary,
            boundary_description=CRASH_BOUNDARY_DESCRIPTIONS[boundary],
            operation_id=operation_id,
            idempotency_key=identity.idempotency_key,
            downstream_executions_a_test_observer_expects=expected_executions,
        )

        with gateway.crash_at(boundary) as crash:
            first = await target.agent.submit(
                identity, refund, timeout_seconds=timeout_seconds
            )
        crash_fired = bool(crash["fired"])

        executions_after_crash = target.ledger.execution_count(operation_id)
        dispatches_after_crash = target.injector.dispatch_count(operation_id)
        log.emit(
            "case.crash",
            (
                f"case {label}: gateway died at {boundary}; the agent saw "
                f"'{first.status}' ({first.client_visible_state}). Independent "
                f"instruments right after the death: "
                f"{executions_after_crash} downstream execution(s), "
                f"{dispatches_after_crash} request(s) into the tool"
            ),
            scenario=self.test_id,
            configuration=configuration,
            case=label,
            boundary=boundary,
            crash_fired=crash_fired,
            status=first.status,
            client_visible_state=first.client_visible_state,
            http_status=first.http_status,
            reason=first.reason,
            latency_ms=round(first.latency_ms, 3),
            downstream_executions=executions_after_crash,
            downstream_requests=dispatches_after_crash,
        )

        backdated = await gateway.backdate_attempts(tenant, seconds=backdate_seconds)
        reconciliation = await gateway.reconcile(idle_seconds=0)
        executions_after_reconcile = target.ledger.execution_count(operation_id)
        dispatches_after_reconcile = target.injector.dispatch_count(operation_id)
        log.emit(
            "case.reconcile",
            (
                f"case {label}: restarted gateway swept {backdated} backdated "
                f"attempt row(s); after reconciliation the independent "
                f"instruments read {executions_after_reconcile} downstream "
                f"execution(s) and {dispatches_after_reconcile} request(s) "
                f"into the tool"
            ),
            scenario=self.test_id,
            configuration=configuration,
            case=label,
            boundary=boundary,
            backdated_rows=backdated,
            backdate_seconds=backdate_seconds,
            downstream_executions=executions_after_reconcile,
            downstream_requests=dispatches_after_reconcile,
            **{f"reconcile_{k}": v for k, v in reconciliation.items()},
        )

        retry_identity = identity.retry()
        retry = await target.agent.submit(
            retry_identity, refund, timeout_seconds=timeout_seconds
        )
        executions_after_retry = target.ledger.execution_count(operation_id)
        dispatches_after_retry = target.injector.dispatch_count(operation_id)
        log.emit(
            "case.retry",
            (
                f"case {label}: same-key retry (new request id) -> "
                f"'{retry.status}' ({retry.client_visible_state}); after it the "
                f"independent instruments read {executions_after_retry} "
                f"downstream execution(s) and {dispatches_after_retry} "
                f"request(s) into the tool"
            ),
            scenario=self.test_id,
            configuration=configuration,
            case=label,
            boundary=boundary,
            request_id=retry_identity.request_id,
            idempotency_key=retry_identity.idempotency_key,
            same_key_as_first=(
                retry_identity.idempotency_key == identity.idempotency_key
            ),
            status=retry.status,
            client_visible_state=retry.client_visible_state,
            http_status=retry.http_status,
            reason=retry.reason,
            receipt_id=retry.receipt_id,
            receipt_outcome=retry.receipt.get("outcome") if retry.receipt else None,
            downstream_executions=executions_after_retry,
            downstream_requests=dispatches_after_retry,
        )

        case: dict[str, Any] = {
            "case": label,
            "boundary": boundary,
            "boundary_description": CRASH_BOUNDARY_DESCRIPTIONS[boundary],
            "operation_id": operation_id,
            "idempotency_key": identity.idempotency_key,
            "expected_downstream_executions": expected_executions,
            "crash_fired": crash_fired,
            "crash_status": first.status,
            "crash_client_visible_state": first.client_visible_state,
            "crash_receipt_id": first.receipt_id,
            "downstream_executions_after_crash": executions_after_crash,
            "downstream_executions_after_reconcile": executions_after_reconcile,
            "downstream_executions_after_retry": executions_after_retry,
            "gateway_dispatches_after_crash": dispatches_after_crash,
            "gateway_dispatches_after_reconcile": dispatches_after_reconcile,
            "gateway_dispatches_after_retry": dispatches_after_retry,
            "backdated_attempt_rows": backdated,
            "backdate_seconds": backdate_seconds,
            "reconciliation": dict(reconciliation),
            "retry_used_same_key": (
                retry_identity.idempotency_key == identity.idempotency_key
            ),
            "retry_status": retry.status,
            "retry_client_visible_state": retry.client_visible_state,
            "retry_receipt_id": retry.receipt_id,
            "retry_receipt_outcome": (
                retry.receipt.get("outcome") if retry.receipt else None
            ),
        }
        return case, [first, retry], operation_id

    # -- gateway-reported rows for one sub-case ---------------------------

    @staticmethod
    def _gateway_rows(snapshot: Any, idempotency_key: str) -> dict[str, Any]:
        """Attribute the wallet's gateway rows to one sub-case by its key."""
        if snapshot is None:
            return {
                "idempotency_record_ids": [],
                "attempt_states": [],
                "attempt_sent_flags": [],
                "attempt_rows": [],
                "receipt_ids": [],
                "case_receipt_outcomes": [],
                "case_gateway_debits": 0,
                "case_gateway_refunds": 0,
                "case_gateway_net_debits": 0,
                "credits_debited": [],
            }
        record_ids = {
            record["record_id"]
            for record in snapshot.idempotency_records
            if record["idempotency_key"] == idempotency_key
        }
        attempt_rows = [
            a for a in snapshot.attempts if a["idempotency_record_id"] in record_ids
        ]
        receipt_rows = [
            r for r in snapshot.receipts if r["idempotency_record_id"] in record_ids
        ]
        debit_rows = [d for d in snapshot.debits if d["operation_key"] in record_ids]
        refund_entry_ids = {f"refund-{d['entry_id']}" for d in debit_rows}
        refund_rows = [r for r in snapshot.refunds if r["entry_id"] in refund_entry_ids]
        return {
            "idempotency_record_ids": sorted(record_ids),
            "attempt_states": [a["state"] for a in attempt_rows],
            "attempt_sent_flags": [a["sent"] for a in attempt_rows],
            "attempt_rows": attempt_rows,
            "receipt_ids": [r["receipt_id"] for r in receipt_rows],
            "case_receipt_outcomes": [r["outcome"] for r in receipt_rows],
            "case_gateway_debits": len(debit_rows),
            "case_gateway_refunds": len(refund_rows),
            "case_gateway_net_debits": len(debit_rows) - len(refund_rows),
            "credits_debited": [d["amount"] for d in debit_rows],
        }

    # -- verdict ----------------------------------------------------------

    @staticmethod
    def _case_failures(case: dict[str, Any]) -> list[str]:
        label = case["case"]
        boundary = case["boundary"]
        expected = case["expected_downstream_executions"]
        failures: list[str] = []

        if not case["crash_fired"]:
            failures.append(
                f"case {label}: the crash hook at {boundary} never fired, so "
                "this sub-case did not measure what it claims to"
            )
        if case["crash_status"] != "gateway_process_died":
            failures.append(
                f"case {label}: the crashing attempt returned "
                f"'{case['crash_status']}', want 'gateway_process_died'"
            )

        if case["downstream_executions_after_crash"] != expected:
            failures.append(
                f"case {label}: downstream executions (effect ledger) at the "
                f"moment of death = {case['downstream_executions_after_crash']}, "
                f"want {expected} for the {boundary} boundary"
            )
        if case["downstream_executions_after_reconcile"] != expected:
            failures.append(
                f"case {label}: reconciliation changed downstream executions to "
                f"{case['downstream_executions_after_reconcile']}, want {expected}"
            )
        if case["downstream_executions_after_retry"] != expected:
            failures.append(
                f"case {label}: the same-key retry changed downstream executions "
                f"to {case['downstream_executions_after_retry']}, want {expected}"
            )

        dispatched = case["gateway_dispatches_after_crash"]
        if case["gateway_dispatches_after_reconcile"] != dispatched:
            failures.append(
                f"case {label}: reconciliation redispatched -- requests into the "
                f"tool went {dispatched} -> "
                f"{case['gateway_dispatches_after_reconcile']}"
            )
        if case["gateway_dispatches_after_retry"] != dispatched:
            failures.append(
                f"case {label}: the same-key retry redispatched -- requests into "
                f"the tool went {dispatched} -> "
                f"{case['gateway_dispatches_after_retry']}"
            )

        outcomes = case.get("case_receipt_outcomes", [])
        if outcomes.count(UNCERTAIN_OUTCOME) != 1:
            failures.append(
                f"case {label}: receipts for this operation record "
                f"{outcomes or ['none']}, want a single '{UNCERTAIN_OUTCOME}'"
            )
        overclaimed = [o for o in outcomes if o == OVERCLAIMED_OUTCOME]
        if overclaimed:
            failures.append(
                f"case {label}: {len(overclaimed)} receipt(s) record "
                f"'{OVERCLAIMED_OUTCOME}' for a call the gateway never saw the "
                "end of -- it claimed knowledge it does not have"
            )

        states = case.get("attempt_states", [])
        if states != [UNCERTAIN_OUTCOME]:
            failures.append(
                f"case {label}: dispatch attempt state(s) after recovery = "
                f"{states or ['none']}, want ['{UNCERTAIN_OUTCOME}']"
            )

        if case.get("case_gateway_net_debits") != 1:
            failures.append(
                f"case {label}: net debit for this operation = "
                f"{case.get('case_gateway_net_debits')} "
                f"({case.get('case_gateway_debits')} debit(s), "
                f"{case.get('case_gateway_refunds')} refund(s)), want 1 retained"
            )

        if case["retry_status"] != UNCERTAIN_OUTCOME:
            failures.append(
                f"case {label}: the same-key retry returned "
                f"'{case['retry_status']}' "
                f"({case['retry_client_visible_state']}), want the "
                f"'{UNCERTAIN_OUTCOME}' disposition"
            )
        if case["retry_client_visible_state"] != "explicit_uncertain":
            failures.append(
                f"case {label}: the same-key retry's client-visible state was "
                f"'{case['retry_client_visible_state']}', want "
                "'explicit_uncertain'"
            )
        if case["retry_receipt_outcome"] != UNCERTAIN_OUTCOME:
            failures.append(
                f"case {label}: the same-key retry cited receipt outcome "
                f"{case['retry_receipt_outcome']!r}, want "
                f"'{UNCERTAIN_OUTCOME}'"
            )
        return failures

    def _verdict(
        self,
        target: Target,
        log: EventLog,
        cases: list[dict[str, Any]],
        attempts: list[AttemptOutcome],
        measurements: Measurements,
        timeout_seconds: float,
    ) -> ConfigurationResult:
        counters = measurements.counters
        all_outcomes = measurements.receipt_outcomes()
        failures = [failure for case in cases for failure in case["failures"]]
        overclaimed_total = [o for o in all_outcomes if o == OVERCLAIMED_OUTCOME]
        if overclaimed_total and not any("record 'success'" in f for f in failures):
            failures.append(
                f"{len(overclaimed_total)} receipt(s) on this wallet record "
                f"'{OVERCLAIMED_OUTCOME}' for a crashed governed call"
            )
        verdict = Verdict.PASS if not failures else Verdict.FAIL

        case_a = cases[0]
        case_b = cases[1]
        extra: dict[str, Any] = {
            "cases": cases,
            "client_timeout_seconds": timeout_seconds,
            "gateway_dispatches_total": counters.gateway_dispatches,
            "gateway_debits_total": counters.gateway_debits,
            "gateway_refunds_total": counters.gateway_refunds,
            "gateway_net_debits_total": counters.gateway_net_debits,
            "gateway_sent_attempts_total": counters.gateway_sent_attempts,
            "gateway_receipts_total": counters.receipts,
            "receipt_outcomes_total": all_outcomes,
            "receipts_claiming_success": len(overclaimed_total),
            "downstream_executions_total": counters.downstream_executions,
            "sent_flag_note": (
                "backdate_attempts writes dispatched_at on every attempt row of "
                "the wallet, so the snapshot's 'sent' flag is not evidence after "
                "the lab ages the clock. Both attempts here genuinely committed "
                "the one-shot claim; the verdict rests on attempt state, the "
                "effect ledger and the fault layer, not on that flag."
            ),
            "wallet_balance": (
                measurements.snapshot.wallet_balance
                if measurements.snapshot is not None
                else None
            ),
            "verdict_failures": failures,
        }

        observation = (
            f"Two independent operations were each driven past the gateway's "
            f"one-shot dispatch claim and then killed. "
            f"Case A ({case_a['boundary']}: "
            f"{case_a['boundary_description']}): the agent saw "
            f"'{case_a['crash_status']}' "
            f"({case_a['crash_client_visible_state']}); the independent effect "
            f"ledger recorded "
            f"{case_a['downstream_executions_after_crash']} downstream "
            f"execution(s) and the fault layer counted "
            f"{case_a['gateway_dispatches_after_crash']} request(s) into the "
            f"tool. Case B ({case_b['boundary']}: "
            f"{case_b['boundary_description']}): the agent saw "
            f"'{case_b['crash_status']}' "
            f"({case_b['crash_client_visible_state']}); the ledger recorded "
            f"{case_b['downstream_executions_after_crash']} downstream "
            f"execution(s) and the fault layer counted "
            f"{case_b['gateway_dispatches_after_crash']} request(s) into the "
            f"tool. A restarted gateway then swept both: reconciliation "
            f"terminalized case A as "
            f"{case_a.get('attempt_states') or ['none']} with receipt "
            f"outcome(s) {case_a.get('case_receipt_outcomes') or ['none']} and "
            f"case B as {case_b.get('attempt_states') or ['none']} with receipt "
            f"outcome(s) {case_b.get('case_receipt_outcomes') or ['none']}. "
            f"Neither sweep and neither same-key retry moved either counter: "
            f"executions stayed at "
            f"{case_a['downstream_executions_after_retry']} for case A and "
            f"{case_b['downstream_executions_after_retry']} for case B, and "
            f"requests into the tool stayed at "
            f"{case_a['gateway_dispatches_after_retry']} and "
            f"{case_b['gateway_dispatches_after_retry']}. Both same-key retries "
            f"came back '{case_a['retry_status']}' and "
            f"'{case_b['retry_status']}', citing receipts "
            f"{case_a['retry_receipt_id']} and {case_b['retry_receipt_id']} "
            f"rather than starting a fresh call. Gateway-reported accounting: "
            f"net {case_a.get('case_gateway_net_debits')} debit for case A and "
            f"net {case_b.get('case_gateway_net_debits')} for case B, "
            f"{counters.gateway_refunds} refund(s) on the wallet, "
            f"{counters.receipts} receipt(s) recording "
            f"{all_outcomes or ['none']}. "
            f"The honesty result is case A: the gateway retained the charge for "
            f"an operation that a test observer can prove never executed, "
            f"because from inside the gateway a claim that died before the send "
            f"looks exactly like case B, where the tool did run. The gateway "
            f"does not redispatch either one and does not sign a claim of "
            f"success for either one; it signs that delivery is uncertain and "
            f"stops. That is a statement about the gateway's own dispatch and "
            f"debit, not evidence about what the downstream did -- only the "
            f"effect ledger, which the gateway cannot reach, speaks to that. "
            f"The caller resolves case A with the upstream provider using the "
            f"idempotency metadata the gateway forwarded, and reclaims or "
            f"writes off the credit there."
        )
        if failures:
            observation += " Guarantee not met: " + "; ".join(failures) + "."

        risks = [
            "Case A retains a charge for an operation that provably did not "
            "execute. The gateway cannot distinguish it from case B, so this is "
            "a cost the caller carries whenever a claim dies before the send.",
            "A delivery_uncertain receipt is a signed statement about the "
            "gateway's own dispatch and debit. It does not establish whether "
            "the refund reached the customer, and nothing the gateway can sign "
            "here would.",
            "Resolution lives outside the gateway: the caller must reconcile "
            "with the tool provider using the forwarded idempotency metadata. "
            "The gateway offers no in-band way to close out an uncertain "
            "operation.",
            "Reconciliation acted here only because the attempt rows were "
            "backdated past the idle window. In production the uncertain "
            "outcome is not signed until that window elapses, so the caller "
            "sits with no terminal receipt for hours.",
        ]

        log.emit(
            "verdict",
            f"{target.configuration.value} -> {verdict.value}",
            scenario=self.test_id,
            configuration=target.configuration.value,
            case_a_executions=case_a["downstream_executions_after_retry"],
            case_a_dispatches=case_a["gateway_dispatches_after_retry"],
            case_a_net_debits=case_a.get("case_gateway_net_debits"),
            case_a_receipt_outcomes=case_a.get("case_receipt_outcomes"),
            case_b_executions=case_b["downstream_executions_after_retry"],
            case_b_dispatches=case_b["gateway_dispatches_after_retry"],
            case_b_net_debits=case_b.get("case_gateway_net_debits"),
            case_b_receipt_outcomes=case_b.get("case_receipt_outcomes"),
            receipts_claiming_success=len(overclaimed_total),
            failures=failures,
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
