"""Test 13 -- Retention expiration."""

from __future__ import annotations

from failure_lab.configurations import GATEWAY_CONFIGURATIONS, Configuration, Target
from failure_lab.scenarios.base import ConfigurationResult, EventLog, Scenario, Verdict


class RetentionExpiration(Scenario):
    """What is left of the replay guarantee once the record ages out?

    WHAT TO IMPLEMENT
    -----------------
    The question the report must answer is: after the idempotency retention
    period, what guarantee remains? Answer it by measurement.

    ``aged_record``  Run one clean call. Backdate its idempotency record,
                     receipt and attempt far into the past by updating
                     ``created_at``/``updated_at`` directly through
                     ``app.db.database.get_session_factory``. Run
                     ``gateway.reconcile(idle_seconds=0)``. Retry the same
                     key. Record whether the replay still returns the original
                     receipt and whether any new dispatch occurred.

    ``effect_free_release``  Crash at ``after_idempotency_begin`` so a record
                     exists with no reservation, debit, attempt or receipt.
                     Backdate it, reconcile, then retry the same key. This is
                     the one path that deliberately releases a key, and it is
                     safe precisely because nothing happened. Record that the
                     retry now executes and that total executions for the
                     operation is still 1.

    ``record_removed``  Run one clean call, then DELETE its idempotency record
                     directly -- standing in for a hypothetical retention
                     purge that the product does not currently implement.
                     Retry the same key and record what happens. If the retry
                     dispatches and produces a second downstream effect, that
                     is the honest answer to "what guarantee remains after
                     expiration": none. Report it as such.

    Verdict: ``PASS`` iff the aged record still replays without a new dispatch
    AND the effect-free release produces exactly one downstream execution in
    total. ``FAIL`` if an aged but intact record stops replaying, or if the
    effect-free release lets a *second* effect land.

    The ``record_removed`` case is descriptive and must NOT be folded into the
    verdict -- it measures the consequence of removing the record, which is
    not something the gateway does. Record it in
    ``extra["record_removed"]`` and put the conclusion in
    ``remaining_risks``: the replay guarantee lasts exactly as long as the
    idempotency record does, and no automatic expiry currently shortens that.
    State in ``extra["retention_policy_observed"]`` what the run shows about
    whether any automatic expiry exists.
    """

    test_id = "T13"
    title = "Retention expiration"
    claim = (
        "The replay guarantee persists for as long as the idempotency record "
        "does; the only automatic release is a provably effect-free one."
    )
    tier = "slow"
    configurations = GATEWAY_CONFIGURATIONS
    inapplicable_reason = "a direct integration has no gateway retention window"
    expected = {
        Configuration.DIRECT_NAIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.DIRECT_NATIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.GATEWAY_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NAIVE.value: Verdict.PASS.value,
    }
    limitations = (
        "Time is simulated by backdating rows, not by waiting.",
        "The record-removal case models a retention purge the product does "
        "not implement; it is reported to answer the question, not to "
        "describe current behaviour.",
    )

    async def run_configuration(self, target: Target, log: EventLog) -> ConfigurationResult:
        raise NotImplementedError
