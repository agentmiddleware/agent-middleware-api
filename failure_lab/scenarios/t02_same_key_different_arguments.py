"""Test 2 -- Same key, different arguments."""

from __future__ import annotations

from typing import Any

from failure_lab.configurations import ALL_CONFIGURATIONS, Configuration, Target
from failure_lab.identity import OperationIdentity
from failure_lab.scenarios.base import (
    REFUSED_STATUSES,
    ConfigurationResult,
    EventLog,
    Scenario,
    Verdict,
)

#: Amount of the refund that is allowed to settle, in minor units.
_SETTLED_AMOUNT = 100
#: Amount smuggled in under the spent key, in minor units.
_CONFLICTING_AMOUNT = 10_000
#: The refusal reason each configuration's enforcement point is documented to
#: use. The gateway refuses at its idempotency layer; the correctly built
#: downstream refuses at its own operation_id store.
_EXPECTED_CONFLICT_REASON: dict[Configuration, str] = {
    Configuration.DIRECT_NATIVE: "operation_id_reused_with_different_payload",
    Configuration.GATEWAY_NATIVE: "idempotency_key_reused",
    Configuration.GATEWAY_NAIVE: "idempotency_key_reused",
}


class SameKeyDifferentArguments(Scenario):
    """A spent key must not smuggle a different business action through.

    WHAT TO IMPLEMENT
    -----------------
    1. Submit refund A (amount 100) under identity K. Assert it settles.
    2. Submit refund B (amount 10000) under the SAME identity K -- same
       idempotency key, same business operation id, different amount.
    3. Measure. Record the precise refusal reason in ``extra["conflict_reason"]``
       (for the gateway that is ``idempotency_key_reused``; for the native
       downstream it is ``operation_id_reused_with_different_payload``).
    4. Verdict rules:
       * ``DIRECT_NAIVE``  -> ``OBSERVED``; it will execute both.
       * every other configuration -> ``PASS`` iff the conflicting request was
         refused AND downstream_executions == 1 AND (for gateway configs) the
         second request produced no additional dispatch and no additional
         debit. ``FAIL`` if a second business effect landed.
    5. Also submit refund B under a *fresh* key as a control and confirm it
       does execute -- otherwise "refused" could mean "the tool is broken"
       rather than "the key was reused". Put the control's outcome in
       ``extra["fresh_key_control"]`` and exclude its operation id from the
       measured set.
    """

    test_id = "T02"
    title = "Same key, different arguments"
    claim = (
        "A reused idempotency key carrying a different payload is refused "
        "before any further downstream business effect occurs."
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
        "Covers a changed amount. Payload equality is by canonical hash, so "
        "any changed field behaves the same way; only one is exercised here.",
    )

    async def run_configuration(self, target: Target, log: EventLog) -> ConfigurationResult:
        configuration = target.configuration

        def emit(step: str, message: str, **data: Any) -> None:
            log.emit(
                step,
                message,
                scenario=self.test_id,
                configuration=configuration.value,
                **data,
            )

        # One business operation, two payloads. ``refund()`` derives the
        # operation id from the payment id, so A and B name the same action.
        operation_id, settled_refund = self.refund("pay_t02", amount=_SETTLED_AMOUNT)
        conflict_operation_id, conflicting_refund = self.refund(
            "pay_t02", amount=_CONFLICTING_AMOUNT
        )
        if conflict_operation_id != operation_id:  # pragma: no cover - guards the premise
            raise RuntimeError(
                "T02 premise broken: the two payloads must name the same business operation"
            )

        identity = OperationIdentity.first_attempt(operation_id)
        emit(
            "identity.minted",
            "one business operation, one idempotency key, two different payloads",
            operation_id=operation_id,
            idempotency_key=identity.idempotency_key,
            settled_amount=settled_refund.amount,
            conflicting_amount=conflicting_refund.amount,
        )

        # -- 1. the honest call ------------------------------------------
        first = await target.agent.submit(identity, settled_refund)
        executions_after_first = target.ledger.execution_count(operation_id)
        emit(
            "attempt.settled",
            f"refund A (amount {settled_refund.amount}) -> {first.status}",
            status=first.status,
            client_visible_state=first.client_visible_state,
            http_status=first.http_status,
            reason=first.reason,
            receipt_outcome=(first.receipt or {}).get("outcome"),
            downstream_executions=executions_after_first,
        )
        if first.status not in ("succeeded", "success"):
            emit(
                "attempt.settled.unexpected",
                "refund A did not settle; the reuse probe below is not interpretable",
                status=first.status,
                reason=first.reason,
            )

        before = await self._gateway_state(target)
        dispatches_before = target.injector.dispatch_count(operation_id=operation_id)

        # -- 2. the same key, a different payload -------------------------
        second = await target.agent.submit(identity.retry(), conflicting_refund)
        after = await self._gateway_state(target)
        dispatches_after = target.injector.dispatch_count(operation_id=operation_id)
        dispatch_delta = dispatches_after - dispatches_before
        deltas = _deltas(before, after)
        executions = target.ledger.execution_count(operation_id)
        conflict_reason = second.reason
        expected_reason = _EXPECTED_CONFLICT_REASON.get(configuration)
        refused = second.status in REFUSED_STATUSES

        emit(
            "attempt.conflicting",
            f"refund B (amount {conflicting_refund.amount}) under the spent key -> {second.status}",
            status=second.status,
            client_visible_state=second.client_visible_state,
            http_status=second.http_status,
            conflict_reason=conflict_reason,
            expected_conflict_reason=expected_reason,
            refused=refused,
            downstream_executions=executions,
            dispatch_delta=dispatch_delta,
            gateway_deltas=deltas,
        )

        amounts = [effect.amount for effect in target.ledger.effects(operation_id)]
        emit(
            "ledger.read",
            f"effect ledger holds {executions} execution(s) for {operation_id}",
            operation_id=operation_id,
            downstream_executions=executions,
            amounts=amounts,
            source="independent effect ledger",
        )

        # Measured BEFORE the control runs, so the gateway-reported debit and
        # receipt columns describe the reuse probe alone.
        measurements = await self.measure(
            target, [first, second], operation_ids=[operation_id]
        )

        # -- 5. the fresh-key control ------------------------------------
        control_operation_id, control_refund = self.refund(
            "pay_t02_control", amount=_CONFLICTING_AMOUNT
        )
        control_identity = OperationIdentity.first_attempt(control_operation_id)
        control = await target.agent.submit(control_identity, control_refund)
        control_executions = target.ledger.execution_count(control_operation_id)
        control_executed = control_executions >= 1
        emit(
            "control.fresh_key",
            (
                f"the same payload under a fresh key -> {control.status} "
                f"({control_executions} execution(s))"
            ),
            operation_id=control_operation_id,
            idempotency_key=control_identity.idempotency_key,
            amount=control_refund.amount,
            status=control.status,
            client_visible_state=control.client_visible_state,
            reason=control.reason,
            executed=control_executed,
        )
        fresh_key_control = {
            "operation_id": control_operation_id,
            "idempotency_key": control_identity.idempotency_key,
            "amount": control_refund.amount,
            "status": control.status,
            "client_visible_state": control.client_visible_state,
            "http_status": control.http_status,
            "reason": control.reason,
            "receipt_outcome": (control.receipt or {}).get("outcome"),
            "downstream_executions": control_executions,
            "executed": control_executed,
            "interpretation": (
                "the same rejected payload executes under a fresh key, so the refusal "
                "above is about the reused key, not a broken tool"
                if control_executed
                else "the payload did not execute even under a fresh key; the refusal "
                "above cannot be attributed to key reuse"
            ),
        }

        extra: dict[str, Any] = {
            "operation_id": operation_id,
            "idempotency_key": identity.idempotency_key,
            "settled_amount": settled_refund.amount,
            "conflicting_amount": conflicting_refund.amount,
            "first_attempt": {
                "status": first.status,
                "client_visible_state": first.client_visible_state,
                "http_status": first.http_status,
                "receipt_outcome": (first.receipt or {}).get("outcome"),
            },
            "conflict_reason": conflict_reason,
            "expected_conflict_reason": expected_reason,
            "conflict_reason_matches": (
                None if expected_reason is None else conflict_reason == expected_reason
            ),
            "conflicting_attempt": {
                "status": second.status,
                "client_visible_state": second.client_visible_state,
                "http_status": second.http_status,
                "refused": refused,
                "receipt_outcome": (second.receipt or {}).get("outcome"),
            },
            "downstream_executions_for_operation": executions,
            "executed_amounts": amounts,
            "dispatches_before_conflict": dispatches_before,
            "dispatches_after_conflict": dispatches_after,
            "additional_dispatch": dispatch_delta,
            "gateway_state_before_conflict": before,
            "gateway_state_after_conflict": after,
            "gateway_deltas_across_conflict": deltas,
            "fresh_key_control": fresh_key_control,
        }

        if configuration is Configuration.DIRECT_NAIVE:
            observation = (
                f"No idempotency anywhere: the spent key was ignored and the changed "
                f"payload executed as a second business effect. Downstream executions "
                f"for {operation_id}: {executions} (amounts {amounts}). The second "
                f"attempt returned {second.status}."
            )
            return self.result(
                target,
                verdict=Verdict.OBSERVED,
                observation=observation,
                measurements=measurements,
                attempts=[first, second],
                remaining_risks=[
                    "The naive downstream has no guarantee to hold here; the numbers "
                    "are the finding. A reused key is a free second refund of any amount.",
                ],
                extra=extra,
            )

        problems: list[str] = []
        if not refused:
            problems.append(
                f"the conflicting request was not refused (status {second.status})"
            )
        if executions != 1:
            problems.append(
                f"downstream executions for {operation_id} = {executions}, expected 1"
            )
        if target.uses_gateway:
            if dispatch_delta != 0:
                problems.append(
                    f"the refused request produced {dispatch_delta} additional dispatch(es) "
                    "across the fault layer"
                )
            if deltas.get("debits"):
                problems.append(
                    f"the refused request produced {deltas['debits']} additional debit(s)"
                )
            if deltas.get("net_debits"):
                problems.append(
                    f"net debits moved by {deltas['net_debits']} across the refused request"
                )

        gateway_clause = ""
        if target.uses_gateway:
            gateway_clause = (
                f" Gateway-reported: +{deltas.get('debits', 0)} debit(s), "
                f"+{deltas.get('receipts', 0)} receipt(s) across the refused request; "
                f"{dispatch_delta} additional dispatch(es) observed at the fault layer."
            )

        if problems:
            observation = (
                f"The documented refusal did not hold: {'; '.join(problems)}. "
                f"Refund A settled, then refund B under the same key "
                f"(amount {conflicting_refund.amount}) returned {second.status}"
                f"{f' ({conflict_reason})' if conflict_reason else ''}. "
                f"Executed amounts for {operation_id}: {amounts}.{gateway_clause}"
            )
            return self.result(
                target,
                verdict=Verdict.FAIL,
                observation=observation,
                measurements=measurements,
                attempts=[first, second],
                remaining_risks=[
                    "A second business effect under a spent key is a duplicate payout "
                    "the caller never authorised.",
                ],
                extra=extra,
            )

        if not control_executed:
            observation = (
                f"The conflicting request was refused ({second.status}"
                f"{f': {conflict_reason}' if conflict_reason else ''}) and downstream "
                f"executions for {operation_id} stayed at {executions} -- but the "
                f"fresh-key control ({control.status}) did not execute either, so the "
                "refusal cannot be attributed to key reuse rather than to a tool that "
                f"refuses this payload outright.{gateway_clause}"
            )
            return self.result(
                target,
                verdict=Verdict.OBSERVED,
                observation=observation,
                measurements=measurements,
                attempts=[first, second],
                remaining_risks=[
                    "The control did not establish that the payload is otherwise "
                    "acceptable; this configuration's refusal is uninterpreted.",
                ],
                extra=extra,
            )

        reason_note = ""
        if expected_reason is not None and conflict_reason != expected_reason:
            reason_note = (
                f" Refusal reason was {conflict_reason!r}, not the documented "
                f"{expected_reason!r}."
            )
        observation = (
            f"Refund A (amount {settled_refund.amount}) settled; refund B "
            f"(amount {conflicting_refund.amount}) under the same key was refused "
            f"({second.status}"
            f"{f': {conflict_reason}' if conflict_reason else ''}) and left the "
            f"downstream at {executions} execution for {operation_id} "
            f"(amounts {amounts}).{gateway_clause} The same payload under a fresh "
            f"key executed normally ({control.status}), so the refusal is about the "
            f"reused key, not the payload.{reason_note}"
        )
        risks = [
            "Only the amount field was changed; payload equality is a canonical hash, "
            "so other fields are argued to behave the same way but are not measured here.",
        ]
        if reason_note:
            risks.append(
                "The refusal reason differs from the documented code, so callers "
                "matching on the reason string would not recognise this refusal."
            )
        return self.result(
            target,
            verdict=Verdict.PASS,
            observation=observation,
            measurements=measurements,
            attempts=[first, second],
            remaining_risks=risks,
            extra=extra,
        )

    # -- helpers ---------------------------------------------------------

    async def _gateway_state(self, target: Target) -> dict[str, Any] | None:
        """Gateway-reported wallet state, or ``None`` for a direct integration."""
        if not target.uses_gateway:
            return None
        gateway, tenant, _ = target.require_gateway()
        snapshot = await gateway.snapshot(tenant)
        return {
            "source": "gateway-reported",
            "sent_attempts": snapshot.sent_attempt_count,
            "debits": snapshot.debit_count,
            "refunds": snapshot.refund_count,
            "net_debits": snapshot.net_debit_count,
            "receipts": snapshot.receipt_count,
            "receipt_outcomes": snapshot.receipt_outcomes(),
            "idempotency_records": len(snapshot.idempotency_records),
            "wallet_balance": snapshot.wallet_balance,
        }


def _deltas(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> dict[str, int]:
    """Integer movement in the gateway-reported columns across one request."""
    if before is None or after is None:
        return {}
    return {
        name: int(after[name]) - int(before[name])
        for name in ("sent_attempts", "debits", "refunds", "net_debits", "receipts",
                     "idempotency_records")
    }
