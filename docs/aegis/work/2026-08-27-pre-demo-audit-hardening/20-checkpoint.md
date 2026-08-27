# Checkpoint

- Current todo: finalize the task record, run fresh exact-head verification, then integrate through the protected `main` branch and deploy that exact SHA.
- Active slice: release-candidate verification and branch lifecycle closeout.
- Completed: clean clone and task branch; all four implementation commits; slice-level specification and quality reviews; aggregate branch review; requested local release gates.
- Evidence refs: base `b357fd95d00d65efab5123e8a4bc5cce28009480`; implementation commits `665f889`, `a294bec`, `119e319`, and `ac53bf1`; detailed command evidence in `90-evidence.md`.
- Blockers: one unrelated baseline portability failure assumes `/bin/false` exists on macOS; exact Linux CI and both platform deployments remain required before whole-task completion. No configured Aegis workspace helper or repository complexity baseline was found, so those structural checks are unavailable.
- Next: commit this advisory task record, rerun the focused suite and release gates against that exact head, then push, open a PR, require protected-branch CI, merge, and verify the integrated SHA before deployment.
- Resume hint: work only in `/Users/sellers/Documents/GitHub/agent-middleware-api-pre-demo-hardening`; the original checkout has an active rebase and must remain untouched.
- Drift decision: continue; scope and compatibility boundaries match the approved plan.

## Public-claims slice

- Necessity: the live audit narrowed two public statements that buyers can independently cross-check; the FAQ needed the dedicated-per-customer boundary and the API error table needed the real 401/403 meanings.
- TDD mode: off; decision skipped. Focused regressions were added with the minimal copy change and are required before integration.
- Complexity budget: within budget. `tests/test_site_agent_interface.py` is already oversized, but this slice adds only local assertions to its existing FAQ and machine-pointer responsibilities. No new dependency, helper, or public interface was introduced.
- Verification state: implementer and coordinator each ran the two focused site tests; targeted Ruff and `git diff --check` are green. Independent specification review approved after two Important issues were corrected. Independent quality review approved with one optional Minor test-naming suggestion.
- Review resolution: fixed the exact 403 article and upgraded FAQ coverage from page-wide substring checks to ordered visible `<dt>/<dd>` pair equality with generated JSON-LD. The optional suggestion to split the API error assertions into a separately named test is deferred because it does not affect correctness and would add no new coverage.
- Next integration boundary: commit only the three public-claims files; keep task records and later slices unstaged.

## Live-target safety slice

- Current todo: make the two data-writing live suites require an explicit target and an explicit production confirmation.
- Necessity: both scripts currently default to the canonical production API, so a missing environment variable can write persistent test data to production.
- TDD mode: off; decision skipped. A new focused safety test module will exercise the resolver and both entrypoints without any network activity.
- Complexity budget: within budget. A small dependency-free resolver becomes the single owner of target parsing and policy; the existing 445-line and 592-line scripts receive entrypoint wiring only. Documentation changes stay in the existing Make target comments and proof matrix.
- Compatibility boundary: no suite semantics, cleanup behavior, auth behavior, schema, deployment config, or proof-router behavior changes. Deliberately confirmed runs still leave persistent test data.
- Next: implement, then perform specification and code-quality reviews before a scoped commit.

### Live-target review resolution

- First specification review found two Important fail-closed gaps: surrounding whitespace was trimmed into validity, and empty ports/multiple trailing dots were silently repaired. The resolver now rejects original whitespace/control characters, empty DNS or bracketed-IPv6 ports, and more than one terminal DNS root dot.
- Specification re-review: APPROVED with no findings.
- First quality review found one Important documentation overclaim: the Proof Matrix newly described the diagnostic stress script as a proof despite non-fail-closed checks. That row was removed while retaining all required target and persistent-data warnings.
- The quality review's import-fallback Minor was also fixed by using explicit package/direct-script branches. The module-global configuration Minor was deliberately deferred because the approved design permits globals populated only after validation in these one-shot CLIs.
- Quality re-review: APPROVED with no findings.
- Coordinator verification: 59 focused tests, targeted Ruff, direct-script and package `--help` probes for both scripts, Make argument dry-run, and `git diff --check` all passed.
- Next integration boundary: commit only the resolver, two scripts, focused test, Makefile, and proof-matrix changes; keep task records unstaged.

