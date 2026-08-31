# Engineering acceptance update

Audit date: **2026-08-31**. Evidence cutoff: the accepted local packet under
`/tmp/amw-launch-20260831`, plus read-only current-source comparisons through
`2026-08-31T22:23:23Z`.

**Current disposition: the earlier PostgreSQL reliability hold is superseded
for the frozen local synthetic engineering packet. Program control accepted
G0-G5 after the default-pool and actual singleton-application-pool replacements
passed on one source manifest. Production readiness and G6 partner validation
remain unaccepted. The original working tree changed again during this audit,
so the frozen packet is accepted but the later current tree cannot inherit its
test status without a new source binding.**

This update supersedes the earlier hold language in this research directory's
`README.md`, `technical.md`, `technical-evidence.json`, and
`independent-review.md`. Those files correctly preserve what was known at their
earlier checkpoint; they are not the current engineering-gate record. The
authoritative current decision is [program control](../../aegis/work/2026-08-31-program-control/README.md),
supported by the [final runtime report](/tmp/amw-launch-20260831/reports/final-runtime.md).

## Execution ownership and evidence provenance

| Responsibility | Owner | What that owner did |
| --- | --- | --- |
| Gate and sequencing authority | Program task `01a056e3-c900-7bc0-a825-f402e12e46a7` | Accepted the bounded local gates and retained production/G6 as separate gates. |
| Application integration and runtime execution | Engineering task `01a056df-ba0b-7472-b6cc-747dccc8cdd9` root | Alone applied the engineering changes and ran the application, PostgreSQL, lint, type, and release-gate commands. Its specialists authored or reviewed bounded inputs; they did not independently execute the final application suites. |
| Independent fix review | Task `01a056e0-9564-7f80-b15b-a6a8d1323e47` | Approved the exact four production files, then the final source/test/runtime binding. It did not authorize deployment or customer-validation claims. |
| Final provenance audit | Task `01a04285-223e-7a31-ac23-96729c605928` root | Independently verified archive/original hashes and modes, command/log bindings, packet membership, dependency pins, application identity, and cleanup without reexecuting application tests. See its [final audit](/Users/sellers/.codex/visualizations/2026/08/27/01a04285-223e-7a31-ac23-96729c605928/engineering-provenance-2026-08-31.md). |
| This update | Delegated research acceptance audit | Read the accepted artifacts, compared current whitelisted source bytes, checked JSON/log/hash relationships, and wrote this report. It ran no application or database tests, opened no private environment file, and changed no application or test file. |

The root integrator's ten final executions therefore supply the runtime
observations. The independent reviewers supply source, method, and provenance
checks. This report does not present their overlapping work as independent
runtime replications.

## Exact source and application binding

The accepted manifest is
[`logs/acceptance-source-manifest.json`](/tmp/amw-launch-20260831/logs/acceptance-source-manifest.json),
SHA-256
`f0c7d4236ffc785ca98e002bc4ea3f1759c9d0cc30e972798f37c2a021b5c289`.
It identifies a dirty working tree on branch `codex/site-structured-data` over
HEAD `46d7310a3b771542dfb1fe874b5cff9d6bf137b2`; HEAD alone does not identify
the tested source.

The relevant counts have different meanings:

- **572 files** are in the accepted source whitelist.
- **22 paths** differ from the launch program's captured baseline because of
  this engineering task.
- **Seven paths** were applied in the final acceptance step: four production
  services and three tests. The
  [application record](/tmp/amw-launch-20260831/logs/acceptance-application.json)
  lists their exact preimage and tested hashes.
- **Four production files** received the narrow independent source approval:
  `app/services/signing_keys.py`, `app/services/permits.py`,
  `app/services/receipts.py`, and
  `app/services/refund_reconciliation.py`. The approval explicitly deferred
  whole-candidate and runtime acceptance to the later evidence.

The read-only drift checks hashed every listed path against its `tested_sha256`
value. At `22:13:47Z`, the original checkout and all four tested roots matched
all 572 entries. By `22:21:13Z`, concurrent changes had moved the original
checkout away from the accepted source; the four frozen tested roots remained
exact at `22:21:40Z`. The `22:23:23Z` closeout check reproduced the same 18
current-checkout mismatches:

