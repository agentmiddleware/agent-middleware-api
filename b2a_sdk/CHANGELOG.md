# Changelog

## Unreleased

- Add `b2a_sdk.receipt_verifier` for offline verification of portable trust
  receipts. It imports nothing from the middleware application and needs no
  network access: given a bundle and a published key set, it checks the
  Ed25519 signature over the exact signed bytes and reports only fields read
  from inside them.
- Distinguish a failed verification (`INVALID`) from an undetermined one
  (`UNKNOWN_KEY`, `MALFORMED`, `UNSUPPORTED`), so callers do not mistake a
  stale key cache for tampering.
- Add the `b2a-verify-receipt` CLI, with exit codes `0` verified, `1` forged,
  `2` undetermined.
- Add the `verify` extra (`pip install "b2a-sdk[verify]"`) for the
  `cryptography` dependency. The base install is unchanged; importing
  `b2a_sdk` without the extra still works, and only signature checking
  requires it.

## 0.4.0

- Add the typed async `AgentMiddlewareClient` trust-loop API.
- Require caller-provided idempotency keys for permit creation and tool calls.
- Expose typed permits, receipts, verification results, and evidence bundles.
- Raise typed authentication, authorization, permit, billing, idempotency,
  delivery-uncertainty, API, and transport errors.
- Retain `B2AClient` as a deprecated compatibility name.
- Build installable wheel and source artifacts from the standard `src/` layout.
