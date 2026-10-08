# Break report: permit reserve and authorize

3 breaks found. 3 fixed and tested. 0 fixed but still failing. 0 blocked.

Local SQLite only. No production calls, no migration, no database left behind.

## High: a negative price changed the permit budget

What broke. `authorize_and_reserve` and `reserve_budget` added the caller's estimate to `spent_credits` with no check that the estimate was a real, storable, non-negative amount. A negative estimate lowered `spent_credits`, which gives the permit more room than the issuer set. `release_budget` with a negative amount raised `spent_credits`. `POST /v1/permits/verify` with `estimated_credits` of `-1` returned `valid: true` for a permit that had already reserved part of its budget, because a negative number still fit under the cap.

How to reproduce. Mint a tool permit, reserve 4 credits, then call `authorize_and_reserve` with `estimated_credits=Decimal("-4")`. Before the fix the call was allowed. The same permit's verify endpoint, sent `estimated_credits: "-1"`, returned valid.

Root cause. `app/services/permits.py` budget comparison inside `_validate_model_for_action`, and the reserve update at `app/services/permits.py:663` (`spent_credits + estimated_credits`). `reserve_budget` applied the same addition at `app/services/permits.py:1157`. Verify passes the body value through at `app/routers/permits.py:262`.

Fix. `_credit_amount_is_storable` (`app/services/permits.py:111`) rejects negatives, non-finite values, and amounts that do not survive eight-decimal storage. Validate denies those with `permit_amount_invalid` before any write (`app/services/permits.py:904`). `reserve_budget` (`:1096`) and `release_budget` (`:1224`) raise `PermitError` and leave the row alone. Zero is still accepted, because verify uses zero when the caller does not name a price. The reason is catalogued in `docs/denial-details.md`.

Tests. `test_negative_and_unstorable_amounts_do_not_change_spent` failed on the old code (`allowed` stayed true) and passes now. Spent stayed at 4 for -4, -0.01, NaN, Infinity, -Infinity, `0.000000001`, and `1.123456789`.

## High: a tool id longer than the receipt column was accepted

What broke. A permit could be minted with a 129-character tool id. The signed receipt stores `tool` in `VARCHAR(128)` (`app/db/models.py:852`). SQLite stores the longer value. PostgreSQL rejects the insert, so a governed refusal of that tool can fail while writing the denial receipt.

How to reproduce. `POST /v1/permits` with `allowed_tools` set to 129 `t` characters. Before the fix the response was 201 and the long id was on the signed permit.

Root cause. `PermitCreateRequest.allowed_tools` had no per-item length (`app/schemas/trust.py`, previously an unbounded `list[str]`). `create_receipt` did not check `tool` before insert. `register_local` accepted any service id, and that id is what a denial receipt records.

Fix. Tool ids on permit create, permit requests, action permits, and per-tool call caps are 1 to 128 characters (`app/schemas/trust.py:44`). Verify still allows a blank tool so a missing tool stays `permit_verify_context_missing`, and rejects one longer than 128 (`app/schemas/trust.py:280`). `create_receipt` raises `receipt_tool_invalid` (`app/services/receipts.py:299`). Local and upstream registration reject an id longer than 128 (`app/services/service_registry.py:272` and `:339`). An older permit request whose stored tool id no longer validates fails the mint with `permit_request_terms_rejected` instead of leaving the claim stuck (`app/services/permit_requests.py:680`).

Tests. `test_tool_names_longer_than_the_receipt_column_are_refused` returned 201 on the old code and now expects 422 for the permit, 422 for a blank tool, 422 for the permit request, `ReceiptError` for the receipt, and `ValueError` for registration. The first run stopped at the 201, so the receipt and registration assertions were not executed until after the fix. They pass with the fix. A normal refused call still returns one signed denial receipt (`test_refused_call_still_has_a_signed_denial_receipt`).

## Medium: a blank agent id minted a wallet

What broke. `POST /v1/billing/wallets/agent` with `agent_id: ""` returned 201 and stored `agent_id` as an empty string. That wallet can be the subject of a permit. Omitting `agent_id` was already rejected. The column is `VARCHAR(100)` (`app/db/models.py:44`), and the request schema did not cap the length either.

How to reproduce. Create a sponsor, then post an agent wallet with `agent_id` set to `""`. Before the fix the body came back with `"agent_id": ""`.

