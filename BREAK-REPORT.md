# Audit chain break report

7 breaks found. 7 fixed and tested. 0 fixed but still failing. 0 blocked.

Four other attacks were tried and already held: a tampered previous hash, eight concurrent appends on one wallet, a wallet key verifying another wallet, and a malformed signature on the verify route. No code change for those.

All of this ran on local SQLite (`sqlite+aiosqlite:///./test.db`). No production database, no production URL.

## High: a time window hides an earlier tampered payload

What broke. `POST /v1/audit/verify-chain` with `created_after` or `created_before` only checked the rows inside that window. Changing an older event's metadata, and leaving its stored hashes alone, still returned `valid: true` when the window started after that event.

How to reproduce. Append three events. Rewrite the first event's `metadata_json`. Verify with `created_after` set to the third event's time. Before the fix the answer was valid, with one event checked.

Root cause. `app/services/audit_chain.py` `_verify_single_chain` (the walk now starts at line 502) used to put the time bounds in the SQL query, so earlier rows were never loaded.

Fix. The integrity walk always loads the wallet's events and its head in one snapshot. Time bounds only choose which event ids are reported on a chain that already passed. `tests/test_audit_chain_break.py::test_time_window_does_not_hide_an_earlier_tampered_payload`.

Test result. Failed on the old code (`valid` was true). Passes after the fix.

## High: a time window hides a deleted tail

What broke. The same window path never loaded the chain head. Deleting the last event, which the unwindowed check already calls `audit_chain_truncated`, returned `valid: true` if the request included any time bound. A bound in the far future, matching nothing, did the same. The HTTP route passed those bounds straight through.

How to reproduce. Append two or three events. Delete the last row and leave the head. `POST /v1/audit/verify-chain` with `created_after` of `2000-01-01`. Before the fix the route returned `valid: true`.

Root cause. Same function. The head was loaded only when both time bounds were absent, so any bound skipped the truncation check.

Fix. The head is loaded in the same snapshot as the events, window or not. A head that does not match the last event is still `audit_chain_truncated`. `test_time_window_does_not_hide_tail_truncation` and `test_verify_route_reports_truncation_inside_a_time_window`.

Test result. The route test failed on the old code (`valid` was true). The service test's first draft deleted the wrong row (see Notes). After that test was pointed at the tail, it passes with the fix, together with the route test.

## High: deleting the head and the tail looks like a valid shorter chain

What broke. Truncation detection trusts the head row. If the last event and the head row are both deleted, the surviving prefix still links, and verification returned `valid: true`. Global verification did too, because the wallet still had events.

How to reproduce. Append three events. Delete the third event and the `audit_chain_heads` row for that wallet. Call `verify_audit_chain`. Before the fix the result was valid, with two events checked.

Root cause. `_verify_single_chain` only compared the tail to the head when a head row existed (the check is now at line 684).

Fix. A chain that uses sequence numbers (any `seq` other than the old default of 0) and has no head row returns `audit_chain_head_missing`. Legacy rows that are all `seq` 0 and have no head are unchanged. `test_deleting_the_head_and_the_tail_is_rejected`.

Test result. Failed on the old code (`valid` was true, two events). Passes after the fix, including the global walk.

## Medium: a hole in the sequence still verifies

What broke. `seq` is not part of the signed payload. Changing the last event from seq 3 to seq 4, and setting the head's `last_seq` to 4, leaves every hash and signature valid. Verification returned `valid: true` for a chain that skips 3.

How to reproduce. Append three events. Set the third `seq` to 4 and the head `last_seq` to 4. Verify the wallet.

Root cause. The walk ordered by `seq` and checked hashes, but never required the numbers to be 1, 2, 3 with no holes. The new check is at line 653.

Fix. When any event has a non-zero `seq`, each next event must be the previous number plus one, starting at 1. A hole returns `audit_sequence_gap`. Hash failures are still reported first, so a deleted middle event whose link is broken stays `audit_previous_hash_mismatch`. `test_sequence_gap_with_intact_hashes_is_rejected`.

Test result. Failed on the old code (`valid` was true, three events). Passes after the fix.

## Medium: replaying an event id adopts a replaced signature

What broke. A second append of the same event id returns the stored row when the caller's fields match. That check rebuilt the payload hash and the chain hash, and it did not check the signature. Replacing the signature and rebuilding `chain_hash` from the new signature made the replay succeed.

How to reproduce. Record one event. Record it again and see the same id. Replace `signature` with 64 bytes that are not the real signature, recompute `chain_hash`, then record the same event a third time. Before the fix the third call returned the tampered row.

Root cause. `_assert_same_audit_intent` in `app/services/audit_chain.py` (line 182). The signature check is at line 255.

Fix. After the hash check, verify the stored signature with the signing key on the same database session. A bad signature raises `AuditEventConflictError` (`audit_event_integrity_conflict`). Chain verification still returns `audit_signature_invalid`. `test_replay_rejects_a_row_whose_signature_was_replaced`.

Test result. Failed on the old code (`DID NOT RAISE AuditEventConflictError`). Passes after the fix. A replay before the tamper still returns the original row.

