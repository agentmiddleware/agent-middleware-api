# AGENTS.md

## Project Mission

This repo is being evaluated as possible trust infrastructure for autonomous agents.
Do not treat it as a generic agent app backend.

The strongest thesis:

> A control layer for agent-to-tool actions where every autonomous action is scoped, authorized, metered, signed, receipted, auditable, and governable.

The weaker thesis to avoid:

> An agent backend with lots of features.

## Core Loop

Judge the product against this loop:

discover → authenticate → authorize → invoke → meter → receipt → audit → govern

Every major feature should support this loop. If a feature does not support this loop, question whether it should be frozen, deleted, or moved out of the main wedge.

## Current Company Phase: Customer Validation

The active company milestone is the 30-day customer-validation sprint in
`docs/30-day-customer-validation.md`, not another core release.

Apply this business invariant:

> No new core capability without documented evidence from a named prospective
> customer.

Work may proceed without new customer evidence only when it is:

- a security or correctness fix
- a reliability fix in the existing one-tool loop
- a documentation or integration fix required to complete an active pilot
- maintenance required to keep existing release gates green

Before unfreezing a capability, require one named active prospect, one concrete
consequential tool, a documented current-workflow blocker, a committed owner and
date, and the smallest vertical slice that clears the blocker. Demo enthusiasm,
generic competitor parity, and speculative roadmap requests are not evidence.

Judge external validation against the partner-owned milestone: one partner
agent, one partner staging tool, one partner engineer, and one receipt that
engineer verifies independently. Do not count local demos, self-issued public
proof, or the stranger test as customer validation.

## Product Wedge Candidates

When making product or architecture recommendations, evaluate these wedges.
**They are not peers — the ordering is the point.** The 2026-08 competitive
sweep ([`docs/market-research-2026-08.md`](docs/market-research-2026-08.md), and
§9 for the 2026-08-25 re-test) established that signed, offline-verifiable
receipts are **table stakes**, not a wedge: they ship in Microsoft's
`agent-governance-toolkit`, Pipelock, and protect-mcp/ScopeBlind. Lead with the
debit, cite the signature as supporting evidence, never as the differentiator.
See [`WEDGE.md`](WEDGE.md) §"Signed receipts are table stakes now".

1. **exactly-once economic authorization at the gateway boundary** — one
   accepted idempotency key yields at most one gateway dispatch **to the
   configured upstream MCP tool** and at most one ledger debit, linked by a
   single persisted chain, with a receipt on every path that finalizes or
   reconciles. (Local governed tools have no dispatch state machine.) This is the wedge. ("Exactly-once" is the
   deduplication term of art: never a duplicate charge, not always a charge.)
2. **crash-semantics accounting** — **for the configured upstream MCP tool**, a
   genuinely ambiguous post-dispatch outcome becomes a distinct receipted state
   rather than a silent redispatch. Local governed tools fail closed into manual
   review; they have no dispatch state machine.
3. agent authorization gateway
4. usage metering layer for agent tools
5. MCP governance proxy
6. secure delegated tool execution API
7. **signed receipt ledger for agent actions — demoted 2026-08.** Real here and
   worth saying, but no longer differentiating. Do not build or pitch around it
   as the wedge.
8. **agent audit log platform — demoted 2026-08**, same reason.

Do not recommend "full agent middleware platform" unless the narrower wedges are already credible.

## Engineering Priorities

Prioritize:

- delegated authority
- permit lifecycle
- scoped authorization
- idempotency
- replay protection
- billing/accounting integrity under crash
- usage metering
- signed receipts
- tenant isolation
- tool execution safety
- auditability
- revocation
- governance policy
- billing/accounting integrity
- developer SDK/demo path

## Security-Critical Areas

Treat these as security-critical:

- auth
- authorization
- tenants
- permits
- delegations
- receipts
- billing/metering
- audit logs
- tool execution
- secrets
- CI/CD
- deployment
- migrations

For changes in these areas, include tests for invalid input, unauthorized access, and relevant negative paths.

## Agent-Specific Risks

Always consider:

- prompt injection
- tool injection
- agentic workflow injection
- confused deputy attacks
- replay attacks
- permit misuse
- over-budget invocation
- billing double-charge
- unsafe tool execution
- unverifiable receipts
- weak key management
- cross-tenant data leakage

