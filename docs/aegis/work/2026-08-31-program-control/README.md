# Operational validation program control

Updated: 2026-08-31. Program task: `01a056e3-c900-7bc0-a825-f402e12e46a7`.
This is the single cross-task ownership and decision record. Workstream reports
are evidence inputs, not separate program plans. Only the program lead edits
this record; managers send updates with evidence paths and completion criteria.

Current decision: the actual singleton-application-pool proof passed all 36
cases with pool size one, zero overflow, no skips and exit zero including
cleanup. The frozen final source manifest is
`f0c7d4236ffc785ca98e002bc4ea3f1759c9d0cc30e972798f37c2a021b5c289`
(572 files, 22 task-changed paths). All ten final commands passed and independent
review cleared guarded application; all seven P10 paths are now applied. All
572 captured original files match the tested snapshot and the Git index is
unchanged. The owned PostgreSQL cluster is stopped; existing user PostgreSQL
is unchanged. Independent source/archive/command verification and the operator
handoff are accepted; the bounded local engineering run is closed. Earlier failed v5 and
auxiliary-pool results remain historical and are not substituted for this proof.
No pool inflation, lock relaxation or assertion weakening was used.
The earlier 15-file patch and final seven-path application are integrated. Optional
browser coverage and the executed oversized-payload observation remain explicit
limitations.
Production readiness and the partner-owned milestone are not accepted.
The next decision requires a named partner, consequential staging tool, partner
engineer and committed date, followed by verified staging ingress restrictions.
Program control retains sequencing and gate authority; idle workers stay idle
until a concrete dependency changes.

## Objective and boundary

Make the existing transaction-integrity loop operational and reproducible, then
test its accounting, dispatch, uncertainty, and evidence assumptions. The
external acceptance milestone remains the partner-owned pilot in
[the active sprint](../../../30-day-customer-validation.md). A passing local
test or self-issued receipt is not customer validation.

One logical action must bind identity and payload, authorize and reserve
configured allowance, debit, claim at most one gateway dispatch, preserve an
uncertain result, link receipt/audit evidence, and permit separate reconciliation.
No new core capability, broad platform work, or unrelated Dollarloop work is in
scope. Correctness/security fixes and existing-loop reliability fixes are in
scope. No production mutations, deployments, prospect outreach, or purchases
are authorized by this management record.

## Chain of responsibility

```text
Program lead: e3-c900 (this task; ownership, priorities, integration decisions)
  Engineering and validation manager: df-ba0b
    engineering_lead: dispatch and state transitions
    accounting_math: credit/allowance conservation and counterexamples
    security_review: authorization and tenant boundaries
    runtime executor: df-ba0b root (transferred from runtime_qa)
    runtime_qa: setup-only handoff complete; no tests run by this child
    platform_readiness: dedicated native PostgreSQL harness and teardown
    receipt_evidence: current receipt and linked-evidence behavior
    integration_contracts: SDK and wire contracts
    adversarial_qa: assertion sufficiency and negative paths
  Launch qualification manager: e0-544d
    assessment complete; eight read-only specialists closed
  Operator readiness manager: e0-13ca
    final local repeat-run handoff complete; partner observation forms unexecuted
  Historical evidence manager: e2-98a5
    historical-only package complete; eight specialists finished
  Independent fix-verification manager: e0-9564 (reviews complete)
    security_platform_lead: MCP, numeric and refund static reviews complete
    transaction_integrity_lead: exact billing and final P10 code/test/runtime evidence approved
  Independent program-control verifier: /root/management_verifier
    final counts, ownership and claim-boundary review complete; idle
  Final source/evidence verifier: task 01a04285-223e-7a31-ac23-96729c605928 root
    final 572-file/archive and ten-command binding accepted; no runtime work
```

An additional user-requested executive task
`01a056ee-5fb7-71a1-ac14-37335fd8bb69` acknowledged this existing structure and
will not create a competing registry, scheduler, automation, or execution pod.
Executive responsibility mapping: ee-5fb7 = CEO/mission and prioritization;
e3-c900 = COO/program control and gate acceptance; df-ba0b = CTO/engineering
integration; existing accounting_math = scientific/numeric methodology;
e0-9564 = independent risk/adversarial fix review; e0-544d = product/customer
utility. These are responsibilities for existing owners, not new staffing or
additional approval layers. ee-5fb7 may independently challenge P9 experiment
methodology; operational source/test scheduling stays with df-ba0b.

Task e2-6aeb relinquished its duplicate management assignment; its one retained
arithmetic worker completed a bounded sprint-target check. Task e0-9564
reported interrupting its eight overlapping workers. Do not recreate either pod
without a concrete unowned deliverable. Root-local agent lists do not inventory
other task trees; use task status plus manager acknowledgements.

## Ownership and resources

| Workstream | Accountable task | Owned output/resource | Acceptance evidence |
| --- | --- | --- | --- |
| Program decisions | `01a056e3-c900-7bc0-a825-f402e12e46a7` | This directory only | Unique owners; explicit dependencies; evidence-reviewed decisions |
| Engineering, math, runtime QA | `01a056df-ba0b-7472-b6cc-747dccc8cdd9` | `/tmp/amw-launch-20260831/` | Repro commands, statuses, logs, source hashes, invariant observations |
| Launch qualification | `01a056e0-544d-7671-8043-1e4824dc390a` | Final parent-task report; eight read-only workers completed/closed, no repo artifacts | Secondary private lead reports triaged at the 10:51 UTC heartbeat; no committed staging pilot verified; speculative economics/schema/scoreboard work deferred |
| Operator handoff | `01a056e0-13ca-7101-bcdf-ccfb4d8b187c` | Durable packet `reports/operator-handoff.md` | Final local handoff accepted; safe repeat-run worksheet, expected results and stop rules; three form specialists completed, no test execution |
| Historical provenance | `01a056e2-98a5-7070-9599-8cb94be2f0b3` | `/tmp/agent-middleware-evidence-98a5/` | Artifact origin, revision, configuration, reproducibility and claim limits |
| Independent fix review | `01a056e0-9564-7f80-b15b-a6a8d1323e47` | Two reused reviewers, no source ownership | Final f0c7 code/test/runtime evidence approved; payload exposure classified with explicit staging guardrail |
| Final provenance | `01a04285-223e-7a31-ac23-96729c605928` root only | Completed read-only final manifest/application review; no new pod | PASS: all 572 archive/original hashes and modes, ten command/log bindings, 194 packet entries, 69 pins, application/index and cleanup checked |

