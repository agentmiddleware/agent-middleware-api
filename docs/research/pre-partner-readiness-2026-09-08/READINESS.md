# Internal preparation before partner testing

September 8, 2026. **The existing one-tool workflow has passed an extensive internal rehearsal. The current hosted deployment is not ready for partner testing.** The remaining immediate work is an operator release: patch the running Redis server, reconcile pending Railway changes, deploy a verified API candidate, and qualify the customer environment and its provider restore procedure.

The critical distinction is between a tested source tree and the service a partner would reach. Redis is still running 8.2.1, despite a configured 8.2.9 image. The public API still reports an older source commit. These are verified release blockers, not requests for a partner to debug the product.

## Source and delivery

- Starting source: `795cd9b3c691a2c697bfef364546940dd5780e93`.
- Final base after refreshing main: `12f9bc960504027b851cd32005850d8969ae0c7c`.
- Corrected candidate: `ff8182bcc9011c052b412e23eff20875d6f650b8`.
- [Draft PR #417](https://github.com/PetrefiedThunder/agent-middleware-api/pull/417): 23 successful hosted checks, none failed or pending at final readback. The PR remains a draft and is not merged or deployed.
- Isolated checkout: historical disposable checkout, not retained in this curated set.
- Packaged evidence: the raw JUnit, provider evidence, and generated validation
  indexes are not retained in this curated source set.
- Existing economics reports and the pilot workbook remain in the original checkout. No customer actuals or partner acceptance rows were filled using synthetic results.

The implementation is limited to validation tooling and documentation. No application route, billing rule, database schema, authorization behavior, deployed configuration, or product capability was changed by this PR. Main advanced during preparation; the candidate was rebased and the full application suite, PostgreSQL checks, release gate, dependency audit, HTTP replay, restore, and site checks were repeated in a fresh application environment. SDK and wrapper source trees were unchanged, and hosted CI repeated those package checks. The maintenance work fits the existing customer-validation freeze.

## Fixes completed

### The PostgreSQL CI job now uses PostgreSQL for its trust primitives

The job previously supplied `TEST_POSTGRES_URL`. That variable is consumed by `TestPostgresTrustLoop` in `tests/test_postgres_datetime_binding.py`; it does not select the database used by the shared application fixtures. The ordinary permit, receipt, MCP, audit, key-management, and idempotency tests consequently ran against SQLite.

The corrected job explicitly migrates PostgreSQL, sets `DATABASE_URL`, and uses one event loop for the asyncpg connection pool. The special datetime fixture runs separately because it rebuilds the application and creates its own connections. The complete corrected primitive command passed on PostgreSQL 17.11 for the final candidate; the initial source also passed on 16.14 and 17.11. Historical green runs do not retroactively establish this broader database coverage.

### The PostgreSQL Make target now invokes a real PostgreSQL proof

`make prove-trust-plane-postgres` previously migrated the supplied database and then invoked `demo_trust_plane.py`, which deliberately overwrites its database URL with a disposable SQLite file. The target now aliases the existing multi-process crash proof. That harness checks PostgreSQL, explicit isolation, environment, migration revision, and an empty application database before its test operations.

The ordinary demo remains a SQLite demo with its own synthetic signing material and tamper checks. No production database URL is passed through to that destructive demo. The Make command expansion was checked, and its underlying crash suite was executed on 17.11 for the final candidate, with both 16.14 and 17.11 covered on the initial source. Run either PostgreSQL Make target only against an explicitly dedicated database: its Alembic migration command precedes the harness's emptiness guard.

### Scanner compatibility and workflow lint

Gitleaks 8.30.1 decodes a public base64 test seed before scanning it, so the existing encoded-value allowance did not cover the same decoded fixture. The change allows only the exact, anchored decoded public test string. A fresh working-tree scan then passed, and the deliberately bad low-entropy credential canary still caused scan failure. The ruleset and secret detection remain enabled.

One shell variable was quoted to clear actionlint. No real credential was found in this working-tree scan. This is not a new historical-secret revocation audit.

## Executed checks

Counts below overlap deliberately: PostgreSQL and production posture exercise different environments, while the release gate repeats a focused subset. Do not sum them into a count of distinct product behaviors.

| Check | Result | Evidence scope |
|---|---:|---|
| Full application suite | 2,565 passed, 42 skipped, 5 deselected | Python 3.12.13, default test posture; includes proof and dormant tests |
| PostgreSQL trust primitives | 55 passed on 17.11 | Permits, receipts, MCP, audit, key management, idempotency |
| PostgreSQL process/crash harness | 17 passed on 17.11 | Real independent API processes and synthetic upstream process; durable effects are observable |
| PostgreSQL permit concurrency | 17 passed on 17.11 | Real row locks and competing operations |
| PostgreSQL datetime regression | 14 passed on 17.11 | Includes five driver-specific integration cases |
| PostgreSQL wallet/status guards | 41 passed on 17.11 | Spendability, KYC authority, freeze and debit checks |
| PostgreSQL security fuzz battery | 12 passed on 17.11 | Includes 20 concurrent unique invokes with exact aggregate charge |
| Production posture | 5 passed | Local production-like flags, synthetic material; no hosted calls |
| Canonical trust release gate | Passed | IaC contract, focused tests, coverage, demo, discovery, OpenAPI and inventory parity |
| Trust-core coverage | 80.55%, above the 80% gate | 427 selected tests; not whole-application coverage |
| Clean SDK wheel | 106 passed | Built wheel installed into a new environment; source-path overrides removed |
| Clean wrapper installations | 80 passed | OpenAI 65, AutoGen 6, LangChain 5, CrewAI 4, each in a separate environment |
| Red-team executable proof | 10 attacks denied | No attack debit; positive control charged once; 8 supported denials had signed receipts |
| Opt-in constant loop | 1 local check passed; final hosted CI passed | Explicitly registered second tool for scope denial; local opt-in run belongs to initial phase |
| Site browser checks | 25 scenarios passed | Desktop 1440 px and mobile 390/320 px; no JS errors, no input transmission, no-JavaScript behavior checked |
| Ruff / mypy | Passed | 183 application source files type checked |
| actionlint / workflow YAML | Passed | Workflow syntax and shell analysis |
| Documentation reference gate | Passed | 440 references across 263 files |
| Dependency audit | 67 packages, zero known advisories found | Fresh resolution of `requirements.txt`; not a server-image or wrapper dependency audit |
| Existing environment consistency | Passed | 69 installed packages compatible |
| Economics model | 33 checks passed | Five explicit scenarios; existing observed provider totals reconcile |

The SDK and wrapper counts prove installation and their automated contracts. They do not prove compatibility with every future framework release or a partner's orchestration strategy. Initial PostgreSQL 16.14 results are archived separately; the final candidate's local database checks all used 17.11, while hosted CI used its PostgreSQL 16 service containers.

### Disposition of the default suite's skips

The 16 opt-in crash cases, 17 row-lock cases, five PostgreSQL datetime cases, and one PostgreSQL rapid-fire accounting case were subsequently exercised with real PostgreSQL. The opt-in constant-loop case was subsequently exercised over live local HTTP. The Linux-only YAML check was covered locally with direct parsing plus actionlint, and the workflow ran in hosted CI. One optional Playwright bridge test remains outside the local run; it belongs to a dormant/proof browser capability outside this pilot. The marketing site's real browser checks were executed separately. Five production-posture cases were deselected from the ordinary suite and passed in their dedicated posture.

No skipped case is counted as a passing test. The generated validation index and
individual result files are intentionally not retained in this curated source set.

## Live HTTP handoff and restart rehearsal

The documented quickstart entry point booted on a fresh loopback port with fresh state and persisted local signing material. `scripts/live_loop_proof.py` produced the complete synthetic handoff bundle. Its success and denial receipts were verified by the clean installed SDK wheel, from outside the repository's import paths. A modified signed charge failed verification with exit code 1; valid bundles returned 0.

The additional restart rehearsal performed 25 unique, scoped notes writes. It then stopped and restarted the actual quickstart/API processes, retained the same database and signing seed, and replayed all 25 original operation identities. Every replay returned the original receipt; the ledger entry set and durable notes count remained unchanged. This tests process restart with persisted identity, not a partner's actual orchestrator.

| Exploratory measurement | 25 unique calls | 25 replays after restart |
|---|---:|---:|
| Median HTTP latency | 18.171 ms | 4.389 ms |
| Nearest-rank p95 | 20.909 ms | 6.537 ms |
| Maximum | 24.532 ms | 11.428 ms |
| Additional effects on replay | — | 0 |
| Additional ledger entries on replay | — | 0 |

Portable success receipts in this sample were 1,117 bytes; successful invocation responses were 1,222 bytes. These are wire payloads, not total retained bytes per operation. Database indexes, audit rows, ledger rows, WAL, backups, denials, retention, and replication add storage.

This is a small sequential SQLite/local-tool sample on a developer computer. It is not a hosted latency forecast, a concurrency capacity test, an SLA, or a dollar cost estimate. The complete sample, including its maximum, remains in the data. The economics model and pricing hypotheses were not recalibrated from these numbers.

The raw HTTP validation and synthetic handoff bundles are intentionally excluded
from this curated index. The public key set in that historical bundle was
first-party synthetic material, not independently established issuer identity.

## Recovery rehearsals

A logical PostgreSQL backup of the synthetic crash-proof database was restored into a different empty local database. All 37 tables and 215 rows compared identically, with per-table hashes. The dump took 0.077 seconds and restore 0.369 seconds for this tiny fixture. These timings are not customer RTO/RPO commitments.

After restore, all nine receipts verified offline using the restored public keys, and 16 audit chains covering 24 events verified through the application verifier. No private signing key was needed for those verification operations. This proves restoration of the tested database evidence; it does not prove recovery of a customer's signing secret, provider PITR, a remote tool's data, production failover, or an arbitrary-instruction crash.

A separate real local Redis 8.6.3 rehearsal saved synthetic application state, restarted Redis with persistence enabled, and read the same state back. With Redis stopped, a new store in production posture raised `DurableStateConfigError` rather than silently falling back to memory. This establishes the tested store behavior and does not attest to the older hosted Redis binary.

The detailed table comparison, cryptographic verification, and Redis validation
snapshots are intentionally excluded from this curated index.

## Mapping to the partner acceptance checklist

The partner workbook remains Pending. This separate mapping records internal preparation only.

| Case | Internal preparation completed | Evidence still owned by the partner |
|---|---|---|
| A01 Ownership | Synthetic local gateway and independent test upstream rehearsed | Actual partner agent, staging tool, engineer, and permitted data boundary |
| A02 Success | HTTP quickstart, PG trust and remote crash harness | Expected consequential tool behavior in partner staging |
| A03 Replay | Same receipt/debit/effect assertions across workers and restarts | Their upstream evidence and their exact persisted operation identity |
| A04 Restart | Real process death and restart, durable identity reused | Their orchestration retry path, including identity creation before network I/O |
| A05 Conflict | Documented quickstart and idempotency tests reject changed payload | Their request serialization and middleware behavior |
| A06 Scope/budget | Scope denial, exhausted budget, row-lock races, concurrent accounting | Their selected tool scopes and meaningful budget |
| A07 Authority | Wrong wallet/key, expired/revoked/tampered permit and missing authority tests | Their credential lifecycle and delegated authority policy |
| A08 Uncertainty | Remote claim/effect/acknowledgement crash cases; no automatic redispatch | Their tool's authoritative effect lookup and reconciliation owner |
| A09 Offline verification | Clean installed wheel verified success/denial; forgery rejected | Partner engineer verifies in their environment against trusted key material |
| A10 Burden | Local latency/wire-size sampling; cost tracker and formulas checked | Real integration labor, hosted overhead, retained storage, failures and investigations |
| A11 Value | Bounded offer and decision template already drafted | Buyer, budget, decision date, willingness to continue and payment |

Fresh idempotency keys are distinct operations. Neither the local replay proof nor the PostgreSQL crash proof establishes universal exactly-once downstream execution. The configured upstream's own idempotency and authoritative effect records determine the end-to-end boundary.

## Hosted release blockers discovered

### 1. Critical: the running Redis binary is unpatched

Both the latest successful deployment metadata and an explicit read-only SSH `redis-server --version` command identify Redis 8.2.1. The service configuration names `redis:8.2.9`, and Railway carries a critical `CVE-2025-49844` remediation notice. Configuration intent is not evidence that a patched process is serving.

The Redis project's advisory describes authenticated Lua use-after-free leading to possible remote code execution, with the 8.2 branch fixed in 8.2.2. The configured 8.2.9 release also includes later security fixes. No exploit was run, and no compromise is asserted. Sources: [Redis advisory](https://github.com/redis/redis/security/advisories/GHSA-4789-qfc9-5f9q), [8.2.9 release](https://github.com/redis/redis/releases/tag/8.2.9).

Required closure: isolate the Redis release from unrelated pending changes; retain a valid recovery path; activate the reviewed patched image; verify the running binary, health, persistence, and application reconnect behavior. The provider's automatic-update notice is not closure. Avoid an aggregate environment deploy merely to activate this one service.

### 2. Public API release identity does not match the tested source

Both public health endpoints report `2880ca706d2f4779876097e9414b6f1fab691a3e`. This differs from the starting source and candidate above. The exact-SHA live preflight correctly failed. The operator must deploy the intended tested candidate and require both endpoints to return that exact identity before inviting a hosted test.

The running PostgreSQL binary was independently read through service SSH: 17.11. The additional local 17.11 runs match that major and minor version, but they do not exercise the provider's network, volume, CPU limits, or deployment process.

### 3. Railway has 69 staged changes

The existing production environment had a staged patch covering multiple
services and variable names. This task did not create, accept, cancel, or deploy
that patch. The read-only per-service snapshots exposed different staged groups,
including API, PostgreSQL, and Redis. Variable values were not retrieved or
placed in this report.

Required closure: establish the intended contents and owner of that existing patch, preserve unrelated work, and separate the precise release changes before activation. The API-only repository IaC is not permission to alter PostgreSQL, Redis, volumes, or PITR storage.

The separate redacted API-only plan completed: zero resources to add, three changes, zero resources to destroy. It proposes removing the API's GitHub source binding, choosing the Dockerfile builder, and setting `/health` with a 300-second timeout. This is not the existing 69-change staged patch. The deployment SOP describes a separately reviewed source disconnect and requires a reviewed maintenance window, configuration-file transition, and disposable convergence proof before activation. The local contract test does not satisfy those provider checks. Nothing was applied. The temporary local Railway link was removed afterward, and all rehearsal servers were stopped. The concrete plan is saved in [RELEASE_PLAN.md](RELEASE_PLAN.md).

### 4. A customer environment and provider restore drill remain unqualified

The current project has a PITR bucket and archive-related configuration names. That does not demonstrate a successful customer restore. The managed pilot SOP requires an isolated customer environment and a provider backup/restore qualification. The local logical restore above is useful preparation, not a substitute.

Required closure before a hosted partner session: supported hosting/commercial terms; an exact candidate and schema; private data services; a selected signing identity and recovery procedure; a completed provider restore drill; one bounded synthetic upstream action; and a named operator for uncertain outcomes. No customer project was purchased or provisioned during this work.

The provider readback is intentionally excluded because it contained
point-in-time operational identifiers. The original customer acceptance workbook
remains separate from these technical records.

## What to freeze and what to do next

Keep broad browser automation, KMS/HSM work, extra integrations, new billing models, shared multi-tenant architecture, and expanded audit products frozen. More capabilities would not repair the immediate release blockers or establish willingness to pay.

The next work is an operator release and qualification pass, starting with the confirmed vulnerable Redis runtime. Complete the bounded CI/tooling PR, reconcile the existing Railway patch, activate and read back the patched runtime, deploy the exact API candidate, and complete the hosted restore qualification. Then bring in one partner engineer to exercise A01–A10 with their own workflow and make the separate A11 commercial decision. No outreach was sent during this preparation.

The existing economics model still contains scenarios, not validated customer margins. The pilot package's setup fee, recurring price, labor budget, and included usage remain hypotheses. Internal synthetic measurements must not be entered as customer actuals or used to claim recurring demand.
