# Technical evidence and harness assessment

Assessment date: 2026-08-31. This research task did not run a second
application test program or modify application code. It independently inspected
the existing engineering program's accepted source manifest, command manifest,
result logs, and review record. Application execution belongs to task
`01a056df-ba0b-7472-b6cc-747dccc8cdd9`; gate acceptance belongs to program task
`01a056e3-c900-7bc0-a825-f402e12e46a7`.

**Finding at the report cutoff: local technical gates G0–G5 are accepted for
the frozen captured source and environments. The pre-integration working tree
was not qualified: concurrent work had changed 18 accepted manifest paths. That
historical comparison does not qualify any later checkout. G6, the partner-owned
experiment, is not accepted.**
The earlier 20-call PostgreSQL pool-starvation failure was reproduced, fixed,
rerun, and independently accepted. This is local synthetic evidence. It is not
a production approval, capacity guarantee, downstream exactly-once guarantee,
or customer validation.

## Source and evidence identity

The accepted source is a dirty working tree over
`46d7310a3b771542dfb1fe874b5cff9d6bf137b2`; the commit alone does not identify
it. The accepted manifest contains **572** whitelisted files and has SHA-256
`f0c7d4236ffc785ca98e002bc4ea3f1759c9d0cc30e972798f37c2a021b5c289`.
[verify_evidence.py](verify_evidence.py) compared every listed file with the
checkout at execution time and four isolated tested roots. All five comparisons
matched when [technical-evidence.json](technical-evidence.json) was generated. A
later pre-integration audit found 18 mismatches and zero missing files. Those
counts are captured validation results. The frozen packet remains valid for its
exact bytes; any later tree needs a new manifest and affected-gate reruns, or the
pilot must use the frozen accepted archive.

The accepted application record states that the Git index was unchanged while
the reviewed files were applied. The index has changed since that cutoff due to
other authorized work, so that historical statement must not be presented as a
current repository-wide cleanliness claim. The 572 listed file bytes still
match in each frozen tested root. The manifest is a scoped inventory, not a
signed attestation or a freeze of unlisted files.

## Accepted validation

These executions belong to the existing engineering owner. This research read
the retained evidence and recomputed file/log hashes. Counts overlap and must
not be added as unique tests.

| Check | Accepted result | Evidence |
|---|---|---|
| Full SQLite suite | 1,688 passed; 65 skipped; 6 deselected | [Log](/tmp/amw-launch-20260831/logs/acceptance-full.log) |
| PostgreSQL accounting/replay regressions and default-pool burst | 65 passed, including 20 invokes and 20 exact replays | [Log](/tmp/amw-launch-20260831/logs/acceptance-regressions.log) |
| Actual application singleton pool, size 1 / overflow 0 | 36 passed, including signatures, denials, refund repair, cleanup, and races | [Log](/tmp/amw-launch-20260831/logs/acceptance-poolone.log) |
| PostgreSQL independent-worker crash/recovery | 9 passed | [Log](/tmp/amw-launch-20260831/logs/acceptance-multiprocess.log) |
| PostgreSQL permit/billing concurrency | 18 passed | [Log](/tmp/amw-launch-20260831/logs/acceptance-concurrency.log) |
| PostgreSQL datetime/trust loop | 5 passed | [Log](/tmp/amw-launch-20260831/logs/acceptance-datetime.log) |
| Local production-posture configuration | 6 passed; no production request made | [Log](/tmp/amw-launch-20260831/logs/acceptance-production.log) |
| Trust release gate | 133 focused, 403 coverage, and 10 discovery tests passed; gate passed | [Log](/tmp/amw-launch-20260831/logs/acceptance-trust.log) |
| Ruff and mypy | Passed; mypy checked 171 source files | [Ruff](/tmp/amw-launch-20260831/logs/acceptance-ruff.log), [mypy](/tmp/amw-launch-20260831/logs/acceptance-mypy.log) |

All ten entries in the
[acceptance command manifest](/tmp/amw-launch-20260831/logs/acceptance-command-manifest.json)
have exit code 0 and bind the same 572 files before and after execution. The
[independent review](/tmp/amw-launch-20260831/logs/acceptance-independent-review.json)
records `accepted` at `2026-08-31T10:07:57.879695+00:00` and explicitly excludes
production deployment and customer validation.

Of the 65 full-suite skips, 63 PostgreSQL cases were executed in the separate
accepted runs. The six deselected posture cases were separately executed. Two
gaps remain: optional Playwright coverage and a credentialed 10 MiB invocation
that the observation test accepts and then skips. That payload result is a
missing request-size boundary, not a passing rejection test. Before pilot
exposure, a pre-application limit must return an observed 413 for an agreed
payload limit. The program's suggested 256 KiB value is not yet verified.

