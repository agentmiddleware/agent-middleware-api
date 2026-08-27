# Evidence

Evidence is appended after each verified slice. This record is advisory and does not grant release or completion authority.

## Baseline

- Command: `uv run --with-requirements requirements.txt pytest tests/test_site_agent_interface.py tests/test_api_keys.py tests/test_invariant_attack_harness.py tests/test_publish_live_proof.py tests/test_published_proof.py -q --disable-warnings`
- Result: 128 passed, 1 failed.
- Failure: `test_social_card_renderer_refuses_unusable_chromium` expected `/bin/false`; that path is absent on this macOS host, so the unrelated renderer check raised a different launch error.
- Decision: preserve the failure without changing unrelated code; exact-SHA CI remains the authoritative cross-platform gate.

## Public claims — implementation evidence

- Changed the visible production-readiness FAQ to define the supported beta as dedicated infrastructure per customer, explicitly exclude shared multi-tenant SaaS and optional proof-surface routers, and retain the replicas/consensus limitation.
- Changed `static/llm.txt` so 401 means missing or invalid bearer authentication and 403 covers key rejection plus wallet/tenant, administrator, policy, or ACL denial.
- Added focused assertions that the visible FAQ exactly matches generated FAQ JSON-LD and that stale FAQ and cross-tenant-only error language are absent.
- Implementer checks: two focused site tests passed; targeted Ruff and `git diff --check` passed.
- Integration authority: withheld pending independent specification review, independent code-quality review, and coordinator-owned fresh verification.

## Public claims — review and verification evidence

- First specification review found two Important gaps: the required article in the 403 sentence was missing, and FAQ parity could not detect swapped answers. Both were fixed by the original implementer.
- Specification re-review: APPROVED with no findings.
- Independent code-quality review: APPROVED; no Critical or Important findings. One Minor suggestion to give the API error assertions their own test name was deferred because the assertions remain local to the existing machine-pointer documentation test and the change would not alter coverage.
- Coordinator verification: `uv run --with-requirements requirements.txt pytest tests/test_site_agent_interface.py::test_machine_pointer_copies_match_and_state_live_access_boundary tests/test_site_agent_interface.py::test_faq_structured_data_is_generated_from_the_visible_answers -q --disable-warnings` — 2 passed in 0.69s.
- Coordinator verification: targeted Ruff passed; `git diff --check` passed.
- Reviewer broader check: 55 tests in the site-interface file passed; the single unrelated `/bin/false` macOS portability failure remains baseline-known.
- Integration authority: granted for the three-file public-claims slice.

## Public claims — integration evidence

- Commit: `665f889` (`fix(site): clarify production and auth claims`).
- Commit contains only `site/compare/index.html`, `static/llm.txt`, and `tests/test_site_agent_interface.py`; task records remained unstaged.
- Pre-commit Ruff and mypy passed. The repository's Ruff-format hook would reformat unrelated baseline lines throughout the oversized site test, so its task-generated formatter output was fully restored and that single hook was skipped for the scoped commit. The focused additions themselves had already passed targeted Ruff and independent review.
- Post-commit readback confirmed no remaining delta in the three owned files.

## Live-target safety — implementation and review evidence

- Added one stdlib-only resolver that requires an explicit target, gives CLI precedence over the environment, permits cleartext only for normalized loopback hosts, strips only a single root slash/default HTTPS port, and requires explicit confirmation for the exact normalized production origin.
- Both data-writing suites are import-safe, read their environment-only key only inside `main`, validate target and credential before client creation, and document persistent data/no cleanup.
- Make passes `TRUST_CONFORMANCE_ARGS`; the Proof Matrix documents explicit targeting and the production confirmation without claiming the diagnostic stress script is a proof.
- Focused regressions cover resolver semantics and both entrypoints' zero-client behavior for every rejected form, plus successful CLI precedence without credential output.
- First specification review found and the implementer fixed whitespace, empty-port, and multiple-root-dot acceptance. Specification re-review: APPROVED.
- First quality review found and the implementer removed a stress-proof overclaim and replaced broad import fallbacks. Quality re-review: APPROVED.
- Coordinator command: focused pytest + targeted Ruff + four direct/package `--help` probes + Make dry-run + `git diff --check`.
- Coordinator result: 59 passed; all other checks passed; no live request executed.
- Residual risk: deliberately confirmed suite runs leave persistent test data; no cleanup was added.
- Integration authority: granted for the six-file live-target slice.

## Live-target safety — integration evidence

- Commit: `a294bec` (`fix(scripts): require explicit live targets`).
- Commit contains only the six approved source, test, Makefile, and proof-matrix files; task records remained unstaged.
- Pre-commit Ruff, Ruff-format, and mypy all passed.
- Post-commit readback confirmed no remaining delta in the six owned files.

