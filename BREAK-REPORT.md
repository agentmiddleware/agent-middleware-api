# Break Report: admin and audit routers

## Summary

Probed admin-gated routes (policies, sponsor creation, refund retry, receipt
verify) and the audit router (events, summary, verify-chain), plus adjacent
key-management reads, with anonymous callers, plain wallet keys, JWTs carrying
caller-chosen admin-like scopes, cross-wallet IDOR attempts, mass assignment
bodies, malformed inputs, idempotency-key replay across wallets, and concurrent
rotation of one key.

Breaks found: 3. Fixed and tested: 3. Fixed but failing: 0. Blocked: 0.

Most attack paths held: anonymous callers get 401/403 everywhere, wallet keys
get 403 on every admin route, forged JWT scopes grant no admin power, audit
reads stay wallet-scoped with victim data present, Bearer [REDACTED] authoritative
(no fallback to a companion API key), and policy update bodies ignore
ownership and privilege fields.

## Finding 1 (medium): concurrent rotation of one key mints two live replacements

What broke: two simultaneous `POST /v1/api-keys/rotate` calls for the same
key with `revoke_old=true` both returned 200, each minting its own live
replacement key. The loser should have been refused.

How to reproduce: create a wallet key, then `asyncio.gather` two rotate calls
with the same `key_id`, `revoke_old=true`, and different Idempotency-Key
values. Both answer 200. See
`test_concurrent_rotate_of_one_key_fails_closed` in
`tests/test_admin_audit_break.py`. The race is timing dependent: without the
fix it failed about half the runs (2 of 4 in one check).

Root cause: `app/services/api_key_service.py:518` (`rotate_key`). The ACTIVE
status snapshot check reads before either transaction commits, and SQLite
ignores the `FOR UPDATE` lock the code relies on for serialization, so both
transactions see ACTIVE and both mint. The revoking UPDATE matched on key id
only, so it always affected one row.

Fix: the revoking UPDATE is now conditional on the key still being ACTIVE, and
a zero rowcount rolls back and raises `InvalidRotationRequestError`
("cannot rotate a key that is not active", answered as 422). Same
compare-and-set pattern already used elsewhere in the codebase
(`billing_engine.py`, `auth.py` refresh flow). The non-revoking rotate path is
unchanged.

Test results: new test passes 8 of 8 runs with the fix (5 plus 3 after final
formatting); without the fix it fails intermittently, as expected for a race.
Full `test_api_keys.py` (53 tests) passes.

## Finding 2 (low): policy creation for an unknown wallet answers 500

What broke: `POST /v1/policies` with a nonexistent `wallet_id` raised an
unhandled `IntegrityError` (foreign key) and answered 500. Admin-only route,
so the only caller who can trigger it already holds full power, but a 500 with
a database error body is still wrong.

How to reproduce: `POST /v1/policies` with `{"wallet_id": "no-such-wallet",
"name": "x"}` as bootstrap admin. See
`test_policy_create_unknown_wallet_is_404_not_500`.

Root cause: `app/routers/policies.py:30` (`create_policy`) inserted without
checking the wallet exists, unlike the key-management and agent-wallet routes
which 404 first.

Fix: the route looks up the wallet with `get_agent_money().get_wallet` and
answers 404 `wallet_not_found` (same body shape as the api-keys routes) before
inserting. Service contract unchanged.

Test results: new test fails without the fix (500, IntegrityError) and passes
with it. `test_policy_bundles.py` and `test_billing_boundary_regressions.py`
pass.

## Finding 3 (low): rotation-log `limit` accepted any integer

What broke: `GET /v1/api-keys/{wallet_id}/logs?limit=-1` returned every row
instead of an error. SQLite reads `LIMIT -1` as "no limit", so the missing
validation silently disabled pagination on this backend (Postgres would error
instead, so behavior also differed by backend).

How to reproduce: seed rotation logs, then `GET .../logs?limit=-1` and compare
with `?limit=1`. See `test_rotation_logs_limit_is_validated`.

Root cause: `app/routers/api_keys.py:418` (`get_rotation_logs`) declared
`limit: int = 50` with no bounds, and the service passes it straight to SQL
`.limit()`.

Fix: `limit: int = Query(50, ge=1, le=200)`, matching the audit list
convention. `limit=0`, negatives, and values over 200 now answer 422.

Test results: new test fails without the fix (200 with all rows for
`limit=-1`) and passes with it.

## Probes that held (no break)

Anonymous access to all ten admin/audit endpoints: 401/403. Wallet key on all
seven admin endpoints: 403. Cross-wallet audit events list, summary scoping
with victim rows present, and chain verification: correctly scoped or 403.
JWT minted with scopes `admin`, `bootstrap`, `bootstrap_admin`, `*:*`: still
403 on admin routes and cross-wallet audit. Policy PATCH with `wallet_id`,
`policy_id`, `is_admin`, `scopes` fields: ignored, ownership unchanged.
Cross-wallet key list, rotation, emergency revoke, and key creation: 403.
Twelve malformed-input cases (bad limit/offset/datetime/summary flag,
10k-char wallet id, wrong JSON types, inverted verify-chain dates): 422/404/
200, never 500. Bad Bearer [REDACTED] a valid key: 401, no fallback. Same
Idempotency-Key across two wallets: separate keys minted, no cross-wallet
replay. Unknown key: 403. Empty/short key: 401.

## Open questions

1. `POST /v1/receipts/verify` answers 403 (admin required) when the receipt id
   does not exist, even for a wallet caller asking about its own receipts.
   Fail-closed and deliberate-looking (avoids a receipt-id oracle), so left
   alone, but C.Lee may want `valid: false` instead for usability.
2. `consume_derived_key_use` (JWT use-budget decrement) has the same
   check-then-act shape as the rotation race and was not probed; worth a
   follow-up round with Postgres, where row locking actually applies.
3. The audit `key_id` filter is silently dropped for non-admin callers rather
   than rejected. Harmless (scope can only narrow to the caller's wallet), but
   a 400 for a filter that names another key would be less surprising.
4. `app/routers/ai.py` has two more unvalidated `limit` params; out of scope
   for this round (not admin/audit), flagged, not changed.