The final-provenance task subsequently received a separate user research brief.
Its research supplement stays outside this runtime program and source ownership,
under its own visualization directory. Its root retains final packet verification;
research workers do not receive implementation, runtime or registry authority.

The original checkout is dirty at base `46d7310` on
`codex/site-structured-data`; HEAD alone does not identify its source content.
Preserve staged and unstaged changes. The engineering manager reports a
565-file source manifest at
`/tmp/amw-launch-20260831/logs/snapshot-manifest.json` and isolated runtime at
`/tmp/amw-launch-20260831/runtime`. Independent verification accepted all 565
captured baseline entries plus the two-template supplement. The subsequently
integrated MCP fix is separately hash-bound below. Do not claim baseline
results prove later source edits.

Execution transferred to df-ba0b root after `runtime_qa` stopped at setup; that
child ran no tests, gates, migrations, probes, or app servers. df-ba0b root now
owns all application suites, `runtime-pg` worker-crash runs, and `repro` probes.
PostgreSQL provisioning and shutdown belong to `platform_readiness`, after
df-ba0b releases the cluster. The cluster is
`/tmp/amw-launch-20260831/postgres/data`, loopback port 56664. Initial PID 28669
was stopped; it was restarted for supplemental cases as PID 34037, then stopped
after the final ten commands. The final cleanup record confirms no owned
PID/listener/pidfile, port 56664 available, retained data and unchanged user
PostgreSQL PID 1147. Do not restart without a newly scoped runtime need. The shutdown
command is `/opt/homebrew/bin/pg_ctl -D /tmp/amw-launch-20260831/postgres/data -m fast -w -t 30 stop`.
Recheck current ownership/PID before cleanup. Use dedicated disposable resources,
loopback endpoints, synthetic data, and temporary dependency/cache directories.
Never run destructive stress checks against an inherited database URL. Live
conformance scripts can write rows and may default to production; do not run
them without an explicitly isolated target.

## Acceptance gates

| Gate | Completion evidence | Current state |
| --- | --- | --- |
| G0: coherent ownership | Manager acknowledgements and no conflicting source/runtime owners | Accepted after independent corrections and manager acknowledgements; monitor transfers |
| G1: reproducible runtime | Clean setup, migration head, boot/health and documented local HTTP loop on captured source | Accepted for the captured local environment: release gate and independently verified source/command/dependency packet; fresh dependency rebuild and assembled PostgreSQL recipe not rerun end-to-end |
| G2: accounting and replay | Same action has at most one dispatch and debit; changed payload conflicts; bounded allowance and exact refund conservation | Final candidate accepted: default-pool PG65 and singleton-app-pool PG36 passed, exact 20-call accounting/replay, valid/invalid recovery and key-state checks; prior failures preserved |
| G3: crash and uncertainty | Separate gateway processes and PostgreSQL; effect then response loss; charged uncertainty; exact replay cannot redispatch; authoritative effect lookup | Final f0c7 source: nine crash cases and 18 concurrency cases passed; synthetic fixture only, no partner-validation credit |
| G4: security and evidence | Unauthorized/invalid/tenant cases deny; portable receipt verifies offline; tampering fails; linked accounting is consistent | Reviewed fixes and joined receipt/tamper scenario passed locally; oversized legacy-MCP request exposure verified; staging acceptance requires verified ingress restriction, no blanket security certification |
| G5: reviewed integration | Minimal patch, meaningful regression, independent review and relevant lint/type/test results on the integrated source | ACCEPTED locally: all 22 paths applied; original572 matches tested f0c7, Git index unchanged; independent final archive audit and operator handoff accepted |
| G6: partner experiment | Named/stable-ID prospect, committed engineer and staging tool; partner runs sprint acceptance and records operational measurements | External proof not verified; no substitute local claim |

G1 depends on G0 and captured source/resource identity. G2/G4 depend on G1;
G3 depends on G1 and isolated PostgreSQL readiness. G5 requires G2-G4 on the
candidate and integrated source. G6 cannot be accepted before the applicable
technical gates and an actual partner-owned run. The program lead accepts each
gate; independent management verification is mandatory for G0, and e0-9564
must independently review candidate fixes and their before/after evidence for
G5. Historical evidence and drafted operator forms never satisfy runtime gates.

For a fixed logical action `a`, distinguish gateway dispatch count `D(a)`, debit
count `B(a)`, refund amount `R(a)`, configured price `p(a)`, and downstream effect
count `E(a)`. Test `D(a) <= 1` and `B(a) <= 1` over exact replays. A refunded
pre-dispatch failure requires `D(a) = 0` and net debit zero; a charged uncertain
dispatch retains the configured charge/allowance and cannot be treated as
refunded. Reconciliation cannot rewrite the signed gateway observation.
`E(a) = 1` requires authoritative partner evidence and its downstream contract;
it does not follow from a gateway signature or from `D(a) <= 1` alone.

Finite tests are counterexample searches, not universal mathematical proofs.
Record assumptions and tested interleavings. Do not infer empirical success
rates, independence, failure probabilities, or commercial conversion from
deterministic test counts or sprint targets.

P10 resource assumption: the observed default pool admits `P = 5 + 10 = 15`
connections, while the probe submits 20 concurrent calls. A possible starving
schedule has one permit-lock holder plus 14 permit-lock waiters occupying all
15 connections; the holder then asks for an additional connection before it
can release the lock. Its progress depends on a connection held by its own
waiters. The 30-second checkout timeout can break the cycle by failing calls;
it does not satisfy successful 20-call accounting. This is a concrete scheduling
counterexample, not a claim that every 20-call run must deadlock. Reusing the
holder's existing session removes this additional checkout dependency without
increasing the pool or relaxing permit serialization. Runtime evidence and
independent verification must still establish that the code does this correctly.

## Priority queue and dependencies

