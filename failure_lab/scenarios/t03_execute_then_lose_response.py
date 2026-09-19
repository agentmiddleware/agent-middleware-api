"""Test 3 -- Execute, then lose the response."""

from __future__ import annotations

from typing import Any

from failure_lab.configurations import ALL_CONFIGURATIONS, AttemptOutcome, Configuration, Target
from failure_lab.faults import FaultMode, FaultPlan
from failure_lab.identity import OperationIdentity
from failure_lab.scenarios.base import (
    ConfigurationResult,
    EventLog,
    Measurements,
    Scenario,
    Verdict,
)

#: How long the fault layer withholds the executed call's response before it
#: severs the connection. It only bounds a leaked handler: every caller in this
#: scenario is meant to give up first, so this must exceed every client budget
#: below.
DEFAULT_HOLD_SECONDS = 30.0

#: Client patience on the gateway path. Comfortably above the gateway's own 2s
#: upstream call timeout, so what this test records is the gateway's
#: classification of the lost response rather than the harness's impatience.
DEFAULT_GATEWAY_TIMEOUT_SECONDS = 8.0

#: Client patience on the direct path. There is no gateway to classify
#: anything here, so the client's own timeout *is* the mechanism under
#: measurement; it only has to be shorter than the hold above.
DEFAULT_DIRECT_TIMEOUT_SECONDS = 4.0

#: Minor units per refund, mirroring :meth:`Scenario.refund`'s default.
AMOUNT_MINOR_UNITS = 5000

#: The only receipt outcome that is honest about a response that never came
#: back after the dispatch claim was committed.
UNCERTAIN_OUTCOME = "delivery_uncertain"

#: A receipt outcome that would assert the gateway knows the call succeeded.
#: It cannot know that here, so recording it is a failure of the claim.
OVERCLAIMED_OUTCOME = "success"


