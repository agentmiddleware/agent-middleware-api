# Changelog

## Unreleased — 0.5.0

`pyproject.toml` carries `0.5.0` from here on. `0.4.0` is published and
tagged `python-sdk-v0.4.0`, and the entries below are new surface area on
top of it, so leaving the source at `0.4.0` would have shipped something
materially different under a version already in the wild. A minor bump:
everything here is additive and no published behaviour changes. The tag is
not cut by this change — `python-sdk-v0.5.0` is still a release decision.

- Add `b2a_sdk.receipt_verifier` for offline verification of portable trust
  receipts. It imports nothing from the middleware application and needs no
  network access: given a bundle and a published key set, it checks the
  Ed25519 signature over the exact signed bytes and reports only fields read
  from inside them.
- Distinguish a failed verification (`INVALID`) from an undetermined one
  (`UNKNOWN_KEY`, `MALFORMED`, `UNSUPPORTED`), so callers do not mistake a
  stale key cache for tampering. A bundle that is internally inconsistent —
  or that disagrees with a caller-supplied `expected_issuer` — is `MISMATCH`:
  a finding about the bundle, distinct from both families.
- Read `kid`, `alg`, and `canonicalization` from the **signed** payload, never
  from the surrounding envelope. The envelope is unauthenticated, so letting it
  select the key or gate the capability checks would let one edited byte
  downgrade a genuine receipt to `UNSUPPORTED` — an attacker-chosen "your
  verifier is too old" that reads as a verifier problem rather than a bundle
  problem. Envelope values are cross-checked *after* the signature verifies,
  and any disagreement is reported as `MISMATCH`.
- Add `VerificationResult.is_rejected`, true for `INVALID` and `MISMATCH` —
  the property callers should branch on for "do not trust this bundle".
  `is_tampered` stays narrow (`INVALID` only), because `MISMATCH` also covers
  an `expected_issuer` disagreement, which is not a claim about tampering.
- Add the `b2a-verify-receipt` CLI, with exit codes `0` verified, `1` rejected
  (`INVALID` or `MISMATCH`), `2` undetermined.
- Add the `verify` extra (`pip install "b2a-sdk[verify]"`) for the
  `cryptography` dependency. The base install is unchanged; importing
  `b2a_sdk` without the extra still works, and only signature checking
  requires it.
- Require `cryptography>=50.0.0` in the `verify` and `dev` extras, matching
  the application's own floor: every 42.x–49.x release carries at least one
  published advisory, and a receipt *verifier* must not itself depend on a
  known-vulnerable cryptography build.

## 0.4.0

- Add the typed async `AgentMiddlewareClient` trust-loop API.
- Require caller-provided idempotency keys for permit creation and tool calls.
- Expose typed permits, receipts, verification results, and evidence bundles.
- Raise typed authentication, authorization, permit, billing, idempotency,
  delivery-uncertainty, API, and transport errors.
- Retain `B2AClient` as a deprecated compatibility name.
- Build installable wheel and source artifacts from the standard `src/` layout.