## Analysis Rules

When analyzing the repo:

- cite specific files and functions
- separate README claims from code evidence
- separate real flows from stubs or demos
- identify overbuilt or unfocused areas
- recommend what to freeze/delete, not only what to build

Use reality levels:

- verified
- partially verified
- not verified
- stubbed
- demo-only
- misleading
- contradicted
- too early to tell

## Implementation Rules

Prefer vertical slices over broad skeletons.

A good change usually includes:

- one focused behavior
- one clear model/service/route change
- tests proving the behavior
- negative-path tests where relevant
- minimal public API disruption

Do not introduce new dependencies unless necessary and justified.

## Local Credentials for Agents

When you need an API key against a local instance, provision your own —
do not ask for production secrets and never hardcode keys:

- **Admin-shaped local testing**: run
  `python scripts/generate_static_dev_keys.py`, put the printed value in
  `.env` as `STATIC_DEV_API_KEYS=...`, and restart the server. Static
  `amw_dev_` keys are bootstrap admins in local-compatible environments
  only and are deliberately never rotated.
- **Wallet-scoped keys with no restart** (server already running with
  `ENABLE_DEV_KEY_SELF_PROVISION=true`): `POST /v1/dev-keys/self-provision`
  mints a sponsor wallet, agent wallet, and wallet-scoped key with no
  pre-shared secret. Use this to exercise the real permit → invoke →
  receipt loop as a non-admin caller.

Both surfaces are refused by production-like deployments at boot. Details:
`docs/static-dev-api-keys.md`.

## Final Summary Format

End every task with:

- Files changed
- What changed
- Tests run
- What passed
- What was not tested
- Remaining risks
- Recommended next step

## Cursor Cloud specific instructions

The startup update script installs `uv` (to `~/.local/bin`, already on PATH) and
prepares a `.venv` (gitignored) at the repo root with everything in
`requirements.txt` plus `ruff`. So all dev tools are directly runnable without
re-resolving: `.venv/bin/{pytest,ruff,mypy,uvicorn,alembic,python}`. Activate
with `source .venv/bin/activate` or call binaries by path.

- Runtime deps live in `requirements.txt`, NOT `pyproject.toml` `[project.dependencies]`. `ruff` is not pinned in `requirements.txt`; the update script installs it alongside.
- Lint / type-check: `ruff check .` and `mypy app` (both must pass; CI runs them).
- Tests: `.venv/bin/pytest tests/ -q -m "not proof"` for the fast product loop (equivalent to `make test`); `make test-all` runs the full suite including proof surfaces. Canonical `make` targets exist for everything (see `Makefile`).
- Run the app (dev): `make quickstart` is the golden path — it boots the real strict-trust server on `http://127.0.0.1:8000` (loopback ONLY), auto-generates and persists an Ed25519 signing seed under `data/quickstart/`, enables self-serve key minting + one governed dogfood tool (`partner.notes.write`), and follows `docs/quickstart.md`. `QUICKSTART_ARGS="--reset"` wipes state.
- Non-obvious boot requirement: the raw server (`uvicorn app.main:app`) refuses to start in default strict-trust mode without `TRUST_SIGNING_PRIVATE_KEY_B64` (base64 of 32 random bytes) — it fails with `SigningKeyError: trust_signing_private_key_required`. `make quickstart` handles this for you; only set it manually if launching uvicorn directly.
- Local storage: SQLite is the intended local default for both the ORM DB (`DATABASE_URL=sqlite+aiosqlite://...`) and durable state (`STATE_BACKEND=sqlite`). No Postgres or Redis is needed for the core loop, tests, or `make quickstart`. Postgres is only required for the crash-recovery proof (`make prove-crash-recovery`).
- Gotcha: `make quickstart`, `make test`, and the other `make`/proof targets invoke `uv run --with-requirements requirements.txt ...`, which builds an ephemeral uv environment and IGNORES the prepared `.venv`. That is fine and self-contained, but for fast iteration prefer the prebuilt `.venv` directly (e.g. `.venv/bin/pytest ...`, `.venv/bin/python scripts/quickstart.py`).
- Do not ask for production secrets. For a governed caller against a local instance, use `POST /v1/dev-keys/self-provision` on the quickstart server (see "Local Credentials for Agents" above and `docs/quickstart.md`).
