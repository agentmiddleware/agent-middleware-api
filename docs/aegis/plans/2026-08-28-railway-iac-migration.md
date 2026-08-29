# Railway Infrastructure-as-Code migration plan

Date: 2026-08-28
Branch: `codex/railway-iac-migration`
Baseline: `origin/main` at `2880ca706d2f4779876097e9414b6f1fab691a3e`

## 2026-08-28 execution addendum — restart defaults

This addendum supersedes the original references below to explicit restart
parity. One authorized disposable apply confirmed the effective Railway
defaults as `ON_FAILURE` with 10 retries, but Railway CLI `5.43.3` immediately
re-proposed both explicit fields because it builds the current graph from
sparse environment configuration and does not normalize those defaults.

The approved compatibility repair therefore leaves restart behavior
provider-owned and enforces that both restart properties are absent from the
tracked graph. Omission removes the known explicit-field false drift and is the
candidate convergent representation, but it accepts provider-default risk: any
actual restart delta is still an abort, and CLI or SDK upgrades require fresh
disposable validation before either field is reintroduced. Local regression
can validate the omission, not convergence; a new disposable
plan/apply/second-plan proof with the repaired graph is still required before
production activation.

## Aegis Visibility

This migration changes the owner of production service configuration from
deprecated per-deploy Config as Code to Railway's generally available
TypeScript project-level IaC, where an incomplete desired graph can delete
variables or resources. Planning is required to pin ownership, compatibility,
activation, and rollback boundaries.

## Plan Basis

- User direction: continue the project by prioritizing the Railway
  configuration migration; do not infer authorization for the separate
  production owner-key retirement.
- Project authority: `AGENTS.md`, especially the customer-validation scope,
  security-critical deployment rules, and exact final reporting contract.
- Repository baseline: `railway.json`, `docs/deploy-railway.md`,
  `SECURITY_LIMITATIONS.md`, `tests/test_production_trust_posture.py`, and the
  exact-SHA release workflow on current `main`.
- Platform authority: Railway's current Infrastructure as Code guide and
  TypeScript reference, plus installed Railway CLI `5.43.3` behavior.
- Read-only production evidence captured on 2026-08-28: project
  `agent-middleware-api`; API service `api-service`; one `us-west2` replica;
  custom domain `api.thisisatest.tech`; PostgreSQL, Redis, partner MCP, volumes,
  and PITR bucket are separate resources; the live API service had 30 variable
  names whose values remained redacted and imported as `preserve()`. The final
  graph also preserves the optional, then-absent `SENTINEL_API_KEY` name without
  creating a value.

## BaselineUsageDraft

- Required baseline refs: `AGENTS.md`, memory entry
  `2026-08-27T21:31:56-0700`, current deployment SOP, current Railway IaC docs.
- Delivered context refs: the user-approved pre-demo hardening plan and the
  exact-SHA release evidence recorded in memory.
- Acknowledged before plan refs: all required refs above.
- Cited in plan refs: repository paths and official Railway docs above.
- Missing refs: disposable non-production Railway project for an apply test.
- Decision: continue locally; production activation remains a separate gate.

## Requirement Ready Check

- Requirement source refs: user's “Continue please” after selecting Railway
  configuration migration over the unrelated production state write.
- Goals and scope refs: replace deprecated `railway.json` before 2026-12-01,
  preserve exact API posture, keep data resources out of this repo's ownership,
  and add deterministic release evidence.
- User / scenario refs: operator-managed, dedicated-per-customer Railway
  deployment using the existing exact-SHA `railway up` SOP.
- Requirement item refs: repository config, docs, tests, and release gate.
- Acceptance / verification criteria refs: offline IaC graph check; focused
  posture/onboarding/preflight tests; docs reference gate; package audit; and a
  read-only Railway plan with no unexpected deletion when activation is
  explicitly authorized later.
- Open blocker questions: no blocker for local implementation. A disposable
  stack and production config-source switch require later operator authority.
- Decision: ready.

## TDD Route

- Mode: off
- Decision: skipped
- Strict authority: not applicable
- Test posture: post-change regression
- Reason: the task is a bounded configuration migration with a known unsafe
  generator; focused checks will validate the hand-authored graph after the
  minimal change.
- Verification: offline SDK evaluation, focused Python regressions,
  documentation checks, and release-gate wiring.

