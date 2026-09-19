"""Test 9 -- Forbidden parameter."""

from __future__ import annotations

from failure_lab.configurations import GATEWAY_CONFIGURATIONS, Configuration, Target
from failure_lab.scenarios.base import ConfigurationResult, EventLog, Scenario, Verdict


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
        raise NotImplementedError
