"""Test 7 -- Concurrent budget race."""

from __future__ import annotations

from failure_lab.configurations import GATEWAY_CONFIGURATIONS, Configuration, Target
from failure_lab.scenarios.base import ConfigurationResult, EventLog, Scenario, Verdict


class ConcurrentBudgetRace(Scenario):
    """Two sevens must not fit inside a ten.

    WHAT TO IMPLEMENT
    -----------------
    The gateway charges ``credits_per_call`` (5 by default via
    ``LabEnvironment``) per call. Mint a permit sized so the race is tight:

    Case A (the PRD's example): issue a permit with
    ``max_credits`` = 10 and fire 2 concurrent calls, each of which will cost
    more than half the budget. Use ``gateway.issue_permit(tenant,
    max_credits=...)`` and drive with ``target.gateway_agent(permit_id)``.
    Each call MUST use a different payment id and a different key -- these are
    distinct business operations racing for one budget, not retries.

    Case B (high concurrency): a permit sized for exactly K calls, with
    ``self.options.get("concurrency", 20)`` calls fired at once. At most K may
    be authorized.

    For each case compute ``authorized`` (attempts that were charged) and
    assert ``authorized * credits_per_call <= max_credits``.

    Verdict: ``PASS`` iff for both cases the total credits actually debited
    never exceeds the permit's ``max_credits``, the permit's final
    ``spent_credits`` does not exceed ``max_credits``, downstream_executions
    equals the number of authorized calls, and every refused call is refused
    with ``permit_budget_exceeded`` and produced no downstream effect.
    ``FAIL`` on any over-authorization.

    Record in ``extra["cases"]``: max_credits, credits_per_call, concurrency,
    authorized count, denied count, total debited, permit spent_credits,
    downstream executions.
    """

    test_id = "T07"
    title = "Concurrent budget race"
    claim = (
        "Concurrent budget consumption never exceeds the permit's authorized "
        "limit, however many calls race for it."
    )
    tier = "slow"
    configurations = GATEWAY_CONFIGURATIONS
    inapplicable_reason = "a direct integration has no permit budget to race for"
    expected = {
        Configuration.DIRECT_NAIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.DIRECT_NATIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.GATEWAY_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NAIVE.value: Verdict.PASS.value,
    }
    limitations = (
        "Runs against SQLite, where the reservation is a single guarded "
        "UPDATE rather than a row lock. The PostgreSQL row-lock path is "
        "covered by the repository's own concurrency suite.",
        "In-process asyncio concurrency, not distributed load.",
    )

    async def run_configuration(self, target: Target, log: EventLog) -> ConfigurationResult:
        raise NotImplementedError
