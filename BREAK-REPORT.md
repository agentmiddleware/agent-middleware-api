# Wallet break-it report

## Summary

Breaks found: 3. Fixed and tested: 3. Fixed but failing: 0. Blocked: 0.

Five other attacks were tried and did not break the product: a negative or zero transfer on the HTTP route, a transfer to the same wallet, two concurrent debits of one balance, spending from a frozen wallet, and a reused transfer idempotency key pointed at a different destination. A transfer with no key, an unknown key, or a key for a different wallet was also refused and did not move money.

## Findings

### 1. High: a transfer the ledger cannot store was marked completed

What broke: A transfer of 0.000000001 credits returned HTTP 200 with status completed. The receipt said the amount was 1e-09, while the stored balances stayed at the amounts from before the transfer (40 and 10). A sponsor wallet opened with initial credits of 1e-9 also returned HTTP 201 and created a wallet. NaN and Infinity, sent straight to the engine, raised decimal.InvalidOperation instead of a normal rejection. That exception would surface as HTTP 500 if a caller reached the engine with those values. The public transfer query already blocks NaN.

How to reproduce: Create two funded agent wallets on the local test app. POST /v1/billing/transfer with amount 0.000000001. Separately, POST /v1/billing/wallets/sponsor with initial_credits 1e-9. Separately, call the engine transfer with Decimal("NaN") or Decimal("Infinity").

Root cause: app/services/wallet_engine.py:928. Before this change the transfer only checked that the amount was greater than zero, then stored it. A NaN comparison raised decimal.InvalidOperation at the pre-fix line wallet_engine.py:867. Amounts such as 0.000000001 and 999999999999.99 pass a greater-than-zero check and the HTTP cap below 1e12, but SQLite binds the decimal through a float and reads back a different number. Sponsor credits were written with no storage check at app/services/wallet_engine.py:390.

Fix: After the existing "amount must be positive" check, refuse any amount that credit_amount_fits_storage rejects. The same check runs for sponsor opening credits, agent budgets, child budgets, and the related limit fields. The HTTP schemas reject those amounts with 422 before a sponsor route, which does not catch ValueError, can turn them into a 500. A dust or overscale transfer is a 400 from the existing transfer error path. 1e12 and above stay 422 from the existing query cap.

Tests: On the old code, tests/test_wallet_breakit.py failed this case with the completed receipt above, and the engine case failed with decimal.InvalidOperation. After the fix the file passed (9 passed in 1.13s). See Tests below.

### 2. High: a sponsor wallet could open with a negative balance

What broke: Calling the wallet engine with initial_credits of -20 created a sponsor wallet. The balance was negative, and no ledger row was written, because the ledger insert only runs when the amount is greater than zero. The HTTP route already rejected a negative body with 422, so this hole was the in-process engine used by pods and dev-key self-provision.

How to reproduce: On the local test app, call create_sponsor_wallet with initial_credits=Decimal("-20"). Before the fix the call returned a wallet and pytest.raises(ValueError) did not fire.

Root cause: app/services/wallet_engine.py:390 sets balance and lifetime_credits from initial_credits with no sign check. app/services/wallet_engine.py:406 writes the opening ledger row only when initial_credits > 0. A negative amount therefore sat on the wallet with nothing in the ledger. The balance guard used on later debits (balance >= amount) is also true for every negative amount, so a negative debit would add credits.

Fix: app/services/wallet_engine.py:333 checks the amount before any session opens. A finite negative amount raises ValueError ("initial_credits cannot be negative"). Zero is still allowed. Agent and child budgets keep their existing "cannot be negative" errors, and a non-finite budget is rejected before that comparison so NaN cannot raise InvalidOperation.

Tests: On the old code, test_negative_and_unstorable_sponsor_credits_are_refused failed with "Failed: DID NOT RAISE ValueError" (1 failed in 1.02s). After the fix it passes inside the 9 passed run.

### 3. High: a blank or foreign currency still minted credits

What broke: Creating a sponsor wallet with currency "" returned HTTP 201 and created wallet spn-909acf82ef53. Spaces, EUR, US, and usd1 were accepted the same way. The wallet table has no currency column, so those credits were stored as the same unit as USD and could be spent like any other credits.

How to reproduce: POST /v1/billing/wallets/sponsor with initial_credits 50 and currency set to an empty string, or to EUR. Before the fix the response was 201 and a wallet row existed.

