# Permit validation rerun — 2026-08-25

An earlier validation bundle scored **PARTIAL PASS**. The accounting chain held
(one receipt, one debit, receipt and ledger naming the same `ledger_entry_id`),
but four claims were not actually exercised:

1. `POST /v1/permits/verify` answered `valid:false` / `permit_wallet_mismatch`
   for a permit that was plainly active and in scope.
2. Both the "first" call and its replay returned `idempotency_key_reused` —
   `echo-test-1` had been spent in an earlier run, so no fresh success was
   captured beside its replay.
3. The out-of-scope test invoked `partner.search`, which is not registered.
   `Tool not found` proves the registry rejects unknown names; it does not
   prove permit scope.
4. The bundle carried a signature and a public key but no `signing_input`, so
   the Ed25519 signature could not be checked independently.

This rerun closes all four. It runs against a local quickstart-posture server
(`make quickstart`), as a **self-provisioned non-admin caller** — no operator
key, no pre-shared secret.

## How to reproduce

```bash
make quickstart                        # terminal 1
make live-loop-proof                   # terminal 2
```

## Result — run `9ec7bac04aa9`, 2026-08-25T10:23:08Z

| Claim | Result | Evidence |
|-------|--------|----------|
| Live trust key published | PASS | `trust-keys.json`, kid `quickstart-local-ed25519`, fetched unauthenticated |
| Active permit metadata | PASS | `permit-e1bdd6fbc8fb49c9`, 10-credit cap, one allowed tool |
| Permit verification endpoint | PASS | `verify-permit` stage: `valid:true` for the granted action |
| One successful governed transaction | PASS | `rcpt-7556fd73343c4671`, outcome `success`, 2.00000000 credits |
| Exactly one debit | PASS | ledger entry `34b65478…`, `-2.0`, `balance_after` 998.0 |
| Fresh call then immediate replay | PASS | replay returned the **same** receipt id, no second debit |
| Reused idempotency key adds no debit | PASS | same stage — debit count before == after |
| Out-of-scope permit denial | PASS | `permit_tool_not_allowed` against a **registered** tool |
| Receipt ↔ ledger linkage | PASS | receipt's `ledger_entry_id` present exactly once in the wallet ledger |
| Offline Ed25519 verification | PASS | `signing_input` exported; verifier exits 0, exits 1 on a tampered byte |
| Audit chain | PASS | `/v1/audit/verify-chain` valid, 1 event checked |

Every stage is asserted, not printed: the run exits non-zero the moment an
invariant breaks.

## What was wrong with claim 1

`POST /v1/permits/verify` decides an **action**, not a permit's health. Asked
without `wallet_id` and `tool` it evaluated both as empty strings, so the
subject-wallet binding check failed first and the answer came back
`permit_wallet_mismatch` — which reads as "this permit is not yours" to the
permit's own subject. The permit was fine; the question was incomplete.

Observed against the running server, same permit, four ways:

| Request | Verdict |
|---------|---------|
| `{permit_id}` only | `valid:false`, `permit_verify_context_missing`, `missing: [wallet_id, tool]` |
| `+ wallet_id` | `valid:false`, `permit_verify_context_missing`, `missing: [tool]` |
| `+ wallet_id, tool, estimated_credits` | `valid:true` |
| out-of-scope `tool` | `valid:false`, `permit_tool_not_allowed` |

The reason string is the change shipped alongside this rerun; the admission
logic is unchanged, as is the 403 that stops an unrelated caller reading a
permit by id.

## Scope of this certification

This is a certification of the **code path**, driven over real HTTP against a
real server, not of the hosted production deployment. The quickstart posture
differs from production in exactly two ways that matter here: the signing key
is a local dev key, and dev-key self-provision is enabled (production-like
deployments refuse both at boot). Certifying the production origin requires a
run there with a credential this run deliberately does not need.