Root cause. `CreateAgentWalletRequest.agent_id` was a required string with no minimum length (`app/schemas/billing.py:223`). `WalletEngine.create_agent_wallet` stored the value with no blank check.

Fix. The schema requires 1 to 100 characters and rejects a whitespace-only id (`app/schemas/billing.py:232`). The engine raises `ValueError("agent_id is required")` for a blank, non-string, or over-long id (`app/services/wallet_engine.py:400`). A permit body still has no agent id field. Permit authority stays the wallet id.

Tests. `test_missing_or_blank_agent_id_cannot_mint_a_wallet` failed on the blank id (201) before the fix and passes now, including whitespace and 101 characters. A normal permit create still returns 201.

## Checked and holding

These were attacked and did not break. No production change for them.

- Per-tool cap of 1. Six concurrent `authorize_and_reserve` calls kept one reservation. Spent and the call counter stayed at that one use. The next call was `permit_max_calls_exceeded`.
- Expired permits. Reserve and verify return `permit_expired` and do not move spent. A negative estimate on an already expired permit still reports expiry.
- Revoked, expired, and use-exhausted keys. Verify with that key returns 403 `invalid_api_key` and does not reserve. The test now accepts 401 or 403, after the run showed 403. The key is refused before reserve.
- Zero and negative `max_calls_per_tool`. The API returns 422. A stored 0 or -1 denies with `permit_max_calls_exceeded` and does not move the counter.
- Unicode tool ids. An NFC id (`café-tool`) reserves one slot. The NFD form and a Cyrillic lookalike are `permit_tool_not_allowed` and do not share that counter.
- Zero wallet balance. Issuing a permit whose `max_credits` exceed the balance returns 400 `permit_budget_exceeds_wallet_balance`. After a funded permit exists, setting the wallet balance to 0 still allows a reserve against the permit budget. The wallet balance stays 0. Reserve does not debit the wallet.
- Second finalize. Two `create_receipt` calls with the same idempotency id return one receipt row, and the signature verifies. `release_dispatch_budget_once` returns true once. The second call returns false and does not move spent or the call counter.
- Finalize after expiry. A receipt written after `expires_at` still verifies. A new reserve is `permit_expired`. Releasing a pre-dispatch attempt after expiry returns the budget and the call slot. An attempt that already dispatched keeps the slot after the budget is returned.
- Refused calls. A governed invoke of a tool outside the permit returns 403 with a signed denial receipt, `credits_charged` 0, and `reason_code` `permit_tool_not_allowed`. Replaying the same idempotency key returns that same receipt.

## Tests

Confirmed the new assertions fail on the old code:

```text
~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_permit_break_reserve.py --no-cov --tb=line
4 failed, 7 passed in 2.04s
```

Failures were the negative estimate (`allowed` stayed true), the 129-character tool permit (201), the blank agent id (201), and the key test expecting 401 where the server returns 403. The 403 case was a test expectation, not a product hole. The other seven attacks passed on the old code.

After the fix, ruff format, and ruff check:

```text
~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_permit_break_reserve.py --no-cov --tb=line
11 passed in 1.30s

~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_permit_break_reserve.py tests/test_permits.py tests/test_permit_v2_constraints.py tests/test_permit_budget_integrity.py tests/test_billing.py --no-cov -x --tb=line
144 passed in 5.90s

~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_permit_request_flow.py tests/test_permit_numeric_storage.py --no-cov -x --tb=line
109 passed in 2.34s
```

`.venv/bin/ruff check` on the edited Python files passed. The full suite was not run.

## Open questions

- Should `authorize_and_reserve` also refuse a key that is revoked, expired, or out of uses, or is the HTTP 403 at authentication enough? Replay of an old receipt must keep working after the key is revoked, so a liveness check does not belong on the replay path. This pass left the reserve function trusting the key id it is given.
- Reserve does not re-read the wallet balance. A permit issued while the wallet had funds can still reserve after the balance is drained. The later charge path is what returns insufficient funds. Say if reserve should refuse in that case too.
- `release_budget` subtracts an amount. It is not a one-time claim. Calling it twice can unwind two reservations, down to zero. `release_dispatch_budget_once` is the one-time gate, and the new test pins that. No change to `release_budget`.