## Compatibility

- No HTTP API, database schema, application auth, billing, proof-router, or
  runtime behavior changes.
- Keep `export const partial = "api-service"` stable so this repository owns
  only the API service. PostgreSQL, Redis, partner MCP, volumes, and PITR bucket
  remain foreign resources.
- Preserve all live variable names with `preserve()`; never decrypt or print
  values. A missing variable is a destructive deletion in Railway IaC.
- Encode the repository-owned deploy contract explicitly: root Dockerfile,
  `/health`, 300-second Railway health timeout, one `us-west2` replica, and
  `api.thisisatest.tech`. Omitting the provider-owned restart defaults removes
  the known explicit-field false drift and is the candidate convergent
  representation; fresh disposable proof remains required.
- Do not carry the live stale GitHub commit binding into IaC. The documented
  release owner remains manual exact-SHA `railway up`; production activation
  must explicitly review the source-disconnect change before applying it.
- `railway config apply`, `railway config migrate --apply`, deployment,
  database writes, owner-key retirement, and live data-writing suites are out
  of scope for this local branch.

## Change Necessity

- User-visible need: Railway will stop reading legacy Config as Code on
  2026-12-01.
- No-change / non-code option: leaving `railway.json` is time-bounded and would
  silently lose the configured build/health contract at the cutoff.
- Why code change is necessary: the replacement source of truth is a tracked
  `.railway/railway.ts` file evaluated by the Railway CLI.
- Minimum change boundary: deployment config, its local SDK/check, focused
  tests, release gate, operator docs, changelog, and ignore rules.
- Decision: docs/config-only plus proportional test/gate updates; no
  application source change.

## Existence Check

- Proposed new surface: `.railway/railway.ts` and its local validation package.
- Existing owner / reuse candidate: `railway.json` and the existing trust
  release gate.
- Why existing surface is insufficient: `railway.json` is deprecated, the
  CLI's automatic migration drops variables, and CLI `5.43.3` does not
  normalize explicit restart defaults into a convergent current graph.
- Creation proof: Railway documents `.railway/railway.ts` as the replacement;
  the local `railway` SDK is required because CLI `5.43.3` cannot evaluate the
  official `railway/iac` import without a project-local module.
- Entropy / retirement impact: delete the legacy file, ignore future legacy
  files and local Railway link state, and keep one validation entry point.
- Decision: add-with-proof.

## Architecture Integrity Lens

- Invariant: one tracked owner describes the API service without gaining
  ownership of customer data services or deleting secret variables.
- Canonical owner / contract: `.railway/railway.ts` owns the API service;
  Railway service variables own secret values; `docs/deploy-railway.md` owns the
  operational sequence; `railway up` owns exact-SHA application deployment.
- Responsibility overlap: the legacy file must be removed; the IaC partial
  must not declare PostgreSQL, Redis, partner MCP, volumes, or buckets.
- Higher-level simplification: evaluate the typed graph once in a small local
  check and include that check in the existing trust release gate.
- Retirement / falsifier: retire `railway.json`; reject activation if a
  read-only plan proposes any variable/resource deletion, service creation or
  service rename, unrelated resource change, or stale source binding.
- Verdict: proceed.

## Files

Create:

- `.railway/railway.ts` — stable API-only partial with preserve-complete env.
- `.railway/package.json` and `.railway/package-lock.json` — pin `railway`
  SDK `3.11.0`; no install scripts.
- `.railway/check.mjs` — offline graph and invariant validation.
- `.railway/README.md` — safe plan/apply workflow and ownership boundary.
- `tests/test_railway_iac_config.py` — repository-level negative and parity
  assertions that do not require credentials or Node.

Modify:

- `.gitignore` — ignore all `.railway` local state except the five tracked IaC
  files; ignore retired root CaC filenames.
- `.dockerignore` — keep operator IaC tooling out of the runtime image.
- `Makefile` and `scripts/trust_release_gate.sh` — one
  `check-railway-iac` owner included in the release gate.
- `.github/workflows/ci.yml` — provide pinned Node 24 for the named trust
  release gate.
- `tests/test_production_trust_posture.py` — remove the invalid legacy JSON
  parser/assertion and update the module description.
