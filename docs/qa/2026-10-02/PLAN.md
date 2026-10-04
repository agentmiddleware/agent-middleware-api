# QA sweep plan — 2026-10-02

PR: opened by orchestrator

CI status: pending at time of writing

## Scope and resume

Resume the interrupted inventory without deleting its files. Inspect commit `d45754e` in `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`, branch `qa/2026-10-02-sweep`, origin `PetrefiedThunder/agent-middleware-api`. Keep all changes uncommitted for the orchestrator. This sweep adds only QA documentation, tests, and test tooling. No product fixes are planned.

Budget: approximately 60–90 minutes for the resumed sweep. Separate QA groups have independent charters, evidence, and session logs. Parallel inspection and browser work are safe; Python test runs are serialized because existing fixtures share `test.db`.

## Repository map

| Surface | Location | QA significance |
| --- | --- | --- |
| FastAPI application | `app/main.py`, `app/routers/`, `app/core/`, `app/services/` | Authentication, permit authorization, tool invocation, accounting, receipts, transport errors |
| Persistence | `app/db/`, `app/core/durable_state.py`, `migrations/` | Transaction boundaries, concurrency, replay and crash recovery; migrations inspected only |
| Existing regression suite | `tests/`, `tests/conftest.py`, `pyproject.toml` | Async pytest, proof/dormant/production-trust markers, greenlet-aware coverage |
| Public website | `site/` | Static HTML/CSS/JS, Python build; no framework component suite or application typecheck script |
| Runtime interface | `static/` | Static human operator index; it deliberately does not collect credentials or provide a stateful application workflow |
| SDKs and integrations | `awi_sdk/`, `b2a_sdk/`, `wrappers/`, `framework_integrations/` | Public contracts, TypeScript compilation, README and quickstart usability |
| Product claims | `README.md`, `WEDGE.md`, `TRUST_MODEL.md`, `docs/`, discovery responses | Exactly-once and fresh-key retry claims need implementation evidence |
| Release checks | `.github/workflows/ci.yml`, `ruff.toml`, `mypy.ini` | Read-only inspection; local checks do not establish hosted CI results |

The project-specific instructions override the shared RegEngine defaults: this repository has a `Makefile`, SQLite is its local backend, and frontend commands must come from its actual package manifests. No RegEngine commands or environments are used.

## Risk ranking

Scores are planning judgments, not measured defect probabilities: impact and likelihood each range from 1 (low) to 5 (high).

| Rank | Area | Impact × likelihood | Reason |
| --- | --- | --- | --- |
| 1 | Replay, concurrent dispatch, retries and economic accounting | 5 × 5 = 25 | Duplicate consequential actions or charges undermine the main promise |
| 2 | Authorization, tenant boundaries and scoped permits | 5 × 4 = 20 | A caller could act outside delegated authority or inspect another tenant |
| 3 | Exactly-once / fresh-key documentation and API claims | 5 × 4 = 20 | Integrators may retry unsafely based on an overstated guarantee |
| 4 | Receipt correctness, crash states, error disclosure | 5 × 3 = 15 | Incorrect evidence or hidden ambiguous outcomes prevent reliable reconciliation |
| 5 | Dependency and public API compatibility | 4 × 3 = 12 | Install or schema failures can stop the first integration entirely |
| 6 | Dashboard/pilot main flows, error states and accessibility | 4 × 3 = 12 | A partner cannot complete or understand the governed workflow |
| 7 | Site layout, navigation, performance and presentation | 3 × 3 = 9 | Trust and discoverability suffer; secondary to authorization integrity |

## Pass 1: Backend QA

Owner: backend group; supplemental independent claims/security review. Log: [BACKEND-SESSION.md](BACKEND-SESSION.md), [CLAIMS-SESSION.md](CLAIMS-SESSION.md).

Methods: run existing local suites with coverage before new tests, then repeat the same scope with QA tests; static lint and type checks; inspect OpenAPI/schema contracts; boundary and equivalence classes; existing fuzz/property probes plus narrowly targeted additions; auth/tenant matrix; retry, concurrent invocation, accounting and error paths; OWASP API Top 10 source review; dependency audit using public package metadata where available. The broad existing suite supplies the test pyramid base, while focused API tests and adversarial probes target the highest-risk boundaries. Existing infrastructure-dependent tests may skip with reasons preserved.

Exploratory charters (timeboxed): 20 minutes on scoped identity/replay/concurrent debit; 15 minutes on authorization and API/error contracts; 20 minutes on claims versus implementation. Each charter records observations and limits in its group report/log. Installation and full-suite execution are separately timed.

## Pass 2: Frontend QA

Owner: frontend group. Log: [FRONTEND-SESSION.md](FRONTEND-SESSION.md).

Methods: run the actual static-site build and SDK compilation; inspect existing frontend test coverage rather than inventing framework commands. Add retained Playwright tests for local main flows with external calls blocked or mocked. Smoke Chromium, Firefox and WebKit if installable. Record console/network failures and performance timings; distinguish local smoke metrics from a production Lighthouse score. The public site and runtime UI mean this group applies. SDK compilation/public API ergonomics supplement the absent framework component layer.

Exploratory charters: 15 minutes following a new partner from landing page to pilot/quickstart; 15 minutes on calculator/proof success, failed load and empty state, plus the static operator index; 10 minutes cross-browser/performance smoke. The runtime dashboard was verified to be a static page without script/form controls, so there is no authenticated dashboard workflow to exercise. No real integration credentials or production endpoints.

## Pass 3: UX QA

Owner: UX group. Log: [UX-SESSION.md](UX-SESSION.md).

Methods: axe WCAG 2.2 AA scans plus keyboard navigation and semantic inspection, responsive desktop/mobile screenshots, Nielsen's ten heuristics, microcopy and error/loading/empty states, and README/quickstart developer experience. Automated accessibility checks detect only a subset of WCAG; semantic inspection is not a screen-reader certification.

Exploratory charters: 15 minutes keyboard-only navigation; 15 minutes mobile layout and accessible state changes; 15 minutes integration comprehension and ten-heuristic review. Capture local screenshots and exact reproduction steps.

## Safety, evidence and exclusions

- Do not read environment or credential files. Scrub subprocess output before writing artifacts. Never retain generated test credentials in screenshots or reports.
- Network access is restricted to public dependency/package/browser acquisition. Application traffic is loopback/in-process only, with nonlocal traffic blocked or mocked. No production validation, real billing, hosted databases or third-party credentials.
- No deployment, remote migration, `railway`, commits, pushes, PR creation, CI writes, secret-scan exceptions, or product behavior changes.
- Record defects with exact evidence and suggested fixes. New tests exposing defects must use expected-failure/skip markers bearing their finding ID, without weakening existing checks.
- Preserve command failures and dead ends. `run_logged.py` records command argv, UTC start/end, duration, exit status and scrubbed output per group. Bootstrap commands before logger discovery are explicitly reconstructed in the aggregate session log.
- Coverage reports identify their denominator and skipped scope. Browser/tool installation failures, real assistive technology, Postgres multiprocess behavior, production performance, and external provider behavior are not silently counted as tested.
- Required deliverables: `PLAN.md`, `SESSION-LOG.md`, `FINDINGS.md`, `COVERAGE.md`, `SUMMARY.md`, separate group reports/logs, screenshots/reports, and retained QA tests. The orchestrator owns the final secret scan, commit, push, single draft PR and hosted CI readback.