## Security-control and evidence-exit slice

- Current todo: align DB-backed key comparison with the constant-time documentation claim and make invariant attacks 1–4 return failure for every non-HELD verdict.
- Necessity: direct string inequality on security-sensitive key hashes contradicts the stated control, while `main()` returning `None` makes `sys.exit(main())` report success even after a BROKE verdict.
- TDD mode: off; decision skipped. Focused regressions will accompany the two minimal behavior changes.
- Complexity budget: within budget. One stdlib call replaces equality; one small helper centralizes verdict-to-exit semantics; a new API-key test module avoids expanding the oversized existing API-key module; the attack harness receives only focused helper/wiring tests.
- Security boundary: no prefix lookup, key status/use-count, auth result, route, schema, deployment, or attack evidence semantics change. Prefix-index selection remains a non-constant-time lookup; the equality comparison protects fixed-length digests only.
- Next: implement, then complete independent specification and quality reviews before a scoped commit.

### Security-control review resolution

- First specification review found one Important test gap: the AST regression pinned the final helper return but not `sys.exit(main())` or evidence preservation. The test now verifies one synchronous main, its sole/final helper return, matching ordered evidence print/write, and the exact final executable guard without running the attacks.
- Specification re-review: APPROVED with no findings.
- Independent quality review: APPROVED with two non-blocking Minors. The AST test is source-shape-heavy, but replacing it with a shared evidence emitter would expand this deploy-critical slice; defer that cleanup. The helper remains annotated exactly as the approved `verdict_exit_code(verdict: str) -> int`; runtime `None` is intentionally tested fail-closed with a localized type ignore.
- Coordinator verification: new DB-key test, invariant harness, and existing API-key suite — 69 passed. Targeted Ruff, targeted mypy, and `git diff --check` passed.
- Security evidence: valid and same-prefix near-miss keys both compare 64-character SHA-256 hex digests through `hmac.compare_digest`; the near miss is rejected. Only exact `HELD` maps to exit 0.
- Residual risks: prefix presence remains observable before digest equality; the effectively 24-bit random lookup prefix is non-unique and active collisions can make `scalar_one_or_none()` raise. Both predate this slice.
- Next integration boundary: commit only the nine approved files; keep task records unstaged.

## Aggregate public-claims review resolution

- Aggregate review questioned whether the mandated 401 wording describes malformed `X-API-Key` input precisely enough and found an adjacent exactly-once sentence that overstated the gateway boundary.
- The 401 sentence was retained because it is the exact approved public wording and uses bearer authentication generically for presented API credentials; no auth behavior changed.
- The exactly-once paragraph now states the actual boundary: one accepted idempotency key maps to at most one gateway dispatch and debit plus one terminal receipt. Visible FAQ and generated JSON-LD equality are pinned by a focused regression.
- Aggregate re-review: APPROVED with no Critical, Important, or Minor branch-regression findings.
- Integration commit: `ac53bf1` (`fix(site): state at-most-once gateway boundary`).

## Release-candidate checkpoint

- Branch-wide requested focused suite: 166 passed with the single known `/bin/false` portability test deselected; the unfiltered run was 166 passed and that one unrelated failure.
- Full local product suite: 1826 passed, 35 skipped, 378 deselected, plus the same single unrelated macOS portability failure.
- Documentation references: 393 references across 257 files passed when the repository virtual environment was placed on `PATH`.
- Trust release gate: passed 166 focused trust tests, 399 coverage tests at 81.52%, the signed-receipt demo proof, discovery drift, OpenAPI parity, and simulation-inventory parity.
- Static gates: Ruff and mypy passed. The repository-wide Ruff-format hook was skipped because existing formatting drift in touched legacy files would create unrelated changes; no global formatting rewrite was accepted.
- Protected-branch policy was read from GitHub: required Linux test, SDK, PostgreSQL, production-trust, concurrency, secret-scan, trust-release, and lint checks; administrator enforcement and conversation resolution are enabled.
- Release state: `needs-verification` until fresh exact-head gates, exact integrated-`main` CI, exact-SHA Vercel and Railway deployments, provenance/health checks, public-copy checks, and offline proof verification all pass.
- Drift decision: continue. No proof-router, rate-limit, SSRF, schema, auth-semantic, or production-writing-suite scope was added.