- `tests/test_onboarding_contract.py` — guard legacy-file absence and tracked
  IaC presence.
- `docs/deploy-railway.md` — separate IaC plan/apply from exact-SHA deployment,
  document fail-closed activation and rollback.
- `SECURITY_LIMITATIONS.md` — point secret hygiene at IaC `preserve()` and
  Railway variables.
- `CHANGELOG.md` — record the unreleased migration.
- `docs/tech-debt-remediation-plan.md` — add one supersession note; preserve
  historical records.

Delete:

- `railway.json` — retired Config as Code owner.

## Complexity Budget

- Artifact class: deployment configuration and release verification.
- Target files / artifacts: one IaC owner, one small checker, one focused test
  module, local doc/test edits.
- Current pressure: deployment docs and production posture test already carry
  historical legacy-config assumptions.
- Projected post-change pressure: low; no application owner grows.
- Budget result: within-budget.
- Planned governance: keep graph validation under `.railway`; do not add an
  application service/helper or duplicate release workflow.

## Plan-Time Complexity Check

- Target files: config/check/docs/gates only.
- Existing size / shape signals: `docs/deploy-railway.md` is large but remains
  the canonical operator owner; edits are local. The new test avoids adding
  another concern to the production-trust module.
- Owner fit: strong.
- Add-in-place risk: low, except duplicating IaC assertions between JS and
  Python; JS proves evaluated graph, Python proves repository/negative policy.
- Better file boundary: `.railway/check.mjs` plus
  `tests/test_railway_iac_config.py`.
- Recommendation: add owner file; keep existing docs and gate entry points.

## Plan Pressure Test

- Owner / contract / retirement: stable named partial; legacy file deleted;
  activation requires source-setting retirement and a clean plan.
- Architecture integrity / higher-level path: no data-resource ownership and no
  second deployment path.
- Verification scope: offline graph, repository guards, focused regressions,
  then a separately authorized live plan/apply/deploy sequence.
- Task executability: exact files, variable names, and commands are known.
- Pressure result: proceed.

## Execution Readiness View

- Intent Lock: local, reviewable migration candidate only.
- Scope Fence: no production config apply/deploy/state write; no proof-router
  work; no owner-key retirement.
- Baseline Lock: exact `2880ca7...` tree and sanitized 2026-08-28 live pull.
- Approved Behavior: API-only IaC partial with explicit repository-owned
  deploy posture, provider-owned restart defaults, and preserve-complete
  variables.
- Owner / Contract Constraints: `.railway/railway.ts` owns selected
  repository-controlled API settings; Railway owns restart defaults and
  variable values; the exact-SHA SOP remains canonical.
- Compatibility Boundary: no application/runtime/API/schema change.
- Retirement Boundary: remove root CaC; source disconnect occurs only during a
  later reviewed activation.
- Task Batches: implementation; local review; focused fresh verification.
- Test Obligations: malformed/secret/legacy negative checks, evaluated graph
  parity, focused tests, package audit, docs references, and release-gate
  wiring.
- Review Gates: spec compliance before code quality; no open findings.
- Drift / Rewind Rules: stop if `origin/main` moves into overlapping paths or
  if the Railway graph/SDK changes; never accommodate with weaker checks.
- Evidence Required Before Completion: clean task diff, focused local gates
  green, production plan/apply/deploy explicitly reported untested.
- Advisory Boundary: method-pack execution guidance only; not `GateDecision`,
  `PolicySnapshot`, or completion authority.

## Tasks

### 1. Author the API-only IaC owner

1. Add the pinned `.railway` package and lock file.
2. Add `.railway/railway.ts` with exact project/service/partial names.
3. Declare Dockerfile build, health, placement, and domain parity; enforce
   omission of the provider-owned restart defaults.
4. List each sanitized live API variable name as `preserve()`; do not add
   values or `--show-values` output.
5. Omit `source` and explain the intentional later source-disconnect gate.
6. Add `.railway/check.mjs` and README.
7. Delete `railway.json`; update ignore and Docker context rules.
8. Run:

   ```bash
   npm ci --prefix .railway --ignore-scripts
   npm test --prefix .railway
   npm audit --prefix .railway --omit=dev --audit-level=high
   git diff --check
   ```

   Expected: all exit `0`; the check reports one API service and no secret
   values.

