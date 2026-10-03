# QA sweep summary — 2026-10-02

PR: opened by orchestrator

CI status: pending at time of writing

Status: **local QA sweep complete**, including separate Backend, Frontend and UX passes plus independent gate review, with explicit untested scope below. No product behavior, deployment configuration, migrations, environment files or secret-scan exceptions changed. Work remains uncommitted on `qa/2026-10-02-sweep` at baseline `d45754e`.

Counts: Critical=0 High=0 Medium=5 Low=3

| Group | Critical | High | Medium | Low | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Backend, including integration claims | 0 | 0 | 1 | 2 | 3 |
| Frontend, including SDK developer experience | 0 | 0 | 2 | 0 | 2 |
| UX | 0 | 0 | 2 | 1 | 3 |
| Total | 0 | 0 | 5 | 3 | 8 |

Verified claim limitations, the rejected BE-001 candidate, environmental test failures and secret-scanner test fixtures are excluded from defect counts. No High/Critical defect was verified within the tested scope; this is not a claim that every such defect is absent.

## Top five risks and next-fix order

1. **BE-100 — retry guidance promises too much:** integration pages imply guaranteed debit/receipt completion and identical local/upstream behavior, which can lead to unsafe reconciliation or retry assumptions. Correct these pages first.
2. **UX-001 — buyer-fit text is hard to read:** four comparison-list items have 2.13:1 contrast against the required 4.5:1. Correct the paper-card text color.
3. **UX-002 — command scrolling lacks explicit keyboard access:** the operator page's overflowing code region is flagged by axe; verify focus and scrolling in Safari after fixing the markup or wrapping.
4. **FE-002 — zero becomes 100 actions:** the unshipped TypeScript SDK replaces an explicit zero step limit with 100. Fix the boundary default before any pilot adopts this SDK.
5. **FE-001 — the SDK cannot build as declared:** its build command lacks project configuration and cannot produce the advertised entrypoints. Keep it unshipped until needed and qualified.

Then address BE-003 multicast destination rejection, UX-003 same-origin operator links, and BE-002 OpenAPI authentication metadata. These are focused corrections; the customer-validation freeze does not justify expanding the SDK or adding another platform feature.

## Evidence and validation

- Backend: final app run **3,655 passed, 60 skipped, four deselected, seven strict expected failures**. Existing-suite before run: **3,628 passed, 60 skipped, four deselected**. Installed Python SDK: **129 passed**; OpenAI wrapper: **65 passed**; separate local strict production-posture checks: **12 passed**. Configured Ruff, mypy (185 source files) and dependency consistency checks pass. Fresh core OpenAPI validates with 73 paths and 76 operations. See [Backend report](BACKEND-REPORT.md).
- Coverage: before/after app coverage is identical at **21,249/24,266 statements (87.566966%)**, a **0.000000-point change**. New tests strengthen assertions on already-covered lines. Two frontend component scripts reached 100% lines/90.38% branches; no whole-frontend baseline or improvement is claimed. [Coverage details](COVERAGE.md).
- Frontend: static-site build and nine JavaScript syntax checks pass; explicit-source SDK typecheck passes. Retained component/SDK tests have **8 passes and 2 expected failures**. The declared SDK build fails as FE-001.
- UX: six local Chrome axe samples, **14 screenshots**, calculator/error checks, accessibility-panel keyboard/Escape checks and responsive samples. Axe reported two rules across five nodes; no full WCAG certification is claimed.
- Dependency metadata: public PyPI reported no known vulnerabilities for all **100** resolved Python QA packages at audit time; npm reported zero known vulnerabilities in the resolved SDK tree and the dependency-free site. These are time-specific package snapshots.
- Security scan: the final current-working-tree scan **passed with zero detections** using unchanged repository rules and relative snapshot paths. Earlier absolute-path scans produced 55 test-fixture alerts because anchored allowances did not match; those failed attempts and their triage remain recorded. No live exposure was verified and no ignore/baseline changed. Environment/credential files and history were excluded.
- Claims: **350 occurrences in 135 files**, classified in [claim inventory](CLAIMS-INVENTORY.md). Same-key gateway guarantees are distinct from arbitrary downstream exactly-once effects. The default guard logs fresh-key repeats; standard MCP creates a fresh auto-permit for a fresh key and therefore remains outside same-permit duplicate detection. Those documented limitations are not new defects.

## What was not tested and why

- PostgreSQL-specific locking/multiprocess crash recovery and remote tool behavior: no eligible local PostgreSQL infrastructure was supplied; remote systems were prohibited.
- Hosted CI, deployments, production settings, real billing, customer-owned agents/tools and external handoffs: outside authorization. No provider CLI, production request or remote mutation was performed.
- Native Chromium/Firefox/WebKit end-to-end compatibility: all three engines failed at process launch under the macOS sandbox. The Chrome computer-use fallback supplied sampled UX evidence, not a replacement cross-browser pass.
- Lighthouse/Web Vitals and clean-context console/network performance: no successful isolated browser launch. Static asset sizes are recorded without a performance score.
- Physical screen-reader behavior, complete keyboard traversal, reduced-motion behavior, 200%/400% zoom and axe incomplete checks: not fully verified; late computer-use deadlines and the timebox are documented.

## Handoff

Files changed are confined to `docs/qa/2026-10-02/` and `tests/test_qa_20261002_backend.py`. The five required docs, separate group logs/reports, redacted artifacts, screenshots and reproducible QA tooling are retained. New bug tests use finding-linked expected failures/TODOs; no product fix was applied. Browser/component QA commands are explicit; CI workflows were not changed. All sweep-owned web servers were stopped and the QA browser tab closed.

The orchestrator must review the final diff, perform its secret scan, commit, push this QA branch and open **one draft PR**, then record hosted CI. No PR URL exists in this run because the orchestrator explicitly retained those actions. Local QA does not establish customer validation or deployment success.

The final register is [FINDINGS.md](FINDINGS.md), with methods in [PLAN.md](PLAN.md), execution evidence in [SESSION-LOG.md](SESSION-LOG.md), and measured scope in [COVERAGE.md](COVERAGE.md).
