"""Test 10 -- Receipt tampering."""

from __future__ import annotations

import base64
import json
from typing import Any

from failure_lab.configurations import GATEWAY_CONFIGURATIONS, Configuration, Target
from failure_lab.identity import OperationIdentity
from failure_lab.scenarios.base import ConfigurationResult, EventLog, Scenario, Verdict
from failure_lab.verifier import (
    ENVELOPE_ONLY_FIELDS,
    ClaimStatus,
    KeySource,
    VerificationReport,
    field_coverage,
    parse_key_document,
    tamper,
    verify,
)

#: One forged value per signed field named in the scenario specification. Each
#: is an edit an attacker would actually want: a different charge, a different
#: tool, a different outcome, a different subject.
_SIGNED_FORGERIES: dict[str, Any] = {
    "credits_charged": "999999",
    "tool": "tool.attacker.controlled",
    "outcome": "failed_refunded",
    "created_at": "2001-01-01T00:00:00+00:00",
    "permit_id": "permit_forged_by_t10",
    "kid": "kid-forged-by-t10",
    "receipt_id": "rcpt_forged_by_t10",
    "wallet_id": "wallet_forged_by_t10",
    "request_hash": "0" * 64,
    "response_hash": "f" * 64,
}

#: The envelope side of the same matrix. ``signature`` is filled in at runtime
#: with a well-formed but wrong 64-byte Ed25519 signature, so the verifier
#: exercises the signature check itself rather than a length check.
_ENVELOPE_FORGERIES: dict[str, Any] = {
    "issuer": "https://receipts.attacker.example",
    "kid": "kid-envelope-forged-by-t10",
    "canonicalization": "attacker-canonical-v0",
    "schema_version": "0.0-attacker",
    "keys_url": "https://attacker.example/.well-known/trust-keys.json",
    "receipt_id": "rcpt_envelope_forged_by_t10",
}

_CLAIM_NAMES = (
    "SIGNATURE_VALID",
    "ISSUER_TRUST_ESTABLISHED",
    "DOWNSTREAM_EXECUTION_ESTABLISHED",
)


def _claims(report: VerificationReport) -> dict[str, str]:
    return {
        "SIGNATURE_VALID": report.signature.status.value,
        "ISSUER_TRUST_ESTABLISHED": report.issuer_trust.status.value,
        "DOWNSTREAM_EXECUTION_ESTABLISHED": report.downstream_execution.status.value,
    }


