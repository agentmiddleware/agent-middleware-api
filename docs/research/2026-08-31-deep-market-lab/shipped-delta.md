# Shipped delta since the Quantum Management baseline

Quantum delta cutoff: `2026-08-31T08:27:37.808Z`. Audit completion cutoff:
`2026-08-31T22:23:12Z`.

## Evidence boundary

The strict cutoff is the start of Codex task
`01a056ee-5fb7-71a1-ac14-37335fd8bb69`, locally titled “Design quantum
management system.” The evidence and attribution rule are recorded in
[`quantum-baseline.md`](quantum-baseline.md). Quantum Management joined the
operational-validation program about 11 minutes after that program started, so
work initiated earlier but proven later is described as **completed during
Quantum Management**, not created by it.

The source baseline is the dirty working-tree snapshot over Git commit
`46d7310a3b771542dfb1fe874b5cff9d6bf137b2`, recorded in
[`snapshot-manifest.json`](/tmp/amw-launch-20260831/logs/snapshot-manifest.json)
(565 included files; SHA-256
`430b1272ced43b6e36020b9f6ff6782a4b3a11234b21fddfbecedc80128ac236`).
The baseline was not a clean checkout, so ordinary `git diff HEAD` cannot
separate this program's work from pre-existing edits. The accepted source
manifest's per-file `baseline_sha256`, `tested_sha256`, and
`changed_by_this_task` fields are the controlling delta evidence.

Nothing was shipped to a customer or production environment. Git `HEAD` is
still `46d7310a3b771542dfb1fe874b5cff9d6bf137b2`, and
[`acceptance-application.json`](/tmp/amw-launch-20260831/logs/acceptance-application.json)
(SHA-256 `50f7a3813eaeb4f6c4ce9e1e5fb42aafc5c96855c56aa5be2860b1ca6b64f993`)
records the application scope as “working tree only” with no commit, push, or
deployment. The objective completion claim is therefore **locally integrated
and accepted on a frozen snapshot**, not externally shipped.

The accepted snapshot is
[`acceptance-source-manifest.json`](/tmp/amw-launch-20260831/logs/acceptance-source-manifest.json),
SHA-256 `f0c7d4236ffc785ca98e002bc4ea3f1759c9d0cc30e972798f37c2a021b5c289`:
572 whitelisted files, 22 program-changed paths, and four isolated tested roots.
That snapshot and its retained extracted roots remain exact evidence of the
accepted run.

At the pre-integration validation cutoff, the checkout no longer equaled the
accepted snapshot. The completion check at `2026-08-31T22:23:12Z` found
**554/572** entries matching and 18 mismatches, including 10 of the 22
program-changed paths. Those edits appeared after the final acceptance commands
and had no replacement source manifest or test packet cited at that cutoff. The
ten passing commands therefore apply to frozen manifest `f0c7…`; the captured
554/572 comparison is historical and does not describe a later working tree.
The mismatch inventory is recorded under “Blockers that remain.”

## What was integrated

The accepted delta contains 11 application files, two generated/example
documents, and nine test or test-support files. The manifest records exact
before/after hashes for every path.

