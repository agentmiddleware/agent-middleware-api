# Independent QA gate review

PR: opened by orchestrator

CI status: pending at time of writing

## Verdict

The retained QA tests, harnesses, findings and evidence have been independently reviewed. No unresolved product-change or safety issue was found in the QA additions. Changes remain uncommitted for orchestrator review; gate did not commit, push, create a PR, deploy, or contact an application service outside loopback.

Gate applied the local review-pr skill and read repository/test AGENTS.md. Identity checks confirmed branch `qa/2026-10-02-sweep`, HEAD `d45754e`, the expected repository remote, and a single worktree. [Scope check](artifacts/gate-qa-only-scope-check.txt) found no tracked-file modifications or staged paths; all additions are inside `docs/qa/2026-10-02/` plus `tests/test_qa_20261002_backend.py`. No product code, migrations, deployment configuration, environment files or secret-scan exceptions changed.

## Independent review decisions

- Accepted BE-100 as Medium documentation correctness: source distinguishes local and upstream execution and permits manual-review outcomes without a finalized receipt. Scoped same-key guarantees and new-key limitations are recorded separately, not counted as new defects.
- Accepted BE-002 as Low API contract metadata: supported Authorization authentication is absent from generated OpenAPI security scheme metadata. No authentication bypass is alleged.
- Accepted BE-003 as Low destination classification: literal multicast addresses pass a public-address classifier. The tests never connect to them; no successful SSRF is alleged.
- Accepted FE-001 as Medium SDK packaging: the retained expected failure executes the declared npm build and verifies advertised entrypoints, rather than merely checking a filename.
- Accepted FE-002 as Medium SDK boundary handling: an explicit maxSteps=0 becomes 100 although `app/schemas/awi.py:157-159` rejects zero. A fake transport verifies this without an API call.
- Accepted UX-001 as Medium accessibility: four comparison-card nodes have 2.13:1 contrast; independently parsed axe evidence and inspected the screenshot.
- Accepted UX-002 as Medium automated accessibility/explicit-focusability gap: overflow code lacks explicit keyboard access. Independently inspected axe evidence and the clipped code screenshot. Physical Safari keyboard behavior remains unverified and is stated as such.
- Accepted UX-003 as Low operator-origin confusion: a locally served dashboard uses fixed production links and terminal examples. No destination was followed.

Final defect totals: **Critical=0 High=0 Medium=5 Low=3**. All eight rows match the consolidated summary. The refined claim inventory contains 350 matches across 135 files; ordinary documentation about credentials is included while actual credential/environment files remain excluded. Lexical matching does not prove absence of arbitrary paraphrases.

## Validation readback

Gate did not run another pytest process, avoiding interference with the backend owner’s shared SQLite suite. It reviewed source, execution artifacts and coverage JSON instead.

- Comparable app baseline: **3,628 passed, 60 skipped, 4 deselected**. After additions: **3,655 passed, 60 skipped, 4 deselected, 7 strict xfails**. Focused new tests: **27 passed, 7 strict xfails**, exactly one BE-002 and six BE-003 expected failures.
- Correct before artifact is `backend-baseline-final-coverage.json`, not the earlier boundary-failed baseline. Before and after both cover **21,249/24,266 statements (87.566966%)**, with 3,017 missing lines and identical covered-line sets: **0.0000 percentage-point change**. Added assertions improve behavioral checks without pretending to improve line coverage.
- Installed Python SDK: **129 passed**. Installed OpenAI wrapper: **65 passed**. Separate strict production-posture configuration: **12 passed**. This is local configuration evidence, not production access.
- Frontend component/SDK rerun: **8 passed, 2 expected failures**, overall exit 0. Browser suite: **24 launch failures before navigation**, not 24 product assertion failures. UX regressions were syntax/discovery checked but not executed in the blocked Playwright engines.
- UX fallback: six local Chrome page samples, two axe rule violations across five nodes, plus retained screenshots/semantics. Gate independently viewed the comparison-card and dashboard-scroll screenshots. Full screen-reader use, complete tab traversal and physical Safari behavior were not claimed.
- Local Markdown evidence links across the five mandatory documents and four pass reports resolved at review; severity count lines matched eight finding rows. Final gate checks confirmed all five required documents contain the mandated PR/CI metadata, eight findings match the 5 Medium/3 Low count, all referenced local evidence links resolve, and no stale running/interim marker remains. Configured repository Ruff also passed. See artifacts/gate-final-mandatory-documents.txt and artifacts/gate-final-lint.txt.

See [backend numeric readback](artifacts/gate-backend-final-numeric-readback.txt), [comparable coverage identification](artifacts/gate-comparable-coverage-location.txt), [backend comparison](artifacts/backend-coverage-comparison.json), [frontend evidence](artifacts/frontend-component-contract-gate-rerun.txt), and [report-link/count check](artifacts/gate-report-link-and-count-check.txt). The numeric readback deliberately preserves an initial comparison against the old baseline; the subsequent comparable-coverage identification corrects it and is authoritative.

## Harness safety and corrections

`run_logged.py` removes inherited application environment variables, avoids shell expansion and scrubs credential-shaped output. The Python guard suppresses dotenv reads, rejects non-loopback connections, denies service CLIs and blocks environment-file opens. Child tests overriding PYTHONPATH were protected by an absolute-path startup hook in the isolated temporary environment; its negative control passed. Legacy numeric IPv4 parsing is permitted for classification only. This remains a Python audit guard, not an OS network sandbox.

Browser tests block non-loopback requests and service workers; receipt mocks use the exact local URL. DOM component fetches and SDK transport are fake. The successful UX server binds loopback, injects local axe only, restricts resources/connections/forms with CSP and serves only the QA site/static dashboard. Source-reviewed subprocesses use local mocked entrypoints or declared build tooling. Owned browser tabs/servers were closed by their owners; no production settings were touched.

The speculative BE-001 surrogate bug was disproved by the transport’s strict JSON parser and removed. The retained regression expects HTTP 400 with no state effects or debit. No false bug xfail remains for that candidate.

An initial new frontend test fixture triggered a credential-assignment scanner rule. It was replaced by a runtime-generated synthetic value without ignore/baseline edits. Initial absolute-path snapshot scans also produced 55 existing fixture alerts because anchored repository path allowances did not match. The corrected full current-tree scan used `gitleaks dir . --config .gitleaks.toml` from the safe snapshot: **1,197 files, exit 0, zero detections**, including new QA artifacts. [Final current-tree scan and scope](artifacts/gate-final-current-tree-secrets-and-scope.txt). Earlier alerts remain logged as scanner-method false positives. No live-secret exposure was verified; environment/credential files and Git history were excluded by instruction.

## Remaining limits and handoff

No hosted CI result, PostgreSQL locking/crash proof, real remote MCP effect, production configuration, billing-provider result, complete browser compatibility pass, Lighthouse score, complete zoom assessment or physical screen-reader result is established. The reports preserve these limits and the skipped-test causes.

Gate-owned files are this report, GATE-SESSION.md and gate-prefixed command artifacts. Every shell command after two disclosed bootstrap reads is logged with UTC outcome; those two reads are reconstructed with their exact commands and an explicit timestamp gap. The orchestrator remains responsible for final secret scanning, commit, push and the single draft PR. Recommended next action is that review/publication handoff, followed by the eight documented product fixes in the agreed order.