| ID | Task | Owner | Completion criterion | State |
| --- | --- | --- | --- | --- |
| P1 | Fix stale prepared cleanup versus late debit | df-ba0b, executor engineering_lead; verifier e0-9564 transaction_integrity_lead | Both serial orders safe; no late unrefunded debit, false receipt or separately committed velocity side effect; PostgreSQL regressions | ACCEPTED and INTEGRATED: exact v3 independent approval, PostgreSQL 64/18/9 and full suite passed; lock inversion resolved |
| P2 | Fix invalid standard-MCP metadata key fallback | df-ba0b, executor integration_contracts; verifier e0-9564 security_platform_lead | Invalid explicit keys reject before effects/debits; valid replay and omitted-key contract preserved; independent before/after review | ACCEPTED and INTEGRATED: original three failures; final 34 passed; reviewed and applied file hashes match |
| P3 | Fix refund amount evidence validation | df-ba0b, executor receipt_evidence; verifier e0-9564 | Partial/zero/excess/wrong-sign refund and altered debit all reject; valid exact refund still verifies | ACCEPTED and INTEGRATED: five baseline failures, final 70 passed and exact-version review; original hashes verified |
| P4 | Resolve example manifest revision 033 versus local migration 034 | df-ba0b integration, informed by e0-544d | Existing preflight test passes against selected migration head without changing deployed state | ACCEPTED and INTEGRATED: example revision and generated OpenAPI synchronized; no migration or deployed-state change |
| P5 | Finish isolated baseline and PostgreSQL fault checks | df-ba0b | Commands, exit codes, collected/passed/skipped counts, logs and source identity | COMPLETE locally: all ten final commands passed; earlier failures retained; owned PostgreSQL stopped; durable packet independently verified |
| P6 | Finish safe operator packet | e0-13ca | Exact commands from df-ba0b, expected results and stop rules; program lead reviews against run evidence | COMPLETE local handoff: R5 procedure/R4 five-database/four-cwd recipe, final source/application/cleanup references accepted; partner observations unexecuted; fresh assembled recipe not rerun end-to-end |
| P7 | Finish historical evidence checks | e2-98a5 | Hash/source/config binding and limitations; program lead checks artifacts, not pass banners | COMPLETE historical package, reviewed matrix; zero current-runtime credit |
| P8 | Preserve zero daily cap and validate numeric authority precision | df-ba0b, executor accounting_math; verifier e0-9564 security_platform_lead; shared billing guard solely engineering_lead | Zero cap denies unchanged ledger/counters; allowed precision round-trips signed authority; invalid precision rejected before signing | ACCEPTED and INTEGRATED: standalone numeric and final combined velocity independently approved, final regressions passed; tighter public numeric validation called out |
| P9 | Join local remote-effect/response-loss/replay/offline verification | df-ba0b, executor adversarial_qa; independent methodology ee-5fb7 | One real fixture effect, lost response, charged uncertainty, replay without extra dispatch/debit, authoritative fixture lookup and offline recovered receipt | ACCEPTED locally: final f0c7 nine cases passed; exact methodology preserved; no partner-validation credit |
| P10 | Diagnose and resolve bounded concurrent-invoke pool starvation | df-ba0b sole runtime/integrator, engineering_lead four-service/new-test owner, adversarial_qa existing fuzz-test owner; e0-9564 independent transaction reviewer | Default-pool 20-call accounting/replay and one-connection refund creation/retry progress with real signatures; invalid signatures/disabled keys preserve zero-mutation denials; final replacement gates and exact review | ACCEPTED and INTEGRATED: actual singleton36/default65/all final gates passed; exact code/test/runtime review accepted; seven files applied with index preserved |

P1/P8 shared-file handoff: accounting_math completed its numeric version;
engineering_lead copied the combined numeric guards and is now sole final
`velocity_monitor.py` owner. df-ba0b integrated the final combined file once
after billing re-review; it was not overwritten with two candidate versions.
Numeric review alone did not approve transactional velocity changes.

P9 independent methodology requirements from ee-5fb7: observe durable
`delivery_uncertain`, one debit, no receipt and incomplete replay before the
intentional worker kill; compare the recovered signed receipt to an additional
exact replay after recovery; assert wallet/debit/permit amounts and zero refund
rows; bind the same authoritative fixture effect ID to input and gateway
operation/request hashes. Pin the verification public key from independently
configured harness material. An `expected_issuer` label alone is not issuer
authentication because its envelope field is unsigned, and worker URLs differ.
Include wrong-key, tamper and wrong-issuer negative checks. Source assertion
inspection and runtime execution remain required before accepting the scenario.

## Explicitly bounded follow-up backlog

Source-review reports contain additional findings; they are not silently closed
by the passing selected suites. These are retained for the stated boundary,
without creating speculative feature work or competing execution owners.

| Observation | Owner / disposition | Evidence boundary |
| --- | --- | --- |
| Legacy auth wrapper ignores Authorization; malformed legacy JSON envelopes can raise errors | Engineering/security backlog; restricted pilot must use the supported explicit wallet-key request contract and validated small schema | Source-backed P2 observations in `reports/security.md`; no universal auth or ingress-hardening claim |
| Local-tool generic recovered response differs from SDK result; standard MCP replay can depend on live registration | Integration owner; keep the pilot on the explicit-permit remote JSON-RPC path with stable tool registration | `reports/integration.md`; no claim that the joined remote recovery experiment validates every local-tool SDK recovery branch |
| Revoked permits can read completed replay despite contrary documentation wording | Integration documentation backlog; preserve intended stable-wallet/key evidence access | `reports/integration.md`; do not weaken replay-access implementation to match stale prose |
| Filtered audit suffix verification and malformed CLI bundle exit classification | Evidence owner; full linked receipt bundle and pinned-key verification are the selected experiment path | `reports/evidence.md`; filtered export and arbitrary malformed CLI compatibility not accepted here |
| Live stress script can print success without valid replay/accounting assertions | Adversarial QA: frozen as a diagnostic; excluded from readiness evidence and operator acceptance commands | `reports/adversarial.md`; use source-bound pytest assertions, not its success banner |
| Legacy arbitrage report has misleading time/refund/cost assumptions | Accounting/product: freeze commercial use and launch claims | `reports/accounting.md`; configured credits are not revenue, cost, profitability or customer demand |

These observations remain source-review findings unless their report contains
reproduction evidence. A named partner blocker or a demonstrated correctness,
security or existing-loop reliability defect can reprioritize them. P10 and
local packet/operator closeout are complete. The current priority is qualifying
the restricted partner experiment and verifying its exposure controls before
use; no new broad platform capability is authorized.

Sequence defects as reproduce -> assign one file owner -> minimal fix in
isolated copy -> independent review -> integrate against unchanged source
preimages -> rerun affected gates. Any demonstrated second dispatch/debit,
unauthorized execution, false refund state, or unverifiable evidence is a
technical no-go until resolved. Failed or skipped tests stay visible; never
weaken assertions or silently remove scenarios to obtain a green result.

## Management loop and evidence contract

