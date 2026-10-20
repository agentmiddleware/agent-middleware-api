# Parked `delivery_uncertain` calls: provider lookup handles and the reconcile worker

Status: receipt fields **shipped**. Status probe, leased reconciler, and
opt-in attested refund **shipped, off by default**
(`UPSTREAM_RECONCILE_WORKER_ENABLED=false`,
`UPSTREAM_RECONCILE_REFUND_ON_ATTESTED_NOT_EXECUTED=false`,
`MCP_UPSTREAM_STATUS_URL=""`). Schema: migration 047
([schema-047-rollout.md](schema-047-rollout.md)).

## Rule

The guarantee is at-most-once dispatch, not exactly-once execution. A call
whose upstream outcome is unknown is **parked and checked against the
provider**. It is never auto-failed and never redispatched. Its budget is
never released because it got old, because the provider answered 404, or
because the provider gave any answer short of an explicit, identifier-bound
"not executed" received after the quiescence window. Age raises an alert.

## What already held on `main` before this change

These are code facts, not new behaviour:

| Property | Where |
|---|---|
| A transport failure after the dispatch checkpoint becomes terminal `delivery_uncertain`, not a failure | `UpstreamMcpAdapter._call_tool_once` (`app/services/upstream_mcp.py`), `_execute_upstream_after_charge` (`app/routers/mcp.py`) |
| Crash-orphaned `dispatch_claimed` rows become `delivery_uncertain` after the idle window, without redispatch | `McpDispatchReconciliationService._reconcile_active` (`app/services/mcp_dispatch_reconciliation.py`) |
| The debit is retained and a signed receipt with outcome `delivery_uncertain` is minted | `_raise_charged_upstream_failure` (`app/routers/mcp.py`) |
| The permit reservation stays consumed (`delivery_uncertain` counts as spent) | `PermitService._sum_permit_charges` (`app/services/permits.py`) |
| Same-key replay returns the same receipt and never redispatches | `tests/test_delivery_uncertain_replay.py` |
| A periodic `mcp_dispatch_operator_alert` log fires while any `delivery_uncertain` rows exist | `periodic_cleanup` (`app/main.py`) |

The gap was the "checked against the provider" half: nothing ever asked the
upstream, and the receipt did not carry the handles a provider lookup needs.

## Shipped: lookup handles on the signed receipt

Upstream receipts minted by the live path now carry, inside the already-signed
`constraints_evaluated` JSON:

```json
"constraints_evaluated": {
  "upstream_dispatch": {
    "forwarded_idempotency_key": "<exact _meta[io.agentmiddleware/idempotency_key] value sent upstream>",
    "provider_request_id": "<optional, from CallToolResult _meta>"
  }
}
```

- The forwarded MCP `_meta` invocation id (`io.agentmiddleware/invocation_id`)
  is already signed on every receipt as `idempotency_record_id`.
- `provider_request_id` is read from the upstream `CallToolResult._meta` at key
  `MCP_UPSTREAM_PROVIDER_REQUEST_ID_META_KEY` (default
  `io.agentmiddleware/provider_request_id`). It must match
  `[A-Za-z0-9._:/@+=-]{1,128}`; anything else is dropped. It is **not** part of
  the canonical payload, so `response_hash` is unchanged.
- Covered receipts: `success`, `delivery_uncertain`, and `response_rejected`
  minted by the live upstream path. `delivery_uncertain` has no response, so
  it carries only the forwarded key.
- **No schema change, no migration.** Same precedent as `jev_risk_guard`
  (`ReceiptService.create_receipt`). Old receipts verify unchanged; new ones are
  verified by the same code path. `_assert_idempotent_match` does not compare
  `constraints_evaluated`, so a live/reconciler race cannot conflict on it.

Not covered (documented gaps):

