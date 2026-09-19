"""Test 6 -- Agent restart with a new idempotency key."""

from __future__ import annotations

from typing import Any

from failure_lab.configurations import ALL_CONFIGURATIONS, AttemptOutcome, Configuration, Target
from failure_lab.faults import FaultMode, FaultPlan
from failure_lab.identity import KeyPolicy, OperationIdentity
from failure_lab.scenarios.base import (
    ConfigurationResult,
    EventLog,
    Measurements,
    Scenario,
    Verdict,
)

#: How long the fault layer withholds the executed call's response before it
#: severs the connection. Every caller here is meant to give up first, so this
#: must exceed every client budget below; it only bounds a leaked handler.
DEFAULT_HOLD_SECONDS = 30.0

#: Client patience on the gateway path. Comfortably above the gateway's own 2s
#: upstream call timeout, so the first attempt records the gateway's
#: classification of the lost response rather than the harness's impatience.
DEFAULT_GATEWAY_TIMEOUT_SECONDS = 8.0

#: Client patience on the direct path. There is no gateway to classify
#: anything, so the client's own timeout is the mechanism; it only has to be
#: shorter than the hold above.
DEFAULT_DIRECT_TIMEOUT_SECONDS = 4.0

#: Minor units per refund, mirroring :meth:`Scenario.refund`'s default.
AMOUNT_MINOR_UNITS = 5000

#: Which layer, if any, stopped the replanned attempt from becoming a second
#: downstream effect. Recorded verbatim in ``extra["deduplicated_by"]``.
DEDUPLICATED_BY_GATEWAY = "gateway"
DEDUPLICATED_BY_DOWNSTREAM = "downstream"
DEDUPLICATED_BY_NOTHING = "nothing"

#: The scope statement this test exists to make explicit. The gateway's
#: documented replay guarantee is keyed on the idempotency key the caller
#: presents; two distinct keys are two distinct operations by design. The
#: business-level property a reader may assume ("one intended refund") is a
#: strictly larger claim, and the gap between the two is what is measured here.
GATEWAY_GUARANTEE_SCOPE = (
    "The gateway's documented guarantee is keyed on the idempotency key the "
    "caller presents, so two distinct keys are two distinct operations by "
    "design -- the gateway never sees the business_operation_id as an identity. "
    "This test measures the gap between that key-scoped guarantee and the "
    "business-level property a reader might assume it covers: one intended "
    "refund, executed at most once and paid for at most once. A FAIL here is a "
    "real gap against the business-level property and is simultaneously outside "
    "the guarantee the product states; both facts belong in any report of it."
)


