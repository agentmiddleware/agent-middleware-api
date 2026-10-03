# AMW issue resolution — October 2, 2026

## Outcome and scope

This work covers all **87 open GitHub issues** in PetrefiedThunder/agent-middleware-api: [audit parent #499](https://github.com/PetrefiedThunder/agent-middleware-api/issues/499), 82 findings and [four QA charters](charter-coverage.md). The 82 findings already had **79 local fixes and three explicit retirements** in recovered commit `f82700f750862b6e51566a46dfc559e5b81e0a95`. Their source and evidence were recovered, not reimplemented. All 63 cited fix/follow-up commits are ancestors and every referenced original failing, passing and independent-review artifact exists.

[Draft PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586), head `359d56393ee950dc4d826164e223f17b28ec8587`, is a separate QA evidence report with eight additional findings. Agents confirmed all eight persisted in the recovered source and prepared corrections. It is **not a fixing PR** for these unpublished repairs. No fixing PR has been created, and no issue was closed.

Independent review found no blocking findings. Final aggregate validation is being collected. Local fixes do not establish hosted CI, deployment, provider behavior or customer acceptance. Detailed status and remaining scope are below and in each domain report.

## Publication scope inherited from the recovered branch

The local candidate includes the earlier single-action foundation and schema migration042, inherited through baseline `dc3da89f278832fdfe1e968737b250530be8790a` and original feature commit `62066eed2e3632cba821ee30003518b9a2017396`. It is a substantial unpublished integration: the recovered pre-audit foundation alone differs from GitHub main in263 files, including prior formatting and tooling work. The full candidate is broader than the eight follow-up fixes. [Schema042 rollout prerequisites](../schema-042-rollout.md) remain release requirements. Publishing a fixing PR must make this inherited scope clear; production rollout is a separate decision.

## Complete documentation map

| Document | Content |
| --- | --- |
| [Complete issue register](issue-index.md) | All 82 finding links, severity, correction, exact local fix commits, original failure, passing evidence and independent-review links |
| [Machine-readable ledger](issue-ledger.json) | Exhaustive mapping, all 87 issue identities, 63 commit-ancestry checks and explicit fixing-PR status |
| [Accounting](accounting.md) | 15 ACCT findings plus signed numeric storage; fresh SQLite and PostgreSQL evidence |
| [Security, actions and integrations](security-actions-integrations.md) | 28 SEC/AE/IP/ACTION findings; fail-closed, tenant, replay and ownership review |
| [Infrastructure](infrastructure.md) | All 19 INFRA findings, local Railway graph check, scanner qualifications and release gaps |
| [Clients and documentation](clients-and-docs.md) | 20 CLIENT findings, SDK/arcade/onboarding/runbook evidence and BE-100 repair |
| [Backend follow-up](backend.md) | BE-002 Bearer OpenAPI and BE-003 multicast guards with failing controls and passing regressions |
| [Frontend follow-up](frontend.md) | FE-001/002 SDK fixes and UX-001/002/003 contrast, keyboard and origin fixes |
| [QA charter matrix](charter-coverage.md) | All 36 TC IDs across issues553–556, evidence scope and remaining acceptance work |

## Parallel ownership and isolation

Eight agents covered inventory, repair recovery, backend, frontend, client/documentation, infrastructure, independent gate review and full regression acceptance. The root coordinator covered accounting, PostgreSQL checks and integration. Workers verified repository identity and worked in distinct AMW worktrees under `/Users/sellers/.openclaw/worktrees/amw-issues-20261002-*`. Each test process used its own checkout/database. Original task evidence remains unchanged under `/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/`.

The chat's configured `/Users/sellers/Documents/GitHub/agent-middleware-api` path is absent. The verified main checkout is `/Users/sellers/Projects/agent-middleware-api`; its existing branch/untracked research files were preserved. Remote: `https://github.com/PetrefiedThunder/agent-middleware-api.git`. Main at time of fetch: `d45754e5c1fe743158b08494dfef6c87d48b8bec`. The team helper is hard-coded to RegEngine, so AMW worktrees were created directly with Git. Repository-specific AGENTS.md Makefile guidance was used.

## Additional corrections from PR586

| Finding | Parent tracking | Correction | Local implementation |
| --- | --- | --- | --- |
| BE-002 | [#556](https://github.com/PetrefiedThunder/agent-middleware-api/issues/556) | Declare Bearer and API-key OpenAPI alternatives while preserving raw Authorization precedence | `eefd1c1d7d57c59e53d12774298545e0dbabe799` |
| BE-003 | [#556](https://github.com/PetrefiedThunder/agent-middleware-api/issues/556) | Reject multicast literal and resolved targets in both outbound guards | Same backend commit |
| FE-001 | [#554](https://github.com/PetrefiedThunder/agent-middleware-api/issues/554) | Build the checked-in TypeScript SDK's declared JS/type entrypoints; keep SDK private/unshipped | `45eccbcc4b797967ab9559af2c7073eaea610f6f` |
| FE-002 | [#554](https://github.com/PetrefiedThunder/agent-middleware-api/issues/554) | Preserve explicit maxSteps:0 for API rejection instead of silently changing to100 | `45eccbcc4b797967ab9559af2c7073eaea610f6f` |
| UX-001 | [#553](https://github.com/PetrefiedThunder/agent-middleware-api/issues/553) | Correct paper-card comparison text contrast | `45eccbcc4b797967ab9559af2c7073eaea610f6f` |
| UX-002 | [#553](https://github.com/PetrefiedThunder/agent-middleware-api/issues/553) | Make scrolling command region named and keyboard-focusable | `45eccbcc4b797967ab9559af2c7073eaea610f6f` |
| UX-003 | [#553](https://github.com/PetrefiedThunder/agent-middleware-api/issues/553) | Use same-origin runtime links, explicit API_URL examples and separately labelled hosted proof | `45eccbcc4b797967ab9559af2c7073eaea610f6f` |
| BE-100 | [#556](https://github.com/PetrefiedThunder/agent-middleware-api/issues/556) | State at-most-one guarantees, upstream/local differences and manual-review/no-receipt outcomes | `7aa67f48e7c84cc5e996eddbdb94b833e460c0de` |

These IDs are findings inside PR586, not additional numbered GitHub issues. Counts must not be represented as 90 closed issues. PR586's retained BE-002/003 strict expected-failure tests refer to the old audit snapshot; if that evidence branch is later integrated, its expectations must be reconciled with these fixes.

## Evidence levels and release boundary

1. **Local source:** recovered 82 remedies plus eight follow-up corrections; exact ancestry and original evidence verified.
2. **Local tests:** per-domain results are in the linked reports; counts overlap and must not be summed as unique suite coverage. Final combined result is recorded separately.
3. **Remote PR/CI:** PR586 has its own evidence-only head. Its checks are not checks of the unpublished repair branch.
4. **Deployment/provider readback:** no deployment, production mutation or real billing/provider effect performed.
5. **Customer proof:** no partner-owned tool/engineer receipt validation or timed human onboarding established.

The supplied team instruction explicitly requires Christopher's reply before pushing or opening a PR. Work is prepared locally for that final publication decision. No external mutation is implied by instructions written inside issue bodies.

## Remaining acceptance and operational risks

- Broad QA charters remain partially verified: production load/claim checks, every-route negative matrices, full-history secret hygiene, complete accessibility/device coverage and human onboarding need separate evidence.
- Existing scanner baseline candidates remain qualified, not a zero-secret certificate. No scanner baseline or suppression was weakened.
- The Dockerfile base tag is not digest-pinned and full requirements include development tools; the enterprise container charter is not complete.
- Uncertain tool delivery/receipt persistence retains authority for manual reconciliation. This is deliberate fail-closed behavior, not a guarantee of automatic recovery.
- Existing general outbound guard DNS-rebinding limitations remain; the additional repair specifically rejects multicast destinations.

## Retained fresh evidence

Safe command outputs and result records from each worker are copied into [evidence/manifest.json](evidence/manifest.json), with byte sizes, SHA-256 digests and original source hashes. Retained text removes trailing whitespace; original logs remain byte-for-byte unchanged. Logs use the .txt extension so repository ignore rules do not omit them. Original raw logs remain at the task-specific temporary paths referenced by lane reports. The original 82-finding audit evidence remains preserved in the prior task directory; those links are local and are not represented as GitHub-hosted attachments.

## Verification closeout

Pending final aggregate source freeze, independent review and retained command results. This section is updated by the coordinator after completion.
