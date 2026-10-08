# Break report: permit, billing, and key request bodies

8 breaks found. 8 fixed and tested. 0 fixed but still failing. 0 blocked.

The checks are schema and service unit tests against the local checkout. Nothing was sent to a live payment or production endpoint. Postgres was not started. SQLite, which the local tests use, does not enforce string column lengths, so the column limits below come from the model field lengths and the service checks that now refuse the bad values before a write.

## High: an emergency revoke reason can cancel the revoke

What broke. The emergency revoke form allowed a reason of 255 characters, and it allowed a NUL byte. The service then stores the text `EMERGENCY: ` (11 characters) plus that reason in `revoke_reason`, a 255 character column. A 255 character reason becomes 266 characters. On Postgres that write fails and the transaction rolls back, so the keys stay active and the refresh tokens stay usable. A NUL byte fails the same way. A one-key delete reason had no length cap, and a rotation reason could contain a NUL. Both of those columns are 255 characters as well (`revoke_reason` and `trigger_reason`).

How to reproduce. Build `EmergencyKeyRevocationRequest` with `reason` set to 245 `r` characters, or to a string containing a NUL byte. Before the fix both were accepted. `len("EMERGENCY: " + ("r" * 255))` is 266. `DELETE /v1/api-keys/{wallet_id}/{key_id}?reason=` with 256 `r` characters returned 204 and called the revoke service.

Root cause. `app/services/api_key_service.py` `emergency_revocation` assigned `f"EMERGENCY: {reason}"` inside the database session (the assignment is now line 805, and it uses a value checked at line 776). The form cap was `EmergencyKeyRevocationRequest.reason` in `app/schemas/billing.py` (now line 1005). The delete query had no max length in `app/routers/api_keys.py` `revoke_api_key`.

Fix. The caller-facing emergency reason is capped at 244 characters, so the stored value is at most 255. NUL bytes are rejected. `stored_revoke_reason` checks the composed value before any session is opened, and the delete route returns 422 for an over-long or NUL reason. A normal revoke or rotation reason may still be 255 characters.

Tests. `test_emergency_reason_must_fit_with_its_prefix`, `test_rotate_reason_rejects_nul_and_keeps_column_length`, `test_direct_key_helpers_reject_limits_and_revoke_reasons`, and `test_revoke_query_rejects_reason_longer_than_column`. On the old code the schema cases did not raise, the helper import failed, and the delete returned 204.

## High: key expiry and max uses accept a boolean and an unstorable number

What broke. JSON `true` became a 1 day expiry or a 1 use cap, because a boolean is a kind of integer and the parser treated it as 1. `expires_in_days` of 10 million passed the form and then `timedelta` raised `OverflowError`, which the route turns into a 500. `max_uses` above 2147483647 passed the form and does not fit the signed 32 bit integer column (a 500 on Postgres).

How to reproduce. `CreateAPIKeyRequest(wallet_id="wallet", expires_in_days=True)` was accepted as 1 day. `expires_in_days=10**7` and `max_uses=2**31` and `max_uses="2147483648"` were accepted. `expires_in_days="30"` and `" 30 "` were also accepted, and still are, because they are the same in-range number.

Root cause. `CreateAPIKeyRequest.expires_in_days` and `max_uses` in `app/schemas/billing.py` only required a number greater than 0. `APIKeyService.create_key` in `app/services/api_key_service.py` added `timedelta(days=expires_in_days)` with no upper bound (the guard is `validate_api_key_limits` at line 52, called before the wallet lookup).

Fix. Booleans are rejected before conversion. Expiry is capped at 2,000,000 days, which stays inside the year range `timedelta` can represent from 2026. Max uses is capped at 2147483647. A direct caller gets `ValueError` instead of `OverflowError`, before any database work. In-range numbers, including the string `"30"`, still work. A missing limit still means no expiry or no use cap.

Tests. `test_api_key_limits_reject_booleans_and_unstorable_bounds` and `test_direct_key_helpers_reject_limits_and_revoke_reasons`. The old schema did not raise. The helper did not exist yet.

