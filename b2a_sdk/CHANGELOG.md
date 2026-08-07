# Changelog

## 0.4.0

- Add the typed async `AgentMiddlewareClient` trust-loop API.
- Require caller-provided idempotency keys for permit creation and tool calls.
- Expose typed permits, receipts, verification results, and evidence bundles.
- Raise typed authentication, authorization, permit, billing, idempotency,
  delivery-uncertainty, API, and transport errors.
- Retain `B2AClient` as a deprecated compatibility name.
- Build installable wheel and source artifacts from the standard `src/` layout.
