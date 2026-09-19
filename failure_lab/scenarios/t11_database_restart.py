"""Test 11 -- Database restart."""

from __future__ import annotations

from failure_lab.configurations import GATEWAY_CONFIGURATIONS, Configuration, Target
from failure_lab.scenarios.base import ConfigurationResult, EventLog, Scenario, Verdict


class DatabaseRestart(Scenario):
    """Take the gateway's persistence away mid-operation and measure the damage.

    WHAT TO IMPLEMENT
    -----------------
    ``gateway.database_outage()`` is an async context manager that disposes
    the pool and refuses every new connection for its duration.

    Three sub-cases, each with its own payment id and key:

    ``outage_before_request``  submit entirely inside the outage. Expect a
                               failure with no downstream effect at all.
    ``outage_after_prepare``   hold with ``gateway.hold_at("after_prepare")``,
                               enter the outage while paused, release inside
                               it, exit the outage, then reconcile and retry.
    ``outage_after_claim``     the same, held after the dispatch claim, so the
                               terminal write is what the outage breaks.

    After each sub-case, exit the outage, run ``gateway.backdate_attempts``
    and ``gateway.reconcile(idle_seconds=0)``, then retry the same key.

    Measure and report exactly the PRD's list: lost accepted operations
    (records admitted but left with no terminal state after recovery),
    duplicate dispatches (fault-layer crossings > 1 for one key), inconsistent
    debits (a debit with no receipt and no refund after recovery), corrupted
    state (an attempt row in no valid state), and recovery behavior.

    Verdict: ``PASS`` iff across all sub-cases there is no duplicate dispatch,
    no duplicate downstream execution, no charge left without either a receipt
    or a refund after reconciliation, and every admitted key ends either
    terminal or safely retryable. ``FAIL`` otherwise. An operation that simply
    failed during the outage with nothing dispatched is a correct outcome, not
    a loss -- classify it as ``failed_closed`` rather than ``lost``.

    Record per sub-case rows in ``extra["cases"]`` and the outage's
    ``refused_connections`` count.
    """

    test_id = "T11"
    title = "Database restart"
    claim = (
        "A persistence outage during an operation never produces a duplicate "
        "dispatch, a duplicate downstream effect, or a charge with neither a "
        "receipt nor a refund."
    )
    tier = "slow"
    configurations = GATEWAY_CONFIGURATIONS
    inapplicable_reason = "a direct integration has no gateway database in the path"
    expected = {
        Configuration.DIRECT_NAIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.DIRECT_NATIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.GATEWAY_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NAIVE.value: Verdict.PASS.value,
    }
    limitations = (
        "The outage is simulated by refusing new connections at the engine, "
        "not by restarting a database server. It reproduces 'the database is "
        "unreachable', not crash recovery of the storage engine itself.",
        "Runs against SQLite. Production runs PostgreSQL, where failover and "
        "replication behaviour differ and are not covered here.",
    )

    async def run_configuration(self, target: Target, log: EventLog) -> ConfigurationResult:
        raise NotImplementedError