## Security-control and evidence-exit — implementation and review evidence

- Replaced direct DB key-hash inequality with `hmac.compare_digest` and corrected the OWASP control owner to `APIKeyService.validate_key`.
- Added a focused real-DB regression: valid key accepted, same-prefix near miss rejected, and both comparisons observed as pairs of 64-character SHA-256 hex digests.
- Added `verdict_exit_code`: only exact `HELD` returns 0. Attacks 1–4 preserve their evidence print/write and return the helper result to existing `sys.exit(main())` guards.
- Strengthened offline AST coverage after the first specification review exposed a false positive around executable guards and evidence preservation. Specification re-review: APPROVED.
- Independent quality review: APPROVED; two maintainability/type Minors were deliberately deferred to avoid adding a shared evidence-emission abstraction or departing from the approved helper signature.
- Coordinator command: focused DB-key + invariant harness + existing API-key suite, targeted Ruff, targeted mypy, and `git diff --check`.
- Coordinator result: 69 passed; Ruff, mypy, and diff check passed. No attack main, network call, or evidence write executed.
- Residual risk: the change protects equality of fixed-length digests only. Prefix selection is not constant-time, and active prefix collisions remain a pre-existing failure mode.
- Integration authority: granted for the nine-file security/evidence slice.

## Security-control and evidence-exit — integration evidence

- Commit: `119e319` (`fix(security): harden key and attack verdict checks`).
- Commit contains only the approved service, mapping, attack-library, four entrypoint, and two focused-test files.
- Pre-commit Ruff and mypy passed. The existing Ruff-format hook was skipped for this scoped commit because accepting its output would have reformatted unrelated baseline lines in touched legacy files.
- Post-commit readback confirmed no remaining delta in the owned files.

## Aggregate branch review — public boundary correction

- Aggregate review identified an adjacent product claim that described idempotency as producing one dispatch and debit rather than bounding accepted gateway work to at most one.
- The FAQ now says: one accepted idempotency key maps to at most one gateway dispatch and debit plus one terminal receipt.
- A focused assertion pins that exact text in both the visible FAQ and generated JSON-LD and rejects the old overstatement.
- Commit: `ac53bf1` (`fix(site): state at-most-once gateway boundary`).
- Aggregate re-review approved the full committed branch with no Critical, Important, or Minor regression findings.

## Branch-wide local verification

- Requested six-file regression command, unfiltered: 166 passed and 1 failed. The only failure is the baseline-known `test_social_card_renderer_refuses_unusable_chromium`, which hardcodes absent macOS path `/bin/false`; the host provides `/usr/bin/false`.
- Same six-file regression set with only that exact unrelated test deselected: 166 passed and 1 deselected.
- `make test` with `.venv/bin` on `PATH`: 1826 passed, 35 skipped, 378 deselected, and the same sole `/bin/false` portability failure.
- `make check-doc-references` with `.venv/bin` on `PATH`: 393 references across 257 files passed. The initial bare invocation found no `python` executable on the macOS default `PATH`; the repository environment resolved that host setup issue.
- `make trust-release-gate`: passed 166 focused trust tests; 399 coverage tests at 81.52% over the 80% threshold; full signed-receipt/offline/tamper/audit/tenant-isolation demo proof; 10 discovery-drift tests; OpenAPI parity; and simulation-inventory parity.
- `ruff check .`: passed. `mypy app`: passed for 180 source files. `SKIP=ruff-format pre-commit run --all-files`: Ruff and mypy passed; format was intentionally skipped to avoid importing unrelated repository formatting drift.
- Focused security regression plus existing API-key suite: 69 passed. Live-target safety: 59 passed. Final FAQ boundary regression: passed.
- No live data-writing suite, production mutation, Vercel deployment, Railway deployment, or production credential output occurred during local verification.

## Release authority and remaining evidence

- GitHub branch protection was inspected directly. Exact protected-branch CI is still required after the task branch is pushed and again for the integrated `main` SHA; local evidence does not substitute for secret scanning or Linux matrix coverage.
- Vercel production evidence must identify the integrated commit as the deployment source. An older deployment must not be redeployed.
- Railway must be built from a clean checkout of the integrated SHA with `COMMIT_SHA` stamped according to `docs/deploy-railway.md`; strict preflight, health, dependency, feature-disablement, logs, and build-provenance checks remain pending.
- Public `llm.txt`, the dedicated-per-customer FAQ, repository-to-production proof-byte identity, and offline signature verification remain post-deploy gates.
- Current whole-task status: `needs-verification`. Implementation slices are reviewed and locally evidenced; integration and production evidence are not yet present.
