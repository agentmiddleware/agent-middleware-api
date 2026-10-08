# Break report: API key and bearer sign-in

Summary: 2 breaks found, 2 fixed and tested, 0 fixed but failing, 0 blocked.

Both breaks were confirmed on the unfixed code (4 tests failed), then fixed. The same tests pass after the fix. No migration. Local SQLite tests only.

## High: a bad Authorization header still signed in with X-API-Key

What broke: On routes that use `verify_api_key`, a bad or malformed `Authorization` header was ignored. If the same request also sent a valid `X-API-Key`, the call succeeded. The documented rule is that a presented `Authorization` header is the deciding credential and must not fall through to a different key.

How to reproduce: `GET /v1/billing/pricing` with `Authorization: Bearer not-a-jwt` and `X-API-Key: test-key`. Before the fix this returned 200. The same hole is on the other routes that depend on `verify_api_key`: billing service list, discover tools and AWI, oracle index/register/registrations/visibility/network, and factory analytics and schedule.

Root cause: `app/core/auth.py` `verify_api_key` (previously the function called `get_auth_context(api_key)` and never read `Authorization`). `get_auth_context` itself already rejected the bad header. The thin helper dropped it. Pricing is `app/routers/billing.py` around the `get_pricing` dependency.

Fix: `verify_api_key` now takes the `Authorization` header and passes it into `get_auth_context`, including the bearer scheme used for the OpenAPI declaration. Invalid bearer shapes return 401. A request with only `X-API-Key` still succeeds.

Test results: `test_invalid_bearer_does_not_fall_through_to_a_valid_api_key` failed before the fix (HTTP 200) and passes after it. The shapes covered are `Bearer not-a-jwt`, `Bearer` with no token, a lowercase scheme, a double space, a trailing space, `Basic`, and `Bearer test-key` with no API key. A plain `X-API-Key: test-key` still returns 200.

## High: a key revoked or expired after it was read still authenticated

What broke: Default API keys have no use limit. `validate_key` loaded the row, then wrote `last_used_at` from that in-memory row without asking the database whether the key was still active or still inside its expiry. A revoke or expiry that committed in that gap still produced a successful sign-in. Keys with `max_uses` already rechecked status and remaining uses on the write, but not expiry, so an expiry in that same gap still counted as a use.

How to reproduce: Local test only. Seed an active unlimited key, start `validate_key`, and after the SELECT commits a revoke (status `revoked`) or sets `expires_at` in the past from another session. Before the fix `validate_key` returned the key. The same expiry interleave on a key with `max_uses=3` also returned the key. Header sign-in and `POST /v1/auth/token` both trust this return value.

Root cause: `app/services/api_key_service.py` `validate_key`. The old unlimited branch assigned `last_used_at` on the loaded object and committed. That branch was the `else` after the `max_uses` update, immediately before `return key`. The capped path's update did not include `expires_at`.

Fix: One guarded UPDATE for every key, matching `consume_derived_key_use`. The write matches only if the row is still `active`, not past `expires_at`, and either unlimited or still under `max_uses`. Unlimited keys do not increment `use_count`. If the update matches nothing, `validate_key` returns None. An already-expired key still returns before any write. A database that reports an unknown row count (`-1`) still accepts, so a driver that cannot count rows does not lock out valid keys.

Test results:
- `test_unlimited_key_revoked_after_read_is_not_accepted`
- `test_unlimited_key_expired_after_read_is_not_accepted`
- `test_capped_key_expired_after_read_is_not_accepted`

All three failed before the fix (`validate_key` returned the key; the interleave hook had fired) and pass after it. The revoked row stays `revoked`. The capped key's `use_count` stays 0. `test_unlimited_key_does_not_spend_a_use_and_capped_key_does` checks the budget rule still holds: an unlimited key stays at `use_count` 0 and gets `last_used_at`, and a one-use key increments once then fails. That budget test is a guard. It was not the pre-fix failure.

## Checked and held (not bugs, no code change)

- Truncated keys, equal-length wrong database keys, a longer key, a SQL-looking key, and a key with a null byte are rejected. The real key still works.
- Equal-length wrong configured key (`test-kez` against `test-key`) is rejected, and `hmac.compare_digest` runs for that comparison.
- A hash stored as SHA-256 of pepper plus key does not match the raw key. This service does not use a pepper. That is not a hole by itself.
- Revoked, already expired, `suspended`, and unknown status `disabled` are rejected. A key that expires tomorrow still works.
- There is no separate disabled-agent flag on the key. Any status other than `active` fails the lookup.
- A key for a suspended, frozen, closed, or disabled wallet still validates. Spending is a later gate. Existing frozen-wallet tests require the key to reach the handler.
- Malformed `POST /v1/auth/token` bodies return 422.
- Self-selected scopes `admin`, `bootstrap`, and `billing:charge` do not make the caller a bootstrap admin. Creating a sponsor wallet with that token stays 403.
- A truncated access token, an equal-length flipped access token, and a refresh token used as an access token are rejected. Replaying a refresh token is rejected.
- After the key status is set to `suspended`, the raw key, the access token, and the refresh token are rejected.

## Tests

Confirmed failing on the unfixed code:

```
~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_brk_api_auth_keys.py::test_capped_key_expired_after_read_is_not_accepted tests/test_brk_api_auth_keys.py::test_unlimited_key_revoked_after_read_is_not_accepted tests/test_brk_api_auth_keys.py::test_unlimited_key_expired_after_read_is_not_accepted tests/test_brk_api_auth_keys.py::test_invalid_bearer_does_not_fall_through_to_a_valid_api_key --tb=line
```

4 failed in 1.25s. The three race tests returned the loaded key. The bearer test got HTTP 200 from `GET /v1/billing/pricing`.

After the fix:

```
~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_brk_api_auth_keys.py --tb=short
```

17 passed in 1.16s.

```
~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_api_key_constant_time.py tests/test_revocation_containment.py tests/test_jwt_auth.py tests/test_jwt_authority.py tests/test_backend_contract_regressions.py tests/test_api_keys.py -x --tb=line && .venv/bin/ruff check app/services/api_key_service.py app/core/auth.py tests/test_brk_api_auth_keys.py
```

151 passed in 3.85s. Ruff: All checks passed.

## Open questions

- No pepper was added. Stored hashes are plain SHA-256 of the key. Adding a pepper would invalidate every stored key and needs a product decision plus a migration.
- Wallet suspend, freeze, and close stay spend controls, not sign-in failures. Say if sign-in should die as well. That would conflict with the frozen-wallet handler tests.
- After `validate_key` returns, the same request can still mint a token or another key if a revoke lands in that later gap. Closing it means holding the check until that later write. This pass only closed the gap inside `validate_key`.
- Clients can ask for scopes on token exchange, and those scopes are copied into the JWT. They did not unlock bootstrap admin in this pass. Left unchanged.
- A wrong database key of the same length does not reach `compare_digest`, because lookup is by the full hash. Configured env keys do use `compare_digest`. That matches the existing constant-time tests.
