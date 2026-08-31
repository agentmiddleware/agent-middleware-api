# Quantum Management baseline

## Cutoff

For this repository, **“Quantum Management began” means 2026-08-31
08:27:37.808 UTC (01:27:37.808 PDT)**, when Codex task
`01a056ee-5fb7-71a1-ac14-37335fd8bb69` started in
`/Users/sellers/Documents/GitHub/agent-middleware-api`. Its session metadata
records the time, repository and user-originated task; the local session index
names it `Design quantum management system`.

Evidence:

- [Quantum task session, line 1](</Users/sellers/.codex/sessions/2026/08/31/rollout-2026-08-31T01-27-37-01a056ee-5fb7-71a1-ac14-37335fd8bb69.jsonl:1>)
- [Local task index, line 1395](</Users/sellers/.codex/session_index.jsonl:1395>)
- [The attached Quantum Management request](</Users/sellers/.codex/attachments/a2179839-6242-4785-ba83-a5ddeb7e29d6/pasted-text.txt:1>)

**Confidence: high.** This is the earliest task carrying that title in this
repository. Tasks with the same title started seconds later in Sentinel,
RegEngine and Voicemail Vault; they are outside this repository's baseline.

The broader management program started earlier, at **08:16:03.870 UTC**, under
task `01a056e3-c900-7bc0-a825-f402e12e46a7`. Its user instruction arrived at
08:16:09.941 UTC and asked for a management and coordination layer, explicit
workstream ownership, independent verification and continuous execution. The
authoritative [program-control record](../../aegis/work/2026-08-31-program-control/README.md)
was then created locally at about 08:19 UTC and remains mutable. Quantum
Management therefore joined an existing program; it did not start the
engineering work from zero.

Evidence: [pre-existing program task metadata](</Users/sellers/.codex/sessions/2026/08/31/rollout-2026-08-31T01-16-03-01a056e3-c900-7bc0-a825-f402e12e46a7.jsonl:1>)
and [its original user instruction, line 10](</Users/sellers/.codex/sessions/2026/08/31/rollout-2026-08-31T01-16-03-01a056e3-c900-7bc0-a825-f402e12e46a7.jsonl:10>).

**Confidence: high** for the task order and **medium** for reconstructing the
control document at that moment, because the document was updated in place and
has no committed historical version.

## Source state at the cutoff

No Git commit represents the full baseline. The checkout was a dirty working
tree on `codex/site-structured-data`, with HEAD/base context
`46d7310a3b771542dfb1fe874b5cff9d6bf137b2` (`feat(site): add website
structured data`, authored 2026-08-13). Claims about change since Quantum
Management must compare captured file bytes, not HEAD-to-current Git history.
The Quantum task's first repository inspection records the branch, dirty status
and five-commit context in [session line 31](</Users/sellers/.codex/sessions/2026/08/31/rollout-2026-08-31T01-27-37-01a056ee-5fb7-71a1-ac14-37335fd8bb69.jsonl:31>).

The best pre-cutoff source artifact is
[snapshot-manifest.json](/tmp/amw-launch-20260831/logs/snapshot-manifest.json),
captured at about 08:15:21 UTC. It binds **565 included working-tree files** to
SHA-256 values and to the isolated snapshot
`/tmp/amw-launch-20260831/runtime`. Manifest SHA-256:
`430b1272ced43b6e36020b9f6ff6782a4b3a11234b21fddfbecedc80128ac236`.
It excluded `.env.example` and `.env.production`; their non-secret tracked
bytes were later recorded separately in
[template-supplement.json](/tmp/amw-launch-20260831/logs/template-supplement.json).

At 08:27:49 UTC, twelve seconds after the strict cutoff,
[baseline-source-verification.json](/tmp/amw-launch-20260831/logs/baseline-source-verification.json)
reported all 565 captured files unchanged in both the original checkout and
the isolated snapshot. It explicitly excludes new management documents from
that check.

**Confidence: high** for the 565 included files and their bytes; **medium** for
the whole repository because the manifest is a whitelist, excluded two tracked
templates, and did not include management artifacts created after capture.

## Objective at the cutoff

The Quantum request's organizational objective was to inspect existing agents,
construct the minimum executive control plane, map workstreams and the critical
path, allocate temporary managers and specialists, require independent
verification, eliminate correlated duplication, protect scarce authority and
mutable state, and continue executing instead of stopping at a plan.

