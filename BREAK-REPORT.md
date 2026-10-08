# Break report: money idempotency

3 breaks found. 3 fixed and tested. 0 fixed but still failing. 0 blocked.

Local sqlite tests only. No production calls, no migrations.

## High: a bad Idempotency-Key still moved money

What broke. On charge, transfer, agent-wallet funding, and x402 settle, a present but unusable Idempotency-Key was treated as a real key or ignored. An empty key, a key of only spaces, a key longer than 128 characters, a key containing a control character, and a key that is not UTF-8 still debited, moved credits, funded a wallet, or reserved permit budget. Two different Idempotency-Key lines used the first line only, so a later call that sent only the second line could charge again. A valid UTF-8 key was stored as the latin-1 reading of those bytes (`cafÃ©-charge-1` instead of `café-charge-1`).

How to reproduce. Against the local test app, POST the route twice with `Idempotency-Key: ""`, with 129 `x` characters, with a NUL or DEL in the key, with the single byte `0xE9`, or with two different Idempotency-Key lines. Before the fix the response was HTTP 200 or 201 and the balance or permit budget changed. Covered by `tests/test_money_idempotency_adversarial.py`.

Root cause. Charge used a truthiness check, so an empty string skipped the record and charged again (`app/routers/billing.py`, pre-fix line 647, `if idempotency_key:`). Transfer and agent-wallet funding used the same check in `app/routers/http_idempotency.py` (pre-fix line 69, `if not idempotency_key:`). x402 settle required the header but did not check its value (`app/routers/x402.py`, pre-fix line 152) and then reserved budget. Each route also declared the header as one string, so FastAPI kept only the first line. None of these routes decoded the header as UTF-8 before storing it.

Fix. `resolve_idempotency_header` in `app/services/idempotency.py:268` applies the existing key rules and UTF-8 decode. `resolve_http_idempotency_header` in `app/routers/http_idempotency.py:63` turns a bad key into HTTP 400 `invalid_idempotency_key` before money moves. Charge calls it at `app/routers/billing.py:622`. Transfer and agent-wallet funding go through `begin_http_idempotency`. x402 settle calls it at `app/routers/x402.py:163`, before reservation. Those routes now take every header line. A missing header on charge and transfer is still an unkeyed call. A missing x402 header is still HTTP 422.

Tests. Before any product change, `~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_money_idempotency_adversarial.py --tb=line -p no:cacheprovider` finished with 24 failed, 9 passed. The failures were HTTP 200 or 201 plus a debit, transfer, funded wallet, or settlement. After the fix that file passed 33 tests. The UTF-8 case was rewritten to send raw bytes, because httpx rejects a non-ASCII string header before the request leaves the client. With decoding removed, that test failed: the stored key was `cafÃ©-charge-1`, not `café-charge-1`. Decoding was restored and the test passed.

## Medium: a transfer retry did not return the first receipt body

What broke. The same Idempotency-Key and the same transfer arguments returned one transfer, but the retry body used strings (`"4975.00000000"`) where the first body used numbers (`4975.0`).

How to reproduce. POST `/v1/billing/transfer` twice with the same key, wallets, and amount. Compare the two JSON bodies.

Root cause. `IdempotencyService.complete` stores the dict with `json.dumps(..., default=str)` (`app/services/idempotency.py`, pre-fix lines 798-799). The transfer engine returns Decimals, so those became strings. The first response is encoded by FastAPI as numbers.

Fix. The transfer route encodes the body the way the live response does, stores that body, and returns it (`app/routers/billing.py:1078`). `complete` itself was left alone so other callers keep their current stored shape.

Tests. On the unfixed code, `test_transfer_same_key_replays_and_different_args_conflict` failed the full JSON comparison with those string and number differences. After the fix the two bodies match, and the billing retry test still shows a single transfer.

## Medium: a different transfer correlation id reused the key

What broke. `correlation_id` is stored on the transfer, but it was not part of the idempotency comparison. The same key with a different correlation id returned the first transfer instead of HTTP 409 `idempotency_key_reused`. Money was not moved a second time. The second correlation id was ignored.

How to reproduce. POST `/v1/billing/transfer` with `correlation_id=corr-1`, then again with the same Idempotency-Key and `correlation_id=corr-2`.

Root cause. The transfer fingerprint in `app/routers/billing.py` (pre-fix lines 1040-1045) omitted `correlation_id`.

Fix. `correlation_id` is now included (`app/routers/billing.py:1049`). The same key and the same correlation id, including both calls omitting it, still replay.

Tests. With that field temporarily removed, `test_transfer_same_key_replays_and_different_args_conflict` returned HTTP 200 and the first `transfer_id` where it expected 409. The field was put back. The existing retry test, which sends no correlation id, still passes and moves credits once.

## Checked, not a break

- Charge and transfer without an Idempotency-Key are still unkeyed. Each call is a new debit or transfer. Direct top-up returns HTTP 410 and does not mint, with or without a key.
- x402 without the header returns HTTP 422.
- Six concurrent charges with the same key produced one debit before the fix and still do.
- A 128-character key replays. `"k"`, `" k"`, and `"k "` stay three different keys.
- `tests/test_delivery_uncertain_replay.py` passed. `delivery_uncertain` stays charged and is not redispatched. The duplicate-guard default was not changed.
- Same key and different charge units still return `idempotency_key_reused`. Same key and a different x402 amount still return that error as a string detail.

## Tests run after the fix

- `~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_money_idempotency_adversarial.py --tb=line -p no:cacheprovider`: 33 passed.
- Broader run, 106 passed in 4.73s: that adversarial file, `tests/test_idempotency.py`, the billing charge, transfer, top-up, and agent-wallet idempotency tests, three API-key idempotency tests, `tests/test_x402.py`, `tests/test_delivery_uncertain_replay.py`, and `tests/test_python_sdk_trust_loop.py::test_python_sdk_charge_idempotency_key_debits_once`.
- After the correlation-id check was restored, the adversarial file plus the three billing charge and transfer retry tests passed again: 36 passed. ruff on the touched files: all checks passed.

## Open questions

- `create_child_wallet` and `reclaim_child_wallet` move money and do not read an Idempotency-Key. Making a key required would be a product change, so they were left as they are.
- `prepare_top_up` was not called. It talks to Stripe and puts a new random id in PaymentIntent metadata. The direct top-up route stays disabled and was tested.
- If a charge debits and the process dies before the idempotency record is completed, a retry gets `idempotency_in_progress` and does not debit again. It also does not return the receipt until that record is completed. Not changed.
- API key create and rotate use the shared helper, so a blank, oversized, or non-UTF-8 Idempotency-Key on those routes is now HTTP 400. Their duplicate header lines still keep the first value, because those routes still take one string. `app/routers/api_keys.py` was not edited.
- A transfer retry that keeps the Idempotency-Key but sends a new correlation id now gets HTTP 409 instead of the original transfer.