- Receipts minted by crash reconciliation (`mcp_dispatch_reconciliation`) and
  the refunded `returned_error` path do not carry `upstream_dispatch`. For
  action-bound permits the forwarded key is a derived `act1-…` value that the
  reconciler cannot recompute without the deployment binding. The worker
  falls back to `invocation_id` for these.
- Clients that read `constraints_evaluated` as "permit constraints only" will
  see one extra key. Additive, not breaking.

## Shipped: status probe (`app/services/upstream_mcp.py`)

`UpstreamMcpStatusProbe` is the upstream half. MCP has no status method, so
the operator configures one HTTPS endpoint:

| Setting | Default | Rule |
|---|---|---|
| `MCP_UPSTREAM_STATUS_URL` | `""` | Must share `MCP_UPSTREAM_URL`'s origin (scheme, host, port), must differ from it, no query or fragment. Validated at boot by `UpstreamMcpConfiguration.from_settings`. Empty means no status endpoint, so calls stay in manual review. |
| `MCP_UPSTREAM_STATUS_TIMEOUT_SECONDS` | `10` | `0 < t <= 3600` |

Request: `POST` with the configured `MCP_UPSTREAM_BEARER_TOKEN` (the
credential is never stored on any row). The body is the exact `_meta` values
the call forwarded:

```json
{"tool": "<upstream tool name>", "invocation_id": "<io.agentmiddleware/invocation_id>", "idempotency_key": "<io.agentmiddleware/idempotency_key, when known>"}
```

The probe reuses the adapter's transport: the same DNS pinning and
private-address refusal, no redirects, identity encoding only, and a 16 KiB
response cap.

| Upstream answer | Outcome |
|---|---|
| `200` + `{"status":"executed", <echoed ids>}` | `executed` |
| `200` + `{"status":"not_executed", <echoed ids>}` | `not_executed` (explicit attestation) |
| `200` with any other status, or ids that do not echo exactly | `unknown` |
| `404` (whatever the body says) | `unknown`. A 404 is never proof of non-execution. |
| other `2xx` | `unknown` |
| `3xx`, other `4xx`, `5xx`, non-JSON, oversize, body reflecting the bearer, private destination | probe error (retry on backoff) |

`provider_request_id` in the answer is kept only if it matches
`[A-Za-z0-9._:/@+=-]{1,128}`.

## Shipped: leased reconciler (`app/services/upstream_reconcile.py`)

Runs inside the 5-minute `periodic_cleanup` loop when enabled. Per sweep:

1. **Lease.** One short transaction runs
   `SELECT ... FOR UPDATE OF mcp_dispatch_attempts SKIP LOCKED` over due rows.
   Due means `delivery_uncertain`, a signed `delivery_uncertain` receipt exists,
   the lease is free or expired, and the row is either unresolved and due on
   backoff for the configured tool and origin, or `not_executed_refund_pending`.
   The transaction stamps a random owner and
   `reconcile_lease_expires_at = now + UPSTREAM_RECONCILE_LEASE_SECONDS`, then
   commits. On SQLite `FOR UPDATE` is a no-op, and the guarded lease UPDATE
   (which re-checks every condition) alone decides ownership.
2. **Verify, then probe.** The receipt signature is checked first. A receipt
   that fails verification is never resolved. Rows are probed one at a time,
   so just before each probe the lease is renewed to
   `now + UPSTREAM_RECONCILE_LEASE_SECONDS`, guarded on this sweep still
   owning it; a row another sweep reclaimed is skipped without a lookup. The
   lease must exceed `MCP_UPSTREAM_CONNECT_TIMEOUT_SECONDS +
   MCP_UPSTREAM_STATUS_TIMEOUT_SECONDS`, or the probe is refused at
   configuration. The probe then runs with **no database transaction open**.
3. **Resolve.** Each row gets its own transaction, a conditional UPDATE that
   matches only while `state = 'delivery_uncertain'`, `reconcile_status IS NULL`,
   the lease owner is this sweep, and the lease is unexpired. A lost lease
   changes nothing.

