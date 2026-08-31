---
name: debug-bug
description: Use when diagnosing and fixing a bug in this repository. Prioritize reproduction, root cause, minimal fix, regression tests, negative-path coverage, and verification.
---

# Debug Bug

## Process

1. Reproduce the failure or locate the failing path from tests, logs, routes,
   services, or docs.
2. Inspect related code before changing anything.
3. Identify the smallest likely root cause and the narrowest fix.
4. Check whether the bug affects auth, tenant isolation, billing, permits,
   receipts, audit, tool execution, secrets, deployment, or migrations.
5. Implement the minimal fix without rewriting surrounding systems.
6. Add a regression test when practical. Add negative-path tests for
   security-critical bugs.
7. Run the targeted test first, then relevant broader checks if the touched
   surface is shared or trust-critical.
8. Explain root cause, fix, verification, untested areas, remaining risk, and
   next step.

## Rules

- Do not mask errors without understanding the failure.
- Do not delete or weaken tests to make the suite pass.
- Do not change public APIs, schemas, auth, billing, or deployment config
  unless the bug requires it and the risk is called out.
- If the issue cannot be reproduced, state that clearly and provide the closest
  evidence found.