## High: money fields turn true into 1 credit and accept amounts the column cannot keep

What broke. JSON `true` on a credit amount became 1.0. Dust such as `1e-9`, and a value such as `999999999999.99`, was accepted even though the money columns are `Numeric(20, 8)` and the stored float round trip would not keep that exact amount. The same hole was on sponsor initial credits, agent budget and refill amounts, child budget and max spend, service price, the retired top-up amount, and the local dev self-provision budget.

How to reproduce. `CreateAgentWalletRequest(..., budget_credits=True)` became 1.0. `budget_credits=1e-9` and `budget_credits=999999999999.99` were accepted. The same boolean was accepted for sponsor `initial_credits`, child `budget_credits`, `RegisterServiceRequest.credits_per_unit`, `TopUpRequest.amount_fiat`, and `SelfProvisionRequest.budget_credits`.

Root cause. Those fields were plain floats with only a range check, in `app/schemas/billing.py` and `app/routers/dev_keys.py` `SelfProvisionRequest`. Permit credits already called `credit_amount_fits_storage` in `app/core/credits.py`. These bodies did not. The shared guard is now `_BoundedMoneyRequest` at `app/schemas/billing.py` line 150.

Fix. A boolean is rejected before it can become 1. The number must pass `credit_amount_fits_storage`. Zero initial credits still work. A daily limit of 0 still means "spend nothing", and an omitted daily limit still means "no cap". The string `"10.5"` still works. The direct top-up route still returns 410 and does not mint credits. The amount is validated anyway so a later change cannot treat `true` as one unit of money.

Tests. `test_money_fields_reject_booleans_and_unstorable_amounts`. The old forms did not raise. Existing permit numeric tests and API key tests still passed after the change.

## High: text longer than the column, or a NUL byte, is accepted

What broke. These request strings were stored as given, with no length cap and no NUL rejection: sponsor email (255), agent id (100), child agent id (100), child task description (500), and permit recipient domain (255). Postgres rejects both an over-long string and a NUL byte, which becomes a 500. A permit write that fails this way can also leave the idempotency row stuck in progress. Justification is a text column, which still cannot hold a NUL. A tool name longer than 128 characters fits the permit JSON but not the later receipt `tool` column. An empty tool name was accepted.

How to reproduce. An email of 256 characters, or of 1,000,000 characters, was accepted. An agent id of 101 characters, a task description of 501, a recipient domain of 256, and `"a\x00b"` in those strings were accepted. `QuoteCreateRequest(tool="")` and a 129 character tool name were accepted.

Root cause. The request models in `app/schemas/billing.py` and `app/schemas/trust.py` did not set `max_length` to the column size, and nothing searched for `"\x00"`. Column sizes are on `WalletModel`, `PermitModel`, `QuoteModel`, and `ReceiptModel` in `app/db/models.py`.

Fix. Each of those fields is capped at its column size and rejects NUL. Wallet ids and key ids that are looked up in a 50 character column are capped at 50. Tool names must be 1 to 128 characters. Empty email and empty key name stay allowed. A normal 255 character email, 100 character agent id, 500 character task, and 255 character domain still pass. A wallet id longer than 50 used to fail later as "not found" and is now a 422. No test in the suite used an id that long.

Tests. `test_stored_strings_reject_column_overflow_and_nul` and `test_tool_names_match_receipt_column`. The old forms did not raise.

## High: a forbidden argument name can be spelled so the denylist misses it

What broke. The forbidden-field check compared dictionary keys as exact strings. The same name written with the accent as a separate character did not match the composed name on the denylist. A fullwidth spelling of `password` missed too. The check walks nested objects, but only when the spelling is identical.

How to reproduce. `_find_forbidden_field({"cafe\u0301": "x"}, {"caf\u00e9"})` returned `None`. The fullwidth letters for `password` also returned `None`. A nested copy of the decomposed name also returned `None`.