Observe task updates and artifact changes; plan the highest-priority unblocked
slice; delegate with one owner and explicit completion criteria; execute in the
assigned resource; verify artifacts and important calculations; integrate only
reviewed changes; reassess gates and repeat. Completion reports must name source
identity, files changed, exact commands/results, untested conditions, remaining
risks, and the next executable action. Completion is accepted only after the
responsible manager reviews evidence; mandatory independent verification for
fixes can reject the implementation or its manager's claim. Every run record
must include source preimage/hash, run ID, exact cwd and command, relevant
configuration names without secrets, pass/fail/skip counts, changed or excluded
fixtures, and artifact digest. Counts from overlapping suites are not added as
unique tests. The eight preliminary checks reported by e0-9564 remain separate
historical input, not part of df-ba0b's current run totals.

Do not keep agents busy on duplicate or speculative work. A stalled report is
reassigned only after identifying whether its dependency, environment, scope,
or approach is actually blocked. External partner access is a separate gate,
not a reason to abandon executable local verification.

Allocation is qualitative: safety, authorization, scope and ownership gates
first; then consequence, milestone relevance, decision-changing evidence,
remaining effort/delay and explicit dependencies. Do not invent success
probabilities or rank blockers using speculative ROI arithmetic. The bounded
local technical gates are accepted on the frozen snapshot. Qualified partner
utility and staging access are the current company bottleneck; secondary private
lead reports do not establish a committed pilot. A need for another core
capability is unsupported and remains frozen.
Stop local expansion once the accepted technical gates leave only external
input. No title-only staffing or new task to bypass a gate is useful work.

## Decision log

- Inventory found six peer kickoff roots before this program created workers.
- Reused the existing eight-specialist engineering pod rather than duplicating
  it; added one independent verifier of management itself.
- Consolidated management work from e2-6aeb and duplicate engineering from
  e0-9564. Retained only e2-6aeb's bounded arithmetic check. Preserve e0-9564
  reviewers `transaction_integrity_lead` and `security_platform_lead` for
  independent review when an actual patch exists.
- Assigned df-ba0b sole engineering integration/test scheduling responsibility.
- Initial checkpoint accepted no source changes. Subsequently all 15 paths
  were independently reviewed and applied; no deployment/customer claim is accepted.
- Program lead independently inspected the malformed-key regression and failure
  log. Reserved candidate changes to `app/routers/mcp_standard.py` plus one
  narrow regression test through df-ba0b; original source remained untouched
  until independent fix review, then the reviewed files were applied.

## Final accepted run set

Durable packet:
[launch-readiness evidence](/Users/sellers/.codex/visualizations/2026/08/31/01a056df-ba0b-7472-b6cc-747dccc8cdd9/launch-readiness/README.md).
The final archive is `tested-source-acceptance.tar.gz`, SHA-256
`7459183a9d86a579e74a4d2c9b147c3fbea785d2f2a4f825c322c04f766f0ed5`.
The application record reports seven final paths applied and 22 total task paths;
all 572 original whitelist files match f0c7. Git index before/after remains
`e8e57c5e8c990f2b980d8fd6f66df36ba1c82e2e1513aa7ea0f8036135cbe771`.
The combined patch SHA-256 is
`6fa31bdc084a7f19810d4d013c70747075e3d9f2422a75f6eb8cb3fe378a5596`.
No commit, push, deployment or production request was performed.

The program lead accepts the completed
[independent final provenance audit](/Users/sellers/.codex/visualizations/2026/08/27/01a04285-223e-7a31-ac23-96729c605928/engineering-provenance-2026-08-31.md)
and [operator handoff](/Users/sellers/.codex/visualizations/2026/08/31/01a056df-ba0b-7472-b6cc-747dccc8cdd9/launch-readiness/reports/operator-handoff.md).
The independent audit checked all 572 archive/original hashes and modes, ten
acceptance command/log bindings, 194 packet entries, 69 dependency pins,
application/index identities and fresh OS-only cleanup observations. The packet
inventory at that audit cutoff has SHA-256
`2d6fda16296e876bbf59a893637ca89381aba5f9e4c2722e3ac0650a7090f676`.
This is direct artifact verification, not independent application reexecution
or a clean-room dependency rebuild. The completed audit arrived while a stalled
assignment was being reassigned; both proposed replacement audits were cancelled
immediately, preserving one verification result and no duplicate approval gate.
Engineering then copied that completed audit and its review record into the
packet, preserved the exact 194-entry cutoff inventory, and added the README
link. Program control independently checked this metadata-only delta: three
added files, README changed, all 193 other audited entries unchanged, exact
197-file membership, matching new-file hashes and an unchanged copied audit.
Current `packet-inventory.json` SHA-256 is
`f56a24f366514bd31f90ffcf3da8224713e121a27b35f04c89b91a8601bbf94d`.
No source/archive/command/log/application bytes changed after the independent
audit. The packet is frozen; no additional acceptance rerun is required.

Only `acceptance-*` records describe the final source. Earlier `release-*`,
`closure-*`, `final-*` and candidate logs are retained history, not substitutes.
`logs/acceptance-command-manifest.json` binds all ten completed exit-zero runs to
`f0c7d4236ffc785ca98e002bc4ea3f1759c9d0cc30e972798f37c2a021b5c289`.

| Final command group | Result |
| --- | --- |
| Full SQLite | 1688 passed, 65 skipped, six deselected |
| PostgreSQL default-pool regressions | 65 passed, including 20 calls and 20 stable replays |
| Actual singleton application pool (1/0) | 36 passed, including cleanup |
| PostgreSQL crash/recovery | Nine passed |
| PostgreSQL permit/billing concurrency | 18 passed |
| PostgreSQL real-driver trust loop | Five passed |
| In-process production posture | Six passed; no production requests |
| Trust release gate | 133 focused, 403 coverage, 10 discovery; 83.27% coverage; demo/OpenAPI/inventory passed |
| Ruff | Passed |
| Mypy | 171 source files passed |

Counts overlap and must not be added as unique tests. Of 65 ordinary-suite
skips, 63 are separately exercised PostgreSQL cases (9+18+5+1+30); optional
Playwright remains unexecuted and the 10 MiB payload observation executed,
accepted the request, then skipped. The six production-posture deselections
separately passed on this same source.

The program lead corrected a reviewer's accidental use of historical
`release-trust-execution.json`: final `acceptance-trust-execution.json` binds
before/after 572 files and exit 0 to f0c7. Its log SHA-256 is
`f57d2b26d51f82a7e03e01e0e3dfa708af8a4446b1515e0edd79763254e99c8b`.
The independent reviewer verified that correction and cleared the hold; no
unnecessary rerun was required. Final cleanup has ten successful ownership,
shutdown, retained-data and unchanged-user-service checks.

