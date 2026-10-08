# Break Report: receipts service and receipt routers

## Summary

Probed `app/services/receipts.py`, `app/services/signing_keys.py` (verify path),
and `app/routers/receipts.py` with 21 adversarial tests in
`tests/test_break_receipts_adv.py`. Result: 2 real breaks found, both fixed and
regression tested. 0 fixed-but-failing. 0 blocked. 19 probes confirmed the code
already behaves correctly (tamper detection, signature swap, unknown key id,
corrupt signature bytes, corrupt stored pubkey, disabled key fail-closed,
retired key still verifies, empty payloads, Unicode fields, denied vs success
shape, request identity edges, response hash override, auth scoping, negative
credits).

## Finding 1 (medium): any outcome string was accepted and signed

What broke: `ReceiptService.create_receipt` validated credits, reason codes,
and hashes, but never validated `outcome`. Calling it with `outcome="banana"`
minted a fully signed receipt with a meaningless outcome. Downstream readers
branch on exact outcome strings (refund reconciliation checks for
`failed_unrefunded`, idempotency repair maps known outcomes to status codes and
falls back to 500), so a typo or a rogue caller could mint signed evidence no
reader understands.

How to reproduce: run
`tests/test_break_receipts_adv.py::test_adv_unknown_outcome_rejected` against
the unfixed service. It fails with `Failed: DID NOT RAISE ReceiptError`
(the receipt is created instead of refused).

Root cause: `app/services/receipts.py`, `create_receipt` had no outcome
allowlist (validation block around line 295-313 only covered credits and
reason codes).

Fix: added a module-level `_RECEIPT_OUTCOMES` frozenset with the seven outcomes
the governed paths actually mint (`success`, `denied`, `insufficient_funds`,
`failed_refunded`, `failed_unrefunded`, `delivery_uncertain`,
`response_rejected`, each confirmed at its call site) and a
`receipt_outcome_invalid` refusal in `create_receipt`.

Test results: the new probe fails without the fix (confirmed by toggling the
check off) and passes with it. Full probe file: 21 passed. Neighbor suites
(receipts, portability, signing snapshots, wallet linkage, dispatch
reconciliation, refund reconciliation, idempotency, contention surface,
interop): all passed.

## Finding 2 (medium): idempotency replay ignored constraints_evaluated

What broke: `_assert_idempotent_match` compared every signed field except
`constraints_evaluated`. Reusing an idempotency record with different evaluated
constraints silently returned the old receipt, presenting stale signed evidence
as the answer to a new evaluation. The parameter was accepted but never
compared.

How to reproduce: run
`tests/test_break_receipts_adv.py::test_adv_idempotency_reuse_with_different_constraints_conflicts`
against the unfixed service. The second `create_receipt` with
`{"scope": "second"}` returns the first receipt instead of raising.

Root cause: `app/services/receipts.py`, `_assert_idempotent_match` (around line
245) accepted `constraints_evaluated` and used it nowhere.

Fix: compare the stored `constraints_evaluated_json` (decoded, defaulting to
`{}`) against the caller-supplied constraints and raise
`receipt_idempotency_conflict` on mismatch. Both sides are post-JEV-merge
because the merge in `create_receipt` runs before the replay check, so honest
retries with identical arguments still replay cleanly.

Test results: the new probe fails without the fix (confirmed by toggling the
check off) and passes with it. Identical-argument replay still returns the same
receipt (covered by the neighboring tool-conflict probe and the pre-existing
`test_receipt_idempotency_matches_reason_code`).

## Probes that held (no fix needed)

Tampering with `reason_code` or `credits_charged` after signing fails
verification. Swapping signatures between two receipts fails both. Unknown key
id, corrupt signature bytes, wrong-length signature bytes, and corrupt stored
public keys all fail closed with `receipt_signature_invalid` and no HTTP 500
(via service, `/v1/receipts/verify`, and portable export returning 409).
Disabling a signing key fails verification closed while retiring keeps history
verifiable, matching the documented key lifecycle. Empty `{}` payloads and
Unicode tool names and arguments create and verify fine; Unicode reason codes
are refused. Denied receipts carry no ledger entry, zero charge, and a signed
reason, and verify; refused MCP calls get a signed denied receipt (also covered
by the pre-existing forbidden-field denial test). Request identity edges (both
payload and hash, neither, non-hex, short hash) are refused; uppercase hex
normalizes to lowercase. Response hash override mismatch and override without a
dispatch attempt are refused. Cross-wallet reads return 403, owner reads 200,
anonymous reads are refused, and unscoped listing requires admin. Negative
credits are refused.

## Open questions

1. The reconciler pre-check in
   `app/services/mcp_dispatch_reconciliation.py::_get_or_create_receipt`
   adopts an existing receipt through its own `_assert_receipt_match`, which
   also does not compare constraints. The shared `create_receipt` replay path
   is now strict, but that adoption path could still accept silently. It was
   left alone because its constraints are pre-JEV-merge while stored ones are
   post-merge, so a naive comparison could false-positive. Worth a follow-up
   with JEV guard enabled.
2. Non-success outcomes are not required to carry a `reason_code`. Every
   current caller sets one, but the service would sign a reason-less denial.
   Left as is to keep the fix minimal; flagging in case the contract wants it
   mandatory.
3. `test_acp_bridge.py::test_acp_rollback_release_failure_neither_masks_nor_skips_abandon`
   fails when run in a 10-file batch but passes alone and as a whole file,
   identically with and without this fix (verified by toggling the fixes off
   and re-running the batch). Pre-existing cross-file interference, unrelated
   to receipts validation. That test stubs `create_receipt` entirely, so the
   changed code never executes in it.
