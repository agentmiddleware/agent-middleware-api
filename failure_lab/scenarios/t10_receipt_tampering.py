"""Test 10 -- Receipt tampering."""

from __future__ import annotations

from failure_lab.configurations import GATEWAY_CONFIGURATIONS, Configuration, Target
from failure_lab.scenarios.base import ConfigurationResult, EventLog, Scenario, Verdict


class ReceiptTampering(Scenario):
    """Edit a receipt field by field and report exactly what the signature covers.

    WHAT TO IMPLEMENT
    -----------------
    1. Run one clean governed call so a genuine receipt exists. Export it with
       ``gateway.portable_receipt(tenant, receipt_id)`` and fetch
       ``gateway.trust_keys()``.
    2. Verify the genuine bundle with ``failure_lab.verifier.verify`` -- the
       INDEPENDENT verifier, not ``b2a_sdk`` and not ``POST /v1/receipts/verify``.
       Assert all three claims come back with the right statuses: signature
       ESTABLISHED, issuer trust NOT_ESTABLISHED (the key came from the
       audited origin), downstream execution ESTABLISHED only when the effect
       ledger observation is passed in. Exercise the no-observation call too
       and confirm it reports NOT_ESTABLISHED.
    3. Tamper matrix, using ``verifier.tamper(bundle, path, value)``, one
       modification at a time, each independently:
       ``signing_input.credits_charged``, ``signing_input.tool``,
       ``signing_input.outcome``, ``signing_input.created_at``,
       ``signing_input.permit_id``, ``signing_input.kid``,
       ``signing_input.receipt_id``, ``signing_input.wallet_id``,
       ``signing_input.request_hash``, ``signing_input.response_hash``,
       and the envelope-side ``issuer``, ``kid``, ``canonicalization``,
       ``schema_version``, ``keys_url``, ``receipt_id``, ``signature``.
    4. For each, record: the field, whether the signature still verified,
       which of the three claims changed, any envelope disagreement the
       verifier flagged, and whether ``verifier.field_coverage`` classifies
       the field as signed or envelope-only.
    5. Also check the gateway's OWN verification surface for the two most
       important cases (a tampered signed field and a tampered envelope field)
       via ``POST /v1/receipts/verify`` and record whether the two verifiers
       agree. A disagreement is a finding.
    6. Verdict: ``PASS`` iff every modification to a field inside
       ``signing_input`` causes the signature to fail, AND the genuine receipt
       verifies. ``FAIL`` if any signed-field edit still verifies.
    7. The envelope-only fields WILL survive tampering with a valid
       signature. That is a property of the format, not a bug, and it must be
       reported: put the surviving fields in ``extra["outside_signature"]``
       and add a ``remaining_risks`` entry naming them. Also add the standing
       risk that key distribution is first-party, so a compromised origin can
       serve keys that validate forged receipts -- signature validity is not
       issuer trust.
    """

    test_id = "T10"
    title = "Receipt tampering"
    claim = (
        "Every field inside the signed payload is covered by the signature; "
        "the fields that are not covered are named rather than implied."
    )
    tier = "fast"
    configurations = GATEWAY_CONFIGURATIONS
    inapplicable_reason = "a direct integration issues no receipts"
    expected = {
        Configuration.DIRECT_NAIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.DIRECT_NATIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.GATEWAY_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NAIVE.value: Verdict.PASS.value,
    }
    limitations = (
        "A valid signature establishes that the signing key signed the "
        "statement. It does not establish issuer trust while keys are fetched "
        "from the audited origin, and it never establishes that the "
        "downstream business action occurred.",
        "Envelope fields outside signing_input can be edited without breaking "
        "the signature. They are enumerated in the result.",
    )

    async def run_configuration(self, target: Target, log: EventLog) -> ConfigurationResult:
        raise NotImplementedError