class AgentRestartNewKey(Scenario):
    """The same business intent, a fresh agent, a brand-new key. Who notices?

    This is the test the PRD says must exist even though it is expected to
    fail today. DO NOT weaken it and DO NOT edit ``expected`` to make a run
    look better.

    WHAT TO IMPLEMENT
    -----------------
    1. Create the identity with ``OperationIdentity.first_attempt(op,
       key_policy=KeyPolicy.ATTEMPT)`` -- an agent that mints its key per
       attempt rather than deriving it from the business operation.
    2. Arm ``RESPONSE_LOST_AFTER_EXECUTION`` for the operation. Submit. The
       first attempt ends ambiguous.
    3. Destroy the agent's context: call ``identity.after_restart()``, which
       under ``KeyPolicy.ATTEMPT`` mints a NEW idempotency key and a new
       request id while keeping the SAME ``business_operation_id``. For the
       gateway configurations, also rebuild the caller
       (``target.gateway_agent(permit_id)``) so nothing in-process carries
       over from the first incarnation.
    4. Submit the replanned attempt and measure.
    5. Verdict rules -- the property under test is *business-level*: one
       intended refund must not execute twice and must not be paid for twice.
       * ``DIRECT_NAIVE``  -> ``OBSERVED``; two executions.
       * ``DIRECT_NATIVE`` -> ``PASS`` iff downstream_executions == 1. The
         downstream deduplicated on ``operation_id``, with no gateway present.
       * ``GATEWAY_NATIVE`` -> ``FAIL`` unless BOTH downstream_executions == 1
         AND gateway_debits == 1. Expect 1 execution (the downstream caught
         it) but 2 debits (the gateway did not), so expect FAIL.
       * ``GATEWAY_NAIVE``  -> ``FAIL`` unless downstream_executions == 1.
         Expect 2 executions and 2 debits.
    6. The observation MUST state, for each gateway configuration, which layer
       prevented the duplicate -- and must say explicitly when the answer is
       "the downstream, not the gateway". Record in
       ``extra["deduplicated_by"]`` one of ``"gateway"``, ``"downstream"``,
       ``"nothing"``.
    7. Record in ``extra["gateway_guarantee_scope"]`` that the gateway's
       documented guarantee is keyed on the idempotency key, so two distinct
       keys are two distinct operations by design; this test measures the gap
       between that guarantee and the business-level property a reader might
       assume it covers.
    """

    test_id = "T06"
    title = "Agent restart with a new idempotency key"
    claim = (
        "One intended business operation executes at most once and is paid "
        "for at most once, even when a restarted agent presents a new "
        "idempotency key for it."
    )
    tier = "fast"
    configurations = ALL_CONFIGURATIONS
    expected = {
        Configuration.DIRECT_NAIVE.value: Verdict.OBSERVED.value,
        Configuration.DIRECT_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NATIVE.value: Verdict.FAIL.value,
        Configuration.GATEWAY_NAIVE.value: Verdict.FAIL.value,
    }
    limitations = (
        "The gateway's documented guarantee is per idempotency key, not per "
        "business operation. The FAIL recorded here is a real gap against the "
        "business-level property, and it is outside the guarantee the product "
        "states. Both facts belong in any report of this result.",
        "An agent that derives its key from the business operation "
        "(KeyPolicy.BUSINESS) does not hit this; the other scenarios use that "
        "policy. This one exists because real agents replan.",
    )

    async def run_configuration(self, target: Target, log: EventLog) -> ConfigurationResult:
        hold_seconds = float(self.options.get("hold_seconds", DEFAULT_HOLD_SECONDS))
        default_timeout = (
            DEFAULT_GATEWAY_TIMEOUT_SECONDS
            if target.uses_gateway
            else DEFAULT_DIRECT_TIMEOUT_SECONDS
        )
        timeout_seconds = float(self.options.get("timeout_seconds", default_timeout))

        operation_id, refund = self.refund("pay_t06")
        identity = OperationIdentity.first_attempt(operation_id, key_policy=KeyPolicy.ATTEMPT)

        target.injector.arm(
            FaultPlan(
                mode=FaultMode.RESPONSE_LOST_AFTER_EXECUTION,
                operation_id=operation_id,
                remaining=1,
                hold_seconds=hold_seconds,
                label="T06: execute, then withhold the response so the agent dies unsure",
            )
        )
        log.emit(
            "fault.arm",
            (
                "armed response_lost_after_execution for one request on this "
                "operation; the agent mints its idempotency key per attempt "
                "(KeyPolicy.ATTEMPT), so a restart will present a new key for "
                "the same business operation"
            ),
            scenario=self.test_id,
            configuration=target.configuration.value,
            operation_id=operation_id,
            key_policy=identity.key_policy.value,
            first_idempotency_key=identity.idempotency_key,
            hold_seconds=hold_seconds,
            client_timeout_seconds=timeout_seconds,
        )

        first = await target.agent.submit(identity, refund, timeout_seconds=timeout_seconds)
        log.emit(
            "attempt.first",
            (
                f"first attempt (generation {identity.agent_generation}) -> "
                f"status={first.status}, "
                f"client_visible_state={first.client_visible_state}"
            ),
            scenario=self.test_id,
            configuration=target.configuration.value,
            request_id=identity.request_id,
            idempotency_key=identity.idempotency_key,
            agent_generation=identity.agent_generation,
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

        # -- the restart: a fresh agent incarnation replans the same intent --
        restarted = identity.after_restart()
        caller = target.agent
        rebuilt_caller = False
        if target.uses_gateway:
            _, _, permit = target.require_gateway()
            caller = target.gateway_agent(permit["permit_id"])
            rebuilt_caller = True
        log.emit(
            "agent.restart",
            (
                "the agent process died without learning the outcome; a fresh "
                f"incarnation (generation {restarted.agent_generation}) replans "
                "the SAME business operation and, having no memory of the old "
                "key, mints a new one"
            ),
            scenario=self.test_id,
            configuration=target.configuration.value,
            business_operation_id=restarted.business_operation_id,
            business_operation_id_unchanged=(
                restarted.business_operation_id == identity.business_operation_id
            ),
            previous_idempotency_key=identity.idempotency_key,
            new_idempotency_key=restarted.idempotency_key,
            key_changed=(restarted.idempotency_key != identity.idempotency_key),
            agent_generation=restarted.agent_generation,
            caller_rebuilt=rebuilt_caller,
        )

        second = await caller.submit(restarted, refund, timeout_seconds=timeout_seconds)
        log.emit(
            "attempt.after_restart",
            (
                f"replanned attempt (new key, new request id, same business "
                f"operation) -> status={second.status}, "
                f"client_visible_state={second.client_visible_state}"
            ),
            scenario=self.test_id,
            configuration=target.configuration.value,
            request_id=restarted.request_id,
            idempotency_key=restarted.idempotency_key,
            agent_generation=restarted.agent_generation,
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
        deduplicated_by = self._deduplicated_by(target, ledger_count, layer_requests)

        log.emit(
            "measure.instruments",
            (
                f"effect ledger (independent): {ledger_count} execution(s); "
                f"fault layer (independent): {layer_requests} request(s) into "
                f"the tool; deduplicated_by={deduplicated_by}"
            ),
            scenario=self.test_id,
            configuration=target.configuration.value,
            downstream_executions=ledger_count,
            downstream_requests=layer_requests,
            deduplicated_by=deduplicated_by,
            gateway_debits=measurements.counters.gateway_debits,
            gateway_refunds=measurements.counters.gateway_refunds,
            gateway_net_debits=measurements.counters.gateway_net_debits,
            gateway_receipts=measurements.counters.receipts,
            gateway_sent_attempts=measurements.counters.gateway_sent_attempts,
            receipt_outcomes=measurements.receipt_outcomes(),
        )

        duplicate_executions = max(0, ledger_count - 1)
        extra: dict[str, Any] = {
            "operation_id": operation_id,
            "key_policy": identity.key_policy.value,
            "first_idempotency_key": identity.idempotency_key,
            "restart_idempotency_key": restarted.idempotency_key,
            "idempotency_key_changed": (
                restarted.idempotency_key != identity.idempotency_key
            ),
            "business_operation_id_unchanged": (
                restarted.business_operation_id == identity.business_operation_id
            ),
            "agent_generations": [identity.agent_generation, restarted.agent_generation],
            "caller_rebuilt_after_restart": rebuilt_caller,
            "fault": FaultMode.RESPONSE_LOST_AFTER_EXECUTION.value,
            "hold_seconds": hold_seconds,
            "client_timeout_seconds": timeout_seconds,
            "first_attempt_status": first.status,
            "first_attempt_client_visible_state": first.client_visible_state,
            "first_attempt_receipt_id": first.receipt_id,
            "first_attempt_receipt_outcome": (
                first.receipt.get("outcome") if first.receipt else None
            ),
            "restart_attempt_status": second.status,
            "restart_attempt_client_visible_state": second.client_visible_state,
            "restart_attempt_receipt_id": second.receipt_id,
            "restart_attempt_receipt_outcome": (
                second.receipt.get("outcome") if second.receipt else None
            ),
            "restart_served_from_stored_result": second.status == "replayed"
            or bool(second.refund and second.refund.get("replayed")),
            "effect_ledger_execution_count": ledger_count,
            "fault_layer_downstream_requests": layer_requests,
            "duplicate_executions": duplicate_executions,
            "value_at_risk_minor_units": duplicate_executions * AMOUNT_MINOR_UNITS,
            "amount_minor_units_per_execution": AMOUNT_MINOR_UNITS,
            "deduplicated_by": deduplicated_by,
            "gateway_guarantee_scope": GATEWAY_GUARANTEE_SCOPE,
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

    # -- which layer, if any, absorbed the replanned attempt --------------

    def _deduplicated_by(
        self, target: Target, ledger_count: int, layer_requests: int
    ) -> str:
        """Name the layer that stopped the replan from becoming a second effect.

        The fault layer sits between the caller (gateway or agent) and the
        tool, so ``layer_requests`` counts what actually reached the tool. One
        request with a gateway in front means the gateway absorbed the replan;
        two requests with one effect means the tool absorbed it; two effects
        means nothing did.
        """
        if ledger_count > 1:
            return DEDUPLICATED_BY_NOTHING
        if target.uses_gateway and layer_requests <= 1:
            return DEDUPLICATED_BY_GATEWAY
        if layer_requests > 1 and ledger_count == 1:
            return DEDUPLICATED_BY_DOWNSTREAM
        return DEDUPLICATED_BY_NOTHING

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
        duplicates = extra["duplicate_executions"]

        observation = (
            f"The tool executed and committed, then its response was withheld; "
            f"the agent saw '{first.status}' ({first.client_visible_state}) and "
            f"died. A fresh incarnation replanned the same business operation "
            f"({extra['operation_id']}) and, having no memory of the old key, "
            f"presented a new one ({extra['first_idempotency_key']} -> "
            f"{extra['restart_idempotency_key']}); that attempt returned "
            f"'{second.status}' ({second.client_visible_state}). The independent "
            f"effect ledger recorded {ledger_count} downstream execution(s) for "
            f"this operation -- {duplicates} beyond the one the agent intended, "
            f"{extra['value_at_risk_minor_units']} minor units of unintended "
            f"refund -- and the fault layer counted {layer_requests} request(s) "
            f"reaching the tool. Nothing here deduplicates on anything: not on "
            f"the key, which changed, and not on the business operation id, "
            f"which did not. Deduplicated by: {extra['deduplicated_by']}. "
            f"Descriptive baseline, no guarantee to test."
        )
        risks = [
            "The agent had no way to distinguish a lost response from a lost "
            "request, and no memory across the restart that could have told it "
            "either way. Retrying duplicated a refund; abandoning might have "
            "left the customer unpaid.",
            "The duplicate is invisible until someone reads the tool's own "
            "ledger. There is no signed artifact here and no third party who "
            "could establish how many refunds this operation caused.",
        ]
        log.emit(
            "verdict",
            f"{target.configuration.value} -> OBSERVED ({ledger_count} executions)",
            scenario=self.test_id,
            configuration=target.configuration.value,
            downstream_executions=ledger_count,
            duplicate_executions=duplicates,
            deduplicated_by=extra["deduplicated_by"],
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

        failures: list[str] = []
        if ledger_count != 1:
            failures.append(
                f"downstream executions (effect ledger) = {ledger_count}, want 1"
            )
        extra["verdict_failures"] = failures
        verdict = Verdict.PASS if not failures else Verdict.FAIL

        observation = (
            f"The tool executed and committed, then its response was withheld; "
            f"the agent saw '{first.status}' ({first.client_visible_state}) and "
            f"died. A fresh incarnation replanned the same business operation "
            f"({extra['operation_id']}) under a brand-new idempotency key "
            f"({extra['first_idempotency_key']} -> "
            f"{extra['restart_idempotency_key']}) and got '{second.status}' "
            f"({second.client_visible_state}). The independent effect ledger "
            f"recorded {ledger_count} downstream execution(s) and the fault "
            f"layer counted {layer_requests} request(s) reaching the tool, so "
            f"the replanned request did reach the tool and was absorbed inside "
            f"it. The new key was irrelevant: this downstream keys its "
            f"idempotency on the business operation_id, which survived the "
            f"restart. Deduplicated by: {extra['deduplicated_by']}. A correctly "
            f"built downstream handles an agent restart on its own, with no "
            f"gateway present."
        )
        if failures:
            observation += (
                " The correct native baseline did NOT hold: " + "; ".join(failures) + "."
            )
        risks = [
            "The protection lives entirely in the tool and is keyed on a field "
            "the agent chose to send. An agent that regenerated its "
            "operation_id along with its key would duplicate here too; nothing "
            "outside the tool checks that.",
            "The deduplication is invisible from outside the tool: no signed, "
            "portable artifact records that a restart happened or that the "
            "second request was absorbed.",
            "The agent still never learned the outcome of its first call; it "
            "recovered only because it was willing to re-issue a consequential "
            "operation blind.",
        ]
        log.emit(
            "verdict",
            f"{target.configuration.value} -> {verdict.value} ({ledger_count} executions)",
            scenario=self.test_id,
            configuration=target.configuration.value,
            downstream_executions=ledger_count,
            restart_status=second.status,
            deduplicated_by=extra["deduplicated_by"],
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
        attempt_states = (
            [a["state"] for a in snapshot.attempts] if snapshot is not None else []
        )
        records = snapshot.idempotency_records if snapshot is not None else []
        duplicate_debits = max(0, (debits or 0) - 1)

        extra.update(
            {
                "gateway_dispatches": dispatches,
                "gateway_debits": debits,
                "gateway_refunds": refunds,
                "gateway_net_debits": net_debits,
                "gateway_sent_attempts": counters.gateway_sent_attempts,
                "gateway_receipts": receipt_count,
                "receipt_outcomes": outcomes,
                "dispatch_attempt_states": attempt_states,
                "duplicate_debits": duplicate_debits,
                "idempotency_record_count": len(records),
                "idempotency_records": records,
                "wallet_balance": (
                    snapshot.wallet_balance if snapshot is not None else None
                ),
                "distinct_receipt_ids": (
                    first.receipt_id is not None
                    and second.receipt_id is not None
                    and first.receipt_id != second.receipt_id
                ),
                "paid_twice": (debits or 0) > 1,
            }
        )

        failures: list[str] = []
        if ledger_count != 1:
            failures.append(
                f"downstream executions (effect ledger) = {ledger_count}, want 1 "
                "-- one intended refund executed more than once"
            )
        if target.configuration is Configuration.GATEWAY_NATIVE:
            if debits is not None and debits != 1:
                failures.append(
                    f"gateway debits (gateway-reported) = {debits}, want 1 -- one "
                    "intended refund was paid for more than once"
                )
        extra["verdict_failures"] = failures
        verdict = Verdict.PASS if not failures else Verdict.FAIL

        dedup = extra["deduplicated_by"]
        if dedup == DEDUPLICATED_BY_GATEWAY:
            layer_sentence = (
                "The gateway prevented the duplicate: only one request crossed "
                "the fault layer into the tool."
            )
        elif dedup == DEDUPLICATED_BY_DOWNSTREAM:
            layer_sentence = (
                "The layer that prevented the duplicate was THE DOWNSTREAM, NOT "
                "THE GATEWAY: the gateway treated the new key as a new operation "
                f"and dispatched again ({layer_requests} request(s) crossed into "
                "the tool), and the tool's own operation_id idempotency absorbed "
                "the second one. Remove the native control and the duplicate "
                "lands."
            )
        else:
            layer_sentence = (
                "NOTHING prevented the duplicate: neither the gateway, which "
                "saw a new key and therefore a new operation, nor the "
                f"downstream, which has no idempotency of its own. "
                f"{layer_requests} request(s) crossed into the tool and "
                f"{ledger_count} execution(s) committed."
            )

        observation = (
            f"The tool executed and committed, then its response was withheld; "
            f"the first attempt came back '{first.status}' "
            f"({first.client_visible_state}) with receipt {first.receipt_id}. "
            f"The agent then died and a fresh incarnation replanned the SAME "
            f"business operation ({extra['operation_id']}) with a NEW "
            f"idempotency key ({extra['first_idempotency_key']} -> "
            f"{extra['restart_idempotency_key']}) through a rebuilt caller; "
            f"that attempt returned '{second.status}' "
            f"({second.client_visible_state}) with receipt "
            f"{second.receipt_id}. Independent instruments: the effect ledger "
            f"recorded {ledger_count} downstream execution(s) and the fault "
            f"layer counted {layer_requests} request(s) crossing into the tool. "
            f"Gateway-reported: {counters.gateway_sent_attempts} attempt(s) past "
            f"the send boundary in state(s) {attempt_states or ['none']}, "
            f"{debits} debit(s) and {refunds} refund(s) for a net {net_debits}, "
            f"{len(records)} idempotency record(s), and {receipt_count} "
            f"receipt(s) recording {outcomes or ['none']}. {layer_sentence} "
            f"Deduplicated by: {dedup}. The gateway's replay guarantee is keyed "
            f"on the idempotency key, and the key changed, so from the gateway's "
            f"point of view these are two operations and it charged for both: "
            f"{duplicate_debits} debit(s) beyond the one the agent intended. "
            f"The business-level property under test -- one intended refund, "
            f"executed at most once and paid for at most once -- is therefore "
            f"{'held' if verdict is Verdict.PASS else 'NOT held'} here."
        )
        if failures:
            observation += " Business-level property not met: " + "; ".join(failures) + "."
        observation += (
            " Scope note: this gap is outside the guarantee the product states, "
            "which is per idempotency key, not per business operation. It is "
            "reported as a real business-level gap and as an out-of-scope one at "
            "the same time; neither half should be dropped."
        )

        risks = [
            "The gateway has no notion of the business operation. Nothing in "
            "the permit, the receipt or the idempotency record ties the two "
            "attempts together, so no gateway-side report would show this as "
            "one intended refund.",
            "Budget and rate limits are consumed per key as well. A restart "
            "loop spends the permit's credits on repeats of a single intent, "
            "and each repeat is individually within policy.",
            "Each attempt produced its own signed receipt. The receipts are "
            "individually truthful about the gateway's own dispatch and debit "
            "and collectively silent about the fact that they describe the same "
            "business action.",
        ]
        if dedup == DEDUPLICATED_BY_DOWNSTREAM:
            risks.append(
                "The single execution recorded here is a property of the "
                "downstream tool, not of the gateway. A buyer reading this row "
                "as evidence that the gateway prevents duplicate refunds would "
                "be reading it wrong."
            )
        if (debits or 0) > 1:
            risks.append(
                "The charge for the second attempt is retained: the first "
                "attempt's delivery was uncertain, so the gateway does not "
                "refund it, and the second was a fully successful governed call "
                "in its own right."
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
            duplicate_debits=duplicate_debits,
            receipts=receipt_count,
            receipt_outcomes=outcomes,
            deduplicated_by=dedup,
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