| Accepted behavior delta | Concrete source delta | Direct falsification and regression evidence |
| --- | --- | --- |
| Explicit malformed MCP idempotency keys now fail closed before permit minting, effects, or debits; valid header precedence and 128-character keys remain supported. | [`_validate_idempotency_key`](/Users/sellers/Documents/GitHub/agent-middleware-api/app/routers/mcp_standard.py#L156) and [`handle_call_tool`](/Users/sellers/Documents/GitHub/agent-middleware-api/app/routers/mcp_standard.py#L355) | The defect was already reproduced before the Quantum cutoff: three failures and two effects/two debits per malformed retry case in [`mcp-validation-repro.log`](/tmp/amw-launch-20260831/logs/mcp-validation-repro.log), SHA-256 `2bdf9a163eaace359e7fce196674539f554db26f8fdd6d951b3b7fac3b75b734`. The delta is the accepted fix and negative/compatibility coverage in the frozen [`test_mcp_idempotency_validation.py`](/tmp/amw-launch-20260831/acceptance-pg-reg/tests/test_mcp_idempotency_validation.py#L23), included in the 65-pass PostgreSQL regression log. |
| A live debit and stale pre-dispatch cleanup now share an attempt fence; velocity, debit, and checkpoint changes commit together, and cleanup adopts a debit that committed before its lock. | [`BillingEngine.charge`](/Users/sellers/Documents/GitHub/agent-middleware-api/app/services/billing_engine.py#L396), [`complete_pre_dispatch_failure`](/Users/sellers/Documents/GitHub/agent-middleware-api/app/services/mcp_dispatch_attempts.py#L896), and [`VelocityMonitor.check_and_record_charge`](/Users/sellers/Documents/GitHub/agent-middleware-api/app/services/velocity_monitor.py#L79) | The two deterministic failures in [`accounting-reconciliation-repro.log`](/tmp/amw-launch-20260831/logs/accounting-reconciliation-repro.log), SHA-256 `5e66af8f951c69fd90edea543f24e76791d777281d0579e0102561643d17d312`, predate Quantum. The delta is the accepted fence plus both serialized race orders and rollback/notification paths in the frozen [`test_late_debit_reconciliation.py`](/tmp/amw-launch-20260831/acceptance-pg-reg/tests/test_late_debit_reconciliation.py#L91), accepted in the 65-pass regression, 18-pass concurrency, and nine-pass process suites. |
| An explicit zero daily cap remains zero and denies spend; permit and approval amounts that cannot round-trip through `NUMERIC(20,8)` are rejected before signing. | [`create_agent_wallet`](/Users/sellers/Documents/GitHub/agent-middleware-api/app/routers/billing.py#L285), [`PermitCreateRequest`](/Users/sellers/Documents/GitHub/agent-middleware-api/app/schemas/trust.py#L10), [`PermitRequestCreate`](/Users/sellers/Documents/GitHub/agent-middleware-api/app/schemas/trust.py#L87), and the velocity fallback at [`_record_charge`](/Users/sellers/Documents/GitHub/agent-middleware-api/app/services/velocity_monitor.py#L109) | The four failures/one pass in [`accounting-input-repro.log`](/tmp/amw-launch-20260831/logs/accounting-input-repro.log), SHA-256 `9da94aa328250c6ae5cb29e14c1b82cb38ec4c7e3fc77839a175054a3f5de96a`, and invalid stored signatures predate Quantum. The delta is the accepted zero-cap/numeric fix, boundary and unchanged-ledger coverage in the frozen [`test_accounting_input_validation.py`](/tmp/amw-launch-20260831/acceptance-pg-reg/tests/test_accounting_input_validation.py#L48), and regenerated OpenAPI. |
| Refunded receipt evidence now requires a finite negative debit, a finite positive refund, and exact offset instead of accepting any correlated refund row. | [`build_receipt_evidence`](/Users/sellers/Documents/GitHub/agent-middleware-api/app/trust/evidence.py#L394), especially the refunded branch at line 581 | This was newly reproduced after the cutoff at `2026-08-31T08:31:01Z`: partial, zero, excess, wrong-sign refund and modified-debit cases all passed incorrectly, yielding five failures in [`refund-evidence-repro.log`](/tmp/amw-launch-20260831/logs/refund-evidence-repro.log), SHA-256 `70ecdb064a06cef83a3d65b85f68a6f7bf2bd579aa1c1939727ec1d096813f47`. The five tamper cases and valid refund are covered in the frozen [`test_refund_amount_evidence.py`](/tmp/amw-launch-20260831/acceptance-pg-reg/tests/test_refund_amount_evidence.py#L119); the focused candidate recorded 70 passes and the final regression lane passed. |
| Permit, receipt, and refund signature verification can reuse a caller-owned database session; signing-key preparation moved outside financial/work-item locks while refusal conditions are rechecked under the lock. This removes the nested checkout needed for the reproduced pool-starvation schedule without increasing the pool or weakening locks. | Frozen source: [`SigningKeyService.get_public_key`](/tmp/amw-launch-20260831/acceptance-pg-poolone/app/services/signing_keys.py#L246), [`PermitService._validate_replay_model_access`](/tmp/amw-launch-20260831/acceptance-pg-poolone/app/services/permits.py#L435), [`ReceiptService.verify_model`](/tmp/amw-launch-20260831/acceptance-pg-poolone/app/services/receipts.py#L577), and [`RefundReconciliationService.create_pending`](/tmp/amw-launch-20260831/acceptance-pg-poolone/app/services/refund_reconciliation.py#L122) | The unchanged baseline and pre-fix candidate each failed the 20-call PostgreSQL rapid-fire test after about 32 seconds: [`baseline-postgres-rapidfire.log`](/tmp/amw-launch-20260831/logs/baseline-postgres-rapidfire.log), SHA-256 `60a3efddb346dde6828c8c69e4d73048d114e537e1332e073855dc96deada8c5`, and [`final-postgres-rapidfire.log`](/tmp/amw-launch-20260831/logs/final-postgres-rapidfire.log), SHA-256 `0e49ac5580f069e5c8c4690402429329e3bebc9118a42e712106a0b97bda045a`. The accepted one-connection and fail-closed cases are in the frozen [`test_permit_verification_sessions.py`](/tmp/amw-launch-20260831/acceptance-pg-poolone/tests/test_permit_verification_sessions.py#L100); 36 cases passed with application pool size 1/overflow 0. The ordinary pool retained size 5/overflow 10 and passed 20 invokes plus 20 exact replays in the final regression lane. |
| The local crash harness now joins a duplicate-visible upstream effect, response loss, charged uncertainty, worker death before receipt persistence, reconciliation, exact replay, and offline signature verification. At the frozen acceptance cutoff, the example deployment manifest was corrected from migration 033 to the then-existing migration 034; the live example is maintained separately at the current merged head. | Frozen [`test_remote_response_loss_recovers_charged_receipt_verified_offline`](/tmp/amw-launch-20260831/acceptance-pg-crash/tests/test_mcp_postgres_multiprocess.py#L1317), frozen [`partner_write`](/tmp/amw-launch-20260831/acceptance-pg-crash/tests/support/mcp_remote_partner_app.py#L147), and the current [`railway-customer-manifest.example.json`](../../railway-customer-manifest.example.json) | The nine-case PostgreSQL process suite passed under the final manifest. The upstream is an explicitly synthetic test fixture, so this closes a local harness gap only; it is not partner evidence. |

The 22 manifest-bound paths are:

- Application: `app/routers/billing.py`, `app/routers/mcp_standard.py`,
  `app/schemas/trust.py`, `app/services/billing_engine.py`,
  `app/services/mcp_dispatch_attempts.py`, `app/services/permits.py`,
  `app/services/receipts.py`, `app/services/refund_reconciliation.py`,
  `app/services/signing_keys.py`, `app/services/velocity_monitor.py`, and
  `app/trust/evidence.py`.
- Contract/example: `docs/openapi.json` and
  `docs/railway-customer-manifest.example.json`.
- Tests/support: `tests/support/mcp_remote_partner_app.py`,
  `tests/test_accounting_input_validation.py`,
  `tests/test_late_debit_reconciliation.py`,
  `tests/test_mcp_idempotency_validation.py`,
  `tests/test_mcp_postgres_multiprocess.py`,
  `tests/test_permit_postgres_concurrency.py`,
  `tests/test_permit_verification_sessions.py`,
  `tests/test_refund_amount_evidence.py`, and
  `tests/test_security_fuzz_battery.py`.

No endpoint, database migration, dependency, authentication model, billing
product, or deployment configuration was added. That claim is bounded to the
22 manifest-selected changes and is corroborated by the path inventory and
[`final-runtime.md`](/tmp/amw-launch-20260831/reports/final-runtime.md), SHA-256
`3c3f7b24eed375a75ee75803f3705ea7d345aa7cbbb948881e129c394dba11f1`.
Public numeric and idempotency input validation did become intentionally
stricter.

## Tests that passed on the frozen accepted source

All ten commands below exited zero and verified the same 572-file manifest
before and after execution. The controlling record is
[`acceptance-command-manifest.json`](/tmp/amw-launch-20260831/logs/acceptance-command-manifest.json),
SHA-256 `37b055206d843f7a8bb055082852db3ace4ff3335ec240f11820561af3ff435c`.
Counts overlap and must not be summed as unique tests. These results do not bind
the 18 files that drifted after the acceptance manifest was created.

| Lane | Observed result | Exact log SHA-256 |
| --- | --- | --- |
| Actual application pool 1 / overflow 0 | 36 passed, 0 skipped, exit 0 | [`acceptance-poolone.log`](/tmp/amw-launch-20260831/logs/acceptance-poolone.log): `68e4d5fa2c6e72b5244ccf1299f8abe7b799150bf6f66080a9cf189c12ce1700` |
| PostgreSQL accounting/replay plus default-pool burst | 65 passed, exit 0 | [`acceptance-regressions.log`](/tmp/amw-launch-20260831/logs/acceptance-regressions.log): `dcb7fef63e8247c1644d33615815053b7b457eb985934fa622358e2ee2c9eec5` |
| Full SQLite suite | 1,688 passed, 65 skipped, 6 deselected, exit 0 | [`acceptance-full.log`](/tmp/amw-launch-20260831/logs/acceptance-full.log): `457264aaf1fe4ff4d107f1afdd354e89b06626273ba0e743377f527abaff36ef` |
| PostgreSQL independent-process crash/recovery | 9 passed, exit 0 | [`acceptance-multiprocess.log`](/tmp/amw-launch-20260831/logs/acceptance-multiprocess.log): `0fbcc36f1981efcbbe636c4ea61be9a4e14452bdef9acbe98846623772052527` |
| PostgreSQL accounting/permit concurrency | 18 passed, exit 0 | [`acceptance-concurrency.log`](/tmp/amw-launch-20260831/logs/acceptance-concurrency.log): `aa0ed578846f5f38c77615b60dfc9deea5b7e7f4eb565420a630a1e7d7f81d35` |
| PostgreSQL datetime trust loop | 5 passed, exit 0 | [`acceptance-datetime.log`](/tmp/amw-launch-20260831/logs/acceptance-datetime.log): `ae4be17b77130d9d6cda6cd1fc088dd55c63a5d6854302776836ce7126aa9212` |
| Local production-posture configuration | 6 passed, exit 0; no production requests | [`acceptance-production.log`](/tmp/amw-launch-20260831/logs/acceptance-production.log): `67a6b9c5594de45da6878757991a51081035f78f7e74330ad0c4e8806f13d95f` |
| Trust release gate | 133 focused + 403 coverage + 10 discovery; OpenAPI/inventory/demo gates passed; exit 0 | [`acceptance-trust.log`](/tmp/amw-launch-20260831/logs/acceptance-trust.log): `f57d2b26d51f82a7e03e01e0e3dfa708af8a4446b1515e0edd79763254e99c8b` |
| Ruff | All checks passed, exit 0 | [`acceptance-ruff.log`](/tmp/amw-launch-20260831/logs/acceptance-ruff.log): `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| Mypy | No issues in 171 source files, exit 0 | [`acceptance-mypy.log`](/tmp/amw-launch-20260831/logs/acceptance-mypy.log): `5a5d18602ec811a5e8d5394689dedc469378e3dc613794f1897fef5a5de66523` |

Of the 65 full-suite skips, 63 PostgreSQL cases were exercised in separate
accepted PostgreSQL lanes. The six production-posture deselections were
exercised separately. The two remaining skips are optional Playwright coverage
and a 10 MiB credentialed request that the application accepted before the test
skipped. The latter is evidence of an open request-size gap, not a passing
rejection check.

Independent review accepted the exact source/test/runtime binding in
[`acceptance-independent-review.json`](/tmp/amw-launch-20260831/logs/acceptance-independent-review.json),
SHA-256 `c5c52591752f5f6241704d73f4acb1fcbd79644f47cf1352847a9590bad6333f`.
That review explicitly excludes production deployment, customer validation,
and any universal key-disable-before-commit guarantee.

## Hypotheses falsified after the Quantum cutoff

Three direct counterexamples were produced after `08:27:37.808Z`:

1. **“A correlated refund row is sufficient evidence of exact compensation”
   was false.** At `08:31:01Z`, partial, zero, excess, wrong-sign, and
   modified-debit cases all passed the old evidence check.
2. **“The normal 5+10 connection pool makes nested verification checkout safe
   for a 20-call burst” was false.** The pre-P10 candidate failed at
   `09:04:34Z`, and the unchanged baseline reproduced the failure at
   `09:07:17Z`, after the 30-second checkout timeout. This is a concrete
   starving schedule, not proof that every schedule deadlocks.
3. **“Passing auxiliary-pool checks or successful test bodies are enough for
   acceptance” was false as a proof method.** V4 used a patched auxiliary
   engine rather than the application singleton factory. V5 ended with 80
   passed bodies and four teardown errors, exit 1. Final acceptance required
   the actual application factory at pool size 1/overflow 0 and clean teardown.
   See
   [`verification-history.md`](/tmp/amw-launch-20260831/reports/verification-history.md).

Four important counterexamples were already present before Quantum began and
must not be counted as new discovery: malformed explicit retry identities,
cleanup/debit ordering, zero-cap loss, and database rounding that invalidated
stored signed authority. What changed after the cutoff is that their bounded
fixes and regressions were source-bound, independently reviewed, and accepted
on `f0c7…`.

No commercial hypothesis was falsified or validated because no partner-owned
experiment, price discussion, budget-owner decision, or purchase occurred.

## External evidence obtained

Accepted external evidence: **none**.

The program record reports two secondary signals: introduction channel
`INTRO-20260831-01` reportedly received the founder's qualification criteria,
and provisional lead `PW-20260831-01` reportedly offered onboarding plus a
20-minute discovery call about human-gated consequential actions. The original
messages, counterparty identity, current offer, and authority were not
independently verified. There is no selected staging mutation, committed partner
engineer/date, permission for response loss, authoritative effect lookup,
commercial commitment, or willingness-to-pay evidence. These signals remain
**lead intelligence**, not G6 evidence. See the continued-management record at
[`docs/aegis/work/2026-08-31-program-control/README.md`](../../aegis/work/2026-08-31-program-control/README.md#continued-management).

## Duplicated work eliminated

The program consolidated decision authority into one program record and retained
one runtime integrator. Task `e2-6aeb` relinquished its duplicate management
assignment, task `e0-9564` reported interrupting eight overlapping workers, and
executive task `ee-5fb7` explicitly declined to create another registry,
scheduler, automation, or execution pod. These are owner-reported coordination
facts in the program record at lines 74–89; they are not measured productivity
or cost savings. The bounded engineering workers are now closed. This task then
paused automation `amw-operational-validation-management`, eliminating its
four-hour unchanged-state poll while preserving it for an intentional resume.

## Kill or freeze recommendations supported by this delta

- **Kill additional local reliability work absent a new defect.** G0–G5 are
  accepted on the frozen local snapshot; repeating the same suites cannot create
  partner evidence.
- **Kill the legacy arbitrage report as a commercial decision input.** It uses
  configured credits and hard-coded cost assumptions, misstates its time period,
  and does not net refunds. Keep it only as clearly labeled diagnostic debt or
  remove it under a separately scoped change. Evidence:
  [`accounting.md`](/tmp/amw-launch-20260831/reports/accounting.md).
- **Kill pass-banner use of `scripts/stress_test_live.py` as a release gate.** Its
  historical replay/accounting checks print failures without necessarily failing
  the process and its “health under load” operation is not actually overlapped.
  Keep the accepted pytest/PostgreSQL lanes as the gate. Evidence:
  [`adversarial.md`](/tmp/amw-launch-20260831/reports/adversarial.md).
- **Freeze broad platform, schema, governance, and new-tool work.** No named
  prospect has documented a blocker that requires it. This follows the repository
  customer-validation invariant and does not authorize deleting existing APIs.

## Blockers that remain

1. G6 has no verified committed partner, consequential retry-sensitive staging
   mutation, partner engineer/date, authoritative effect reconciliation, or
   commercial decision evidence.
2. Pre-application request-size rejection has not been demonstrated. A pilot
   requires an actual 413 observation on a dedicated restricted staging path;
   the proposed 256 KiB threshold is unverified.
3. Gateway state and an external effect remain non-atomic. The product can
   preserve durable uncertainty and prevent gateway redispatch, but only the
   partner's authoritative system can establish the real downstream effect.
4. Optional Playwright coverage remains unexecuted. A fresh dependency rebuild
   and the assembled PostgreSQL reproduction recipe were documented but not
   independently rerun end to end.
5. The accepted changes are not committed, pushed, deployed, or exercised on a
   production or partner system.
6. At the pre-integration validation cutoff, the checkout had 18
   post-acceptance hash mismatches against `f0c7…` (a historical inventory, not
   a live status):
   `app/services/human_approval.py`, `app/services/quotes.py`,
   `app/services/receipts.py`, `app/services/refund_reconciliation.py`,
   `tests/support/mcp_remote_partner_app.py`,
   `tests/test_accounting_input_validation.py`,
   `tests/test_human_approval_gate.py`,
   `tests/test_late_debit_reconciliation.py`,
   `tests/test_mcp_dispatch_reconciliation.py`,
   `tests/test_mcp_idempotency_validation.py`,
   `tests/test_mcp_postgres_multiprocess.py`,
   `tests/test_mcp_upstream_governed.py`,
   `tests/test_permit_verification_sessions.py`,
   `tests/test_refund_amount_evidence.py`,
   `tests/test_security_fuzz_battery.py`, `tests/test_signed_quotes.py`,
   `tests/test_site_agent_interface.py`, and `tests/test_wedge_honesty.py`.
   The observed aggregate diff is 90 insertions and 104 deletions; no replacement
   acceptance manifest or execution packet was found at this cutoff. Use the
   frozen archive for any accepted-source claim, or requalify these exact bytes.

## Single highest-leverage next action

The founder should schedule the offered 20-minute qualification conversation
with the privately identified `PW-20260831-01` now. The only acceptable output
is a written yes/no on one specific staging mutation, one accountable partner
engineer, a run date no later than **September 11, 2026**, permission to induce
effect-then-response-loss, the authoritative effect lookup, and the commercial
decision/budget owner. A “yes” unlocks the restricted ingress check and partner
A/B run; a “no” or no scheduled conversation is demand evidence and should keep
core expansion frozen.

## Audit verification receipt

- Evidence action / check performed at `2026-08-31T22:23:12Z`: recomputed
  SHA-256 for all 572 manifest entries against the then-current repository,
  checked the then-current `HEAD`, read every
  acceptance command result and log hash, compared the 22-path manifest delta to
  the application record, and inspected retained baseline failure logs.
- Result / exit status: the frozen manifest and all ten log hashes verified, all
  ten accepted command receipts record exit 0, and `HEAD` remains
  `46d7310a3b771542dfb1fe874b5cff9d6bf137b2`. The captured checkout comparison
  intentionally failed the exact-source assertion: 554/572 entries matched and
  18 differed, including 10/22 program-changed paths. These are historical
  cutoff values.
- Covered scope: frozen accepted source identity, program-selected code/test/doc
  delta, retained local runtime results, byte-drift detection at the stated
  cutoff, and explicit claim boundaries.
- Uncovered scope: no application test rerun by this audit, no production or
  partner system, no primary-source verification of private lead reports, and no
  commercial measurement.
- Residual risk recorded at the cutoff: the then-current working-tree edits were
  not source-bound to the accepted packet; external effect semantics, ingress
  limits, key timing, and demand remained bounded or unverified.
- Confidence grade at the cutoff: **B** for the frozen local integrated delta,
  **C** for the then-current working tree and lead status; no confidence grade
  is assigned to unperformed partner or commercial outcomes.
