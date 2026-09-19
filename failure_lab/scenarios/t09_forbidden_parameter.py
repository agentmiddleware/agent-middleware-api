"""Test 9 -- Forbidden parameter."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from failure_lab.configurations import (
    GATEWAY_CONFIGURATIONS,
    AttemptOutcome,
    Configuration,
    Target,
)
from failure_lab.gateway import GATEWAY_TOOL_ID, GatewaySnapshot
from failure_lab.identity import OperationIdentity
from failure_lab.scenarios.base import (
    REFUSED_STATUSES,
    ConfigurationResult,
    EventLog,
    Scenario,
    Verdict,
)

#: The probes whose refusal the permit is responsible for. The verdict is
#: computed over exactly these, in this order.
PERMIT_PROBES: tuple[str, ...] = (
    "amount_above_cap",
    "aggregate_value_cap",
    "forbidden_recipient",
    "forbidden_field",
    "forbidden_field_nested",
    "changed_destination",
    "max_calls_per_tool",
)

#: Probes that are argument-*shape* questions, not permit questions. They are
#: measured and reported, never folded into the verdict -- except that a
#: business effect from one of them is a failure like any other.
SCHEMA_PROBES: tuple[str, ...] = (
    "omitted_value_field",
    "alternate_representation",
)

#: The refusal reason each permit-scoped probe is documented to produce.
#: Recorded next to what was observed so a divergence is visible in the
#: result document; it is reported, never asserted away.
DOCUMENTED_REASON: dict[str, str] = {
    "amount_above_cap": "permit_budget_exceeded",
    "aggregate_value_cap": "permit_aggregate_value_cap_exceeded",
    "forbidden_recipient": "permit_recipient_domain_mismatch",
    "forbidden_field": "permit_forbidden_field:customer_id",
    "forbidden_field_nested": "permit_forbidden_field:customer_id",
    "changed_destination": "permit_tool_not_allowed",
    "max_calls_per_tool": "permit_max_calls_exceeded",
}

#: What each probe is trying to smuggle past the permit, in one line.
PROBE_INTENT: dict[str, str] = {
    "amount_above_cap": "a call that costs more credits than the permit allows",
    "aggregate_value_cap": "a second call after the permit's cumulative value cap is used up",
    "forbidden_recipient": "a call to a tool whose origin is not the permit's bound domain",
    "forbidden_field": "a forbidden argument carried at the top level",
    "forbidden_field_nested": "the same forbidden key nested inside a sub-object",
    "changed_destination": "a tool the permit does not list",
    "max_calls_per_tool": "a second call against a single-use permit",
    "omitted_value_field": "arguments with the value field missing entirely",
    "alternate_representation": "the value field sent as a string instead of an integer",
}

#: A domain the governed tool's origin (``localhost``) is not.
FOREIGN_DOMAIN = "payments.not-the-governed-tool.invalid"

#: A tool id the gateway does not serve, used as the permit's sole allowed
#: tool so that invoking the real one is an out-of-permit destination.
UNPERMITTED_TOOL = "lab.unpermitted.tool"

#: Client patience. Nothing here is expected to be slow; this only keeps the
#: harness from being the thing that times out.
SUBMIT_TIMEOUT_SECONDS = 30.0

#: Refund amount, in minor units, used by every probe.
PROBE_AMOUNT = 5000


def _added(
    before: list[dict[str, Any]], after: list[dict[str, Any]], key: str
) -> list[dict[str, Any]]:
    """Rows in ``after`` that were not in ``before``, matched on ``key``."""
    seen = {row[key] for row in before}
    return [row for row in after if row[key] not in seen]


def _credits(rows: list[dict[str, Any]]) -> Decimal:
    """Signed credit total of a set of ledger rows (debits are negative)."""
    total = Decimal("0")
    for row in rows:
        amount = row.get("amount")
        if amount is not None:
            total += Decimal(str(amount))
    return total


def _drop_customer_id(arguments: dict[str, Any]) -> dict[str, Any]:
    """Move ``customer_id`` out of the top level and into a sub-object."""
    nested = dict(arguments)
    customer_id = nested.pop("customer_id", None)
    nested["metadata"] = {"customer_id": customer_id}
    return nested


def _omit_amount(arguments: dict[str, Any]) -> dict[str, Any]:
    stripped = dict(arguments)
    stripped.pop("amount", None)
    return stripped


def _amount_as_string(arguments: dict[str, Any]) -> dict[str, Any]:
    restated = dict(arguments)
    restated["amount"] = str(restated["amount"])
    return restated


class ForbiddenParameter(Scenario):
    """Probe the edges of the permit. Enforcement must happen before dispatch.

    WHAT TO IMPLEMENT
    -----------------
    A probe matrix. Each probe gets its own permit where the constraint needs
    one, its own payment id and its own key, and each records whether the
    refusal happened BEFORE the fault layer saw anything.

    Probes (``extra["probes"]`` holds one row each):

    ``amount_above_cap``       permit ``max_credits`` below one call's cost.
                               Expect ``permit_budget_exceeded``.
    ``aggregate_value_cap``    permit with ``aggregate_value_cap`` already
                               consumed by a first call, second call refused.
    ``forbidden_recipient``    permit with ``recipient_domain`` set to a
                               domain that is not the tool's origin. Expect
                               ``permit_recipient_domain_mismatch``.
    ``forbidden_field``        permit with ``forbidden_fields=("customer_id",)``
                               and a call that carries it.
    ``forbidden_field_nested`` same permit, the forbidden key nested inside a
                               sub-object of the arguments.
    ``changed_destination``    invoke a tool the permit does not allow. Expect
                               ``permit_tool_not_allowed``.
    ``max_calls_per_tool``     permit with ``max_calls_per_tool={tool: 1}``,
                               second call refused.
    ``omitted_value_field``    arguments with ``amount`` missing.
    ``alternate_representation`` ``amount`` sent as the string ``"5000"``
                               instead of the integer ``5000``.

    For every probe record: ``reason``, ``dispatches`` (fault-layer crossings
    for that operation), ``executions`` (effect ledger), ``net_debit``, and
    ``refused_before_dispatch = dispatches == 0``.

    Verdict: ``PASS`` iff every *permit-scoped* probe -- the first seven --
    is refused with ``refused_before_dispatch`` true, zero executions and no
    net charge. ``FAIL`` if any of them dispatches or executes.

    The last two probes are schema-shaped rather than permit-scoped. Do not
    fold them into the verdict. Record what actually happens: if a
    schema-invalid argument is forwarded to the downstream and refused there,
    say so, put it in ``extra["schema_probes"]``, and add the finding to
    ``remaining_risks`` -- a caller reading "enforcement happens before
    dispatch" should learn that argument *shape* is not part of that
    enforcement, if that is what the run shows. What matters for safety is
    that no business effect lands; assert ``executions == 0`` for these two as
    well, and ``FAIL`` if a malformed probe produces a refund.
    """

    test_id = "T09"
    title = "Forbidden parameter"
    claim = (
        "Operations outside the permit are refused before the gateway "
        "dispatches anything, and none of them produces a downstream effect."
    )
    tier = "slow"
    configurations = GATEWAY_CONFIGURATIONS
    inapplicable_reason = "a direct integration has no permit to exceed"
    expected = {
        Configuration.DIRECT_NAIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.DIRECT_NATIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.GATEWAY_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NAIVE.value: Verdict.PASS.value,
    }
    limitations = (
        "Covers the permit constraints this product documents. It is not a "
        "general argument-validation audit of the tool interface.",
    )

    async def run_configuration(self, target: Target, log: EventLog) -> ConfigurationResult:
        gateway, tenant, _ = target.require_gateway()
        call_cost = Decimal(gateway.credits_per_call)
        generous = call_cost * 10

        attempts: list[AttemptOutcome] = []
        operation_ids: list[str] = []
        probes: list[dict[str, Any]] = []
        setup_calls: list[dict[str, Any]] = []

        log.emit(
            "t09.start",
            f"{target.configuration.value}: probing the permit's edges; "
            f"one governed call costs {call_cost} credits",
            scenario=self.test_id,
            configuration=target.configuration.value,
            call_cost=str(call_cost),
            permit_probes=list(PERMIT_PROBES),
            schema_probes=list(SCHEMA_PROBES),
        )

        async def probe(
            name: str,
            *,
            permit_id: str,
            permit_description: str,
            mutate: Any = None,
            setup: dict[str, Any] | None = None,
        ) -> None:
            record, outcome = await self._call(
                target,
                log,
                label=name,
                permit_id=permit_id,
                payment_id=f"pay_t09_{name}",
                mutate=mutate,
            )
            record["probe"] = name
            record["probe_kind"] = "permit" if name in PERMIT_PROBES else "schema"
            record["intent"] = PROBE_INTENT[name]
            record["permit_id"] = permit_id
            record["permit"] = permit_description
            record["documented_reason"] = DOCUMENTED_REASON.get(name)
            record["reason_matches_documented"] = (
                None
                if name not in DOCUMENTED_REASON
                else record["reason"] == DOCUMENTED_REASON[name]
            )
            record["setup_call"] = setup
            probes.append(record)
            attempts.append(outcome)
            operation_ids.append(str(record["operation_id"]))
            log.emit(
                "t09.probe",
                f"{name}: status={record['status']} reason={record['reason']} "
                f"dispatches={record['dispatches']} executions={record['executions']}",
                scenario=self.test_id,
                configuration=target.configuration.value,
                probe=name,
                probe_kind=record["probe_kind"],
                status=record["status"],
                reason=record["reason"],
                documented_reason=record["documented_reason"],
                dispatches=record["dispatches"],
                executions=record["executions"],
                net_debit=record["net_debit"],
                net_charge_credits=record["net_charge_credits"],
                refused_before_dispatch=record["refused_before_dispatch"],
                receipt_outcomes=record["receipt_outcomes"],
            )

        async def consume(name: str, *, permit_id: str, what: str) -> dict[str, Any]:
            """Spend the constraint this probe is about, with a separate call."""
            record, outcome = await self._call(
                target,
                log,
                label=f"{name}_setup",
                permit_id=permit_id,
                payment_id=f"pay_t09_{name}_setup",
            )
            record["probe"] = f"{name}_setup"
            record["purpose"] = what
            record["permit_id"] = permit_id
            record["succeeded"] = record["status"] == "success"
            setup_calls.append(record)
            attempts.append(outcome)
            operation_ids.append(str(record["operation_id"]))
            log.emit(
                "t09.setup",
                f"{name}: setup call status={record['status']} "
                f"({what}); executions={record['executions']}",
                scenario=self.test_id,
                configuration=target.configuration.value,
                probe=name,
                status=record["status"],
                reason=record["reason"],
                dispatches=record["dispatches"],
                executions=record["executions"],
                net_charge_credits=record["net_charge_credits"],
            )
            return {
                "status": record["status"],
                "reason": record["reason"],
                "succeeded": record["succeeded"],
                "operation_id": record["operation_id"],
                "executions": record["executions"],
                "net_charge_credits": record["net_charge_credits"],
            }

        # 1 -- the permit's credit cap is below what one call costs.
        cap_permit = await gateway.issue_permit(
            tenant, max_credits=max(call_cost - Decimal("1"), Decimal("1"))
        )
        await probe(
            "amount_above_cap",
            permit_id=str(cap_permit["permit_id"]),
            permit_description=(
                f"max_credits={cap_permit['max_credits']} against a call that "
                f"costs {call_cost}"
            ),
        )

        # 2 -- the cumulative value cap is used up by a first, allowed call.
        aggregate_permit = await gateway.issue_permit(
            tenant, max_credits=generous, aggregate_value_cap=call_cost
        )
        aggregate_setup = await consume(
            "aggregate_value_cap",
            permit_id=str(aggregate_permit["permit_id"]),
            what="one allowed call consumes the whole aggregate_value_cap",
        )
        await probe(
            "aggregate_value_cap",
            permit_id=str(aggregate_permit["permit_id"]),
            permit_description=(
                f"aggregate_value_cap={call_cost}, max_credits={generous}, "
                f"already consumed by one call"
            ),
            setup=aggregate_setup,
        )

        # 3 -- the permit is bound to a domain the tool's origin is not.
        recipient_permit = await gateway.issue_permit(
            tenant, max_credits=generous, recipient_domain=FOREIGN_DOMAIN
        )
        await probe(
            "forbidden_recipient",
            permit_id=str(recipient_permit["permit_id"]),
            permit_description=f"recipient_domain={FOREIGN_DOMAIN!r}",
        )

        # 4, 5 -- one permit forbidding a field, probed flat then nested.
        field_permit = await gateway.issue_permit(
            tenant, max_credits=generous, forbidden_fields=("customer_id",)
        )
        await probe(
            "forbidden_field",
            permit_id=str(field_permit["permit_id"]),
            permit_description="forbidden_fields=['customer_id']",
        )
        await probe(
            "forbidden_field_nested",
            permit_id=str(field_permit["permit_id"]),
            permit_description="forbidden_fields=['customer_id'] (same permit)",
            mutate=_drop_customer_id,
        )

        # 6 -- the permit allows a different tool than the one invoked.
        destination_permit = await gateway.issue_permit(
            tenant, max_credits=generous, tool=UNPERMITTED_TOOL
        )
        await probe(
            "changed_destination",
            permit_id=str(destination_permit["permit_id"]),
            permit_description=(
                f"allowed_tools=[{UNPERMITTED_TOOL!r}] while the call names "
                f"{GATEWAY_TOOL_ID!r}"
            ),
        )

        # 7 -- a single-use permit, used once.
        single_use_permit = await gateway.issue_permit(
            tenant, max_credits=generous, max_calls_per_tool={GATEWAY_TOOL_ID: 1}
        )
        single_use_setup = await consume(
            "max_calls_per_tool",
            permit_id=str(single_use_permit["permit_id"]),
            what="one allowed call consumes the permit's single use",
        )
        await probe(
            "max_calls_per_tool",
            permit_id=str(single_use_permit["permit_id"]),
            permit_description=f"max_calls_per_tool={{{GATEWAY_TOOL_ID!r}: 1}}, already used once",
            setup=single_use_setup,
        )

        # 8, 9 -- argument shape, under a permit that forbids nothing.
        shape_permit = await gateway.issue_permit(tenant, max_credits=generous)
        await probe(
            "omitted_value_field",
            permit_id=str(shape_permit["permit_id"]),
            permit_description="unconstrained permit; the question is the argument shape",
            mutate=_omit_amount,
        )
        await probe(
            "alternate_representation",
            permit_id=str(shape_permit["permit_id"]),
            permit_description="unconstrained permit; the question is the argument shape",
            mutate=_amount_as_string,
        )

        measurements = await self.measure(target, attempts, operation_ids=operation_ids)

        permit_rows = [row for row in probes if row["probe"] in PERMIT_PROBES]
        schema_rows = [row for row in probes if row["probe"] in SCHEMA_PROBES]
        problems: list[str] = []

        for row in permit_rows:
            problems.extend(self._permit_problems(row))
        for row in schema_rows:
            if int(row["executions"]) > 0:
                problems.append(
                    f"{row['probe']}: a malformed argument produced "
                    f"{row['executions']} downstream refund(s) -- a business "
                    f"effect the caller never validly asked for"
                )

        verdict = Verdict.PASS if not problems else Verdict.FAIL

        refused_before_dispatch = sum(
            1 for row in permit_rows if row["refused_before_dispatch"]
        )
        forwarded_schema = [row for row in schema_rows if int(row["dispatches"]) > 0]
        reason_divergences = [
            f"{row['probe']} was refused as {row['reason']!r}, not "
            f"{row['documented_reason']!r}"
            for row in permit_rows
            if row["reason_matches_documented"] is False
        ]

        observation = self._observation(
            permit_rows=permit_rows,
            schema_rows=schema_rows,
            setup_calls=setup_calls,
            refused_before_dispatch=refused_before_dispatch,
            forwarded_schema=forwarded_schema,
            reason_divergences=reason_divergences,
            problems=problems,
        )

        remaining_risks = self._remaining_risks(
            schema_rows=schema_rows,
            forwarded_schema=forwarded_schema,
            setup_calls=setup_calls,
            reason_divergences=reason_divergences,
        )

        log.emit(
            "t09.verdict",
            f"{target.configuration.value} -> {verdict.value}",
            scenario=self.test_id,
            configuration=target.configuration.value,
            permit_probes_refused_before_dispatch=refused_before_dispatch,
            permit_probes_total=len(permit_rows),
            schema_probes_forwarded=[row["probe"] for row in forwarded_schema],
            probe_executions=sum(int(row["executions"]) for row in probes),
            problems=problems,
        )

        return self.result(
            target,
            verdict=verdict,
            observation=observation,
            measurements=measurements,
            attempts=attempts,
            remaining_risks=remaining_risks,
            extra={
                "call_cost_credits": str(call_cost),
                "tool": GATEWAY_TOOL_ID,
                "probes": probes,
                "permit_probes": permit_rows,
                "schema_probes": schema_rows,
                "setup_calls": setup_calls,
                "problems": problems,
                "reason_divergences": reason_divergences,
                "totals": {
                    "permit_probes": len(permit_rows),
                    "permit_probes_refused_before_dispatch": refused_before_dispatch,
                    "permit_probe_dispatches": sum(
                        int(row["dispatches"]) for row in permit_rows
                    ),
                    "permit_probe_executions": sum(
                        int(row["executions"]) for row in permit_rows
                    ),
                    "schema_probe_dispatches": sum(
                        int(row["dispatches"]) for row in schema_rows
                    ),
                    "schema_probe_executions": sum(
                        int(row["executions"]) for row in schema_rows
                    ),
                    "setup_executions": sum(
                        int(row["executions"]) for row in setup_calls
                    ),
                },
            },
        )

    # -- one call ---------------------------------------------------------

    async def _call(
        self,
        target: Target,
        log: EventLog,
        *,
        label: str,
        permit_id: str,
        payment_id: str,
        mutate: Any = None,
    ) -> tuple[dict[str, Any], AttemptOutcome]:
        """Submit one governed call and attribute everything it moved."""
        gateway, tenant, _ = target.require_gateway()
        operation_id, refund = self.refund(payment_id, amount=PROBE_AMOUNT)
        arguments: dict[str, Any] = dict(refund.as_dict())
        if mutate is not None:
            arguments = mutate(arguments)
        identity = OperationIdentity.first_attempt(operation_id)
        agent = target.gateway_agent(permit_id)

        log.emit(
            "t09.submit",
            f"{label}: submitting {operation_id} under permit {permit_id}",
            scenario=self.test_id,
            configuration=target.configuration.value,
            probe=label,
            permit_id=permit_id,
            operation_id=operation_id,
            idempotency_key=identity.idempotency_key,
            argument_keys=sorted(str(key) for key in arguments),
        )

        before = await gateway.snapshot(tenant)
        outcome = await agent.submit(
            identity, arguments, timeout_seconds=SUBMIT_TIMEOUT_SECONDS
        )
        after = await gateway.snapshot(tenant)

        record = self._accounting(
            target,
            before=before,
            after=after,
            operation_id=operation_id,
            outcome=outcome,
        )
        record.update(
            {
                "operation_id": operation_id,
                "payment_id": payment_id,
                "idempotency_key": identity.idempotency_key,
                "arguments_sent": arguments,
            }
        )
        return record, outcome

    # -- accounting -------------------------------------------------------

    def _accounting(
        self,
        target: Target,
        *,
        before: GatewaySnapshot,
        after: GatewaySnapshot,
        operation_id: str,
        outcome: AttemptOutcome,
    ) -> dict[str, Any]:
        """What this one call did, from the fault layer, ledger and gateway."""
        added_debits = _added(before.debits, after.debits, "entry_id")
        added_refunds = _added(before.refunds, after.refunds, "entry_id")
        added_receipts = _added(before.receipts, after.receipts, "receipt_id")
        added_attempts = _added(before.attempts, after.attempts, "attempt_id")
        net_charge = -(_credits(added_debits) + _credits(added_refunds))
        dispatches = target.injector.dispatch_count(operation_id=operation_id)
        return {
            "status": outcome.status,
            "client_visible_state": outcome.client_visible_state,
            "reason": outcome.reason,
            "http_status": outcome.http_status,
            "refused": outcome.status in REFUSED_STATUSES,
            # Independently observed: the fault layer sits outside the gateway.
            "dispatches": dispatches,
            "refused_before_dispatch": dispatches == 0,
            # Ground truth: the effect ledger the gateway cannot reach.
            "executions": target.ledger.execution_count(operation_id=operation_id),
            # Gateway-reported.
            "debit_count": len(added_debits),
            "credit_refund_count": len(added_refunds),
            "net_debit": len(added_debits) - len(added_refunds),
            "net_charge_credits": str(net_charge),
            "receipt_outcomes": [str(r["outcome"]) for r in added_receipts],
            "receipt_reason_codes": [r.get("reason_code") for r in added_receipts],
            "receipt_ids": [str(r["receipt_id"]) for r in added_receipts],
            "gateway_attempt_states": [
                {"state": a["state"], "sent": a["sent"]} for a in added_attempts
            ],
        }

    # -- verdict ----------------------------------------------------------

    @staticmethod
    def _permit_problems(row: dict[str, Any]) -> list[str]:
        """Everything about one permit-scoped probe that breaks the claim."""
        name = row["probe"]
        problems: list[str] = []
        if not row["refused"]:
            problems.append(
                f"{name}: the call was not refused (status {row['status']!r}, "
                f"reason {row['reason']!r})"
            )
        if int(row["dispatches"]) > 0:
            problems.append(
                f"{name}: {row['dispatches']} request(s) crossed the fault "
                f"layer, so the refusal did not happen before dispatch"
            )
        if int(row["executions"]) > 0:
            problems.append(
                f"{name}: {row['executions']} downstream refund(s) executed"
            )
        if int(row["net_debit"]) != 0 or Decimal(row["net_charge_credits"]) != 0:
            problems.append(
                f"{name}: left a net charge of {row['net_charge_credits']} "
                f"credits across {row['net_debit']} net debit(s)"
            )
        return problems

    # -- narration --------------------------------------------------------

    @staticmethod
    def _observation(
        *,
        permit_rows: list[dict[str, Any]],
        schema_rows: list[dict[str, Any]],
        setup_calls: list[dict[str, Any]],
        refused_before_dispatch: int,
        forwarded_schema: list[dict[str, Any]],
        reason_divergences: list[str],
        problems: list[str],
    ) -> str:
        permit_summary = ", ".join(
            f"{row['probe']}={row['reason'] or row['status']}" for row in permit_rows
        )
        parts = [
            (
                f"{refused_before_dispatch}/{len(permit_rows)} permit-scoped "
                f"probes were refused before anything crossed the fault layer, "
                f"with zero downstream executions and no net charge: "
                f"{permit_summary}."
            )
        ]
        if setup_calls:
            executed = sum(int(row["executions"]) for row in setup_calls)
            parts.append(
                f"{len(setup_calls)} deliberate setup calls (one per consumable "
                f"constraint) were allowed and account for all {executed} "
                f"downstream executions in this run."
            )
        if reason_divergences:
            parts.append(
                "Refusal reasons that differ from what the product documents: "
                + "; ".join(reason_divergences)
                + "."
            )
        if forwarded_schema:
            names = ", ".join(row["probe"] for row in forwarded_schema)
            outcomes = ", ".join(
                f"{row['probe']}={row['status']}"
                f"{'/' + str(row['receipt_outcomes'][0]) if row['receipt_outcomes'] else ''}"
                f" after {row['dispatches']} dispatch(es), "
                f"{row['executions']} execution(s), net "
                f"{row['net_charge_credits']} credits"
                for row in forwarded_schema
            )
            parts.append(
                f"Argument shape is NOT part of the pre-dispatch permit check: "
                f"{names} reached the tool and were refused there ({outcomes}). "
                f"No business effect landed, but the call was dispatched."
            )
        else:
            parts.append(
                "Both schema-shaped probes were also stopped before dispatch."
            )
        clean_schema = [row for row in schema_rows if int(row["executions"]) == 0]
        parts.append(
            f"{len(clean_schema)}/{len(schema_rows)} schema-shaped probes "
            f"produced no downstream refund."
        )
        if problems:
            parts.append("FAILURES: " + "; ".join(problems) + ".")
        return " ".join(parts)

    @staticmethod
    def _remaining_risks(
        *,
        schema_rows: list[dict[str, Any]],
        forwarded_schema: list[dict[str, Any]],
        setup_calls: list[dict[str, Any]],
        reason_divergences: list[str],
    ) -> list[str]:
        risks: list[str] = []
        if forwarded_schema:
            names = ", ".join(row["probe"] for row in forwarded_schema)
            risks.append(
                f"The permit governs who may call what, with which credits and "
                f"which forbidden keys -- not whether the argument values are "
                f"well formed. {names} passed every permit check and were "
                f"dispatched to the tool, which refused them. A reader of "
                f"'refused before dispatch' should not extend it to argument "
                f"shape: a malformed call still reaches the tool, still "
                f"occupies an attempt, and still has to be refused downstream."
            )
        charged = [
            row
            for row in schema_rows
            if Decimal(row["net_charge_credits"]) != 0
        ]
        if charged:
            risks.append(
                "A schema-invalid call that reaches the tool can still leave a "
                "net charge: "
                + ", ".join(
                    f"{row['probe']} kept {row['net_charge_credits']} credits"
                    for row in charged
                )
                + ". The money follows the dispatch, not the validity of the "
                "arguments."
            )
        if reason_divergences:
            risks.append(
                "A refusal reason that differs from the documented one is still "
                "a refusal, but it changes what a caller can act on: "
                + "; ".join(reason_divergences)
                + "."
            )
        failed_setup = [row for row in setup_calls if not row["succeeded"]]
        if failed_setup:
            risks.append(
                "A setup call that was meant to consume a constraint did not "
                "succeed ("
                + ", ".join(
                    f"{row['probe']}={row['status']}" for row in failed_setup
                )
                + "), so the probe that follows it may have been refused for a "
                "different reason than the one it was built to test."
            )
        risks.append(
            "Each probe is a single call against a freshly issued permit. This "
            "measures where the boundary is, not how it behaves under "
            "concurrent pressure against the same permit."
        )
        risks.append(
            "The probe set is the constraint vocabulary this product ships. A "
            "constraint the permit cannot express is not tested here and is not "
            "enforced anywhere else either."
        )
        return risks