| Answer | Action |
|---|---|
| `unknown` / probe error | `reconcile_next_probe_at` = now + backoff; lease released |
| `executed` | `reconcile_status = executed`; debit stands |
| `not_executed`, `now <= dispatch time + quiescence` | deferred; next probe after the deadline; nothing moves |
| `not_executed` after quiescence, refund policy off | `not_executed_review`; refund candidate; debit stands |
| `not_executed` after quiescence, refund policy on | `not_executed_refund_pending` committed **first**, then refund (`refund-<entry>`), `mark_debit_refunded`, `release_dispatch_budget_once`, then `not_executed_refunded` |

Quiescence = `UPSTREAM_RECONCILE_UPSTREAM_TIMEOUT_SECONDS` (0 = the fixed
11,430 s rolling-deployment dispatch lifetime; an explicit value is floored at
this deployment's connect + 3 x call timeout) +
`UPSTREAM_RECONCILE_CLOCK_SKEW_SECONDS` (default 300). Dispatch time is
`dispatched_at`, falling back to the terminal time for historical rows.

Every terminal resolution writes one signed, hash-chained audit event
`mcp_delivery_uncertain_provider_resolution` with deterministic id
`audit-ur-<attempt_id>`. Metadata: provider outcome, provider request id,
`receipt_id`, `reconcile_status`, `budget_action` (`none` | `refunded`),
`refund_candidate`, refund ledger entry, and quiescence deadline. If the writer
dies between the resolution commit and the audit write, the next sweep writes
it (`repaired: true`).

**Charge-once.** The refund and release go through the live failure path's
once-only gates. `mark_debit_refunded` and `release_dispatch_budget_once` accept
a `delivery_uncertain` attempt only in `not_executed_refund_pending` (the
release additionally requires `debit_refunded_at`). Plain, `executed`, and
`not_executed_review` rows are still refused. `PermitService._consumed_credits`
stops counting a `delivery_uncertain` receipt only once both halves are durable
and the exact refund entry exists, so a budget rebuild cannot double-subtract.
A crash at any point resumes from the committed decision and is never repeated.

**Receipts.** The attempt's `state` and its signed receipt are never rewritten,
and `credits_charged` on the receipt records the charge at signing time. No
second receipt is minted: receipts are unique per idempotency record and per
dispatch attempt, and the outcome vocabulary is unchanged. Same-key replay
still returns the original receipt and never redispatches.

Tools without a status endpoint, or a status endpoint configured for a
different tool or origin, are never leased. Those calls stay in manual review
and only raise `mcp_delivery_uncertain_aged` (`manual_review: true`).

Tests: `tests/test_delivery_uncertain_reconcile.py`,
`tests/test_upstream_reconcile_worker.py`,
`tests/test_dispatch_reconcile_migration.py`,
`tests/test_reconcile_staging_pilot.py`.

## Staging pilot

Production defaults stay off. Staging-only Railway variables, the
`after_effect=hang` call, log lines, and rollback are in
[reconcile-staging-pilot.md](reconcile-staging-pilot.md). That pilot points
`MCP_UPSTREAM_STATUS_URL` at the refund-partner fixture's `POST /status`.

## Not done (next steps)

1. **Surface the resolution** on `GET /v1/receipts/{id}/evidence` (and replay),
   so a verifier sees "uncertain, later confirmed executed by provider ref X"
   or "refunded by entry Y" without reading the audit chain.
2. **A signed resolution receipt** an offline verifier can hold. Today offline
   verification of the receipt alone does not reveal a later refund.
3. Put `upstream_dispatch` on reconciliation-minted receipts where the
   forwarded key is derivable (non-action permits). Until then the probe binds
   to `invocation_id` alone for those calls.
4. A standard MCP status mechanism instead of a bespoke endpoint; see
   [`docs/proposals/mcp-sep-idempotency-key.md`](proposals/mcp-sep-idempotency-key.md).
