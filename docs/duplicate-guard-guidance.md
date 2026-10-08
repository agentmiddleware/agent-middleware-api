# Duplicate-guard guidance for sales and operators

**Audience:** sellers, pilot operators, and partner integrators.
**Technical reference:** `POLICY_ENFORCEMENT.md` section 9,
`docs/failure-semantics.md`, `docs/failure-lab-suite.md`.

## The one-line story

Same idempotency key retried: always safe, replays the stored receipt with no
second dispatch and no second charge. Fresh key with identical arguments: safe
only when the operator opts into enforcement. Never promise retry safety
beyond the same key unless you have confirmed the deployment runs in enforce
mode.

## Modes

The cross-key guard is set with `MCP_UPSTREAM_DUPLICATE_GUARD`:

- `log` (the shipped default): a fresh-key duplicate is detected, logged as a
  warning, and still dispatched. The caller pays twice. Use this default only
  to observe before enforcing.
- `enforce`: a fresh-key duplicate is refused before dispatch with
  `duplicate_request_new_key`. One dispatch, one debit, four denials is the
  measured concurrent outcome on PostgreSQL.
- `off`: no detection at all. Measured on PostgreSQL only.

Recommend `enforce` for any pilot where an agent may retry a payment, refund,
or booking after losing its key store (for example an agent restart that mints
a new key for the same invoice). In the failure lab the restart case pays twice
under the default, and no lab run covers that case under enforce, so confirm
enforce behavior on the pilot deployment itself before promising it.

## Limits, stated plainly

- Same permit only. A retry under a different permit is never treated as a
  duplicate. By code reading, the standard `POST /mcp` surface mints a
  separate auto-permit per client key, so a fresh-key retry there never matches
  in any mode. No test covers that surface.
- Identical arguments only. Any argument change (a timestamp, a request id, a
  rotated nonce) is a new request in every mode. No test covers this.
- Upstream tools only. Local governed tools are not covered by the guard
  (documented, not tested on local tools).
- Permits can opt out. A permit with `allow_identical_repeats` set bypasses
  the guard in every mode.
- The window expires. The default window is 24 hours
  (`MCP_UPSTREAM_DUPLICATE_WINDOW_SECONDS`), overridable per permit with
  `repeat_window_seconds`. Only a 60-second override is exercised in tests;
  the 24-hour default is not.
- The agent still owns its keys. Nothing at the boundary recovers a key the
  agent lost. Agents must persist the idempotency key with the business
  operation (invoice, order), not with the attempt.