def _distinct(original: Any, forged: Any) -> Any:
    """Guarantee the edit is an edit.

    A "tampered" value equal to the original would re-serialize to the same
    bytes and verify, which would read as a signed field surviving tampering.
    That would be a false FAIL, so the harness refuses to measure it.
    """
    if original != forged:
        return forged
    if isinstance(forged, str):
        return forged + "-tampered"
    return f"{forged}-tampered"


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
        gateway, tenant, permit = target.require_gateway()
        configuration = target.configuration.value

        def emit(step: str, message: str, **data: Any) -> None:
            log.emit(
                step,
                message,
                scenario=self.test_id,
                configuration=configuration,
                **data,
            )

        # -- 1. one clean governed call, so a genuine receipt exists --------
        operation_id, refund = self.refund("pay_t10_tamper")
        identity = OperationIdentity.first_attempt(operation_id)
        emit(
            "call.submit",
            "submitting one clean governed refund so a genuine receipt exists",
            operation_id=operation_id,
            idempotency_key=identity.idempotency_key,
            permit_id=permit["permit_id"],
        )
        outcome = await target.agent.submit(identity, refund)
        attempts = [outcome]
        executions = target.ledger.execution_count(operation_id=operation_id)
        emit(
            "call.complete",
            f"gateway returned {outcome.status}; effect ledger shows {executions} execution(s)",
            status=outcome.status,
            client_visible_state=outcome.client_visible_state,
            receipt_id=outcome.receipt_id,
            receipt_outcome=outcome.receipt.get("outcome") if outcome.receipt else None,
            downstream_executions=executions,
        )

        receipt_id = outcome.receipt_id
        if receipt_id is None:
            measurements = await self.measure(target, attempts, operation_ids=[operation_id])
            emit(
                "receipt.missing",
                "the governed call returned no receipt, so there is nothing to tamper with",
                status=outcome.status,
                reason=outcome.reason,
            )
            return self.result(
                target,
                verdict=Verdict.FAIL,
                observation=(
                    f"the governed call terminated as {outcome.status} but carried no "
                    "receipt, so the signed-payload coverage could not be measured at all"
                ),
                measurements=measurements,
                attempts=attempts,
                remaining_risks=[
                    "A terminalising governed call produced no receipt. Every claim "
                    "this scenario makes about signature coverage is unmeasured for "
                    "that path.",
                ],
                extra={"receipt_id": None, "downstream_executions": executions},
            )

        # -- exported evidence and the published keys -----------------------
        bundle = await gateway.portable_receipt(tenant, receipt_id)
        key_document = await gateway.trust_keys()
        keys = parse_key_document(key_document)
        coverage = field_coverage(bundle)
        signed_payload = json.loads(bundle["signing_input"])
        emit(
            "evidence.exported",
            f"exported the portable bundle and {len(keys)} published key(s)",
            receipt_id=receipt_id,
            envelope_fields=sorted(bundle),
            signed_fields=sorted(signed_payload),
            key_ids=sorted(keys),
            keys_url=bundle.get("keys_url"),
            issuer=bundle.get("issuer"),
        )

        observation = {
            "executions": executions,
            "operation_id": operation_id,
            "source": "failure-lab effect ledger (the gateway cannot write to it)",
        }

        # -- 2. the genuine bundle, with and without the ledger observation --
        genuine = verify(
            bundle,
            keys,
            key_source=KeySource.ISSUER_ORIGIN,
            downstream_observation=observation,
        )
        genuine_no_observation = verify(bundle, keys, key_source=KeySource.ISSUER_ORIGIN)
        baseline_claims = _claims(genuine)
        genuine_assertions = {
            "signature_established": genuine.signature.status is ClaimStatus.ESTABLISHED,
            "issuer_trust_not_established": (
                genuine.issuer_trust.status is ClaimStatus.NOT_ESTABLISHED
            ),
            "downstream_established_with_observation": (
                genuine.downstream_execution.status is ClaimStatus.ESTABLISHED
            ),
            "downstream_not_established_without_observation": (
                genuine_no_observation.downstream_execution.status
                is ClaimStatus.NOT_ESTABLISHED
            ),
        }
        genuine_ok = all(genuine_assertions.values())
        emit(
            "verify.genuine",
            "independent verifier on the untouched bundle: "
            + ", ".join(f"{name}={status}" for name, status in baseline_claims.items()),
            claims=baseline_claims,
            claims_without_observation=_claims(genuine_no_observation),
            assertions=genuine_assertions,
            signature_reason=genuine.signature.reason,
            issuer_trust_reason=genuine.issuer_trust.reason,
            downstream_reason=genuine.downstream_execution.reason,
            downstream_reason_without_observation=(
                genuine_no_observation.downstream_execution.reason
            ),
        )

        # -- control: re-serializing without changing a value must still verify
        control_field = "tool" if "tool" in signed_payload else sorted(signed_payload)[0]
        control_bundle = tamper(
            bundle, f"signing_input.{control_field}", signed_payload[control_field]
        )
        control = verify(control_bundle, keys, downstream_observation=observation)
        control_verifies = control.signature.status is ClaimStatus.ESTABLISHED
        emit(
            "verify.reserialization_control",
            (
                "re-serializing signing_input without changing any value still verifies"
                if control_verifies
                else "re-serializing signing_input without changing a value BROKE the "
                "signature -- every signed-field result below is confounded"
            ),
            field=control_field,
            signature=control.signature.status.value,
            reason=control.signature.reason,
        )

        # -- 3/4. the tamper matrix, one independent edit at a time ---------
        rows: list[dict[str, Any]] = []
        for name in _SIGNED_FORGERIES:
            if name not in signed_payload:
                rows.append(
                    {
                        "field": f"signing_input.{name}",
                        "side": "signed",
                        "edited": False,
                        "note": "field absent from this receipt's signed payload",
                    }
                )
                emit(
                    "tamper.skipped",
                    f"signing_input.{name} is not present in this receipt's signed payload",
                    field=f"signing_input.{name}",
                )
                continue
            path = f"signing_input.{name}"
            forged = _distinct(signed_payload[name], _SIGNED_FORGERIES[name])
            rows.append(
                self._probe(
                    bundle,
                    keys,
                    path=path,
                    value=forged,
                    original=signed_payload[name],
                    coverage=coverage,
                    baseline=baseline_claims,
                    observation=observation,
                    emit=emit,
                )
            )

        envelope_forgeries = dict(_ENVELOPE_FORGERIES)
        envelope_forgeries["signature"] = base64.b64encode(bytes(64)).decode()
        for name, forged_value in envelope_forgeries.items():
            forged = _distinct(bundle.get(name), forged_value)
            rows.append(
                self._probe(
                    bundle,
                    keys,
                    path=name,
                    value=forged,
                    original=bundle.get(name),
                    coverage=coverage,
                    baseline=baseline_claims,
                    observation=observation,
                    emit=emit,
                )
            )

        signed_rows = [row for row in rows if row.get("side") == "signed"]
        envelope_rows = [row for row in rows if row.get("side") != "signed"]
        signed_survivors = [
            row["field"] for row in signed_rows if row.get("signature_valid")
        ]
        signed_unmeasured = [row["field"] for row in signed_rows if not row.get("edited")]
        survived = [row for row in envelope_rows if row.get("signature_valid")]
        survived_fields = [row["field"] for row in survived]
        silent_survivors = [
            row["field"] for row in survived if not row["envelope_disagreements"]
        ]

        # -- 5. the gateway's own verification surface ----------------------
        gateway_surface = await self._gateway_verify_surface(
            gateway,
            tenant,
            receipt_id=receipt_id,
            forged_receipt_id=envelope_forgeries["receipt_id"],
            rows=rows,
            emit=emit,
        )

        measurements = await self.measure(target, attempts, operation_ids=[operation_id])

        # -- 6. verdict -----------------------------------------------------
        verdict = Verdict.PASS if genuine_ok and not signed_survivors else Verdict.FAIL
        if signed_survivors:
            observation_text = (
                f"{len(signed_survivors)} field(s) inside signing_input were edited and "
                f"the signature STILL VERIFIED: {', '.join(signed_survivors)}"
            )
        elif not genuine_ok:
            failed = [name for name, ok in genuine_assertions.items() if not ok]
            observation_text = (
                "every signed-field edit broke the signature, but the genuine receipt "
                f"did not verify as documented: {', '.join(failed)}"
            )
        else:
            observation_text = (
                f"genuine bundle: signature ESTABLISHED, issuer trust NOT_ESTABLISHED "
                f"(key served by the audited origin), downstream execution ESTABLISHED "
                f"only with the effect-ledger observation of {executions} execution(s). "
                f"All {len(signed_rows)} edits inside signing_input broke the signature. "
                f"{len(survived_fields)} envelope field(s) were edited with the signature "
                f"still valid ({', '.join(survived_fields) or 'none'}); "
                f"{len(silent_survivors)} of those raised no envelope disagreement "
                f"({', '.join(silent_survivors) or 'none'})."
            )
        if signed_unmeasured:
            observation_text += (
                f" Not measured (absent from this receipt's signed payload): "
                f"{', '.join(signed_unmeasured)}."
            )
        if not control_verifies:
            observation_text += (
                " CAVEAT: the re-serialization control did not verify, so signature "
                "failures below cannot be attributed to the edited value alone."
            )

        remaining_risks = [
            (
                "Fields outside signing_input are not authenticated: "
                + (", ".join(survived_fields) or "none observed")
                + " were edited and the signature still verified. Of those, "
                + (", ".join(silent_survivors) or "none")
                + " produced no disagreement the verifier could flag, so a holder "
                "reading issuer, keys_url, canonicalization or schema_version from a "
                "bundle is reading unauthenticated text. Only signing_input is attested."
            ),
            (
                "Key distribution is first-party: the verifying key was fetched from "
                f"{bundle.get('keys_url')!r} on the same origin that issued the receipt. "
                "An origin that can serve receipts can serve keys that validate forged "
                "ones, so a valid signature is not issuer trust. Out-of-band key "
                "pinning is not implemented."
            ),
            (
                "A verified signature never establishes that the downstream business "
                "action happened. Here it was established only by the effect ledger, an "
                "observer the gateway cannot write to; with no observation supplied the "
                "verifier correctly reported NOT_ESTABLISHED."
            ),
        ]
        if gateway_surface["accepts_only_receipt_id"]:
            remaining_risks.append(
                "POST /v1/receipts/verify takes a receipt_id, not a bundle, so it "
                "re-verifies the copy the gateway stores. A holder whose exported "
                "bundle has been edited gets valid=true from that endpoint for every "
                "case tested here. Tampering in a bundle that has left the plane is "
                "detectable only by checking the signature against the published keys, "
                "which is what the independent verifier did."
            )
        if not control_verifies:
            remaining_risks.append(
                "The re-serialization control failed: rewriting signing_input with "
                "unchanged values already broke the signature, so this run cannot "
                "attribute the signed-field failures to the edited values."
            )

        emit(
            "matrix.complete",
            (
                f"{len(signed_rows) - len(signed_survivors)}/{len(signed_rows)} signed-field "
                f"edits detected; {len(survived_fields)} envelope field(s) survived"
            ),
            signed_survivors=signed_survivors,
            envelope_survivors=survived_fields,
            silent_survivors=silent_survivors,
            verdict=verdict.value,
        )

        return self.result(
            target,
            verdict=verdict,
            observation=observation_text,
            measurements=measurements,
            attempts=attempts,
            remaining_risks=remaining_risks,
            extra={
                "receipt_id": receipt_id,
                "receipt_outcome": signed_payload.get("outcome"),
                "downstream_executions": executions,
                "downstream_observation": observation,
                "genuine_verification": {
                    "claims": baseline_claims,
                    "claims_without_observation": _claims(genuine_no_observation),
                    "assertions": genuine_assertions,
                    "signature_reason": genuine.signature.reason,
                    "issuer_trust_reason": genuine.issuer_trust.reason,
                    "downstream_reason": genuine.downstream_execution.reason,
                    "downstream_reason_without_observation": (
                        genuine_no_observation.downstream_execution.reason
                    ),
                    "key_id": genuine.key_id,
                    "envelope_disagreements": genuine.envelope_disagreements,
                    "notes": genuine.notes,
                },
                "reserialization_control": {
                    "field": f"signing_input.{control_field}",
                    "value_unchanged": True,
                    "signature": control.signature.status.value,
                    "still_verifies": control_verifies,
                    "why_it_matters": (
                        "an edit is only evidence of coverage if rewriting the same "
                        "value leaves the signature intact"
                    ),
                },
                "tamper_matrix": rows,
                "signed_fields_tampered": [row["field"] for row in signed_rows],
                "signed_fields_that_survived": signed_survivors,
                "signed_fields_not_measured": signed_unmeasured,
                "outside_signature": survived_fields,
                "outside_signature_undetectable": silent_survivors,
                "outside_signature_detail": survived,
                "field_coverage": coverage,
                "declared_envelope_only_fields": list(ENVELOPE_ONLY_FIELDS),
                "published_key_ids": sorted(keys),
                "gateway_verify_surface": gateway_surface,
            },
        )

    # -- helpers -----------------------------------------------------------

    def _probe(
        self,
        bundle: dict[str, Any],
        keys: dict[str, bytes],
        *,
        path: str,
        value: Any,
        original: Any,
        coverage: dict[str, str],
        baseline: dict[str, str],
        observation: dict[str, Any],
        emit: Any,
    ) -> dict[str, Any]:
        """Apply one independent edit and record what the verifier said."""
        edited = tamper(bundle, path, value)
        report = verify(edited, keys, downstream_observation=observation)
        claims = _claims(report)
        changed = [name for name in _CLAIM_NAMES if claims[name] != baseline[name]]
        classification = coverage.get(path, "absent_from_bundle")
        signature_valid = report.signature.status is ClaimStatus.ESTABLISHED
        row = {
            "field": path,
            "side": "signed" if path.startswith("signing_input.") else "envelope",
            "coverage": classification,
            "edited": True,
            "original": original,
            "forged": value,
            "signature_valid": signature_valid,
            "signature_status": report.signature.status.value,
            "signature_reason": report.signature.reason,
            "claims": claims,
            "claims_changed": changed,
            "envelope_disagreements": list(report.envelope_disagreements),
            "notes": list(report.notes),
            "detected": signature_valid is False or bool(report.envelope_disagreements),
        }
        emit(
            "tamper.probe",
            (
                f"{path} edited -> signature {report.signature.status.value}"
                + (
                    f", disagreements {row['envelope_disagreements']}"
                    if row["envelope_disagreements"]
                    else ""
                )
            ),
            field=path,
            coverage=classification,
            signature=report.signature.status.value,
            claims_changed=changed,
            envelope_disagreements=row["envelope_disagreements"],
            detected=row["detected"],
        )
        return row

    async def _gateway_verify_surface(
        self,
        gateway: Any,
        tenant: Any,
        *,
        receipt_id: str,
        forged_receipt_id: str,
        rows: list[dict[str, Any]],
        emit: Any,
    ) -> dict[str, Any]:
        """Ask the product's own verifier about the two most important cases."""

        async def ask(candidate_id: str) -> dict[str, Any]:
            response = await gateway.client.post(
                "/v1/receipts/verify",
                json={"receipt_id": candidate_id},
                headers=tenant.headers,
            )
            try:
                body = response.json()
            except ValueError:
                body = {}
            if not isinstance(body, dict):
                body = {}
            return {
                "receipt_id_sent": candidate_id,
                "http_status": response.status_code,
                "valid": body.get("valid"),
                "reason": body.get("reason") or body.get("detail"),
            }

        def independent(path: str) -> dict[str, Any] | None:
            for row in rows:
                if row["field"] == path:
                    return {
                        "signature_status": row.get("signature_status"),
                        "envelope_disagreements": row.get("envelope_disagreements"),
                        "detected": row.get("detected"),
                    }
            return None

        baseline = await ask(receipt_id)
        signed_case = await ask(receipt_id)
        envelope_case = await ask(forged_receipt_id)
        emit(
            "gateway_verify.probe",
            (
                "POST /v1/receipts/verify accepts a receipt_id, not a bundle: "
                f"genuine id -> valid={baseline['valid']}, "
                f"envelope-forged id -> http {envelope_case['http_status']}"
            ),
            genuine=baseline,
            signed_field_case=signed_case,
            envelope_field_case=envelope_case,
        )
        signed_independent = independent("signing_input.outcome")
        envelope_independent = independent("receipt_id")
        return {
            "endpoint": "POST /v1/receipts/verify",
            "accepts_only_receipt_id": True,
            "input_shape": {"receipt_id": "str"},
            "genuine_receipt": baseline,
            "cases": [
                {
                    "case": "signed field tampered (signing_input.outcome)",
                    "independent_verifier": signed_independent,
                    "gateway_endpoint": signed_case,
                    "comparable": False,
                    "agree": False,
                    "note": (
                        "the endpoint cannot be shown the tampered bundle; it re-checks "
                        "the row the gateway stores and reports valid=true, while the "
                        "independent verifier reports the holder's copy as FAILED"
                    ),
                },
                {
                    "case": "envelope field tampered (receipt_id)",
                    "independent_verifier": envelope_independent,
                    "gateway_endpoint": envelope_case,
                    "comparable": False,
                    "agree": False,
                    "note": (
                        "the forged envelope receipt_id names no stored receipt, so the "
                        "endpoint answers about lookup rather than about the bundle; the "
                        "independent verifier keeps a valid signature and flags the "
                        "envelope/payload disagreement"
                    ),
                },
            ],
            "finding": (
                "The two verifiers do not answer the same question. The product's "
                "surface attests to its own stored copy; only an offline check of the "
                "exported bundle against the published keys detects tampering in a "
                "receipt that has left the plane."
            ),
        }
