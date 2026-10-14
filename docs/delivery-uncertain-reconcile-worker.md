# Parked `delivery_uncertain` calls: provider lookup handles and the reconcile worker

Status: receipt fields **shipped**; worker **skeleton shipped, off by default**
(`UPSTREAM_RECONCILE_WORKER_ENABLED=false`). Backlog item #7.

## Rule

A call whose upstream outcome is unknown is **parked and checked against the
provider**. It is never auto-failed, never auto-refunded, never redispatched,
and its budget is never released because it got old. Age raises an alert.

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

## Shipped: worker skeleton (`app/services/upstream_reconcile.py`)

```
ProviderStatusProbe.lookup(ParkedCall) -> ProviderLookup(outcome, provider_request_id)
    outcome ∈ {executed, not_executed, unknown}
NullProviderStatusProbe            # default; MCP has no standard status method
DeliveryUncertainReconcileWorker.run_once() -> ReconcileSweepResult
```

Per sweep, for the oldest `UPSTREAM_RECONCILE_BATCH_LIMIT` unresolved
`delivery_uncertain` attempts:

1. **Backoff.** First probe at `completed_at + backoff[0]`; after the n-th
   probe the next is `now + backoff[min(n, len-1)]`
   (`UPSTREAM_RECONCILE_BACKOFF_SECONDS`, default `30,120,600,3600`). The
   worker runs inside the 5-minute `periodic_cleanup` loop, so effective
   granularity is 5 minutes.
2. **Probe** with `forwarded_idempotency_key` (read from the signed receipt)
   and `invocation_id`.
3. **`executed` / `not_executed` → close.** Write one audit event
   `mcp_delivery_uncertain_provider_resolution` with deterministic id
   `audit-ur-<attempt_id>` (hash-chained and signed like every audit event).
   Metadata: provider outcome, provider request id, `budget_action: "none"`,
   `refund_candidate: true|false`. Closed attempts drop out of the listing
   (anti-join on that event id). Concurrent workers converge on one event.
4. **`unknown` / probe error →** stay parked, back off.
5. **Age ≥ `UPSTREAM_RECONCILE_ALERT_AGE_SECONDS`** (default 3600) and still
   unresolved → log `mcp_delivery_uncertain_aged` once per attempt per
   process. **No budget release, no refund.**

The worker never mutates the attempt, the receipt, the ledger, or the permit.
Tests: `tests/test_upstream_reconcile_worker.py`.

## Not done (next steps, in order)

1. **A real probe.** Needs one provider with a status-by-idempotency-key
   lookup. Options: (a) an HTTP lookup the partner exposes; (b) a
   standardized MCP mechanism — see
   [`docs/proposals/mcp-sep-idempotency-key.md`](proposals/mcp-sep-idempotency-key.md);
   (c) re-calling the upstream tool with the **same** forwarded key, which is
   only safe if the provider is natively idempotent on that key. (c) is a
   redispatch at the transport level and must stay opt-in per tool.
2. **Money on `not_executed`.** Today it is a flagged refund candidate. An
   automatic refund needs an explicit operator policy, a once-only gate keyed
   on the attempt (like `release_dispatch_budget_once`), and its own signed
   receipt. Do not wire it to the probe answer alone: a provider's "not found"
   can mean "not yet visible".
3. **Durable backoff/alert state.** Per-process today; a restart re-probes due
   calls and may re-alert once. Acceptable for an opt-in skeleton.
4. **Surface the resolution** on `GET /v1/receipts/{id}/evidence` so a
   verifier sees "uncertain, later confirmed executed by provider ref X".
5. Put `upstream_dispatch` on reconciliation-minted receipts where the
   forwarded key is derivable (non-action permits).