The repository narrowed that generic operating model to an existing product
goal. At 08:28:07 UTC, the Quantum task recorded its working objective as:
prove one partner-owned, retry-sensitive action through the existing gateway
loop; do not expand the core, contact prospects or change production. The
[first scope statement, line 22](</Users/sellers/.codex/sessions/2026/08/31/rollout-2026-08-31T01-27-37-01a056ee-5fb7-71a1-ac14-37335fd8bb69.jsonl:22>)
records that decision. It came from the captured
[project instructions](/tmp/amw-launch-20260831/runtime/AGENTS.md)
and [30-day customer-validation sprint](/tmp/amw-launch-20260831/runtime/docs/30-day-customer-validation.md),
which was already active from August 12 through September 11.

The original success conditions were therefore:

1. Locally establish a reproducible transaction-integrity loop: logical action
   identity, bounded authority/allowance, at most one gateway dispatch and
   debit, durable `delivery_uncertain`, reconciliation and linked portable
   evidence.
2. Keep new core capability frozen without evidence from a named prospect.
3. Obtain the external result that local tests cannot supply: one partner-owned
   agent, consequential retry-sensitive staging tool, partner engineer,
   authoritative effect lookup, offline receipt verification and commercial
   commitment or paid-pilot evidence.
4. Treat passing local tests as engineering evidence, never as customer or
   market validation.

**Confidence: high.** These goals appear in the original attachment, the first
Quantum-task scope statement and the byte-captured repository instructions.

## What was already true before Quantum Management

The following evidence predates the 08:27:37 UTC cutoff and must not be
reported as a Quantum Management delta:

| Baseline fact | Pre-cutoff evidence |
| --- | --- |
| Ruff and mypy passed | [ruff.log](/tmp/amw-launch-20260831/logs/ruff.log); [mypy.log](/tmp/amw-launch-20260831/logs/mypy.log) reported 171 source files |
| Trust gates passed | [trust-release-gate.log](/tmp/amw-launch-20260831/logs/trust-release-gate.log): 133 focused, 403 coverage, 10 discovery; 83.45% coverage |
| Full suite was not green | [full-suite-with-git.log](/tmp/amw-launch-20260831/logs/full-suite-with-git.log): 1,612 passed, 34 skipped, 6 deselected, 6 failed |
| Five of those six failures were missing-template artifacts; one manifest-revision failure remained | [onboarding-preflight-quickstart.log](/tmp/amw-launch-20260831/logs/onboarding-preflight-quickstart.log): 97 passed, 1 failed after template restoration |
| Existing PostgreSQL crash/concurrency tests passed | [postgres-multiprocess.log](/tmp/amw-launch-20260831/logs/postgres-multiprocess.log): 8 passed; [postgres-concurrency.log](/tmp/amw-launch-20260831/logs/postgres-concurrency.log): 18 passed |
| Invalid explicit MCP retry keys were already reproduced as a defect | [mcp-validation-repro.log](/tmp/amw-launch-20260831/logs/mcp-validation-repro.log): 3 failed |
| Cleanup/late-debit ordering was already reproduced as a defect | [accounting-reconciliation-repro.log](/tmp/amw-launch-20260831/logs/accounting-reconciliation-repro.log): 2 failed |
| Zero-cap and excessive-precision defects were already reproduced | [accounting-input-repro.log](/tmp/amw-launch-20260831/logs/accounting-input-repro.log): 4 failed, 1 passed; [permit-signature-roundtrip.log](/tmp/amw-launch-20260831/logs/permit-signature-roundtrip.log): 2 failed |

Filesystem timestamps place every listed log before the strict cutoff. The
source manifest and near-cutoff verification bind the underlying working-tree
files, but the logs do not contain a common signed timestamp or immutable
external attestation. **Confidence: high** for local chronology and contents,
**medium** for independently portable provenance.

No named partner, partner-owned staging run, authoritative external effect
record, buying commitment, payment or production result is present in this
baseline evidence. That is a repository-evidence statement; it does not prove
that no private customer evidence existed elsewhere.

## Attribution rule for the delta report

Use **08:27:37.808 UTC** as the reporting cutoff and the 565-file manifest as
the byte baseline. Describe work initiated by the earlier program but completed
after the cutoff as **completed during Quantum Management**, not **created by
Quantum Management**. Count a completion only when a source-bound test, log,
artifact, independent review or external record supports it. Current prose in
the mutable program-control document is a pointer to evidence, not evidence of
the historical baseline by itself.