## Chronological evidence log (latest first)

These entries preserve what was known at each checkpoint. Earlier pending,
blocked or candidate wording is superseded by the current tables and final run
set above. A historical successful component is not a final-source acceptance.

- Actual application singleton proof: `acceptance-poolone.log` reports 36 passed,
  four warnings in 2.27 seconds, zero skips and exit 0 including teardown.
  `DB_POOL_SIZE=1` and `DB_MAX_OVERFLOW=0` configure the production singleton
  engine before initialization; per-service factory substitution is gone.
  The 36-case module contains six default/unit and 30 real PostgreSQL cases:
  warm/cold pending creation, refund completion/denials, current and valid legacy
  public signing input, terminal/missing/mismatched preflight refusals and the
  preflight-to-lock completion race. Test SHA-256:
  `6fc6d6b5f5eaa46e33bb27d5ea14cb79862e4a9e8fe236070941e87e6701e71c`.
  Whole-source manifest SHA-256:
  `f0c7d4236ffc785ca98e002bc4ea3f1759c9d0cc30e972798f37c2a021b5c289`.
  The four approved production hashes are unchanged. Default-pool burst and
  full/crash/concurrency/release/posture gates must bind this same source.
- Independent review approved the exact four production files handed off in
  `acceptance-source-review/source-manifest.json`; this is not whole-candidate
  acceptance. A short closed preflight checks checkpoint/permit/approval before
  active-key preparation; the original locked recheck remains authoritative.
  If the record terminalizes after preflight, no receipt/work-item persists.
  That race may still prepare/reactivate key metadata; neither unconditional
  zero side effects across that race nor disable-before-commit precedence is
  claimed. The singleton-pool, valid legacy, refusal/race and cleanup runtime
  proofs remain pending on the final combined test/source manifest.
- V5 independent review accepted static propagation coverage but withheld final
  acceptance. Its small-pool tests use a separate engine with module factory
  substitution; the reviewer requires the shared application engine/session
  seam so an unpatched path cannot obtain hidden pool capacity. The public
  legacy signing-input case needs a valid legacy receipt and native signature
  verification, rather than only a corrupt legacy rejection. Key preparation
  before invalid/complete-record checks may change denied or no-op behavior;
  engineering/review are checking a minimal preflight with locked revalidation.
  These are concrete closure questions, not authority for broader redesign.
- Program lead inspected v5 runtime logs: full SQLite reports 1688 passed,
  44 skipped, six deselected. PostgreSQL reports 80 passed **and four teardown
  errors**: refund test receipts remain referenced when the inherited seeded
  permit fixture tries deleting its permit, then key cleanup also fails. The
  run is failed, not an accepted 80-pass gate. The test author must clean only
  owned test rows in dependency order, preserve all business assertions and
  rerun on fresh owned PostgreSQL. The failed log stays in the final evidence.
- V5 frozen source: `logs/closure-source-manifest.json`, SHA-256
  `c79be88f85531399d2debdf937fe107adc30593a9872a72b11edc288735854b1`.
  Three exclusive test working directories and fresh databases have begun the
  full SQLite, PostgreSQL 80-case and nine-case crash suites. Each
  `closure-*-execution.json` binds command, cwd, environment, source before/after,
  log and exit status. No earlier candidate result is substituted for these
  pending runs. Operator R4 logic is accepted; only final metadata remains.
- Operator manager accepted R4 replay procedure and R3 PostgreSQL/extractor/Git
  helper safety logic after static review; no remaining findings in that scope.
  This includes disabled ambient pip configuration and explicit offline inputs.
  Final filename/hash-only binding does not require another duplicate logic
  review. Final candidate application, archive, valid-case helper result and
  resource cleanup remain separate pending evidence. The full pinned-package
  reinstall and assembled PostgreSQL recipe were not rerun end-to-end.
- Final provenance verifier completed the invariant portion read-only:
  all 69 dependency pins match runtime inventory and installed distribution
  metadata; ten v3 command/source/log bindings include the failed burst; eight
  available v4 receipts bind to their 572-file source with consistent before/after
  hashes and chronology. Eleven negative-evidence files remain retained. This
  does not yet verify final v5 archive membership or application. Each replacement
  gate, including six in-process production-posture cases, needs its own exact
  source/run record rather than inheriting the v3 result.
- Replacement release candidate manifest:
  `9601eccc5b7b06b691260f88563d77a3a04bed2f3689ba26122070edf1f495f3`,
  572 listed files and 19 changed paths. `release-regressions.log` reports
  72 PostgreSQL cases passed in 5.03 seconds, including the strengthened burst
  and seven session/verification cases. The actual application pool remains
  5 plus 10 overflow. A separate test-owned one-connection pool exercises
  bounded progress. Before/after source checks are retained in
  `release-regressions-execution.json`. Replacement Ruff and mypy (171 files)
  passed; full/crash/concurrency and independent acceptance are pending.
- Independent review approved the initial four-path P10 candidate: borrowed
  session lookup performs no extra checkout/commit/rollback/close and refreshes
  cached signing-key identity so disabled keys still fail closed. Program then
  challenged a residual initially labelled non-blocking: `refund_reconciliation.py`
  starts a transaction at line 499, holds receipt/wallet/charge/permit row locks
  at lines 527/554/559/564, then calls `verify_signature` at 573 without passing
  that session. Its process lock does not exclude ordinary requests waiting for
  those database locks. Engineering and independent review must resolve this
  same dependency before closing P10; successful burst evidence is retained.
- Engineering's static refund trace found an earlier nested lookup at receipt
  verification (`verify_model` -> signing `verify_payload`), showing that
  fixing only the permit call would be incomplete. This refund-specific
  one-connection runtime probe is still pending. P10 now owns the same
  session-propagation behavior across four production files: signing keys,
  permits, receipts and refund reconciliation. The regression must exercise
  actual receipt and permit signatures without mocking validation or adding
  pool capacity. Independent review and engineering are inventorying all
  active-session verification call sites before the next freeze.
- The final implementation inventory also caught the portable
  `signing_input` -> `signing_input_for_model` verification/fallback branch
  retaining a read session. The same four-file fix now includes that branch,
  with public signing-input assertions inside existing one-connection cases.
  The expected candidate has a 15-case session regression module plus the
  strengthened rapid-fire test and compatible PostgreSQL test wrapper; seven
  remaining application paths, 22 total task-changed paths, 572 listed files.
  These are candidate inventory counts, not final test/apply acceptance. No v5
  runtime result or source freeze had occurred at this inventory checkpoint.