## Medium: a blank wallet id splits the wallet-less chain

What broke. Events with no wallet, events with `wallet_id=""`, and events with a whitespace wallet id all advance the same head (the key `""`), but they were stored and verified as different wallets. Verification of the wallet-less chain then saw one event and a head that had moved on, and returned `audit_chain_truncated`. `sign_audit_model` looked up only SQL NULL, so it would sign the next system event against the wrong predecessor.

How to reproduce. Record three system events with wallet id `None`, `""`, and `"   "`. Verify with `wallet_id=None`. Before the fix the result was invalid, truncated, one event checked.

Root cause. `append_chained_audit_event` used `model.wallet_id or ""` only for the head key (now line 277). Verification filtered with `wallet_id IS NULL`, which dropped the blanks.

Fix. Blank and whitespace wallet ids are stored as NULL before signing (`_canonical_wallet_id`, line 105). The wallet-less query includes NULL and trim-empty ids. Asking to verify `""` or whitespace verifies that one chain, not every wallet. `test_blank_wallet_id_does_not_split_the_wallet_less_chain`, including a `sign_audit_model` check that the next seq is 4 and the previous hash is the real tail.

Test result. Failed on the old code (truncated, one event). Passes after the fix.

## Medium: an earlier timestamp on a later append makes an honest window look tampered

What broke. Append order is the sequence number, not `created_at`. A caller can pass an earlier `created_at` on a later append (concurrent writers can do this too, because the timestamp is taken before the head update). A `created_before` window that keeps the later-seq row and drops the genesis row then compared that row to "no predecessor" and returned `audit_previous_hash_mismatch` for an honest chain.

How to reproduce. Append event A at 2026-06-01, then event B with `created_at` two days earlier. Verify with `created_before` one day before A. The full chain was already valid. The window was not.

Root cause. The window walk treated the time filter as the chain order, and it only seeded a predecessor when `created_after` was set.

Fix. Same full-chain walk as the tamper fix. The window is applied after the chain has verified, so this case stays valid and reports one event. `test_out_of_order_created_at_window_stays_valid`.

Test result. Failed on the old code (`audit_previous_hash_mismatch` on the single in-window event). Passes after the fix.

## Cases that held

- Tampered `previous_hash` on the second event, with payload hash and chain hash rebuilt, is `audit_previous_hash_mismatch`. `test_tampered_previous_hash_is_rejected` passed before and after the fix.
- Eight concurrent appends on one wallet produce seq 1..8, each previous hash equal to the prior chain hash, and a head on the last event. `test_concurrent_appends_stay_one_contiguous_chain` passed before and after.
- A wallet key gets 403 verifying another wallet, and 200 verifying its own. `test_wallet_key_cannot_verify_another_wallets_chain` passed before and after.
- A signature of `@@@` on `POST /v1/audit/verify-chain` is HTTP 200 with `audit_signature_invalid`, not a 500. `test_malformed_signature_is_an_invalid_chain_not_an_error` passed before and after.

## Tests

Command before the fix (new file only):

`DATABASE_URL=sqlite+aiosqlite:///./test.db STATE_BACKEND=memory ~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_audit_chain_break.py --tb=line`

Result: `8 failed, 4 passed in 2.22s`. The eight failures are the seven findings above (truncation is covered twice, once in the service and once on the route). The service truncation test's first version deleted the earliest row, so that one failure was `audit_previous_hash_mismatch` rather than `valid: true`. The route test of the same hole failed with `valid: true`, which is the break.

Command after the fix:

`DATABASE_URL=sqlite+aiosqlite:///./test.db STATE_BACKEND=memory ~/metacode/fleet/heavy .venv/bin/ruff check app/services/audit_chain.py tests/test_audit_chain_break.py tests/test_audit_chain.py`

`All checks passed!`

`DATABASE_URL=sqlite+aiosqlite:///./test.db STATE_BACKEND=memory ~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_audit_chain_break.py tests/test_audit_chain.py tests/test_audit_snapshot.py tests/test_audit_routes.py --tb=line`

Result: `38 passed in 3.29s`.

`tests/test_audit_chain.py::test_windowed_verify_of_valid_chain_is_valid` now expects `audit_chain_hash_mismatch` for a tampered `chain_hash` outside the window. The old code reported `audit_previous_hash_mismatch` on the first in-window row, because it never opened the tampered row. The chain is still rejected.

Not run: the full suite, Postgres, and anything that charges or calls a live URL.

## Open questions

Rewriting the head, instead of deleting it, is still invisible. Set `last_seq` and `last_chain_hash` to the surviving tail after deleting the real tail, and verification matches. The head row is not signed. Closing that needs a signed checkpoint. I did not add a migration.

Deleting every event and the head removes the wallet from the global check. There is nothing left to disagree with.

Setting every `seq` back to 0 and deleting the head makes the chain look like the old unnumbered rows, so the new "numbered chains must have a head" rule does not fire. The hash links of whatever remains are still checked.

`seq` is still outside the signature. Contiguity is enforced by the verifier, not by the signature.