Root cause: app/services/wallet_engine.py:375 accepts currency in _create_sponsor_wallet_in and never reads it. The request schema defaulted currency to USD and did not check the value. Stripe top-up already rejects a non-USD currency, but wallet creation did not.

Fix: supported_wallet_currency in app/core/credits.py:21 accepts only USD, after trimming spaces and ignoring letter case. The sponsor schema calls it (HTTP 422) and create_sponsor_wallet calls it before any insert (ValueError). "usd" and " USD " still succeed and are stored as the normal credit balance. No currency column was added.

Tests: On the old code, test_missing_or_foreign_currency_does_not_mint_credits failed because blank currency returned 201. After the fix it passes inside the 9 passed run.

## Attacks that held

Negative and zero HTTP transfers return 422 and leave the balance unchanged. A transfer to the same wallet returns 400. These passed on the old code.

Two concurrent transfers of the full balance, and two concurrent platform-fee charges of the full remaining balance, did not drive a wallet below zero. One transfer succeeded, the source ended at 0, and the two destinations conserved the credits. The fee wallet ended at 0. This passed on the old code after the test wallets were given a starting budget of 1. A budget of 0 is already rejected by the HTTP agent schema, which was a test fixture mistake, not a product bug.

A frozen source cannot transfer (HTTP 400) or be charged (HTTP 403). Balances stay put. This passed on the old code.

The same Idempotency-Key with a different destination returns 409 and does not move money again. Replaying the original destination returns 200. The source, the first destination, and the untouched destination match a single transfer. This passed on the old code.

A transfer with no API key returns 401. An unknown key, and a key that belongs to the destination wallet rather than the source, return 403. Balances stay put. This passed after the fix (it does not depend on the amount or currency change).

## Tests

New file: tests/test_wallet_breakit.py. tests/conftest.py lists that module so the dormant transfer route is mounted in tests.

Confirmed on the old code, before the product change:

- `~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_wallet_breakit.py --tb=line` ended "6 failed, 2 passed in 1.53s". Real failures: InvalidOperation at wallet_engine.py:867, dust transfer HTTP 200 with amount 1e-09 and status completed, blank currency HTTP 201 (wallet spn-909acf82ef53), and initial_credits 1e-9 HTTP 201 (wallet spn-581a42870a2d). The other two failures were the zero-budget fixture described above.
- `~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_wallet_breakit.py::test_negative_and_unstorable_sponsor_credits_are_refused --tb=short` ended "Failed: DID NOT RAISE ValueError" and "1 failed in 1.02s".
- The concurrent-debit and reused-key tests, re-run alone on the old code after the fixture correction, ended "2 passed in 1.34s".

After the fix:

- `~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_wallet_breakit.py --tb=short` ended "9 passed in 1.13s".
- `~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_transfers.py tests/test_wallet_concurrency.py tests/test_wallet_status_enforcement.py tests/test_wallet_ledger_integrity.py tests/test_swarm_wallets.py tests/test_pods.py tests/test_wallet_spendable_status.py -x --tb=line` ended "94 passed in 3.07s".
- `~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_billing.py tests/test_idempotency.py -x --tb=line` ended "81 passed in 2.23s".
- `~/metacode/fleet/heavy .venv/bin/ruff check app/core/credits.py app/services/wallet_engine.py app/schemas/billing.py tests/test_wallet_breakit.py tests/conftest.py` ended "All checks passed!".

The full suite was not run. The change is limited to wallet amount and currency checks, the suites above cover those routes, and this machine is shared by the fleet.

Local SQLite only, through the existing test fixture. No Postgres database was created. No production URL was called.

## Open questions

A transfer into a frozen wallet is still allowed. The code checks the source status (app/services/wallet_engine.py:952) and does not check the destination status before crediting it (app/services/wallet_engine.py:997). That looks intentional, so a refund can land while spending is blocked. It was not changed.

Currency is rejected instead of stored. Adding a currency column would be a migration and a product decision. Clients that previously sent EUR now get 422 and no wallet.

Some numbers that look like they have at most 8 decimal places are refused because they do not survive the float bind SQLite uses. 999999999999.99 is under the 1e12 cap and is refused. Ordinary 8-decimal values such as 0.16666666 still pass.

correlation_id is not part of the transfer idempotency hash (app/routers/billing.py:1040). A retry with the same key, wallets, and amount replays the first receipt even if correlation_id differs. Money is not moved a second time. A different destination with the same key returns 409. The hash was not changed.
