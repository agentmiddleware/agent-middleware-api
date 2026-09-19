"""Test 8 -- Permit revocation race."""

from __future__ import annotations

from failure_lab.configurations import GATEWAY_CONFIGURATIONS, Configuration, Target
from failure_lab.scenarios.base import ConfigurationResult, EventLog, Scenario, Verdict


class PermitRevocationRace(Scenario):
    """Revoke authority while a call is in flight, at several interleavings.

    The product must define the authoritative point at which authorization is
    evaluated. This scenario's job is to find that point empirically and
    report it -- not to assert a preferred answer.

    WHAT TO IMPLEMENT
    -----------------
    Four interleavings, each with its own permit, payment id and key:

    ``before_request``   revoke, then submit. Control case.
    ``after_prepare``    hold the in-flight call with
                         ``gateway.hold_at("after_prepare")``, revoke while it
                         is paused, release, observe.
    ``after_attach_charge`` same, held after the debit is linked.
    ``after_claim``      same, held after the one-shot dispatch claim.

    Mechanics for a held case::

        with gateway.hold_at(boundary) as hold:
            task = asyncio.create_task(agent.submit(identity, refund))
            await asyncio.wait_for(hold.reached.wait(), timeout=10)
            await gateway.revoke_permit(tenant, permit_id)
            hold.release.set()
            outcome = await task

    Record per interleaving: the attempt status, whether a dispatch crossed
    the fault layer, downstream executions, net debit, receipt outcome, and
    the permit's final status.

    Verdict: ``PASS`` iff every interleaving lands on one of two coherent
    dispositions and never on an incoherent one.
      * Coherent: (a) denied with zero dispatches, zero executions and no net
        charge; or (b) admitted exactly once -- at most one dispatch, at most
        one execution, exactly one receipt, and the charge matching the
        receipt's outcome.
      * Incoherent, and therefore ``FAIL``: more than one dispatch or
        execution for one key, a charge with no receipt, a receipt with no
        corresponding accounting, or a revoked permit admitting a *second*
        distinct operation after revocation completed.
    Then, in the observation, name the boundary at which revocation stopped
    being effective, and record it in ``extra["authoritative_point"]``.
    Also submit a fresh operation under the revoked permit afterwards and
    confirm it is denied -- revocation must be effective for anything not
    already in flight. Record as ``extra["post_revocation_control"]``.
    """

    test_id = "T08"
    title = "Permit revocation race"
    claim = (
        "Authorization is evaluated at one well-defined point; a revocation "
        "arriving after it cannot produce a second dispatch, an unreceipted "
        "charge, or a newly admitted operation."
    )
    tier = "slow"
    configurations = GATEWAY_CONFIGURATIONS
    inapplicable_reason = "a direct integration has no permit to revoke"
    expected = {
        Configuration.DIRECT_NAIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.DIRECT_NATIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.GATEWAY_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NAIVE.value: Verdict.PASS.value,
    }
    limitations = (
        "A call already past the authorization point completes under the "
        "authority it had when it was admitted. This test records where that "
        "point is; it does not argue that the location is correct.",
        "Interleavings are forced at instrumented boundaries, so they are "
        "deterministic rather than a natural race.",
    )

    async def run_configuration(self, target: Target, log: EventLog) -> ConfigurationResult:
        raise NotImplementedError
