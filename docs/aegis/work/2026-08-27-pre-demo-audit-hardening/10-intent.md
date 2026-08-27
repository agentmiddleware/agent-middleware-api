# Pre-demo audit hardening

## Task intent

- Requested outcome: land the approved honesty and safety fixes, then deploy and verify the exact production revision.
- Success evidence: focused regressions, product and trust release gates, exact-SHA CI, Vercel copy verification, Railway stamped build provenance, and a dated memory entry.
- Stop states: done, blocked, needs-verification, or scope-exceeded.

## Scope fence

- In scope: public FAQ/error wording, live-script target safety, DB-key constant-time comparison, invariant-script exit semantics, tests, documentation, release verification, and memory.
- Out of scope: proof-router tenant hardening, rate-limiter redesign, SSRF-policy redesign, schema or HTTP API changes, stale deployment-file retirement, and production-writing conformance runs.

## Baseline usage

- Required: root `AGENTS.md`, `app/services/AGENTS.md`, `tests/AGENTS.md`, `CONTEXT.md`, the user-approved plan, and `docs/deploy-railway.md`.
- Acknowledged: all required repository instructions and vocabulary; deployment SOP will be read again before release.
- Missing: none for implementation. Production credentials and platform authority are intentionally deferred to the release gate.

## Execution readiness

- Intent lock: the smallest pre-demo honesty and safety slice.
- Baseline lock: clean clone at `b357fd95d00d65efab5123e8a4bc5cce28009480` before edits.
- Compatibility boundary: no HTTP, schema, auth-semantic, or proof-router behavior changes.
- Test obligations: invalid target, unauthorized/same-prefix key, fail-closed verdict, rendered copy/JSON-LD, full product gate, and trust release gate.
- Review gates: spec compliance, code quality, fresh coordinator verification, clean task commit, exact-SHA CI, then deployment.
