# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — planned v1.3.0

The next release consolidates the accumulated trust-plane and public-product
work as `v1.3.0`. Create that tag only from the exact commit that passes the
full release gate; do not backfill a final `v1.2.0` tag.

### 🔌 Standard `/mcp` endpoint now served by the official MCP SDK

- **The opt-in `POST /mcp` endpoint no longer hand-rolls JSON-RPC.** The
  official MCP python SDK's stateless Streamable HTTP transport (JSON-response
  mode, one fresh transport per request) now owns the entire protocol
  surface: `initialize` and protocol-version negotiation (through
  `2025-11-25`), notifications, `ping`, JSON-RPC framing, parse errors,
  Accept/Content-Type validation, and error envelopes.
- The trust plane is unchanged and stays this codebase's only contribution to
  the endpoint: API-key/JWT auth and origin validation at the HTTP layer, and
  a `tools/call` handler that mints the bounded single-tool permit and runs
  the same governed permit → meter → exactly-once dispatch → signed receipt
  pipeline, preserving the JSON-RPC governance error codes (`-32001`,
  `-32003`, `-32004`, `-32005`) and receipt-bearing error `data`.
- Signed receipts now also ride the spec's extension point —
  `result._meta["io.agentmiddleware/receipt"]` — alongside the existing
  top-level `receipt` field, so standards-compliant clients that strip
  unknown result fields still get the receipt.
- Added an external end-to-end proof (`tests/test_minimal_path_e2e.py`): a
  real uvicorn process in strict trust mode, driven over HTTP by the official
  MCP SDK client, proving one governed tool call is authorized by a
  server-minted permit, charged exactly once for an idempotency key, replay
  answered with the original receipt, and the receipt verifiable via
  `/v1/receipts/verify`.

### 🌐 Public product direction

- Canonical public origins are `https://www.thisisatest.tech/` for the
  buyer-first marketing site and `https://api.thisisatest.tech` for API and
  machine discovery.
- Public product naming is **Agent Middleware API**. Contact metadata is omitted
  until an accountable display name and monitored address are configured.
- The broad production-beta roadmap and launch-thread draft are explicitly
  superseded by a one-tool design-partner pilot.
- Added a buyer-first, contact-gated marketing build with canonical metadata,
  robots/sitemap, favicon, social preview, and non-PII funnel analytics.
- Published one self-issued live `partner.echo` portable receipt plus its
  public-key snapshot and CI-covered offline tamper checks. The proof is
  explicitly not customer traction or independent key-identity attestation.
- Replaced the fabricated dashboard telemetry and parse-only verifier with a
  truthful public status/evidence index that never requests browser API keys.
- Added exact build commit metadata to both health endpoints and labeled
  process-local call counters separately from durable dispatch history.
- Documented the supported enterprise pilot boundary: one vendor-managed
  Railway project and dedicated API, PostgreSQL, Redis, origin, signing key,
  and administrator set per low-sensitivity design partner. Shared SaaS,
  customer-VPC/BYOC, and regulated production data remain out of scope.

### 🔬 Competitive research, and the positioning correction it forced

