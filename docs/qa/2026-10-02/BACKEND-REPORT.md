# Backend QA pass

Status: complete within the documented local scope. Resumed 2026-10-03 UTC from the interrupted sweep. PR: opened by orchestrator. CI status: pending at time of writing.

## Scope and safety

Worktree `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`, branch `qa/2026-10-02-sweep`, baseline `d45754e`. Test-only changes; no product fixes, commits, remote mutations, deployments, remote databases, billing calls, environment-file reads, or real credentials used. Runtime/test packages installed in `/private/tmp/amw-qa-python`. The only database operations use disposable local SQLite files created by the suite and a separately named surrogate probe DB.

`backend_safety/sitecustomize.py` suppresses dotenv loaders, rejects external DNS/socket destinations before contact, denies external service CLIs, and rejects `.env` access. An absolute-path `.pth` hook in the isolated environment ensures Python subprocesses retain these controls even when an existing test replaces `PYTHONPATH`; a negative control passed. Numeric IPv4 spellings accepted by `inet_aton` may be classified by the local resolver without DNS traffic; external connection attempts remain denied. This is a Python audit guard, not an OS network sandbox. Reviewed shell/Node children use local mocked entrypoints or static assets. The explicitly excluded provider modules are `tests/test_prepare_railway_release.py`, `tests/test_railway_preflight.py`, and `tests/test_railway_iac_config.py`; none of their CLI commands was run. Four additional nodes are deselected because they read an environment example file, prohibited by the task: `tests/test_onboarding_contract.py::test_signing_seed_is_a_visible_required_key`, `::test_signing_seed_ships_empty_rather_than_with_a_real_value`, `::test_env_example_documents_how_to_generate_the_seed`, and `::test_default_state_backend_boots_locally`. PostgreSQL tests remain opt-in and skip because no test PostgreSQL URL or run flag is supplied.

## Risk methods

Highest priority is unauthorized execution, cross-wallet access, debit/dispatch replay integrity, ambiguous outcomes, and signing/evidence integrity. Existing route, service, database race, retry, and negative-security tests provide most of the pyramid; the QA additions fill public auth-contract, schema, and destination-boundary gaps. A 30-minute exploratory charter challenged replay-key encoding, credential precedence, schema metadata, and outbound IP equivalence classes. Optional Hypothesis runs 200 deterministic valid-Unicode cases; OpenAPI validation checks the generated document and unique operation IDs. No runtime dependency was added.

## Verified evidence

- `ruff check .`: passed after removing an unused import introduced in the QA harness.
- `mypy app`: passed, 185 source files.
- Fresh core OpenAPI validates: 73 paths, 76 operations, no duplicate operation IDs.
- Lone-surrogate replay-key candidate was disproved: strict transport returns HTTP 400 `Invalid JSON`, with unchanged effects, ledger entries, permit count, and idempotency-record count. Retained a passing regression; BE-001 is a retired candidate, not a finding.
- Both outbound URL guards accept multicast addresses because Python classifies them as `is_global=True`; no external connection was attempted.

## Confirmed findings

| ID | Severity | Title | Reproduction | Expected / actual | Evidence | Suggested fix |
| --- | --- | --- | --- | --- | --- | --- |
| BE-002 | Low | Supported Bearer authentication is missing from OpenAPI security schemes | Generate `app.openapi()` and inspect `components.securitySchemes`; compare `get_auth_context` accepting the Authorization header. | Expected an HTTP Bearer scheme usable by generated clients/Swagger authentication; actual only `APIKeyHeader` is declared. Runtime Bearer validation itself is not bypassed. | `app/core/auth.py:28`, `app/core/auth.py:119`; `artifacts/backend-openapi-contract-probe.txt`; strict xfail `test_openapi_declares_supported_bearer_authentication`. | Declare optional HTTPBearer and API-key schemes with OR semantics while preserving authoritative Authorization precedence. |
| BE-003 | Low | Destination guards accept multicast addresses as public targets | Call `check_outbound_url("http://224.0.0.1/")` and `check_outbound_url("http://[ff02::1]/")` with private targets disabled; call `validate_upstream_url` for corresponding HTTPS URLs in production configuration. | Expected rejection before connection; actual general guard returns None and upstream guard returns the multicast address. This demonstrates a classifier gap, not successful SSRF or tool execution. | `app/core/url_guard.py:41-49`, `app/services/upstream_mcp.py:406-412`; `artifacts/backend-ssrf-address-boundaries-retry.txt`; strict xfail multicast tests. | Reject `is_multicast` explicitly in both guards, alongside `is_global`; add literal and resolved-address regression cases. |

## OWASP API Top 10 review lens

| Risk | Evidence reviewed / validation |
| --- | --- |
| API1 Object authorization | `AuthContext.require_wallet_access`; existing tenant-isolation and replay-to-unauthorized-caller tests. |
| API2 Authentication | Authoritative Authorization parsing, live API-key binding, JWT revocation checks; 24 added protected-route missing/malformed-credential cases. |
| API3 Object property authorization | Existing permit scope, wallet constraints, KYC authority, and input-hardening tests; no universal mass-assignment proof claimed. |
| API4 Resource consumption | Global streamed request-body cap, request throttling, response-size/time caps, bounded discovery; multicast classifier gap BE-003. |
| API5 Function authorization | Bootstrap-admin guard and route auth inventory; generated-schema security discrepancy BE-002. |
| API6 Sensitive business flows | Existing permit budgets, revocation, idempotency, dispatch fencing, reconciliation, and wallet-concurrency tests. |
| API7 SSRF | URL checks, DNS-pinned upstream adapter, unsafe-origin tests; BE-003 low-priority guard completeness. DNS/network effects not exercised externally. |
| API8 Misconfiguration | Strict-trust startup guardrails, production-posture tests, defaults; no hosted configuration inspected. |
| API9 Inventory | Fresh generated OpenAPI; proof/dormant routers distinguished from core; no remote inventory. |
| API10 Unsafe API consumption | Existing upstream schema/response-size/redirect/error/secret-reflection controls and local fake upstream tests. |

