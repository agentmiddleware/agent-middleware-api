---
name: implement-mvp-feature
description: Use when implementing a new MVP product feature in this repository. Focus on the smallest user-testable trust-plane slice, existing FastAPI/service patterns, targeted tests, and avoiding overengineering.
---

# MVP Feature Implementation

## Goal

Ship the smallest useful version of the requested feature that a real design
partner could test, without widening the product beyond the governed agent
trust-plane wedge.

## Process

1. Read the relevant `AGENTS.md` files and inspect existing code before
   proposing or editing.
2. Classify the feature as core trust plane or proof surface.
3. Define the smallest vertical slice: route, schema, service behavior, storage
   change if needed, and tests.
4. Prefer existing router/service/schema patterns and the `app.trust` facade.
5. Avoid new dependencies, broad abstractions, and public API changes unless
   necessary and explicitly justified.
6. Implement the focused diff.
7. Add or update tests, including negative paths for security-critical behavior.
8. Run the narrowest relevant checks, plus trust gates when the change touches
   permits, billing, receipts, audit, idempotency, MCP, auth, or migrations.
9. Report files changed, what changed, tests run, what was not tested, risks,
   and the recommended next step.

## Pushback Rules

Push back before implementation if the requested feature:

- Expands the product into a broad platform instead of strengthening the trust
  loop.
- Requires major architecture changes where a smaller pilot slice would work.
- Weakens auth, tenant isolation, billing integrity, receipt verification,
  auditability, sandbox isolation, or deployment safety.
- Claims production readiness for a simulation-gated or demo-only surface.

## Good Default Shape

Prefer one clear behavior, one route or service change, one test file update,
and one verification command. Broaden only when the existing code proves the
behavior crosses module boundaries.