class ExecuteThenLoseResponse(Scenario):
    """The headline failure: the tool ran, the answer vanished, the agent retried.

    WHAT TO IMPLEMENT
    -----------------
    1. Arm ``FaultPlan(mode=FaultMode.RESPONSE_LOST_AFTER_EXECUTION,
       operation_id=op, hold_seconds=...)`` on ``target.injector``. The tool
       executes and commits; the response never comes back.
    2. First attempt: submit and let the client time out (direct configs) or
       let the gateway's call timeout fire (gateway configs). Use a client
       timeout comfortably above the gateway's own 2s call timeout so the
       gateway's classification, not the harness's impatience, is what is
       measured.
    3. Retry with ``identity.retry()`` -- same key, new request id.
    4. Measure and record ALL of: downstream execution count (effect ledger),
       gateway dispatch count (fault layer), gateway attempt state, debit
       state, receipt state, and client-visible state for both attempts.
    5. Verdict rules:
       * ``DIRECT_NAIVE``  -> ``OBSERVED``; expect 2 executions. This is the
         duplicate the whole lab exists to show.
       * ``DIRECT_NATIVE`` -> ``PASS`` iff downstream_executions == 1 and the
         retry was answered from the stored result.
       * gateway configs   -> ``PASS`` iff downstream_executions == 1 AND
         gateway_dispatches == 1 AND the first attempt's client-visible state
         is ``explicit_uncertain`` AND the retry returns the SAME receipt id
         without a second dispatch or debit.
    6. CRITICAL honesty rule: the gateway must not claim knowledge it does not
       have. ``FAIL`` if any gateway receipt for this operation records
       ``success``. The correct outcome is ``delivery_uncertain``. State in the
       observation that the charge is retained by design and that the receipt
       does not establish whether the refund reached the customer.
    """

    test_id = "T03"
    title = "Execute then lose response"
    claim = (
        "When a tool executes but its response is lost, the gateway records a "
        "distinct uncertain outcome, never a second dispatch and never a "
        "claim of success it cannot support."
    )
    tier = "fast"
    configurations = ALL_CONFIGURATIONS
    expected = {
        Configuration.DIRECT_NAIVE.value: Verdict.OBSERVED.value,
        Configuration.DIRECT_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NAIVE.value: Verdict.PASS.value,
    }
    limitations = (
        "The gateway retains the charge on an uncertain outcome by design; "
        "this test measures that, it does not argue for it.",
        "A delivery_uncertain receipt is not evidence about the downstream "
        "effect. Only the independent effect ledger speaks to that here.",
    )

    async def run_configuration(self, target: Target, log: EventLog) -> ConfigurationResult:
        hold_seconds = float(self.options.get("hold_seconds", DEFAULT_HOLD_SECONDS))
        default_timeout = (
            DEFAULT_GATEWAY_TIMEOUT_SECONDS
            if target.uses_gateway
            else DEFAULT_DIRECT_TIMEOUT_SECONDS
        )
        timeout_seconds = float(self.options.get("timeout_seconds", default_timeout))

        operation_id, refund = self.refund("pay_t03")
        identity = OperationIdentity.first_attempt(operation_id)

        target.injector.arm(
            FaultPlan(
                mode=FaultMode.RESPONSE_LOST_AFTER_EXECUTION,
                operation_id=operation_id,
                remaining=1,
                hold_seconds=hold_seconds,
                label="T03: execute, then withhold the response",
            )
        )
        log.emit(
            "fault.arm",
            (
                "armed response_lost_after_execution for one request on this "
                "operation: the tool executes and commits, the answer never returns"
            ),
            scenario=self.test_id,
            configuration=target.configuration.value,
            operation_id=operation_id,
            idempotency_key=identity.idempotency_key,
            hold_seconds=hold_seconds,
            client_timeout_seconds=timeout_seconds,
        )

        first = await target.agent.submit(identity, refund, timeout_seconds=timeout_seconds)
        log.emit(
            "attempt.first",
            (
                f"first attempt -> status={first.status}, "
                f"client_visible_state={first.client_visible_state}"
            ),
            scenario=self.test_id,
            configuration=target.configuration.value,
            request_id=identity.request_id,
            status=first.status,
            client_visible_state=first.client_visible_state,
            http_status=first.http_status,
            reason=first.reason,
            receipt_id=first.receipt_id,
            receipt_outcome=first.receipt.get("outcome") if first.receipt else None,
            latency_ms=round(first.latency_ms, 3),
            executions_so_far=target.ledger.execution_count(operation_id),
            downstream_requests_so_far=target.injector.dispatch_count(operation_id),
        )

        retry_identity = identity.retry()
        second = await target.agent.submit(
            retry_identity, refund, timeout_seconds=timeout_seconds
        )
        log.emit(
            "attempt.retry",
            (
                f"retry (same key, new request id) -> status={second.status}, "
                f"client_visible_state={second.client_visible_state}"
            ),
            scenario=self.test_id,
            configuration=target.configuration.value,
            request_id=retry_identity.request_id,
            idempotency_key=retry_identity.idempotency_key,
            same_key_as_first=(
                retry_identity.idempotency_key == identity.idempotency_key
            ),
            status=second.status,
            client_visible_state=second.client_visible_state,
            http_status=second.http_status,
            reason=second.reason,
            receipt_id=second.receipt_id,
            receipt_outcome=second.receipt.get("outcome") if second.receipt else None,
            latency_ms=round(second.latency_ms, 3),
        )

        attempts = [first, second]
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
            gateway_refunds=measurements.counters.gateway_refunds,
            gateway_net_debits=measurements.counters.gateway_net_debits,
            gateway_receipts=measurements.counters.receipts,
            gateway_sent_attempts=measurements.counters.gateway_sent_attempts,
            receipt_outcomes=measurements.receipt_outcomes(),
        )

        extra: dict[str, Any] = {
            "operation_id": operation_id,
            "idempotency_key": identity.idempotency_key,
            "fault": FaultMode.RESPONSE_LOST_AFTER_EXECUTION.value,
            "hold_seconds": hold_seconds,
            "client_timeout_seconds": timeout_seconds,
            "first_attempt_status": first.status,
            "first_attempt_client_visible_state": first.client_visible_state,
            "first_attempt_receipt_id": first.receipt_id,
            "first_attempt_receipt_outcome": (
                first.receipt.get("outcome") if first.receipt else None
            ),
            "retry_status": second.status,
            "retry_client_visible_state": second.client_visible_state,
            "retry_receipt_id": second.receipt_id,
            "retry_receipt_outcome": (
                second.receipt.get("outcome") if second.receipt else None
            ),
            "retry_used_same_key": (
                retry_identity.idempotency_key == identity.idempotency_key
            ),
            "effect_ledger_execution_count": ledger_count,
            "fault_layer_downstream_requests": layer_requests,
            "amount_minor_units_per_execution": AMOUNT_MINOR_UNITS,
        }

        if target.uses_gateway:
            return self._gateway_result(
                target, log, attempts, measurements, extra, ledger_count, layer_requests
            )
        if target.configuration is Configuration.DIRECT_NATIVE:
            return self._direct_native_result(
                target, log, attempts, measurements, extra, ledger_count, layer_requests
            )
        return self._direct_naive_result(
            target, log, attempts, measurements, extra, ledger_count, layer_requests
        )

    # -- per-configuration verdicts --------------------------------------

    def _direct_naive_result(
        self,
        target: Target,
        log: EventLog,
        attempts: list[AttemptOutcome],
        measurements: Measurements,
        extra: dict[str, Any],
        ledger_count: int,
        layer_requests: int,
    ) -> ConfigurationResult:
        first, second = attempts
        duplicates = max(0, ledger_count - 1)
        extra["duplicate_executions"] = duplicates
        extra["value_at_risk_minor_units"] = duplicates * AMOUNT_MINOR_UNITS

        observation = (
            f"The tool executed and committed, then its response was withheld. "
            f"The agent saw '{first.status}' "
            f"({first.client_visible_state}) and retried the same business "
            f"operation with the same idempotency key and a new request id; the "
            f"retry came back '{second.status}' ({second.client_visible_state}). "
            f"The independent effect ledger recorded {ledger_count} downstream "
            f"execution(s) for this operation -- {duplicates} beyond the one the "
            f"agent intended, {duplicates * AMOUNT_MINOR_UNITS} minor units of "
            f"unintended refund -- and the fault layer counted {layer_requests} "
            f"request(s) reaching the tool. Nothing in this configuration "
            f"deduplicates and nothing told the agent the first call had already "
            f"landed: descriptive baseline, no guarantee to test."
        )
        risks = [
            "A lost response is indistinguishable from a lost request to this "
            "agent, so the only safe options are to retry (and duplicate) or to "
            "abandon (and possibly never refund). It has no third option.",
            "There is no signed artifact here; an auditor asking later how many "
            "refunds this operation caused has only the tool's own ledger.",
        ]
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
        ledger_count: int,
        layer_requests: int,
    ) -> ConfigurationResult:
        first, second = attempts
        retry_from_store = second.status == "replayed"
        extra["retry_served_from_stored_result"] = retry_from_store

        failures: list[str] = []
        if ledger_count != 1:
            failures.append(
                f"downstream executions (effect ledger) = {ledger_count}, want 1"
            )
        if not retry_from_store:
            failures.append(
                "the retry was not answered from the tool's stored result "
                f"(status={second.status}, client_visible_state="
                f"{second.client_visible_state})"
            )
        extra["verdict_failures"] = failures
        verdict = Verdict.PASS if not failures else Verdict.FAIL

        observation = (
            f"The tool executed and committed, then its response was withheld; "
            f"the agent saw '{first.status}' "
            f"({first.client_visible_state}) and retried with the same business "
            f"operation id. The retry returned '{second.status}' "
            f"({second.client_visible_state}). The independent effect ledger "
            f"recorded {ledger_count} downstream execution(s) and the fault layer "
            f"counted {layer_requests} request(s) reaching the tool, so the "
            f"second request did reach the tool and was absorbed inside it. A "
            f"correctly built downstream handles this failure on its own: the "
            f"gateway adds nothing to the duplicate-suppression question here."
        )
        if failures:
            observation += (
                " The correct native baseline did NOT hold: " + "; ".join(failures) + "."
            )
        risks = [
            "The agent still never learned the outcome of its first call; it "
            "recovered only because it was willing to retry a consequential "
            "operation blind. The tool made that safe, not the agent.",
            "The deduplication is invisible from outside the tool -- there is no "
            "signed, portable artifact a third party could check, and no record "
            "that the first response was lost at all.",
        ]
        log.emit(
            "verdict",
            f"{target.configuration.value} -> {verdict.value} ({ledger_count} executions)",
            scenario=self.test_id,
            configuration=target.configuration.value,
            downstream_executions=ledger_count,
            retry_status=second.status,
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

    def _gateway_result(
        self,
        target: Target,
        log: EventLog,
        attempts: list[AttemptOutcome],
        measurements: Measurements,
        extra: dict[str, Any],
        ledger_count: int,
        layer_requests: int,
    ) -> ConfigurationResult:
        first, second = attempts
        counters = measurements.counters
        dispatches = counters.gateway_dispatches
        debits = counters.gateway_debits
        refunds = counters.gateway_refunds
        net_debits = counters.gateway_net_debits
        receipt_count = counters.receipts
        outcomes = measurements.receipt_outcomes()
        snapshot = measurements.snapshot

        overclaimed = [o for o in outcomes if o == OVERCLAIMED_OUTCOME]
        uncertain_receipts = [o for o in outcomes if o == UNCERTAIN_OUTCOME]
        attempt_states = (
            [a["state"] for a in snapshot.attempts] if snapshot is not None else []
        )
        sent_attempts = counters.gateway_sent_attempts

        extra.update(
            {
                "gateway_dispatches": dispatches,
                "gateway_debits": debits,
                "gateway_refunds": refunds,
                "gateway_net_debits": net_debits,
                "gateway_sent_attempts": sent_attempts,
                "gateway_receipts": receipt_count,
                "receipt_outcomes": outcomes,
                "dispatch_attempt_states": attempt_states,
                "receipts_claiming_success": len(overclaimed),
                "receipts_recording_uncertainty": len(uncertain_receipts),
                "charge_retained": net_debits,
                "wallet_balance": (
                    snapshot.wallet_balance if snapshot is not None else None
                ),
                "idempotency_records": (
                    snapshot.idempotency_records if snapshot is not None else []
                ),
                "same_receipt_id_on_retry": (
                    first.receipt_id is not None
                    and second.receipt_id is not None
                    and first.receipt_id == second.receipt_id
                ),
            }
        )

        failures: list[str] = []
        if ledger_count != 1:
            failures.append(
                f"downstream executions (effect ledger) = {ledger_count}, want 1"
            )
        if dispatches != 1:
            failures.append(f"gateway dispatches (fault layer) = {dispatches}, want 1")
        if first.client_visible_state != "explicit_uncertain":
            failures.append(
                "the first attempt's client-visible state was "
                f"'{first.client_visible_state}' (status={first.status}), want "
                "'explicit_uncertain'"
            )
        if first.receipt_id is None:
            failures.append("the first attempt returned no receipt id")
        elif second.receipt_id != first.receipt_id:
            failures.append(
                f"the retry cited receipt id {second.receipt_id!r}, not the "
                f"first attempt's {first.receipt_id!r}"
            )
        if layer_requests > 1:
            failures.append(
                f"the retry produced a second request into the tool "
                f"({layer_requests} crossings observed)"
            )
        if debits is not None and debits != 1:
            failures.append(f"gateway debits (gateway-reported) = {debits}, want 1")
        if overclaimed:
            failures.append(
                f"{len(overclaimed)} receipt(s) record outcome "
                f"'{OVERCLAIMED_OUTCOME}' for a call whose response never "
                "returned -- the gateway claimed knowledge it does not have"
            )

        verdict = Verdict.PASS if not failures else Verdict.FAIL
        extra["verdict_failures"] = failures

        observation = (
            f"The tool executed and committed, then its response was withheld. "
            f"Independent instruments: the effect ledger recorded {ledger_count} "
            f"downstream execution(s) and the fault layer counted "
            f"{layer_requests} request(s) crossing into the tool across both "
            f"attempts. The first attempt came back '{first.status}' "
            f"({first.client_visible_state}) with receipt {first.receipt_id}; the "
            f"retry, carrying the same idempotency key and a new request id, came "
            f"back '{second.status}' ({second.client_visible_state}) citing "
            f"receipt {second.receipt_id}. Gateway-reported: {sent_attempts} "
            f"attempt(s) past the send boundary in state(s) "
            f"{attempt_states or ['none']}, {debits} debit(s) and {refunds} "
            f"refund(s) for a net {net_debits}, and {receipt_count} receipt(s) "
            f"recording {outcomes or ['none']}. "
            f"The charge is retained by design: the dispatch claim was committed "
            f"before the send, so the gateway cannot prove the call did not land "
            f"and does not redispatch it. The receipt records that the delivery "
            f"is uncertain; it does not establish whether the refund reached the "
            f"customer. Only the effect ledger, which the gateway cannot reach, "
            f"speaks to that -- and here it says the tool ran and committed once."
        )
        if overclaimed:
            observation += (
                f" HONESTY FAILURE: {len(overclaimed)} receipt(s) assert "
                f"'{OVERCLAIMED_OUTCOME}' for a response the gateway never saw."
            )
        if failures:
            observation += " Guarantee not met: " + "; ".join(failures) + "."

        risks = [
            "The charge is retained on an uncertain outcome. A caller whose "
            "downstream silently dropped the call pays for a refund that may "
            "never have happened; reconciling that is the caller's job, not the "
            "gateway's.",
            "A delivery_uncertain receipt is a signed statement about the "
            "gateway's own dispatch and debit, not evidence about the downstream "
            "effect. Nothing the gateway can sign here says how many refunds the "
            "customer received.",
            "The agent is told the outcome is unknown but is given no resolution "
            "path inside the gateway; it must reconcile with the tool provider "
            "using the forwarded idempotency metadata.",
        ]
        if ledger_count == 1 and layer_requests == 1:
            risks.append(
                "The downstream here honours a forwarded idempotency key only in "
                "the native configuration; this scenario never needed it, because "
                "the gateway sent the call once. That is a statement about this "
                "run's counts, not a general guarantee about the tool."
            )

        log.emit(
            "verdict",
            f"{target.configuration.value} -> {verdict.value}",
            scenario=self.test_id,
            configuration=target.configuration.value,
            downstream_executions=ledger_count,
            gateway_dispatches=dispatches,
            gateway_debits=debits,
            gateway_net_debits=net_debits,
            receipts=receipt_count,
            receipt_outcomes=outcomes,
            receipts_claiming_success=len(overclaimed),
            first_client_visible_state=first.client_visible_state,
            retry_receipt_matches_first=extra["same_receipt_id_on_retry"],
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