## Historical failure and resolution

The accepted result does not erase the failure that caused the hold. The
[first rapid-invoke run](/tmp/amw-launch-20260831/logs/final-postgres-rapidfire.log)
and the
[baseline comparison](/tmp/amw-launch-20260831/logs/baseline-postgres-rapidfire.log)
both failed because 20 concurrent calls exhausted a pool of 5 plus 10 overflow
connections. This falsified the assumption that earlier duplicate-key and
smaller concurrency proofs qualified 20 distinct simultaneous actions.

The bounded fix reused caller sessions through permit, receipt, and refund
verification and prepared signing keys outside the financial transaction. It
did not enlarge the pool or weaken assertions. The replacement evidence is the
65-case default-pool run and the 36-case one-connection run above. The program
control records P10 as accepted and integrated after independent source,
transaction, and runtime review.

## What the architecture supports

| Boundary | Inspected implementation | Assessment |
|---|---|---|
| Stable logical-action identity | [Governed router](../../../app/routers/mcp.py), [idempotency service](../../../app/services/idempotency.py) | Implemented; replay checks do not infer equivalence between different caller keys. |
| Bounded configured authority | [Permit service](../../../app/services/permits.py), [dispatch preparation](../../../app/services/mcp_dispatch_attempts.py) | Credit and call reservations support the existing loop; configured credits are not collected revenue. |
| One gateway send authority | [claim_dispatch](../../../app/services/mcp_dispatch_attempts.py:798), [upstream transport](../../../app/services/upstream_mcp.py:501) | Durable claim and no automatic transport retries; conditional on durable state, the governed path, and stable identity. |
| Ambiguity and repair | [Reconciliation service](../../../app/services/mcp_dispatch_reconciliation.py), [startup sweep](../../../app/main.py:231) | Preserves uncertainty and repairs linked gateway state. External effect truth remains the partner's responsibility. |
| Gateway evidence | [Evidence service](../../../app/trust/evidence.py), [receipt verifier](../../../b2a_sdk/src/b2a_sdk/receipt_verifier.py) | Establishes issuer statements and linked consistency; it does not prove the upstream business effect. |
| Deployment boundary | [Security limitations](../../../SECURITY_LIMITATIONS.md:16), [deployment runbook](../../deploy-railway.md:6) | Vendor-managed, single tenant, synthetic/redacted pilot boundary; no accepted production HA, load, restore, BYOC, or on-prem evidence. |

See [mechanism.md](mechanism.md) for the conditional state-machine reasoning.
Finite tests do not prove arbitrary crash schedules, database failover, or a
malicious operator. No retained evidence establishes scaled partner production.

## Harness findings that remain open

1. **Ingress is not qualified for a pilot.** Add and observe a pre-application
   request limit before external exposure; keep larger-payload workflows out of
   the pilot until then.
2. **Some proof labels exceed their environment.** The CI step described as a
   PostgreSQL trust loop still lets most application tests use SQLite through
   [conftest](../../../tests/conftest.py:90). Cite the dedicated accepted
   PostgreSQL logs rather than that label.
3. **Customer-facing replay wording conflicts with code.**
   [validate_replay_access](../../../app/services/permits.py:405) intentionally
   permits finalized evidence replay after permit expiry or revocation while
   [failure-semantics](../../failure-semantics.md:138) says revocation prevents
   reading. Correct the document after preserving the accepted source record;
   do not weaken stable evidence access to match stale prose.
4. **External effect truth remains outside the gateway transaction.** The
   partner must reconcile its own authoritative system. A signed gateway
   receipt cannot establish that business effect by itself.

Do not restart broad platform work. The local technical program has reached its
bounded stop. The critical path is a restricted partner comparison after the
ingress check, using one partner-owned action and its strongest current control.

## Required reporting

- Files changed: this report, the read-only audit script, and its evidence JSON.
- What changed: the earlier reliability hold was reconciled to accepted local
  evidence while the historical failure remains visible.
- Tests run: `python3 docs/research/2026-08-31-deep-market-lab/verify_evidence.py`;
  no application suite was rerun by this research task.
- What passed: all 572 listed files still match each of the four frozen tested
  roots; every retained acceptance command exited 0; independent review says
  the frozen packet is accepted. At the pre-integration validation cutoff, the
  then-current checkout matched 554/572; that count is historical.
- What was not tested: partner or production systems, ingress 413 behavior,
  restored-history/load/HA behavior, customer demand, and optional browser use.
- Remaining risks: external non-atomicity, request-size exposure, mutable local
  state outside the manifest, and no commercial or partner-owned proof.
- Recommended next step: verify the pilot ingress limit, then run the prepared
  A/B comparison with one named partner, tool, engineer, and commercial owner.