Root cause. `app/services/permits.py` `_find_forbidden_field` (line 192) used `key in forbidden`.

Fix. Keys are compared after NFKC normalization, and the original key is what gets reported. The signed permit body is not rewritten. Letters from another script are not folded: a Greek omicron inside `token` still does not count as Latin `token`. That matches the existing fuzz test, which requires the lookalike call to succeed. Forbidden names on a new permit are also capped at 256 characters and cannot contain NUL, so a signed permit cannot carry a megabyte field name.

Tests. `test_forbidden_field_match_folds_compatible_unicode_only` failed on the old code (`None` instead of the decomposed key) and passed after. `tests/test_security_fuzz_battery.py::test_forbidden_fields_with_unicode_injection_denied` still passed: the Greek lookalike is allowed, and a real `token` key is denied.

## Medium: deeply nested action arguments can crash the checker

What broke. Action arguments are walked by a recursive function. A chain on the order of a thousand nested objects raises `RecursionError` instead of a validation error. A separate signing helper, `canonical_json` in `app/services/signing_keys.py`, has the same shape. A probe in this task saw that helper raise `RecursionError` around depth 1200. `json.dumps` of that same depth did not crash, so metadata and the service manifest were not treated as this bug.

How to reproduce. `ActionPermitCreateRequest` with arguments nested 40 levels was accepted. Calling `_strict_json` on that object did not raise. Depth 40 is deep enough to prove the missing cap, and shallow enough to keep the suite from crashing the interpreter.

Root cause. `app/services/action_permits.py` `_strict_json` (line 83) recurses into every nested list and object. The request field had no depth limit.

Fix. Nesting deeper than 32 levels is rejected in the schema and at the start of `_strict_json`. The depth check uses its own stack, so a hostile payload cannot crash the check. Depth 32 is still accepted. Depth 40 raises `json_too_deep`. Signed payloads are not rewritten.

Tests. `test_action_arguments_reject_deep_nesting`. The old schema did not raise.

## Medium: a permit verify estimate can be a value the credit column cannot store

What broke. `PermitVerifyRequest.estimated_credits` accepted a ninth decimal place and a negative number. Permit credit columns keep 8 decimal places. An estimate the column would change should not be used. An omitted estimate, and an estimate of zero, are real and must stay valid.

How to reproduce. `estimated_credits="0.123456789"` and `estimated_credits=-1` were accepted. `true` was already rejected. `0`, `None`, and `"1.5"` were accepted and still are.

Root cause. `app/schemas/trust.py` `PermitVerifyRequest.estimated_credits` (now line 313) was an unconstrained decimal. The permit create type rejects zero, so verify could not reuse it.

Fix. `None` and zero pass. Anything `credit_amount_fits_storage` rejects, including negatives and a ninth decimal, is a validation error.

Tests. `test_verify_estimate_rejects_scale_the_column_cannot_keep`. The old schema did not raise for the dust value.

## Medium: the same recipient host in two Unicode spellings does not match

What broke. A permit bound to a host written with a composed accent did not match that same host when the URL used a base letter plus a separate accent. The check failed closed: the call was denied. This is not a bypass. It rejects a recipient the permit was meant to allow.

How to reproduce. `recipient_binding_matches("caf\u00e9.example", "https://cafe\u0301.example/pay")` was `False`. The same pair of spellings as bare hosts was also `False`.

Root cause. `app/services/permits.py` `recipient_binding_matches` (line 231) compared the strings exactly after taking the URL hostname.

Fix. Both sides are compared in NFC, so composed and decomposed forms of the same host match. NFKC is not used here, so a lookalike letter is not treated as the allowed host. ASCII hosts and chain addresses are unchanged.

Tests. `test_recipient_binding_matches_equivalent_unicode_hosts` failed on the old code (`False` instead of `True`) and passed after. `tests/test_x402.py::test_recipient_binding_matches_addresses_and_hosts` still passed.

## Checked, and not a break

