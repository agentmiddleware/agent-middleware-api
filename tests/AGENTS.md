# AGENTS.md — Tests

Tests should verify business-critical behavior, not just happy paths.

Prefer:

- negative-path tests
- authorization failure tests
- tenant isolation tests
- billing/idempotency tests
- receipt verification tests
- replay prevention tests
- malformed input tests

Do not remove tests unless replacing them with equal or better coverage.

Every test must be able to fail: assert one exact expected value (never a
range containing the failure mode), give `pytest.raises` a `match` or a
narrow exception type, and call production code instead of recomputing the
expected value inline. Skips and `xfail` marks need a reason, an owner, and
a linked issue. `ruff check` (PT011/PT015/PT017, B011/B015) and
`xfail_strict = true` enforce this in CI. See the test quality convention
in `CONTRIBUTING.md`.
