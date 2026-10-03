# QA coverage — 2026-10-02

PR: opened by orchestrator

CI status: pending at time of writing

## Measurement rules

Backend coverage uses the same `app` source denominator before and after retained QA tests, with greenlet-aware tracing from `pyproject.toml`. Pass/fail counts and exclusions are reported separately from executed-line coverage. These are statement/line metrics; Python branch coverage was not measured. Coverage does not prove correctness, PostgreSQL parity, crash safety or production readiness.

## Comparable backend before and after

| Run | Pass | Skip | Deselected | Expected failures | Executed / executable statements | Coverage | Pytest duration |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Existing suite, before QA test module | 3,628 | 60 | 4 | 0 | 21,249 / 24,266 | 87.566966% | 336.82 s |
| Same scope plus QA test module | 3,655 | 60 | 4 | 7 | 21,249 / 24,266 | 87.566966% | 307.72 s |

**Delta: 0.000000 percentage points; executed-line sets are identical.** The 34 added cases strengthen behavior assertions on already-covered paths: 24 authentication/credential-precedence cases, valid schema/operation IDs, a deterministic 200-example Unicode property, a malformed-JSON/no-effect regression, and seven strict expected failures (one BE-002, six BE-003). Expected failures are not fixed behavior.

Evidence: [before output](artifacts/backend-baseline-final.txt), [before JSON](artifacts/backend-baseline-final-coverage.json), [after output including skip reasons](artifacts/backend-after-full.txt), [after JSON](artifacts/backend-after-coverage.json), [exact comparison](artifacts/backend-coverage-comparison.json), and [focused additions](artifacts/backend-added-tests.txt). Full command arguments are retained in [BACKEND-SESSION.md](BACKEND-SESSION.md).

The initial attempted run had 3,624 passes, 60 skips and eight QA-guard failures; it is preserved in [initial output](artifacts/backend-baseline-suite.txt). Its separate `backend-baseline-coverage.json` is **not** the comparable before measurement. Numeric-loopback classification was calibrated without external DNS/network access, and the four prohibited environment-file-reading tests were deselected identically in the final before/after runs.

### Exclusions and runtime posture

- Three provider-CLI modules were excluded from both runs to honor the explicit CLI ban: `test_prepare_railway_release.py`, `test_railway_preflight.py`, and `test_railway_iac_config.py`.
- Four nodes were deselected because they read environment-example files: `test_signing_seed_is_a_visible_required_key`, `test_signing_seed_ships_empty_rather_than_with_a_real_value`, `test_env_example_documents_how_to_generate_the_seed`, and `test_default_state_backend_boots_locally`.
- The 60 skips comprise **44 PostgreSQL/infrastructure**, **13 optional framework imports**, **one Python Playwright**, **one Linux-only**, and **one opt-in long integration** case. Node-level reasons remain in the after output.
- The broad suite uses its local compatibility configuration and includes proof/dormant surfaces. A separate isolated strict production-trust configuration passed **12 tests** ([output](artifacts/backend-production-posture-local.txt)); this is local posture validation, not deployed-state evidence.

### Risk-ranked application coverage

The values below are identical before and after. Full JSON lists every missing line; 3,017 executable app statements remain uncovered, plus 45 excluded statements. No nonempty app module had zero executed statements, which does not establish complete behavior coverage.

| Module | Covered / statements | Line coverage | Missing |
| --- | ---: | ---: | ---: |
| `app/core/auth.py` | 138 / 142 | 97.18% | 4 |
| `app/services/idempotency.py` | 264 / 295 | 89.49% | 31 |
| `app/services/permits.py` | 515 / 537 | 95.90% | 22 |
| `app/services/wallet_engine.py` | 278 / 307 | 90.55% | 29 |
| `app/services/mcp_dispatch_attempts.py` | 531 / 617 | 86.06% | 86 |
| `app/services/mcp_dispatch_reconciliation.py` | 298 / 350 | 85.14% | 52 |
| `app/services/signing_keys.py` | 205 / 210 | 97.62% | 5 |
| `app/services/upstream_mcp.py` | 476 / 531 | 89.64% | 55 |
| `app/routers/mcp.py` | 948 / 1,022 | 92.76% | 74 |

### Existing installed-package suites

| Package | Test result | Covered / statements | Line coverage | Evidence |
| --- | --- | ---: | ---: | --- |
| Python SDK | 129 passed | 960 / 1,418 | 67.700987% | [tests](artifacts/backend-python-sdk-installed-tests.txt), [JSON](artifacts/backend-sdk-coverage.json) |
| OpenAI wrapper | 65 passed | 237 / 249 | 95.180723% | [tests](artifacts/backend-openai-wrapper-installed-tests.txt), [JSON](artifacts/backend-openai-wrapper-coverage.json) |

These are separate coverage denominators and existing package tests; no before/after improvement is claimed for them. AutoGen, CrewAI and LangChain/LangGraph integration execution remains unverified because optional framework packages were absent.

## Frontend component scope

The browser-free fallback executes the real `site/pilot-fit.js` and `site/proof/proof.js` with jsdom and mocked local data, plus a transpiled TypeScript SDK with a fake transport. The command passes with **eight successes and two expected failures/TODOs**, linked to FE-001 and FE-002.

| Measured JavaScript | Lines | Branches | Functions |
| --- | ---: | ---: | ---: |
| `site/pilot-fit.js` | 100.00% | 96.15% | 100.00% |
| `site/proof/proof.js` | 100.00% | 84.62% | 100.00% |
| Two-script total | 100.00% | 90.38% | 100.00% |

These are V8 metrics for the two named product scripts, **not whole-site or SDK coverage**. See [component output](artifacts/frontend-component-contract-final.txt) and [frontend report](FRONTEND-REPORT.md). The first coverage experiment reported only test-driver code; its 7.49% number is not product coverage and is not a before baseline. Source-level transpiled SDK coverage was not reported.

The native Chromium, Firefox and WebKit baseline could not launch under the macOS sandbox. A blocked baseline is **not 0% coverage**, so no frontend before/after delta is claimed. All 24 original browser-case attempts stopped before assertions. The later nine UX project/case combinations were collected, not executed. The separate Chrome computer-use fallback provides exploratory/axe evidence and does not substitute for cross-browser Playwright execution.

## UX coverage

Six 390px page samples ran axe 4.13.0 with WCAG 2.0/2.1/2.2 A/AA tags: overview, proof, compare, 404, concept and dashboard. There were two violated rules across five nodes, 138 passing rule-page outcomes and five incomplete rule-page outcomes. These are samples, not a WCAG conformance percentage. Fourteen screenshots plus DOM snapshots document responsive and keyboard/state checks. See the [UX report](UX-REPORT.md) for exact tested/untested interactions and artifact links.

## Untested or incomplete areas

- Real remote MCP effects, databases, billing and provider integrations: prohibited.
- PostgreSQL-specific multiprocess locking/crash recovery: requires isolated local infrastructure, not supplied by SQLite tests.
- Hosted CI and deployed configuration/performance: orchestrator follow-up only.
- Full browser matrix, whole-site JS branch coverage, Lighthouse/Web Vitals, animations/arcade and live email/booking handoff: constrained by sandbox/tooling or outside the highest-risk scope.
- Several engine-specific, external-failure, recovery and concurrency branches remain unexecuted despite high statement coverage. SQLite results do not establish PostgreSQL locking or multiprocess crash behavior.
- Real screen-reader use and complete WCAG certification: beyond automated axe and DOM/keyboard checks.