Required nulls on these forms were already rejected. The test `test_required_permit_fields_still_reject_null` passed before any fix.

An extra `balance` field on sponsor create is ignored and does not set the balance. That test passed before any fix.

Numeric strings that are the same in-range number (`"30"` days, `"10.5"` credits, `" 30 "` days) are still accepted. Rejecting them would break clients that send numbers as strings.

Child wallet time-to-live already rejected a boolean. The string `"10"` still becomes 10 seconds. That behavior was left as it is.

`requires_human_approval` already parses `"yes"`, `"no"`, `"true"`, and `"false"`, and it already rejects `"nope"`. That field was not changed. The earlier probe in this task confirmed it. It was not re-run after the fix.

Sponsor `currency` is not stored on the wallet. A huge currency string is waste, not a column overflow. No migration was added to store it.

`POST` top-up still returns 410 and does not add credits. `payment_method` is not written into a short column.

A 1 megabyte `key_name` was already rejected by the existing 50 character cap.

Metadata and `mcp_manifest` were not depth-capped. The probe's `json.dumps` of a 1200-deep object did not crash. `canonical_json` can still recurse if some other caller hands it a deep object that did not come through the action-argument form.

## Tests

New file: `tests/test_request_body_boundaries.py`.

Confirmed the new tests fail on the old code, before any product edit:

```
~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_request_body_boundaries.py --tb=line
```

Result: 12 failed, 3 passed, 1 warning, in 0.68s. The failures were `Failed: DID NOT RAISE ValidationError` (emergency reason, rotation NUL, key limits, money, over-long strings, tool names, verify dust, deep arguments), `ImportError` for `stored_revoke_reason`, delete status 204 instead of 422, forbidden-field `None` instead of the decomposed key, and recipient match `False` instead of `True`. The 3 passes were the cases that were already correct: extra `balance` ignored, child time-to-live boolean rejected, required null rejected.

After the fix, one test helper was corrected so a 51 character wallet id is passed once. The old form had no max length, so that value was accepted. The assertion is in the passing run below.

```
~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_request_body_boundaries.py tests/test_permit_numeric_storage.py tests/test_billing_boundary_regressions.py tests/test_x402.py::test_recipient_binding_matches_addresses_and_hosts tests/test_wallet_status_enforcement.py::test_child_wallet_ttl_rejects_unsafe_values tests/test_security_fuzz_battery.py::test_forbidden_fields_with_unicode_injection_denied tests/test_api_keys.py -x --tb=short
```

Result: 147 passed, 1 warning, in 2.77s. The warning is the existing Starlette note about `httpx` and `TestClient`.

```
.venv/bin/ruff check app/schemas/request_bounds.py app/schemas/billing.py app/schemas/trust.py app/services/api_key_service.py app/services/permits.py app/services/action_permits.py app/routers/api_keys.py app/routers/dev_keys.py tests/test_request_body_boundaries.py
.venv/bin/ruff format --check <same files>
```

Result: all checks passed, 9 files already formatted.

```
~/metacode/fleet/heavy .venv/bin/python scripts/export_openapi.py
~/metacode/fleet/heavy .venv/bin/python scripts/export_openapi.py --check
```

Result: wrote `docs/openapi.json`, then `--check` reported that the file matches `app.openapi()`.

Not run: the full pytest suite, and any test against Postgres. No fix was backed out.

## Open questions

Should numbers sent as strings (`"30"`, `"10.5"`) be rejected? They convert to the same in-range value. Rejecting them would be a breaking API change. They were left accepted.

Should a Greek lookalike of `token` be treated as the forbidden word `token`? The current fuzz test says no. Doing that needs a confusable-character list and a product decision. NFKC does not do that, and this change does not either.

Should sponsor `currency` be stored? It is accepted and ignored today. Storing it needs a migration. None was added.

`canonical_json` is still recursive for callers that do not pass through the action-argument cap. This change does not rewrite signed payloads. A follow-up can put the same depth cap in front of that helper if a real caller can still reach it with a deep object.