| Compared root | Matching files | Missing | Mismatched |
| --- | ---: | ---: | ---: |
| Current original checkout, `/Users/sellers/Documents/GitHub/agent-middleware-api` | 554 | 0 | 18 |
| `/tmp/amw-launch-20260831/acceptance-sqlite` | 572 | 0 | 0 |
| `/tmp/amw-launch-20260831/acceptance-pg-reg` | 572 | 0 | 0 |
| `/tmp/amw-launch-20260831/acceptance-pg-crash` | 572 | 0 | 0 |
| `/tmp/amw-launch-20260831/acceptance-pg-poolone` | 572 | 0 | 0 |

The 18 current mismatches are exact and have unknown validation status in this
audit:

- `app/services/human_approval.py`
- `app/services/quotes.py`
- `app/services/receipts.py`
- `app/services/refund_reconciliation.py`
- `tests/support/mcp_remote_partner_app.py`
- `tests/test_accounting_input_validation.py`
- `tests/test_human_approval_gate.py`
- `tests/test_late_debit_reconciliation.py`
- `tests/test_mcp_dispatch_reconciliation.py`
- `tests/test_mcp_idempotency_validation.py`
- `tests/test_mcp_postgres_multiprocess.py`
- `tests/test_mcp_upstream_governed.py`
- `tests/test_permit_verification_sessions.py`
- `tests/test_refund_amount_evidence.py`
- `tests/test_security_fuzz_battery.py`
- `tests/test_signed_quotes.py`
- `tests/test_site_agent_interface.py`
- `tests/test_wedge_honesty.py`

The final source archive is `tested-source-acceptance.tar.gz`, SHA-256
`7459183a9d86a579e74a4d2c9b147c3fbea785d2f2a4f825c322c04f766f0ed5`.
The earlier provenance audit verified all 572 archive members against the
manifest and original checkout, including file modes and safe-path rules.

The [application record](/tmp/amw-launch-20260831/logs/acceptance-application.json)
also shows that the Git index digest was unchanged during the accepted apply:
before and after were
`e8e57c5e8c990f2b980d8fd6f66df36ba1c82e2e1513aa7ea0f8036135cbe771`.
That is a time-bounded provenance fact. At the current drift check, `.git/index`
instead hashed to
`a342662d1436fa2ce58b3418817148d7f4011f83d585fd82df44e4b7cdb32352`.
A second check five minutes later observed another index digest,
`3c22a4ca12e64241797ecd080d3983bd0fccc5b4992c626323f7f86870b5b6cf`.
The index was actively changing after acceptance; the later source check also
found the 18 working-tree mismatches above. Current summaries must not say the
index is unchanged or that the present working tree is the tested source.

## Failed evidence retained rather than rewritten

The accepted packet preserves the failure that created the earlier hold:

- [`final-postgres-rapidfire.log`](/tmp/amw-launch-20260831/logs/final-postgres-rapidfire.log),
  SHA-256
  `0e49ac5580f069e5c8c4690402429329e3bebc9118a42e712106a0b97bda045a`,
  records **one failed test and 13 warnings** in 32.32 seconds. The 20-call
  case encountered `QueuePool` size 5 plus overflow 10 exhaustion at the
  30-second timeout, then failed on the missing successful `data` envelope.
- [`baseline-postgres-rapidfire.log`](/tmp/amw-launch-20260831/logs/baseline-postgres-rapidfire.log),
  SHA-256
  `60a3efddb346dde6828c8c69e4d73048d114e537e1332e073855dc96deada8c5`,
  records the unchanged-baseline comparison with the same **one failed test and
  13 warnings** in 32.36 seconds. This established that the starvation defect
  predated the earlier v3 correctness changes.
- The v5 regression command also remains a failed historical run:
  [`closure-regressions.log`](/tmp/amw-launch-20260831/logs/closure-regressions.log),
  SHA-256
  `cc97cee6e549a8d524f3ed7137c1debc13dcb366650d74c31c78c5b5493afbab`,
  reports **80 passed test bodies and four teardown errors**, exit 1. The four
  errors were foreign-key cleanup failures and are not relabeled as assertion
  failures or a passing command.

V4's auxiliary one-connection engine and v5's monkeypatched factory remain
historical method evidence. Neither is substituted for the final actual
application-pool proof. Only `acceptance-*` receipts and logs describe the
accepted source.

