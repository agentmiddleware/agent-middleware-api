# AMW issue release candidate — October 3, 2026

**82 finding remedies are integrated and locally validated: 79 fixes and three explicit retirements.** GitHub still has 87 open issues: the 82 findings, parent #499 and four broader QA charters (#553–556). None was closed or changed by this task. [Current issue mapping](issue-status.json).

Branch: `openclaw/amw-issues-20261003-release`. Tested product/test source: `079bb7290f6ed86c6762baec02827305b5cb9da7`. This candidate includes current upstream `e0b5fd6cc8792b76233df7b016a3ff303d5144cd` and all 63 fix/follow-up commits cited by the prior ledger. Subsequent additions to this packet are documentation/evidence only.

## What changed

Recovered the existing unpublished 82-finding integration at `cac86ae0baa34e328dc8191c25340758fd910366` and merged current main. Preserved the newer #587/#589 repairs and TypeSafe documentation, resolved ten merge conflicts, removed a duplicate Bearer declaration introduced by the merge, and regenerated OpenAPI. Required hooks reformatted eight imported Python QA files; AST equivalence was verified.

The retained fixes cover JWT scope/key-budget enforcement, tenant isolation, approval reuse, permit/accounting precision and concurrency, AWI admission before effects, uncertain X402 settlement ownership, durable integrations, release/proof tooling, clients and documentation. Retired unsupported paths are #511, #529 and #570; they refuse explicitly instead of pretending to work. The [previous detailed ledger](../issue-resolution-2026-10-02/issue-ledger.json) retains original finding, reproduction and fix provenance.

Review found remaining startup guidance related to #567 that advised blindly stamping the database at head. The follow-up changes only that error message/comments, adds an empty-revision refusal test, and verifies revision state is unchanged. It does not change schema enforcement or perform a migration.

A browser QA follow-up gives the synthetic ArrowRight key a 100ms hold. The original instantaneous press also failed on current main in WebKit. Accessible name, Tab focus, visible outline and positive scrolling assertions are unchanged. All 66 tested frontend source hashes match the committed source.

## Verification

| Check | Result | Evidence |
| --- | --- | --- |
| Complete Python suite, including proof surfaces | 4908 passed, 87 skipped, 6 warnings in 302.81s (0:05:02) | [Output](evidence/local/full.txt), [command/SHA](evidence/local/full-result.json) |
| Python SDK and OpenAI wrapper suites | 213 passed in 0.50s | [Output](evidence/local/sdk.txt) |
| Fresh PostgreSQL 17 | 44 passed, zero failed/errors/skipped: accounting 12, process/crash recovery 10, schema042 1, migration038 1, permit concurrency/expiry 20 | [Summary](evidence/postgres/summary.json) |
| Optional OpenAPI/Hypothesis QA checks | 2 passed separately in existing Python3.13 environment; no packages installed | [Metadata](evidence/postgres/optional-qa.json) |
| Browser QA | 33 passed: Chromium 11, Firefox 11, WebKit 11; no skips/flaky cases | [Results](evidence/frontend/final-playwright-results.json), [committed hashes](evidence/frontend/committed-source-verification.json) |
| Other frontend checks | 22 component/arcade, 2 TypeScript package tests; SDK build, 78 design scenarios and 25 calculator scenarios passed | [Components](evidence/frontend/components.txt), [SDK](evidence/frontend/sdk-package.txt), [design](evidence/frontend/site-design.txt), [calculator](evidence/frontend/pilot-fit.txt) |
| Required hooks | Ruff, format and mypy passed | [Output](evidence/local/hooks.txt) |
| Generated contracts | OpenAPI, inventory and document references passed | [OpenAPI](evidence/local/openapi.txt), [inventory](evidence/local/inventory.txt), [references](evidence/local/docrefs.txt) |
| Secret scanning | Staged merge and proposed-branch commit scans reported zero findings; unchanged rules | [Staged](evidence/local/gitleaks.txt), [branch](evidence/local/branch-gitleaks.txt) |

Counts overlap; do not sum them into unique coverage. Main-suite skips remain explicit. Selected PostgreSQL and optional QA skips have separate passing results above; all other skip reasons remain in the full output. Browser/API fixtures are local and mocked, not deployment proof. Fresh PostgreSQL clusters and task-owned browser servers were stopped; prior evidence was retained.

The first full run stopped after 4,164 passes because the runner forced `/tmp` while the site builder requires the macOS system temporary directory. Correcting the runner made the same check pass without product/test changes. A second preliminary run was intentionally interrupted to wait for the final source commit. Both outputs are preserved; only the final complete run is acceptance evidence.

## Independent review and remaining scope

Independent scoped reviews found no blocking regression in JWT/key authority, approval expiry, AWI accounting/ownership, X402 compensation, billing tenant checks, migrations038/042, startup parity, negative-control CI, diagnostic streaming limits and release preflight. The three-file final follow-up was independently reviewed; no schema enforcement or test assertion was weakened.

This is a substantial integration and includes previously unpublished single-action authority and schema042. [Schema042 rollout prerequisites](../schema-042-rollout.md) remain required before a separately authorized deployment. Hosted CI on this candidate, operational schema/recovery/worker isolation, production load/provider behavior, full-history scanner qualification, full charter matrices and human/customer acceptance remain unverified. Existing ambiguous outcomes can require operator reconciliation. The five audit/QA tracking issues are not fully complete; see [36-case charter coverage](../issue-resolution-2026-10-02/charter-coverage.md).

## Publication decision

[Prepared draft PR](pr-draft.md). Push and PR creation are the next actions requiring Christopher's explicit reply under the supplied team instructions. No GitHub issue update, push, PR, merge, deployment, credential change or real provider/payment action was performed. The unrelated open PR #590 was left untouched.

[Artifact hashes](evidence/manifest.json) preserve exact original hashes and note any trailing-whitespace normalization in retained text copies. One source-checksum mapping was represented as explicit path/sha256 records after the scanner mistook the checksum for a key; every value was verified against its tracked file, and no scanner rules or suppression were changed. Original logs remain at recorded local paths.
