# Accounting, money precision and durable ownership

Date: October 2, 2026 (America/Los_Angeles). Owner: root coordinator. Verification source: `f82700f750862b6e51566a46dfc559e5b81e0a95`.

All 15 ACCT findings and the overlapping SEC-009 numeric boundary have existing local corrections. This lane verified their fix ancestry and ran acceptance regressions from a separate AMW worktree. It did not change product behavior or execute payment/provider operations.

Related tracking: [parent #499](https://github.com/PetrefiedThunder/agent-middleware-api/issues/499), [backend charter #556](https://github.com/PetrefiedThunder/agent-middleware-api/issues/556). [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence, not a fixing PR. No remote fixing PR has been created.

## Fresh verification

| Batch | Result | Evidence |
| --- | --- | --- |
| Permit approval, permits, x402, Stripe concurrency, billing boundaries, schema boot, billing, ledger integrity | 264 passed in 10.31 seconds | [Log](evidence/accounting/focused.txt), [command and source](evidence/accounting/focused-result.json) |
| Signed quotes, price validation, migration interruption, profitability and numeric storage | 145 passed; one PostgreSQL opt-in skipped in 2.77 seconds | [Log](evidence/accounting/numeric-migration.txt), [command](evidence/accounting/numeric-migration-result.json) |
| Fresh PostgreSQL17 migration038 interruption/recovery, incompatible-schema refusal, upgrade through042 | 1 passed; the previous SQLite-batch skip is exercised here | [Log](evidence/accounting/postgres/dispatch.txt), [command](evidence/accounting/postgres/dispatch-result.json) |
| Fresh PostgreSQL17 approval row-lock wait crossing expiry | 1 passed; both competing claims expire without minting | [Log](evidence/accounting/postgres/permit.txt), [command](evidence/accounting/postgres/permit-result.json) |

PostgreSQL used two newly created task-only databases on loopback 127.0.0.1:55439 with ENVIRONMENT=test and repository target guards. No production credentials were read. The benign asyncpg warning reports that /dev/null is not a regular password file; tests passed without passwords. Database service shutdown is recorded in the final coordinator report.

The recovered prior exact-SHA evidence separately records PostgreSQL accounting 12, multiprocess 10 and migration 1 passing. Those historical outputs are not added to fresh totals. Counts across all lanes and the aggregate suite overlap.

## Per-issue acceptance mapping

### ACCT-001 — Accepted sub-credit tool prices produce unverifiable quotes and receipts

[Issue #502](https://github.com/PetrefiedThunder/agent-middleware-api/issues/502) · P2 · **local_fixed**.

**Correction:** Reject unsupported precision before signing/pricing and preserve exact stored credit amounts.

**Local fix/follow-ups:** `d978982c615d84a5c597c350c47f3d823eadeef0`, `0620f6f45ea5c272f6c5819d4d86527c16e1ee0d`.

**Regression source:** [tests/test_signed_quotes.py](../../tests/test_signed_quotes.py), [tests/test_tool_price_validation.py](../../tests/test_tool_price_validation.py), [tests/test_upstream_mcp.py](../../tests/test_upstream_mcp.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### ACCT-002 — New client request keys can reuse one human approval to mint additional permits

[Issue #500](https://github.com/PetrefiedThunder/agent-middleware-api/issues/500) · P1 · **local_fixed**.

**Correction:** Bind the provider approval identity to the logical local request; a new client key cannot reuse one approval to mint another permit.

**Local fix/follow-ups:** `ee54ae16e635e6a4c66dc73f57db1a5539514619`.

**Regression source:** [tests/test_permit_request_flow.py](../../tests/test_permit_request_flow.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### ACCT-003 — Permit-request approval can cross its local deadline while polling and still mint

[Issue #501](https://github.com/PetrefiedThunder/agent-middleware-api/issues/501) · P2 · **local_fixed**.

**Correction:** Recheck approval expiry through polling and transaction contention; roll back mint claims crossing the deadline.

**Local fix/follow-ups:** `ee54ae16e635e6a4c66dc73f57db1a5539514619`, `0e2d2f1c92909fb3db9eee6e8f275d960ed6936d`.

**Regression source:** [tests/test_permit_postgres_concurrency.py](../../tests/test_permit_postgres_concurrency.py), [tests/test_permit_request_flow.py](../../tests/test_permit_request_flow.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### ACCT-004 — Startup schema verification misses every required single-action column

[Issue #520](https://github.com/PetrefiedThunder/agent-middleware-api/issues/520) · P2 · **local_fixed**.

**Correction:** Startup validates all required action-binding columns rather than only table presence.

**Local fix/follow-ups:** `ea73b3c76491aa6e64dc3aaa9e29f0fe770fb792`.

**Regression source:** [tests/test_schema_boot.py](../../tests/test_schema_boot.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### ACCT-005 — Concurrent Stripe top-ups lose settled credits on SQLite

[Issue #521](https://github.com/PetrefiedThunder/agent-middleware-api/issues/521) · P2 · **local_fixed**.

**Correction:** Apply settled Stripe top-up credits atomically so concurrent SQLite updates do not lose credits.

**Local fix/follow-ups:** `1cd4d0c31ed2873f370b65f20d6a52fc3af30e6d`.

**Regression source:** [tests/test_stripe_accounting_concurrency.py](../../tests/test_stripe_accounting_concurrency.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### ACCT-006 — Concurrent Stripe cumulative refunds double-claw back on SQLite

[Issue #522](https://github.com/PetrefiedThunder/agent-middleware-api/issues/522) · P2 · **local_fixed**.

**Correction:** Serialize cumulative Stripe refund deltas and apply each newly observed amount once.

**Local fix/follow-ups:** `1cd4d0c31ed2873f370b65f20d6a52fc3af30e6d`.

**Regression source:** [tests/test_stripe_accounting_concurrency.py](../../tests/test_stripe_accounting_concurrency.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### ACCT-007 — PostgreSQL migration 038 cannot recover after concurrent-index interruption

[Issue #523](https://github.com/PetrefiedThunder/agent-middleware-api/issues/523) · P2 · **local_fixed**.

**Correction:** Recover interrupted PostgreSQL concurrent-index construction safely on migration 038 retry.

**Local fix/follow-ups:** `6387945279ac7254c672ff7010975f0de57f5cbd`.

**Regression source:** [tests/test_dispatch_call_slot_migration.py](../../tests/test_dispatch_call_slot_migration.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### ACCT-008 — Zero-price tools receive signed quotes but cannot execute

[Issue #539](https://github.com/PetrefiedThunder/agent-middleware-api/issues/539) · P2 · **local_fixed**.

**Correction:** Refuse unsupported zero-price governed quotes before issuing an unusable signed quote.

**Local fix/follow-ups:** `ef64d0291cbf50c8f00fbf5d2e4be22d2c781916`.

**Regression source:** [tests/test_tool_price_validation.py](../../tests/test_tool_price_validation.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### ACCT-009 — Terminal billing-policy denial leaves its idempotency key in progress

[Issue #541](https://github.com/PetrefiedThunder/agent-middleware-api/issues/541) · P2 · **local_fixed**.

**Correction:** Complete/release keyed terminal billing denial correctly instead of leaving the key in progress.

**Local fix/follow-ups:** `edfd71a8088cc1aabaa42ba88a1fba94e46a3eec`.

**Regression source:** [tests/test_billing_boundary_regressions.py](../../tests/test_billing_boundary_regressions.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### ACCT-010 — Keyed billing charge for unknown wallet returns500 instead of404

[Issue #542](https://github.com/PetrefiedThunder/agent-middleware-api/issues/542) · P2 · **local_fixed**.

**Correction:** Preserve the unknown-wallet 404 at the keyed billing boundary instead of converting it to 500.

**Local fix/follow-ups:** `edfd71a8088cc1aabaa42ba88a1fba94e46a3eec`.

**Regression source:** [tests/test_billing_boundary_regressions.py](../../tests/test_billing_boundary_regressions.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### ACCT-011 — Ledger period exact totals are calculated from binary floats

[Issue #543](https://github.com/PetrefiedThunder/agent-middleware-api/issues/543) · P3 · **local_fixed**.

**Correction:** Calculate exact ledger period totals with decimal arithmetic rather than binary floats.

**Local fix/follow-ups:** `edfd71a8088cc1aabaa42ba88a1fba94e46a3eec`.

**Regression source:** [tests/test_billing_boundary_regressions.py](../../tests/test_billing_boundary_regressions.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### ACCT-012 — Wallet-scoped credentials can read global profitability and other tenants' ledger details

[Issue #557](https://github.com/PetrefiedThunder/agent-middleware-api/issues/557) · P2 · **local_fixed**.

**Correction:** Require administrator authority for global profitability and cross-tenant ledger detail.

**Local fix/follow-ups:** `d446f0b554307040654526f318699873d1b2e305`.

**Regression source:** [tests/test_arbitrage_regressions.py](../../tests/test_arbitrage_regressions.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### ACCT-013 — Profitability report labels all-history totals as a one-day period

[Issue #558](https://github.com/PetrefiedThunder/agent-middleware-api/issues/558) · P3 · **local_fixed**.

**Correction:** Restrict profitability rows and totals to the stated report interval.

**Local fix/follow-ups:** `d446f0b554307040654526f318699873d1b2e305`.

**Regression source:** [tests/test_arbitrage_regressions.py](../../tests/test_arbitrage_regressions.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### ACCT-014 — Receiptless x402 crash recovery consumes permit budget twice

[Issue #559](https://github.com/PetrefiedThunder/agent-middleware-api/issues/559) · P2 · **local_fixed**.

**Correction:** Retain ambiguous receiptless x402 owners and reservations for review; recovery cannot consume authority twice.

**Local fix/follow-ups:** `2cc557d69172df14d369167899fb81e50adcdda7`.

**Regression source:** [tests/test_x402.py](../../tests/test_x402.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### ACCT-015 — Failed x402 compensation releases the accepted request owner

[Issue #585](https://github.com/PetrefiedThunder/agent-middleware-api/issues/585) · P2 · **local_fixed**.

**Correction:** Retain x402 request ownership when settlement compensation is uncertain or incomplete; do not release authority for another retry.

**Local fix/follow-ups:** `d9275789138a1f22e3adb9c62a1e6868f3dce650`, `9d8c962301a35705c184534979ec7f8c06da9af0`.

**Regression source:** [tests/test_x402.py](../../tests/test_x402.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

### SEC-009 — SQLite permit issuance signs values that change during persistence

[Issue #584](https://github.com/PetrefiedThunder/agent-middleware-api/issues/584) · P2 · **local_fixed**.

**Correction:** Reject permit max_credits/aggregate caps that cannot survive exact storage before signing; preserve the numeric bounds in generated schemas.

**Local fix/follow-ups:** `f27c213cd2e48c2fd1c9927a8fea85d4af5479ee`, `34040b3ad1e574445ad1ead70622967b58e3240a`.

**Regression source:** [tests/test_permit_numeric_storage.py](../../tests/test_permit_numeric_storage.py), [tests/test_permit_request_flow.py](../../tests/test_permit_request_flow.py), [tests/test_permits.py](../../tests/test_permits.py).

**Original failure / historical review:** preserved in [complete finding register](issue-index.md) and [machine ledger](issue-ledger.json). Each commit resolves as an ancestor of the recovered integration.

## Remaining risk and untested scope

- Stripe/x402 tests use synthetic local settlement, not real payment rails. Dormant routes retain their enablement gates.
- The PostgreSQL work is targeted proof for migrations038/042 and approval timing, not an every-migration downgrade audit or a live production rehearsal.
- Ambiguous x402 receipt/compensation paths deliberately retain ownership for manual review; operators still require reconciliation procedures.
- Hosted CI, deployment identity, external provider behavior and independent customer receipt verification remain unverified for unpublished repairs.