## Results and limitations

Comparable existing-suite baseline: **3,628 passed, 60 skipped, 4 deselected**, 336.82 seconds, exit 0. Before coverage: **21,249 / 24,266 executable app lines = 87.566966%**. The four deselections and three excluded modules above are identical for the before/after comparison.

Added QA module: **27 passed, 7 strict expected failures**, 3.55 seconds, exit 0 (`artifacts/backend-added-tests.txt`). The seven xfails comprise one BE-002 schema repro and six BE-003 multicast repros. The 27 passing cases include 24 auth/credential-precedence checks, fresh OpenAPI schema validation, the 200-example Unicode property, and the disproved surrogate candidate retained as an HTTP400/no-side-effect regression. Expected failures document known behavior and do not count as passing fixes.


Initial attempted baseline: 3,624 passed, 60 skipped, 8 failures, 360.54 seconds. All eight were caused by the task safety boundary: four encoded-loopback tests received `dns_resolution_failed` because the guard blocked numeric resolver classification, and four onboarding tests were denied environment-file reads. Numeric classification was calibrated without permitting external network calls, and prohibited file-reading nodes were deselected for both comparable runs. This attempted run remains in `artifacts/backend-baseline-suite.txt` and is not presented as a product failure or a passing gate. Full after suite: **3,655 passed, 60 skipped, 4 deselected, 7 strict expected failures**, 307.72 seconds, exit 0 (`artifacts/backend-after-full.txt`). App line coverage remains **21,249 / 24,266 = 87.566966%**, a **0.000 percentage-point** change; executed-line sets are identical. These 34 new cases strengthen assertions on already-covered code. This is line coverage, not branch coverage or proof of real-provider correctness.

Installed-package checks use built local wheels and isolated pytest roots, so root application fixtures/source-path overrides do not mask packaging problems:

- Python SDK: **129 passed**, 1.55 seconds; **960 / 1,418 = 67.700987%** package line coverage. `b2a_sdk/mcp.py` is unexecuted in this SDK-only suite; root app tests and CLI subprocess execution have distinct coverage scopes.
- OpenAI wrapper: **65 passed**, 0.57 seconds; **237 / 249 = 95.180723%** package line coverage. All interactions use fake tool-call data and local HTTP mocks; no OpenAI API is contacted.
- Dedicated strict production-posture pass: **12 passed**, 3.94 seconds, with a disposable local SQLite DB, generated in-process test signing material, production trust flags, and outbound guards. This validates configuration/auth posture, not PostgreSQL locks or production deployment.
- Dependency consistency: `python -m pip check` passed. Public package vulnerability metadata is documented by the coordination pass; no separate advisory API was contacted here.

The 60 app-suite skips comprise 44 PostgreSQL/dialect/multiprocess/concurrent-budget cases, 13 missing optional LangChain/LlamaIndex framework-import cases, one missing Python Playwright case, one Linux-only CI test, and one explicitly opt-in long integration loop. Separate AutoGen, CrewAI, and LangChain wrapper suites were not installed/executed because those optional framework stacks are absent; the budget stayed focused on gateway economics, auth, contracts, and the installed SDK/OpenAI path. Root app coverage leaves 3,017 executable lines untested; exact missing lines and module totals are in the before/after JSON artifacts. In particular, live LLM, real notifications, hosted database/Redis behavior, real browser bridge, and provider SDK behavior remain outside this local proof. Local coverage cannot establish hosted PostgreSQL locks, real upstream side effects, provider behavior, or customer evidence. Dependency vulnerability metadata is owned by the coordination pass.


## Handoff

- Files changed: `tests/test_qa_20261002_backend.py`; QA-only `backend_safety/sitecustomize.py`, `requirements-qa.txt`, this report, `BACKEND-SESSION.md`, and backend-prefixed artifacts under this dated QA folder.
- Product behavior changes: none. No database migrations, deploy configuration, CI secret-scan baselines, or environment files edited.
- Confirmed findings from this pass: **Critical=0 High=0 Medium=0 Low=2** (BE-002, BE-003). BE-001 is a disproved candidate preserved in the investigation log only. The separate claim-review lane owns BE-100+.
- Independent gate reviewed the test scope, finding roots/severity, discarded candidate, and isolation calibration. Full task closeout and draft PR creation remain owned by the root/orchestrator.
- Recommended next fixes: document supported Bearer authentication in OpenAPI; explicitly reject multicast destinations in both guards. Keep their strict xfails until implementation fixes and negative controls are reviewed. Complete isolated PostgreSQL concurrency/crash proof before drawing hosted accounting conclusions.
- PR: opened by orchestrator
- CI status: pending at time of writing