### 2. Replace legacy evidence with focused guards

1. Remove legacy JSON parsing from `tests/test_production_trust_posture.py`.
2. Add `tests/test_railway_iac_config.py` to pin file presence, named partial,
   exact non-secret posture, preserve-complete variable names, absence of
   secret literals/stale source, and retired-file absence.
3. Extend onboarding guards without weakening existing stale-artifact checks.
4. Run:

   ```bash
   uv run --with-requirements requirements.txt pytest -q \
     tests/test_railway_iac_config.py \
     tests/test_production_trust_posture.py \
     tests/test_onboarding_contract.py
   uv run --with-requirements requirements.txt ruff check \
     tests/test_railway_iac_config.py \
     tests/test_production_trust_posture.py \
     tests/test_onboarding_contract.py
   ```

   Expected: all tests and lint pass.

### 3. Wire release evidence and operator documentation

1. Add `check-railway-iac` to `Makefile` and the existing trust release gate.
2. Pin Node 24 in the trust-release-gate CI job.
3. Update the deployment SOP with the non-mutating plan, activation, exact-SHA
   deploy, post-deploy, and rollback sequence. State that `railway up` does not
   apply IaC.
4. Update security limitations, changelog, and one historical supersession note.
5. Run:

   ```bash
   make check-railway-iac
   make check-doc-references
   uv run --with-requirements requirements.txt pytest -q \
     tests/test_railway_preflight.py \
     tests/test_prepare_railway_release.py
   ```

   Expected: all exit `0`.

### 4. Review and verify locally

1. Review the final diff against the API-only ownership, preserve-complete,
   no-source, and no-live-mutation boundaries; resolve every local finding.
2. Run fresh focused verification:

   ```bash
   npm ci --prefix .railway --ignore-scripts
   npm test --prefix .railway
   npm audit --prefix .railway --omit=dev --audit-level=high
   uv run --with-requirements requirements.txt pytest -q \
     tests/test_railway_iac_config.py \
     tests/test_production_trust_posture.py \
     tests/test_onboarding_contract.py \
     tests/test_railway_preflight.py \
     tests/test_prepare_railway_release.py
   uv run --with-requirements requirements.txt ruff check \
     tests/test_railway_iac_config.py \
     tests/test_production_trust_posture.py \
     tests/test_onboarding_contract.py
   make check-doc-references
   git diff --check
   ```

3. Compare with the task-start snapshot and report the unstaged implementation
   diff. Do not stage, commit, push, open a PR, merge, apply IaC, or deploy.

## Risks

- Railway TypeScript IaC is generally available, but its automatic migrator is
  incomplete.
- A future live variable added outside IaC must also be added as `preserve()` or
  a plan may delete it; every apply requires deletion review.
- Full production plan validation is blocked while the service remains managed
  by legacy Config as Code. Clearing that setting is an external mutation and
  remains unapproved in this slice.
- Removing the stale GitHub source binding is desirable for the documented
  manual deploy path but is still a production configuration change; require an
  explicit maintenance-window decision.
- Effective restart behavior relies on Railway's documented provider defaults;
  a new disposable plan/apply/second-plan proof of the repaired graph remains
  required before production activation.
- The IaC check depends on pinned Node 24 and `railway` SDK `3.11.0`; Renovate or
  Dependabot-style upgrades require re-running graph checks and disposable
  plan/apply/plan validation before changing restart-field ownership.

## Retirement and rollback

- Repository retirement: delete `railway.json`, reject future root
  `railway.json`/`railway.toml`, and keep one `.railway/railway.ts` owner.
- Activation: first prove on a disposable synthetic stack. For production,
  capture the existing config-file path and previous green SHA, clear the
  legacy setting during a maintenance window, and immediately run a read-only
  `railway config plan` without `--show-values`.
- Abort/rollback trigger: any resource/variable deletion, service creation or
  rename, unexpected change to the Dockerfile builder/path, health-check
  path/timeout, domain/source, region/replica count, or restart behavior, or
  any unrelated resource delta. Restore the legacy config path and stop
  without deploying.
- After a clean apply, deploy the exact integrated SHA through the existing
  immutable `railway up` checklist and repeat stamped provenance, health,
  dependency, discovery, public-claim, and proof checks.
- Never reverse database migrations as an IaC rollback.