- The inventory also found the write-side pending-refund path calling receipt
  signing while holding a transaction; active-key provisioning opens another
  connection. Engineering is bounding a real one-connection creation probe and
  the already-existing `sign_payload_with_key_id` prepared-key pattern. Do not
  redesign key bootstrap/commit/cache lifecycle or silently change disabled-key
  semantics. Any extension must remain the same demonstrated nested-checkout
  reliability defect, with independent review of signing-key timing and mapping.
- Reality/ownership correction: the engineering manager confirmed that only the
  root has executed application/database tests; specialists author code/tests
  and inspect source, while platform owns cluster provisioning. Earlier wording
  about the refund "trace/probe" described source analysis, not an executed
  refund runtime test. The prior 72-case suite and its one-connection permit
  verification case did execute; the new refund retry and warm/cold pending
  creation cases have not. No runtime result is inferred from their source.
- The guarded replay helper's initial integrity checks used `assert`, which
  Python optimization can disable. Operator review rejected this safety
  dependence; archive and PostgreSQL ownership/path/identity guards are being
  converted to explicit failures, including an optimized-mode negative check.
  Git environment isolation and fail-fast extraction guards were accepted.
- Operator review challenged unsafe reproduction instructions before execution:
  ambient `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE` could redirect Git writes,
  and a failed `cd`/fetch could leave subsequent commands in the wrong checkout.
  Engineering is correcting the recipe to use a cleared environment, disabled
  ambient Git config, fresh task-owned extraction, canonical-path guards and
  fail-fast commands. Mixed reset changes temporary HEAD/index, not source
  bytes. No unsafe reproduction command was run by the operator reviewer.
- Supplemental `final-postgres-datetime.log`: five passed, exit 0.
  `final-postgres-rapidfire.log`: one FAILED, 13 warnings in 32.32 seconds,
  QueuePool size 5 plus overflow 10 exhausted at the 30-second timeout.
  This is a new reliability finding, not a skip or successful closure. The same
  existing test failed on baseline in 32.36 seconds, so it predates billing-v3.
  The runtime trace follows `authorize_and_reserve` -> `_validate_model_for_action`
  -> `verify_signature` -> `SigningKeyService.verify_payload` -> `get_public_key`:
  the permit lock holder needs a second pooled connection while pool slots are
  occupied by requests waiting for that permit. Engineering owns a two-file
  caller-session propagation candidate and focused tests. Original source is
  unchanged by this follow-up so far. The earlier eight-command packet is incomplete
  until both follow-up runs and the failure's disposition are recorded.
- Final source manifest SHA-256:
  `a8907221800e8ab2f467e1e3e5e51c480686041b5cb77130f6740cbeb1b3d43b`.
  ee-5fb7 independently rehashed all 571 entries against the original checkout
  and all three tested copies: zero missing/mismatched entries. This establishes
  the listed scope, not completeness of every file in the dirty repository.
- `logs/final-application.json` records all 15 changed paths, their original and
  tested digests, the 11 remaining applications and four previously applied
  files. Git index before/after SHA-256 is unchanged:
  `e8e57c5e8c990f2b980d8fd6f66df36ba1c82e2e1513aa7ea0f8036135cbe771`.
  Combined patch SHA-256:
  `2e0d2806db114e10ba59720b744e78fb6e7abbb6952f601afe9d552b68da2fe1`.
  No commit, push, deployment or production call was performed.
- Final full suite: 1682 passed, 35 skipped, six production-posture cases
  deselected. Those six separately passed in-process. Final PostgreSQL suites:
  64 new regressions passed, 18 existing concurrency cases passed, nine
  multiprocess/crash cases passed. These are overlapping suite results, not a
  summed unique-test total. Final Ruff, mypy (171 files), and trust release gate
  passed. The program lead directly inspected the log tails.
- Of 35 skipped cases, 27 correspond to the separate 18+9 PostgreSQL runs;
  another five real-driver trust-loop cases separately passed. The rapid-invoke
  PostgreSQL case separately FAILED. Optional Playwright remains unexecuted.
  The 10 MiB payload observation executed, succeeded, then called `pytest.skip`;
  it is an observed missing enforcement boundary, not an unexecuted case.
- e0-9564 explicitly approved exact billing-v3 after reviewing manifests,
  preimages, executed PostgreSQL source and results. The R2 lock cycle was real;
  v3 preserves writer exclusion while allowing FK KEY SHARE and retains the
  attempt compare-and-swap serialization. Upstream effect and gateway state
  remain non-atomic; uncertainty and authoritative reconciliation are required.
- Residual payload risk: e0-9564 independently verified that credentialed
  `app/routers/mcp.py` parses `/mcp/messages` with `request.json()` without an
  application body-size limit. The program lead confirmed that parse path.
  The 10 MiB fuzz case skips on a successful result and is not passing security
  evidence. The controlled staging experiment must use a restricted dedicated
  instance, approved small-schema tool/wallet scope, and an actually tested
  ingress limit rejecting overlarge requests with 413 before app parsing.
  256 KiB is the reviewer's proposed pilot limit, not observed configuration.
  The operator/partner engineer owns confirming that guardrail before exposure;
  no ingress or production limit was verified or changed here. A workflow that
  requires larger payloads remains held until its appropriate limit and negative
  test exist. This does not block the loopback synthetic experiment already run.

## Historical evidence checkpoints

The following observations preserve the failed attempts and decisions as they
occurred. Their pending/held wording is historical and superseded by the current
gates and final checkpoint above; do not treat an earlier candidate as final.

- Billing-v3/final candidate `final-postgres-regressions.log`: 64 passed, 54
  warnings in 4.94 seconds, using the single-loop test configuration and fresh
  owned PostgreSQL database. `final-full-suite.log`: 1682 passed, 35 skipped,
  6 deselected. Earlier failures and stopped R2 run remain retained. Final
  nine-case crash rerun and existing 18-case concurrency rerun are required;
  source hashes, v3 approval and final integration must still be checked.
- The complete response-loss scenario passed: `integrated-postgres-multiprocess.log`
  reports 9 passed, 2 warnings in 149.57 seconds, exit 0. ee-5fb7 independently
  checked actual execution CWD `integrated-pg`, clean environment/preflight and
  both methodology file hashes against the approved candidate. These nine cases
  include the eight baseline cases; do not add those eight again. It remains a
  local synthetic fixture experiment, not a partner-owned pilot.
