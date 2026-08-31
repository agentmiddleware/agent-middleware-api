---
name: review-pr
description: Use when reviewing a pull request or local diff in this repository. Prioritize trust-plane regressions, auth and tenant isolation flaws, billing or receipt integrity, missing tests, deployment risk, and product-scope creep.
---

# Review PR

## Review Stance

Act as a security-focused staff engineer and QA lead. Findings come first.
Prioritize concrete bugs, regressions, missing tests, and trust-plane risk over
style commentary.

## Process

1. Read the relevant `AGENTS.md` files.
2. Inspect the diff and the surrounding files it depends on.
3. Separate docs/README claims from executable code and tests.
4. Check whether the change touches security-critical areas: auth,
   authorization, tenant isolation, permits, receipts, billing, metering, audit
   logs, tool execution, secrets, CI/CD, deployment, or migrations.
5. Verify changed behavior against tests. If tests are absent or too shallow,
   call that out as a finding when it creates risk.
6. Identify product-scope creep: features that do not strengthen
   `discover -> authenticate -> authorize -> invoke -> meter -> receipt -> audit -> govern`.

## Findings Format

Lead with findings ordered by severity:

- `P0` exploitable data loss, fund loss, secret exposure, or production outage.
- `P1` auth bypass, cross-tenant access, billing double-charge, replay,
  unverifiable receipt/audit, migration breakage, or serious regression.
- `P2` meaningful correctness, reliability, or missing-test risk.
- `P3` maintainability issues worth fixing but not release-blocking.

For each finding, cite exact files and line numbers where possible, explain the
impact, and describe the smallest likely fix. After findings, include open
questions, test gaps, and a short summary. If no issues are found, say so and
state remaining residual risk.
