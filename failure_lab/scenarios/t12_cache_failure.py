"""Test 12 -- Redis / cache failure."""

from __future__ import annotations

from failure_lab.configurations import GATEWAY_CONFIGURATIONS, Configuration, Target
from failure_lab.scenarios.base import ConfigurationResult, EventLog, Scenario, Verdict


class CacheFailure(Scenario):
    """If the cache participates in enforcement, kill it and see what degrades.

    WHAT TO IMPLEMENT
    -----------------
    1. Establish whether the cache is in the correctness path at all, by
       measurement rather than by reading the source. Point ``REDIS_URL`` at a
       closed loopback port (``app.core.config.get_settings()`` is cached --
       mutate the settings object and, where the rate limiter holds its own
       module-level ``settings``, patch ``app.core.rate_limiter.settings``
       too; restore both in a ``finally``).
    2. With the cache unreachable, drive the full governed loop: one clean
       call, one replay of the same key, one out-of-scope denial. Assert the
       correctness invariants are untouched -- one downstream execution, one
       debit, one receipt, the replay returning the same receipt id, and the
       denial still denied.
    3. Assert the degradation is SURFACED rather than silent: read
       ``GET /health/dependencies`` (and
       ``app.core.runtime_degradation``) and record whether the run reports a
       memory fallback. Correctness-critical state must not silently degrade
       into unsafe behaviour; a limiter that quietly falls back is acceptable
       only if it says so.
    4. Record in ``extra["participates_in_enforcement"]`` whether any
       correctness invariant changed with the cache down, and in
       ``extra["degradation_surfaced"]`` whether the runtime reported it.
    5. Verdict: ``PASS`` iff no correctness invariant changed AND the
       degradation was surfaced. ``FAIL`` if a correctness invariant changed
       with the cache down, or if the fallback happened silently.
    6. In the observation, state plainly which components use the cache in
       this configuration (rate limiting and optional durable state) and that
       the permit, idempotency, dispatch, debit and receipt path is backed by
       the relational database alone -- as demonstrated by the run, not
       asserted from the source.
    """

    test_id = "T12"
    title = "Cache failure"
    claim = (
        "Correctness does not depend on the cache, and a cache outage "
        "degrades loudly rather than silently."
    )
    tier = "fast"
    configurations = GATEWAY_CONFIGURATIONS
    inapplicable_reason = "a direct integration has no gateway cache in the path"
    expected = {
        Configuration.DIRECT_NAIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.DIRECT_NATIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.GATEWAY_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NAIVE.value: Verdict.PASS.value,
    }
    limitations = (
        "Exercises an unreachable cache in a local-environment posture. The "
        "production-like fail-closed rate-limiter path is a separate "
        "configuration and is not driven here.",
    )

    async def run_configuration(self, target: Target, log: EventLog) -> ConfigurationResult:
        raise NotImplementedError