- R2 lock observation was not dismissed as a harness-only problem: billing held
  an identity `FOR UPDATE` lock while cleanup's attempt update waited for a
  foreign-key lock on that parent. Advancing billing could create the opposite
  wait edge. The owner stopped only its test process, preserving log/database.
  Candidate v3 uses `FOR NO KEY UPDATE` for non-key identity checkpoint updates;
  competing writers still exclude each other while foreign-key `KEY SHARE`
  can proceed. Program lead checked the
  [PostgreSQL 16 conflict table](https://www.postgresql.org/docs/16/explicit-locking.html#LOCKING-ROWS)
  and [SQLAlchemy flag semantics](https://docs.sqlalchemy.org/en/20/core/selectable.html#sqlalchemy.sql.expression.GenerativeSelect.with_for_update),
  then compiled `with_for_update(key_share=True)` with the actual installed
  library and observed `FOR NO KEY UPDATE`. This validates the lock assumption,
  not the complete runtime fix; v3 must pass bounded winner schedules on PostgreSQL.
- df-ba0b recovered from a task turn error into the same task/new turn; no runtime
  owner was duplicated or transferred. Current source integration remains
  solely with that engineering manager.
- Combined isolated candidate full suite:
  `logs/integrated-full-suite.log` reports 1682 passed, 35 skipped, 6 deselected;
  integrated Ruff passed and mypy found no issues in 171 files. This is not yet
  acceptance of the original working checkout or optional PostgreSQL gates.
  The three simultaneous runs use distinct `integrated`, `integrated-pg`, and
  `integrated-pg-reg` working directories, SQLite paths and PostgreSQL databases.
- Initial combined PostgreSQL regressions failed with 41 failures/41 errors
  from cached asyncpg connections used across different test event loops.
  Failed database/logs were retained. R2 uses a fresh owned database and one
  pytest-asyncio session loop, with AnyIO plugin disabled, same 64 assertions,
  no production pool change. R2 then stalled after one case; df-ba0b is inspecting
  the active lock relation and the unbounded cleanup await in the second case.
  Neither failed/stalled run is accepted PostgreSQL correctness evidence.
- Billing-v2's exact four-file static review was approved by e0-9564, conditional
  on PostgreSQL race/lock evidence. Its 209-pass focused suite includes rollback,
  counter/alert/freeze state and postcommit-notification cases. Standalone
  numeric review is approved only for its reviewed schema/router/None-guard
  semantics; it does not approve later combined velocity bytes transitively.
- P9 exact two-file methodology accepted by ee-5fb7:
  fixture `bd6a5a227397067c9296fa6510ba4192a83128d4e4ea645a70d2a07881431968`;
  multiprocess test `684ca863d559708dff1f1a9f0bdb7cbef2cd0cacc4f128c3ea663c4c11e1492a`.
  Static inspection preserved all eight prior cases and verifies the six
  recorded methodology constraints. Runtime acceptance is still pending.
- P2 integration accepted for patch SHA-256
  `c786cdd4859a199f806e4f1ad1c0de44250830a92be2f8e1d155820f148c2be1`.
  Program lead independently hashed the applied original files:
  `app/routers/mcp_standard.py` =
  `991ac11fbf5e144635b30b603846baff1c2775db6be05162477e20296e27de9a`;
  `tests/test_mcp_idempotency_validation.py` =
  `33e6a54127d08ef82b14ae325f3e82016bd66668153d4079f39ea3d366bdf475`.
  These exactly match e0-9564's independent approval and the 34-pass candidate.
  Application record: `/tmp/amw-launch-20260831/logs/mcp-application.json`;
  final test log digest:
  `b222c8066cb7bc7951ad15294624c78156bd91f3de1c09dbd48a0b3b939c5adf`.
  This accepts P2 only, not the final integrated suite or remaining patches.
  A subsequent lint-only correction replaced imported fixture aliases with
  explicit same-name reexports; no assertions or router code changed. The
  superseding test SHA-256 is
  `7fcd1e73dd3515e31fbd3b2f276c75340d8ebc8292edb279b53cb79ad7bcb5cd`;
  `mcp-final-lint.log` passed and `mcp-final-lint-corrected-tests.log` again
  reports 34 passed. Program lead verified original/candidate equality and
  accepted `logs/mcp-test-lint-amendment.json` as the corresponding chain update.
- P3's 70-pass candidate and seven regression cases received e0-9564 static
  approval matching `patches/evidence-manifest.json`. It verifies finite
  negative debit and exactly offsetting finite positive correlated refund for
  online evidence. Offline receipt signatures cannot detect later mutable
  ledger corruption; that trust boundary is unchanged. Original evidence
  source was subsequently applied by df-ba0b. Program lead verified both
  original file hashes against `logs/evidence-application.json`:
  evidence service `bc13dcbbece9f28b0ae3e3ed39d985f78894da07f37cd3429328aa101adeb952`;
  regression test `1a69b86e780617c0f798ce33eae32904e0176a1c6fa8a2edb13a47169b7f096d`.
- Independent program verifier checked all 565 source manifest entries against
  original, runtime, runtime-pg and repro: no included file mismatch or omission.
  Manifest SHA-256:
  `430b1272ced43b6e36020b9f6ff6782a4b3a11234b21fddfbecedc80128ac236`.
  Canonical source digest (sorted path, NUL, file SHA-256, LF):
  `8ae68c2591c591effe006e512463eba2b2a4f7a71bc76557608fd5db3d41aa51`.
  With two safe tracked templates restored in ordinary runtime, the 567-file
  digest is `0a10e9ac158c45dcc57652c4dd4c906048ec91c038107cff9ef124b87605f905`.
  Both original and runtime base HEAD resolve to
  `46d7310a3b771542dfb1fe874b5cff9d6bf137b2`; dirty bytes are captured separately.
  Untracked agent/editor configs, `.envrc`, technical recommendations and this
  later registry are outside runtime scope. New probe/candidate files require
  supplemental hashes and are not covered by the baseline manifest.
- Program lead read `logs/ruff.log`: `All checks passed!`; `logs/mypy.log`:
  `Success: no issues found in 171 source files`.
- Program lead read `logs/trust-release-gate.log`: suite sections report
  `133 passed`, `403 passed`, and `10 passed`; final release-gate marker passed.
  These are section counts, not a deduplicated total. Offline receipt and
  tamper checks passed within the local demo. PostgreSQL and new defect probes
  were still running/pending at this checkpoint.
- Exact commands, environment and artifact digests are pending df-ba0b's
  runtime report. Treat the above as observed log output, not complete G1-G5
  acceptance or proof against newly identified schedules.
- Independently recomputed e2-6aeb's calendar arithmetic using Python `date`:
  Aug 12 to Sep 11 is 30 elapsed days and 31 inclusive date labels. After EOD
  Aug 31, Sep 1-11 supplies 11 dates. Conditional on zero completions, target
  daily rates are `10/11`, `3/11`, `2/11`, `1/11`, `1/11` for interviews, use
  cases, qualifications, pilots, and commitments. Actual counts are unknown;
  these are planning ratios, not observed conversion rates or forecasts.
- `logs/postgres-multiprocess.log` ends `8 passed, 2 warnings`; migration 034
  applied on the disposable database. This is separate from ordinary release
  gates and the older eight preliminary checks in task e0-9564.
- `logs/mcp-validation-repro.log` contains three failed assertions for overlength,
  wrong-type and empty explicit metadata keys. The probe issues two identical
  requests and counts the tool calls and ledger entries; all three observed
  `(2, 2)` instead of `(0, 0)`. This is reproduced invalid-input behavior, not
  a claim that accepted valid keys defeat the existing replay mechanism.
- Initial `logs/full-suite.log` failed collection because the copied runtime
  lacked a resolvable Git HEAD for preflight tests. Engineering owns repairing
  snapshot Git provenance and rerunning; do not exclude the tests or mislabel
  a synthetic snapshot commit as the original checkout's HEAD.
- Engineering restored the actual original base commit metadata in the temporary
  runtime. `logs/full-suite-with-git.log`: 1612 passed, 34 skipped, 6 deselected,
  6 failed. Five failures were missing tracked templates in the sanitized copy;
  one was example manifest 033 versus migration head 034. Template restoration
  and rerun are assigned; no tests were excluded to hide failures.
- `logs/accounting-reconciliation-repro.log`: 2 failed; program lead read both
  assertions. One schedule charged 1.5 credits after a zero-charge terminal
  receipt, and the other failed repair with `dispatch_charge_transition_invalid`.
- `logs/accounting-input-repro.log`: 4 failed, 1 passed. Zero daily cap became
  `None` and allowed a 0.1-credit charge. Excess decimal input was stored at
  eight decimals; runtime signature implications require explicit confirmation
  before choosing rejection versus normalization semantics.
- `logs/permit-signature-roundtrip.log` explicitly shows both excess-precision
  permits issued with HTTP 201 and persisted with `stored_signatures_valid:
  [False]`. Input validation will reject unrepresentable values before signing;
  this contract tightening was called out to the user. P1 owns the shared
  `billing_engine.py` zero-limit guard; P8 owns separate router/schema/velocity
  files to avoid competing writers.
- `logs/onboarding-preflight-quickstart.log` after safe template restoration:
  97 passed and one genuine revision-manifest failure; `logs/production-trust.log`:
  6 passed. `logs/postgres-concurrency.log` is reported 18 passed by df-ba0b;
  the program lead still requires final run provenance and candidate reruns.
- Historical evidence matrix reviewed at
  `/Users/sellers/.codex/visualizations/2026/08/31/01a056e2-98a5-7070-9599-8cb94be2f0b3/launch-evidence/README.md`.
  It correctly separates unauthenticated historical checks, sample output,
  self-issued public receipts, and scenario definitions from current test
  execution. Do not reuse its pass counts as present evidence. Legacy arbitrage
  estimates and broad platform roadmaps remain excluded from this experiment.

## Continued management

Latest dependency check: `2026-08-31T21:01:28Z`. Engineering, independent review
and operator status are unchanged. The private partner-watch task now reports
that introduction channel `INTRO-20260831-01` received the founder's criteria
and confirmed a focus on people able to authorize a one-tool staging experiment.
Source: new task turn `b208c643-5879-49f9-9008-e84f97804fe7`; original sent/inbound
messages were not independently verified here. No specific introduction,
committed pilot, or new technical defect is supplied. The launch owner received
this bounded status update; the next useful event for this channel is a specific
qualified introduction, not another refinement message. G6 and all exposure
controls remain open. No prospect outreach, workers, application tests,
accepted audits or disposable services were started by this check.

The dependency heartbeat was reduced from every 30 minutes to every four hours
at `2026-08-31T12:58:57Z` after successive unchanged checks. Its scope and
ownership remain unchanged; concrete new evidence can reopen execution.

Prior substantive heartbeat review: `2026-08-31T10:51:26Z`. Existing engineering,
independent review and operator tasks report local completion; no new runtime
failure or source-change request was supplied. The final source-manifest and
197-entry packet-inventory digests were rechecked unchanged. This did not rerun
application tests or rehash the current checkout. The independent fix-review
manager corrected its final summary: 63 PostgreSQL skips and six production
deselections were exercised separately; the proposed ingress cap remains
unverified configuration.

The existing private partner-watch task
`6a7d0101-ae1c-83e8-b6d3-b269ceea481f` supplied secondary lead reports. The launch
owner reviewed its latest two turns without creating workers or sending
outreach. Provisional prospect `PW-20260831-01` has the most specific reported
next step: onboarding and a 20-minute discovery call concerning currently
human-gated consequential actions. Identity stays in the private task record;
the original inbound and present availability of the offer are not verified.
This is a named lead, not a committed partner-owned experiment. Other reports
describe an introduction channel, general interest, and an explicit no-follow-up
hold; do not treat any of them as permission for outreach or tool execution.

Next owner/action: founder schedules the offered qualification conversation;
launch owner records one selected staging mutation, a committed partner
engineer and date, authoritative effect lookup, and permission for the
controlled response-loss case. These fields are all still unverified. Program
control then sequences restricted staging and an actual pre-application HTTP
413 check before exposure. No capability is unfrozen and no test resource is
restarted by this intake. This checkpoint updates the existing record rather
than creating another report or execution pod.

The app heartbeat `amw-operational-validation-management` is active for this
task every four hours. It resumes this same record and existing managers, not a
new task/pod. The initial setup call failed argument validation without creating
an automation; the corrected create call succeeded and its app card was viewed.
The bounded local engineering work is complete. The heartbeat was rechecked as
ACTIVE for this task at closeout and provides continuity for partner input,
changed evidence or newly scoped existing-loop defects. Keep external partner
qualification and verified staging ingress controls explicit; do not manufacture
local work or restart test resources merely to keep agents busy.