## Replacement scenarios

The bounded production change reuses an active caller session for signing-key
lookups through permit, receipt, and refund verification. Pending-refund signing
prepares its operation key outside the financial transaction, with an advisory
preflight followed by locked revalidation. The accepted change did not increase
the pool, relax row-lock/serialization behavior, or weaken assertions.

### Default application pool, 20 calls plus exact replay

[`acceptance-default-pool-inspection.json`](/tmp/amw-launch-20260831/logs/acceptance-default-pool-inspection.json)
observed configured and actual pool size **5**, maximum overflow **10**, zero
checked-out connections, and zero database queries. It was a separate
read-only engine-construction check under the regression environment, not
instrumentation inside the pytest process.

The default-pool regression command then passed **65 selected cases**, exit 0,
with log SHA-256
`dcb7fef63e8247c1644d33615815053b7b457eb985934fa622358e2ee2c9eec5`.
Within that command,
`test_rapid_fire_invokes_all_accounted` issued 20 concurrent one-credit calls
and asserted:

- 20 successful responses, 20 unique receipt IDs, and 20 unique action-record
  IDs;
- wallet balance reduced by exactly 20 credits, permit spend exactly 20,
  exactly 20 one-credit debits, and exactly 20 linked receipts/records;
- 20 exact replays returned the original results; and
- replay left debit IDs and all persisted accounting unchanged.

Those assertions and the passing bound command clear the reproduced bounded
pool-starvation case. They do not prove arbitrary concurrency, throughput, or
every scheduler interleaving.

### Actual singleton application pool

The singleton command set `DB_POOL_SIZE=1` and `DB_MAX_OVERFLOW=0` before
application import and used the real application engine/session factory. It
did not create an auxiliary engine or replace per-service factories.

[`acceptance-poolone.log`](/tmp/amw-launch-20260831/logs/acceptance-poolone.log)
records **36 passed, zero skipped, four warnings, exit 0, including teardown**
in 2.27 seconds; log SHA-256
`68e4d5fa2c6e72b5244ccf1299f8abe7b799150bf6f66080a9cf189c12ce1700`.
The module contains six ordinary caller-session guards and 30 PostgreSQL cases:
one validation/reservation/replay case, four refund completion/denial cases,
13 pending-refund/key/checkpoint cases, and 12 current-or-legacy public receipt
export cases. The cases cover native Ed25519 verification, current and authentic
legacy signing bytes, valid and malformed/tampered inputs, disabled/retired or
missing state, warm/cold key preparation, checkpoint/permit/approval refusal,
and terminalization between preflight and the locked recheck. Caller-session
guards fail if verification tries a forbidden nested acquisition or commits or
closes the caller-owned session.

The retained limit is exact: terminalization after advisory preflight may still
prepare or reactivate configured signing-key metadata, but locked revalidation
prevents a new receipt or work item. No universal disable-before-commit guarantee
is claimed.

## All final replacement gates

Every row below is one command result from
[`acceptance-command-manifest.json`](/tmp/amw-launch-20260831/logs/acceptance-command-manifest.json).
The selections overlap, so the counts are intentionally not added into a
single test total.

| Command group | Exact observed result |
| --- | --- |
| Actual singleton application pool | 36 passed; 0 skipped; 4 warnings; exit 0; teardown completed |
| Default-pool PostgreSQL regressions | 65 passed; 66 warnings; exit 0; includes the 20-call and 20-replay case |
| Full SQLite suite | 1,688 passed; 65 skipped; 6 deselected; 67 warnings; exit 0 |
| PostgreSQL independent-worker crash/recovery | 9 passed; 2 warnings; exit 0 |
| PostgreSQL permit/billing concurrency | 18 passed; 1 warning; exit 0 |
| PostgreSQL real-driver datetime/trust loop | 5 passed; 1 warning; exit 0 |
| Local production-posture configuration | 6 passed; exit 0; no production request or deployment |
| Trust release gate | 133 focused passed; 403 coverage cases passed at 83.27% against the existing 80% gate; 10 discovery cases passed; demo, OpenAPI parity, and simulation inventory passed; exit 0 |
| Ruff | All checks passed; exit 0 |
| Mypy | No issues in 171 source files; exit 0 |