- **Second research pass (2026-08-15) answered two of the open questions.**
  The protect-mcp receipt draft
  (`draft-farley-acta-signed-receipts`) was read directly: it is an individual
  submission with no IETF standing, its -02 revision adds a
  `spending_authority` receipt type (the closest competitor is standardizing
  *spend* evidence, though still nothing binding a debit to an idempotency
  record), and its namespaced types plus Merkle commitment mode make emitting
  our receipts in its envelope structurally cheap — interop is now a costed
  option rather than an unknown. Problem evidence was upgraded from one
  reproduction to a **confirmed production incident** of silent retry
  re-execution (`langchain-ai/langgraph#7417`, LangGraph Cloud, "2–3x
  redundant work and cost"), a second framework with the same documented gap
  (`crewAIInc/crewAI#5802`), and a first-hand practitioner report of one
  request producing four sends — while still recording that no duplicated
  *payment charge* in production is publicly confirmed, and that none of this
  is willingness-to-pay evidence. See `docs/market-research-2026-08.md` §8.

- Added `docs/market-research-2026-08.md`: MCP-native competitive set, market
  sizing, and problem evidence, each row carrying an explicit verification
  level. `stripe/ai#402` — a third-party issue report, with a reproduction, of
  agent-level retries creating duplicate charges — was read directly and is now
  the strongest external evidence for the wedge. It is a reported reproduction,
  not a confirmed production incident, and is labeled as such.
- **Signed, offline-verifiable receipts are no longer differentiating**, and the
  docs now say so. At least one MCP policy proxy ships Ed25519 receipts
  verifiable without calling its issuer, with an IETF Internet-Draft for the
  format. `WEDGE.md` and `ELEVATOR_PITCH.md` now lead with the economic claim
  instead: one accepted idempotency key, one dispatch, one ledger debit, one
  receipt, in a single persisted chain.
- `COMPETITIVE_ANALYSIS.md` gained a scope note and §9. Its "no competitor
  offers this" statements were true against Stripe/AWS/Okta and are false
  against the MCP-native set; both facts are now recorded rather than edited
  away.
- Added two prohibitions to `WEDGE.md`'s never-claim list: uniqueness
  superlatives, and compliance mapping to any named framework.
- Added `/compare/` to the marketing site — a named comparison including the
  rows this product loses, a build-vs-buy section against in-process
  reliability libraries, explicit fit/poor-fit criteria, and FAQ answers on
  compliance and the absence of pricing. A test asserts the page keeps naming
  alternatives, keeps conceding ground, and never acquires a superlative or a
  compliance guarantee. Static asset cache token bumped to `v=gateway-3`.

### 🧾 Denials an agent can act on, and trust reads a wallet can do itself

- **Permit denials now carry `details`** — the evaluated constraint and its
  numbers: `required_credits`/`remaining_credits` on a budget denial,
  `limit`/`calls_made` on a call-cap denial, `requested_tool`/`allowed_tools`,
  `missing_scopes`, `expired_at`, and so on. Surfaced on both governed
  transports (`detail.details` and JSON-RPC `error.data.details`), on
  `POST /v1/permits/verify`, on governed AWI actions, and as `denial_details`
  in the signed audit metadata. New terminal denial receipts also sign an
  optional stable `reason_code`, while richer details remain adjacent API and
  audit context and legacy receipts remain valid. See
  [`docs/denial-details.md`](docs/denial-details.md).
- **Offline verification now displays signed denial reasons.** Portable
  receipt exports include `reason_code` in `signing_input` only when present;
  successful and legacy receipts omit it. `b2a-verify-receipt` prints the
  verified reason without trusting an unsigned response field.
- **Binding mismatches stay silent about values.** `permit_wallet_mismatch` and
  `permit_key_mismatch` report only which binding failed — a caller that has
  not proved it is the subject learns nothing about the wallet or key the
  permit belongs to. Forbidden-field denials echo the field name, never its
  value.
- **Trust reads that required an operator key are now wallet self-service**,
  scoped to the caller: `GET /v1/permits` with no `wallet_id`,
  `GET /v1/audit/events` (including `summary=true`), `GET /v1/audit/summary`,
  `POST /v1/audit/verify-chain` with no wallet, and
  `GET /v1/receipts/reconciliation/refunds`. Naming another wallet is still
  refused, operator keys still get the cross-tenant view, and the refund
  **retry** stays operator-only because it moves money.

### 🔭 Self views for the two new front-door steps, and the positioning to match

- **Added `GET /v1/me/permit-requests` and `GET /v1/me/quotes`** — the calling
  wallet's own outstanding asks and unspent price commitments, alongside the
  existing `/v1/me/permits`, `/v1/me/receipts`, and `/v1/me/audit/events`.
  Listing permit requests is strictly read-only: it never advances a decision,
  so an agent can survey what it is waiting on without paging a human or
  minting a permit as a side effect of looking. `/v1/me/quotes?status=active`
  lists the spendable ones, and an unspent quote past its window reads as
  `expired` here exactly as the invoke path would treat it.
- **Positioning updated to cover the front door** — `WEDGE.md` (the ask/price
  steps, what they prove, and what not to claim about them), `README.md`
  (implemented table, API surfaces, docs index, governed call shape),
  `ELEVATOR_PITCH.md`, and the landing copy in `site/`.
- The permit-request API projection moved into the service layer so the poll
  endpoint and the wallet's own view report a request identically.

### 💵 Signed quotes — a price an agent can rely on

- **Added `POST /v1/quotes` and `GET /v1/quotes/{id}`** (`app/routers/quotes.py`):
  an agent asks what one call of a tool costs and gets a signed statement of
  the price, valid for `QUOTE_TTL_SECONDS` (default 600). Backed by the new
  `quotes` table (migration `031_quotes`). See
  [`docs/signed-quotes.md`](docs/signed-quotes.md).
- **The quote locks the price.** Passing `mcpContext.quote_id` on a governed
  invoke charges the quoted credits even if the tool's registered price has
  moved since — in either direction. The permit budget is checked against the
  quoted price too, so the permit sees what will actually be charged.
- **Single use.** A quote is spent by an atomic `active → consumed` UPDATE that
  also requires the window to still be open, so concurrent invokes cannot both
  ride one quote. An invoke that consumed a quote but could not charge returns
  it to `active`.
- **Invalid quotes deny rather than silently reprice** — `quote_expired`,
  `quote_already_consumed`, `quote_wallet_mismatch`, `quote_tool_mismatch`,
  `quote_not_found`. Substituting a different number is the one outcome a price
  lock must never produce.
- **Verifiable offline.** The signature covers the wallet, tool, credits, and
  window under the same Ed25519 key as permits and receipts, and is pinned to
  the `active` commitment so spending a quote does not invalidate the proof of
  what was promised.
- Tool pricing moved to `app/services/pricing.py` so the quote endpoint and the
  governed invoke that honors the quote compute from one definition.

### 🙋 Permit requests — an agent can ask a human for authority

- **Added `POST /v1/permit-requests` and `GET /v1/permit-requests/{id}`**
  (`app/routers/permit_requests.py`): an agent states the scope, budget,
  expiry, and justification it needs; a human is paged through Sentinel; the
  middleware mints the signed permit on approval and the agent polls until it
  appears. Backed by the new `permit_requests` table (migration
  `030_permit_requests`). See [`docs/permit-requests.md`](docs/permit-requests.md).
- **The decision binds to the reviewed terms.** Requested scopes, tools,
  budget, and expiry are frozen on the row and hashed; the mint reads that row,
  never the polling request, so an approved request cannot be re-aimed. Reusing
  an `Idempotency-Key` with different terms is a `409`, not a second page.
- **Minting happens exactly once.** The `pending → minting` transition is a
  conditional UPDATE, and the permit id is reserved when the human is paged —
  so a mint retried after a crash adopts the existing permit instead of issuing
  a second one carrying the same authority.
- **Expiry is enforced locally** (Sentinel keeps timed-out approvals "pending"
  forever), and the fail-closed rules match the invoke gate: simulated
  approvals never mint production authority, real mode without Sentinel config
  refuses, and a Sentinel outage returns a retryable `503` having minted
  nothing.
- **Added the approver card** (`app/services/approval_card.py`): scope, budget,
  and justification rendered from one template into both the notification email
  and a hosted page at `GET /v1/permit-requests/{id}/card`, so the two surfaces
  cannot show different terms for one decision. Read-only — approve/reject
  stays in Sentinel.

### 🔌 Standard MCP endpoint (opt-in)

- **Added `POST /mcp`** (`app/routers/mcp_standard.py`): a spec-compliant
  stateless Streamable HTTP surface for standard MCP clients — `initialize`
  with protocol-version negotiation, notifications (202), `ping`,
  `tools/list`, and `tools/call`. JSON responses only; no SSE stream, no
  sessions, so GET/DELETE answer 405. Cross-origin browser calls are
  rejected; batch requests are refused per the 2025-06-18 revision.
- **Server-minted permits keep the trust loop intact.** Standard clients
  cannot supply wallet/permit context, so `tools/call` mints a bounded,
  signed, single-tool, short-lived permit from the caller's wallet
  (`STANDARD_MCP_PERMIT_TTL_SECONDS`, default 120s) and delegates to the
  same governed invoke path as `/mcp/messages` — metering, receipts, and
  audit unchanged. Bootstrap/admin keys are refused (`-32003`): no wallet,
  no call. A client `Idempotency-Key` reuses the same auto-minted permit on
  retry, so governed replay returns the original receipt without a second
  charge.
- **Disabled by default.** `ENABLE_STANDARD_MCP_ENDPOINT=false` returns 404,
  so the surface cannot be advertised — or pass the MCP registry publish
  preflight — before an operator deliberately enables it.

### 📖 Failure semantics as a first-class spec

- **Added [docs/failure-semantics.md](docs/failure-semantics.md).** The
  complete contract for a metered call that dies mid-flight: all seven signed
  terminal outcomes (`success`, `denied`, `insufficient_funds`,
  `failed_refunded`, `delivery_uncertain`, `response_rejected`,
  `failed_unrefunded`), the crash windows the reconciler finalizes (after
  debit, after dispatch, after response, lost commit acks, effect-free), the
  replay contract, exactly-once refunds, and — deliberately — the list of
  things the system does not claim. Every behavioral row names the test that
  asserts it; all 31 cited tests exist and run in CI.
- **Crash-recovered receipts now sign byte-identical permit constraints.**
  The live invoke path normalized `aggregate_value_cap`
  (`Decimal("10.50")` → `"10.5"`) while the reconciler used `str(...)`, so a
  receipt minted during crash recovery could hash a different
  `constraints_evaluated` than a live receipt for the same permit. Both paths
  now delegate to a single `permit_constraints_snapshot` in
  `app/services/permits.py`, with a parity regression test.
- **Closed the one untested terminal outcome.** No test asserted a receipt
  with `outcome="insufficient_funds"`; `tests/test_mcp_trust.py` now proves a
  balance shortfall signs that receipt at 402/`-32004`, executes nothing,
  debits nothing, releases the reserved budget, and replays identically.
- **`delivery_uncertain` is now proved by a real process kill, not only by
  seeded state.** The two-process PostgreSQL harness previously exercised the
  local execution path only: its stress tool was registered with
  `register_local`, its control endpoint never called the dispatch reconciler,
  and so no `mcp_dispatch_attempts` row — and no `delivery_uncertain` — was
  ever produced by an actual crash. The remote state machine's crash behavior
  was covered only by in-process tests that seed durable states through the
  production service API. The harness now also registers an upstream-backed
  tool and gates the two boundaries that matter: `after_mark_dispatched` (past
  the durable checkpoint, before any effect) and `after_upstream_effect` (the
  effect landed, the acknowledgement did not). Killing a worker at either one
  and reconciling proves the attempt terminalizes to `delivery_uncertain`, the
  charge and permit reservation are retained with no refund, the upstream
  side-effect count never grows, a client retry replays the ambiguity instead
  of re-executing, a second sweep is a no-op, and the recovered receipt's full
  evidence bundle verifies.
- The upstream effects table permits duplicate call tokens deliberately, so a
  redispatch after ambiguity would surface as a second row rather than being
  hidden by a unique constraint.
- **The pre-checkpoint window is proved by kill too.** A third scenario gates
  `after_debit_commit` on the remote path, killing the worker while the attempt
  is still `prepared` and has not yet been told which ledger entry paid for it.
  Recovery must locate the orphaned debit by its operation identity rather than
  by the attempt's null pointer, refund it exactly once, release the
  reservation, sign `failed_refunded`, and never contact the upstream server.
  This is the counterpart to the ambiguous cases: a crash *before* the
  checkpoint is provably non-delivered, so it resolves in the caller's favour
  rather than being retained.

### 🔍 Observability

- **`/health/dependencies` now reports `environment` and `production_like`.**
  Whether the production trust guardrails engage depends entirely on
  `ENVIRONMENT`, which defaults to `"local"` — but no endpoint exposed the
  resolved value, so the only way to audit a running host was to read its
  secret store. A deploy that never sets the variable runs with those
  guardrails silently disabled; both fields are non-secret and make that
  externally verifiable. Additive: no existing field changed.

### 🔒 Security

- **`.env.production` now sets `ENVIRONMENT=production`.** It omitted the
  variable entirely, so `Settings.ENVIRONMENT` fell back to its `"local"`
  default and `is_production_like_environment()` returned `False` — meaning a
  host deployed from the file named `.env.production` ran with *every*
  production trust guardrail silently disabled.

### 📝 Documentation honesty

An audit of the documented setup paths found 26 confirmed defects. The README
was already accurate; almost everything else was not.

- **Removed `pip install` commands for packages that are not published.**
  `agent-middleware-api`, `agent-middleware-awi`, `langchain-agent-middleware`,
  `crewai-agent-middleware`, and `autogen-agent-middleware` are all absent from
  PyPI, yet were documented as plain installs across the four
  `framework_integrations/README.*` files, the three `wrappers/*/README.md`
  files, `docs/awi-adoption-guide.md`, and two package docstrings. Each now
  documents the local path install that actually works. The wrapper
  instructions install `./b2a_sdk` first, without which the editable install
  fails to resolve its own `b2a-sdk>=0.3.0` dependency.
- **Fixed imports of a module that does not exist.** Every
  `framework_integrations` README documented `from agent_middleware import ...`;
  the importable module is `framework_integrations`.
- **Documented startup blocks now include the signing seed.**
  `docs/golden-path.md`, `DEMO_SCRIPT.md`, and `docs/demo-instance.md` each
  started the API without `TRUST_SIGNING_PRIVATE_KEY_B64`, so the server exited
  before binding a port and every subsequent step in those guides was
  unreachable. Each now generates the seed once and reuses it, because
  rebinding a `TRUST_SIGNING_KEY_ID` to new material against a persistent
  database is rejected with `signing_key_id_public_key_mismatch`.
- **Corrected SDK constructor keywords.** `docs/agent-recipes.md` and
  `docs/agentmarket-submission.md` passed `api_url=` and `wallet_id=`, both of
  which raise `TypeError`; the parameter is `base_url=` and there is no
  `wallet_id`. All five documented constructors are now verified to construct.
- **Fixed the runnable examples.** `examples/dry_run_example.py` and
  `examples/mcp_tool_example.py` inserted the repository root onto `sys.path`,
  which shadowed the real package (sources live in `b2a_sdk/src`) and made
  every run die at `ImportError: cannot import name 'B2AClient'`.
- **Marked the aspirational parts of `docs/awi-adoption-guide.md`.** `AWIAdapter`
  does not exist anywhere in the tree. AWI sections are now labelled
  `[implemented]` or `[not implemented]`, and the guide leads with the frozen
  proof-surface status. The one adapter that does exist, `AWIFallbackAdapter`,
  now shows its real import path.
- **`examples/dry_run_example.py` now runs to completion.** It created a sponsor
  wallet, then billed every operation against the hardcoded id `sponsor-0`,
  which never exists — the server assigns ids like `spn-bde42b5c4606`. Each
  dry-run call returned `404 wallet_not_found`. The example now uses the id it
  is given, and the `@billable` functions moved inside the demo because the
  decorator captures `wallet_id` at decoration time, before any wallet exists.
  Its docstring now records the real prerequisite: the dry-run endpoints are on
  the billing router, a proof surface, so the API must run with
  `ENABLE_PROOF_SURFACES=true`.
- **`docs/demo-instance.md` no longer points at a missing compose file.**
  `docker-compose.demo.yml` is not in the repository; the guide now says to save
  the inline YAML under that name first.
- **Corrected the `VALID_API_KEYS` comment in `.env.example`.** It promised that
  an empty value yields open/development mode. Open mode also requires
  `DEBUG=true`, and the file ships `DEBUG=false`, so an empty value actually
  fails closed with `403 invalid_api_key`.

### 🐛 Reliability & fixes

- **Added the missing `scripts/core_quality_gate.sh`.**
  `scripts/repo_guardian.py` has always invoked it, but the file did not exist,
  so the guardian's "core quality gate" check failed unconditionally on every
  run and inflated its failure count. It now runs the same `ruff` and `mypy`
  checks as CI's lint job.

### 🐛 Onboarding & developer experience

- **`.env.example` now produces a server that boots.** `TRUST_MODE_ENABLED`
  defaults to true and trust mode refuses to start without signing material, so
  `TRUST_SIGNING_PRIVATE_KEY_B64` is required in *every* environment — but it
  was documented only inside a commented-out block labelled "production
  checklist". Copying the file and starting the API died with
  `SigningKeyError: trust_signing_private_key_required`. The signing seed is now
  a required top-level key with the generation command inline. The durable-state
  defaults also moved from a placeholder PostgreSQL DSN (which failed with
  `socket.gaierror` under `ENVIRONMENT=local`) to the local SQLite path the
  README documents, with the PostgreSQL block kept as commented production
  guidance.
- **Failed startups now say how to fix themselves.** Signing-key validation
  failures log an actionable `remediation` field — including the exact seed
  generation command — next to the existing error code. The
  `trust_signing_private_key_required` /
  `invalid_trust_signing_private_key` codes are unchanged, so
  `/health/dependencies` consumers are unaffected.
- **Trust gate scripts no longer depend on a specific interpreter name.**
  `scripts/trust_coverage_gate.sh` and `scripts/trust_release_gate.sh` resolved
  `python3.12` by existence alone and fell back only to `python`, skipping
  `python3`. On any machine where a bare `python3.12` is on `PATH` without the
  project's dependencies, both gates failed with `No module named pytest`. They
  now share `scripts/lib/python_env.sh`, which selects the first interpreter
  that can actually import pytest and otherwise falls back to
  `uv run --with-requirements requirements.txt`, matching every other Makefile
  target. `PYTHON` and `PYTEST` overrides still work, and CI behaviour is
  unchanged.

## 1.2.0 deployment (untagged) - 2026-08-08

The Railway deployment reported application version `1.2.0`, but no final
`v1.2.0` tag was created. `f365b69` was part of the deployment history, not a
final release tag. These are the accumulated changes since v1.1.0; they will be
released together with subsequent public-product work as `v1.3.0` after the
exact release commit passes the full gate.

### 🔒 Security

- Removed a leaked production API key, added secret scanning, and hardened the
  live test harness (#201).
- API key rotation: runbook, generator/verifier tooling, and incident record
  (#202).
- Closed confirmed trust-plane authorization and isolation gaps (#203).
- Key revocation now contains compromises; negative-balance chargebacks are
  contained (#204).
- Removed plaintext owner keys and made owner-key retirement rolling-safe
  (#205); closed the refresh-token rollout window.
- **CORS: never pair credentialed responses with a wildcard origin** (#206).
  With `CORS_ORIGINS="*"` (the default) and `allow_credentials=True`, Starlette
  reflected the caller's `Origin` and still returned
  `Access-Control-Allow-Credentials: true`, allowing any website to make
  credentialed cross-origin reads against the trust plane. Credentials are now
  enabled only when `CORS_ORIGINS` is an explicit allowlist; a wildcard origin
  serves `Access-Control-Allow-Origin: *` with credentials disabled. Operators
  running a browser client on a separate origin must set `CORS_ORIGINS` to that
  origin's exact value. Added regression tests in `tests/test_cors_security.py`.

### 🛡️ Trust plane & governance

- Hardened governed MCP dispatch and the SDK; closed MCP transport and refund
  gaps.
- Trust-plane P0 integrity hardening; permit creation captures `subject_key_id`
  from the auth context.
- **Key rotation now revokes the old authority** (#207). Rotation previously
  left the superseded authority usable, so a rotation performed in response to a
  compromise did not actually contain it.
- **Frozen-wallet denial semantics preserved** (#208), keeping the distinct
  frozen error code rather than collapsing it into a generic denial.
- **Child-wallet TTL enforced across every governed spend path** (#209), with
  follow-up review gaps closed (#213).

### ✨ Features

- Human dashboard, observability endpoints, and accessibility tests.
- Budget percentage alerts and `/v1/me/alerts`.
- Opt-in `ENABLE_DOGFOOD_TOOL` for live `partner.notes.write`.
- Agent-discovery pointers on the marketing site, plus published agent discovery
  entrypoints (#210).

### 🌐 Site

- Canonicalized the legacy Vercel host (#211) and redirected the legacy Vercel
  root (#212).

### 🐛 Reliability & fixes

- Validate the signing key at startup and in health checks.
- Normalize tz-aware datetimes to naive UTC for PostgreSQL; keep migration
  revisions PostgreSQL-compatible.
- Fix sponsor-wallet ledger FK ordering; harden production migration boot.
- Discovery honesty: stop advertising unpublished SDK installs; gate MCP
  discovery behind the wedge.

### 📦 Dependencies

- Bumped `mcp`, `stripe`, `uvicorn`, and `redis` (Dependabot).

## [v1.0.0] - 2026-04-16

### 🚀 Historical broad-platform release

**This release completes the full Agentic Web Interface (AWI) vision from arXiv:2506.10953v1.**

#### Phase 9: AWI Phase 9 — Paper Gap Closure

- **Agentic Web Interface (AWI)** — Stateful sessions, semantic actions, progressive representations
- **Passkey Authentication** — FIDO2/WebAuthn for high-risk action verification (`/v1/awi/passkey/*`)
- **Bidirectional DOM Bridge** — Playwright-powered browser automation for real website interaction (`/v1/awi/dom/*`)
- **RAG Memory Engine** — Semantic search over session histories with ChromaDB persistence (`/v1/awi/rag/*`)
- **Agent Discoverability** — Full discovery surfaces: `/.well-known/agent.json`, `/v1/discover`, `/mcp/tools.json`, `/llm.txt`

#### Phase 9.1: Agent Discoverability Sprint

- All Phase 9 capabilities registered in MCP tool manifest (9 new tools)
- `/.well-known/agent.json` updated with Phase 9 capabilities
- `/llm.txt` documentation includes Phase 9 examples
- Root endpoint includes `awi_phase9` service definition

#### Phase 9.2: Playwright DOM Bridge

- **Real browser execution** — `page.click()`, `page.fill()`, `page.goto()`, etc.
- DOM extraction — forms, buttons, links, navigation from live pages
- Session lifecycle — proper page/context management
- AWISessionManager routing — actions automatically route to live browser when attached

#### Phase 9.3: WebAuthn Real Verification

- **py_webauthn integration** for production-ready cryptographic verification
- Signature verification against stored public key
- Authenticator counter checking (prevents cloned credentials)
- Challenge freshness and origin validation
- Credential registration API

#### Production Hardening

- **Auth fail-safe** — Rejects requests if `VALID_API_KEYS` unset in production
- **Background cleanup** — Periodic task cleans expired WebAuthn challenges and AWI sessions
- **ChromaDB RAG persistence** — Vector storage for semantic memory

#### All Phase 9 MCP Tools

| Tool | Credits | Description |
|------|----------|-------------|
| `awi_passkey_challenge` | 1 | Generate passkey challenge |
| `awi_passkey_verify` | 2 | Verify passkey response |
| `awi_dom_bridge_session` | 5 | Create browser session |
| `awi_dom_sync` | 3 | Execute action via DOM |
| `awi_dom_state` | 2 | Get DOM state representation |
| `awi_dom_action_preview` | 2 | Preview action translation |
| `awi_memory_index` | 5 | Index session for search |
| `awi_rag_query` | 3 | Semantic search |
| `awi_session_context` | 2 | Get session context |

**Tests:** 69 Phase 9 tests passing (339 total)

---

## [v0.3.0] - 2026-04-16

### ✨ Major Features — Agentic Web Interface (AWI)

**Implements arXiv:2506.10953v1 "Build the web for agents, not agents for the web"**

- Full **Agentic Web Interface** layer (stateful AWI sessions, higher-level actions, progressive representations)
- Standardized action vocabulary (13 high-level actions: `search_and_sort`, `add_to_cart`, etc.)
- Progressive information transfer engine (`awi_representation.py`)
- Agentic task queues with concurrency limits and safety controls
- Human-in-the-loop intervention (`/v1/awi/intervene`)
- Full integration with existing MCP proxy, Behavioral Sandbox, and `/v1/ai` intelligence layer
- Behavioral Sandbox Engine (Phase 6) for real tool execution in isolated environments

**Tests:** +22 new AWI tests (total 302 passing)

**Next:** Phase 8 — External AWI Adoption Kit for website owners.

---

## [v0.2.0] - 2026-04-16

### 🚀 Major Features

- **MCP Server Generator** — `@mcp_tool` decorator, unified ServiceRegistry, dynamic MCP proxy (`/.well-known/mcp/tools.json` + JSON-RPC), standalone CLI generator
- **Dry-Run Sandbox / Shadow Ledger** — Stateful Redis-backed cost simulation with `async with b2a.simulate_session() as sim:`
- **Stripe Identity KYC** — Human sponsor verification before fiat top-ups
- **API Key Rotation** — Automatic on velocity freeze + grace period + webhooks
- **Agent Intelligence Layer** — Full `/v1/ai` (decide/heal/query/memory/learn) with multi-provider support

### Additional Features

- PostgreSQL Ledger with ACID Transactions (`app/services/agent_money.py`)

- **PostgreSQL Ledger with ACID Transactions** (`app/services/agent_money.py`)
  - Complete rewrite replacing in-memory `WalletStore` with SQLModel + PostgreSQL
  - `SELECT ... FOR UPDATE` locking for atomic operations
  - Decimal precision for all monetary calculations

- **Stripe Fiat Ingestion** (`app/services/stripe_integration.py`)
  - `/top-up/prepare` endpoint generates PaymentIntent client secret
  - Stripe webhook handler with hybrid idempotency (DB UNIQUE constraint + IntegrityError catch)
  - Automatic credit allocation on successful payment

- **Stripe Identity KYC Verification** (`app/services/kyc_service.py`, `app/routers/kyc.py`)
  - `/v1/kyc/sessions` - Create Stripe Identity verification session
  - `/v1/kyc/status/{wallet_id}` - Check KYC verification status
  - `/v1/kyc/verifications/{verification_id}` - Get verification details
  - Sponsor wallets can require KYC before allowing fiat top-ups
  - Wallet status changes to "pending_kyc" until verification completes
  - Webhook handlers for Identity verification events
  - KYC verification status enforced on top-up preparation
  - Email/Slack notifications for KYC approval/rejection

- **Agent Notifications** (`app/services/notifications.py`)
  - Email alerts via Resend API
  - Slack webhook notifications
  - Velocity freeze/unfreeze alerts

- **Agent-to-Agent Transfers** (`app/routers/billing.py`, `app/services/agent_money.py`)
  - `/transfer` endpoint for atomic credit transfers between wallets
  - Child wallet creation with spend limits and TTL
  - Swarm budget aggregation

- **Service Marketplace** (`app/services/agent_money.py`, `app/schemas/billing.py`)
  - Service registry for agent-to-agent service offerings
  - `/services` endpoints for registration and discovery
  - Service invocation with automatic credit transfer

- **Spend Velocity Monitoring** (`app/services/velocity_monitor.py`)
  - Per-wallet hourly/daily spend tracking
  - Anomaly detection using rolling average and standard deviation
  - Auto-freeze on velocity threshold breach
  - `/wallets/{wallet_id}/velocity` status endpoint

- **Webhook Router** (`app/routers/webhooks.py`)
  - `POST /webhooks/stripe` - Stripe event handler
  - `POST /webhooks/stripe/test` - Test webhook connectivity
  - `POST /webhooks/stripe/identity` - Stripe Identity webhook handler

- **Python SDK** (`b2a_sdk/`)
  - `B2AClient` async HTTP client for agent integration
  - `@monitored` decorator for usage tracking
  - `@billable` decorator for automatic credit deduction
  - `@combined` decorator for chained operations
  - Full type hints and documentation

- **MCP Server Generator** (`app/services/service_registry.py`, `app/services/mcp_generator.py`, `app/routers/mcp.py`)
  - Unified service registry for local (SDK) + persistent (DB) services
  - `@mcp_tool` decorator for auto-registering Python functions as MCP tools
  - Dynamic MCP proxy: `/.well-known/mcp/tools.json`, `/mcp/messages` JSON-RPC
  - Standalone server generator: `python -m b2a_sdk.mcp standalone --output server.py`
  - CLI tools: `generate`, `list`, `serve`, `standalone` subcommands
  - Pydantic to MCP JSON Schema conversion

- **Dry-Run Sandbox** (`app/services/shadow_ledger.py`, `b2a_sdk/`)
  - Redis-backed shadow ledger with 15-minute TTL sessions
  - Stateful cumulative simulation (balance tracking across charges)
  - `async with b2a.simulate_session()` context manager
  - `b2a.get_dry_run_estimate()` for single-shot cost checks
  - Velocity isolation: dry runs never touch VelocityMonitor

- **API Key Rotation** (`app/services/api_key_service.py`, `app/routers/api_keys.py`)
  - `POST /v1/api-keys` - Create new API key for wallet
  - `GET /v1/api-keys/{wallet_id}` - List all keys for wallet
  - `POST /v1/api-keys/rotate` - Rotate key with optional revocation
  - `DELETE /v1/api-keys/{wallet_id}/{key_id}` - Revoke specific key
  - `POST /v1/api-keys/emergency-revoke` - Emergency revocation for compromised wallets
  - `GET /v1/api-keys/{wallet_id}/logs` - Rotation audit logs
  - Keys stored hashed (SHA-256) with masked display
  - Automatic rotation on suspicious activity
  - Security alerts via Slack notifications

- **Sandbox Engine Wired to Billing** (`app/services/shadow_ledger.py`, `app/routers/billing.py`)
  - `POST /v1/billing/dry-run/session/{session_id}/commit` - Commit sandbox to real billing
  - `POST /v1/billing/dry-run/session/{session_id}/revert` - Revert and discard sandbox
  - Simulate operations in sandbox, then commit to apply charges
  - Revert to cancel without affecting real wallet
  - Full audit trail of committed vs reverted operations

- **Database Migrations** (`migrations/versions/`)
  - `001_initial.py` - Core wallet/ledger schema
  - `002_stripe_fields.py` - Stripe payment tracking fields
  - `003_velocity_monitoring.py` - Velocity monitoring fields
  - `004_kyc_verification.py` - KYC verification tables
  - `005_api_keys.py` - API key rotation tables

### Changed

- **`app/core/config.py`** - Added Stripe, notification, velocity monitoring, and KYC settings
- **`app/main.py`** - Added KYC and API key routers
- **`app/schemas/billing.py`** - Added KYCStatus, APIKeyStatus, RotationType, and sandbox schemas
- **`app/db/models.py`** - Added KYCVerificationModel, APIKeyModel, KeyRotationLogModel
- **`app/db/converters.py`** - Added kyc_status to wallet conversion
- **`app/services/shadow_ledger.py`** - Added commit_session and revert_session methods
- **`app/routers/billing.py`** - Added commit/revert endpoints for sandbox sessions
- **`tests/conftest.py`** - Added cleanup for API key tables

### Fixed

- Decimal serialization in Pydantic schemas (use float for API compatibility)
- Offset-naive vs offset-aware datetime handling in velocity monitor
- Child wallet `owner_key` made nullable (child wallets don't have owners)

### Dependencies

- Added `stripe>=6.0.0` for payment processing
- Added `mcp>=1.0.0` for MCP Server SDK (optional)
