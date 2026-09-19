"""Test 6 -- Agent restart with a new idempotency key."""

from __future__ import annotations

from failure_lab.configurations import ALL_CONFIGURATIONS, Configuration, Target
from failure_lab.scenarios.base import ConfigurationResult, EventLog, Scenario, Verdict


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
        raise NotImplementedError