The read-only artifact audit found that all ten command-manifest entries exactly
equal their individual execution receipts. Every receipt is completed with
exit 0, binds source manifest `f0c7d423...`, records 572 source files verified
before and after, and matches its retained log SHA-256. The application record's
source-manifest, independent-review, and combined-patch digests also match the
referenced files.

The 65 full-suite skips were not counted as passes. The packet's node-ID
reconciliation maps 63 PostgreSQL skips to the separately selected final
PostgreSQL commands. The remaining two limitations are the optional Playwright
case and the oversized-input observation described below. The six production
marker deselections were separately executed by the production-posture command.

## What remains open

- **Ingress/request size:** the credentialed legacy-MCP fuzz observation sent a
  10 MiB argument, received a successful result, and then called `pytest.skip`.
  That is evidence of missing enforcement on the tested application path, not
  a passing rejection test. Before any pilot exposure, a dedicated restricted
  staging deployment needs a suitable pre-application limit and an observed
  HTTP 413 before application parsing. The suggested 256 KiB cap was not
  configured or verified. Workflows requiring larger payloads remain held.
- **Optional browser scope:** Playwright was absent and its optional case was
  not executed. It is outside the active one-tool wedge but remains an explicit
  test gap.
- **External atomicity and evidence:** the gateway database cannot commit
  atomically with an external tool. Durable uncertainty, non-redispatch, and
  reconciliation are the supported boundary. A gateway signature authenticates
  gateway claims under a trusted key; it does not prove an upstream business
  effect.
- **Reproducibility:** Python 3.12.13, PostgreSQL 16.14, and 69 installed
  distribution versions were recorded. A clean dependency rebuild from those
  pins and the complete assembled PostgreSQL recipe were documented but not
  independently rerun end to end. Version pins do not identify immutable wheel
  bytes across platforms.
- **No qualifying partner:** private records now mention a provisional lead and
  an introduction channel, but no partner-owned experiment is committed or
  verified. There is still no selected consequential staging mutation,
  committed partner engineer and date, verified authority for controlled
  response loss, partner-authoritative effect reconciliation, or commercial
  commitment. Local P9 is a synthetic fixture and earns no G6/customer-
  validation credit.
- **Current repository state:** 18 manifest-listed working-tree paths and the
  Git index changed after the accepted application/audit. Their provenance and
  validation are outside this audit. Any current-tree release, commit, or pilot
  decision needs a new source binding and applicable verification; the frozen
  f0c7 packet's passes cannot silently transfer to those bytes.

The next decision is therefore commercial and partner-owned, with one staging
security prerequisite. Qualify one prospect against its strongest existing
solution, name the consequential retry-sensitive mutation and partner engineer,
agree a date, and verify restricted ingress with an actual 413. Then have the
partner run effect-then-response-loss, exact replay without another dispatch or
debit, authoritative effect reconciliation, and offline receipt verification.
Do not unfreeze another core capability unless that named partner documents a
concrete blocker.

## Completion record

- **Files changed:** `docs/research/2026-08-31-deep-market-lab/engineering-acceptance-update.md` only by this audit.
- **What changed:** added the dated evidence update that supersedes the earlier
  local reliability hold while retaining production, ingress, and partner
  boundaries.
- **Tests run:** no application or database tests. Read-only SHA-256/source-root,
  JSON-receipt, log-binding, application-record, and historical-failure
  consistency checks only.
- **What passed:** all 572 manifest files still match each of the four frozen
  tested roots; ten final command/receipt/log bindings matched; application,
  independent-review, patch, and retained-failure digests were consistent. The
  original checkout matched at the first check, then ended with 18 mismatches.
- **What was not tested:** runtime behavior by this auditor, production,
  partner systems, clean-room dependency installation, request-size rejection,
  browser coverage, market demand, payment, or profitability.
- **Remaining risks:** ingress accepts the observed 10 MiB request, external
  effects are non-atomic, key-lifecycle timing has a bounded caveat, the current
  Git index and 18 listed paths drifted after acceptance, and G6/customer
  evidence is absent.
- **Recommended next step:** preserve the accepted frozen local packet and
  update the research synthesis to remove the stale hold only for that f0c7
  source. Before using the current tree, either restore the exact accepted
  bytes or freeze and verify the intended successor. Then execute only the
  restricted partner comparison plus actual ingress-413 prerequisite before
  the September 11 decision.
