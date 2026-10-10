# AMW insight source map

Verified against the isolated `codex/amw-usage-failure-insight` checkout at
`d9d31e31199b1caa204d77162ddd0938e29c8867` on 2026-10-10. This is a
source inspection, not deployed schema or production evidence. The two approved
inputs are `amw-usage-failure-insight-spec-2026-10-10.md` and
`amw-usage-failure-insight-implementation-plan-2026-10-10.md` in the local
`../inputs/` directory; both were read completely. The checkout is clean and
its `origin/main` ref equals the pinned commit. The integration owner separately
verified the live remote main at that commit.

## Authorization decision: implementation gate

**No existing read-only operator authorization was found.**
`get_auth_context` authenticates API keys or JWTs
(`app/core/auth.py:130-153`). `AuthContext` can authorize one exact wallet or
an unrestricted bootstrap admin (`app/core/auth.py:41-94`). Configured
`VALID_API_KEYS` and local static development keys grant bootstrap-admin power
(`app/core/auth.py:236-262`); DB API keys and JWTs bind to one wallet
(`app/core/auth.py:264-278,400-437`). Existing DB-key validation records
`last_used_at` and may consume a bounded use
(`app/services/api_key_service.py:481-510`); JWT verification also consumes a
derived key use (`app/core/auth.py:412-425`). Those existing authentication
side effects are distinct from read-only evidence queries.
An explicit DEBUG plus `ALLOW_UNAUTHENTICATED_DEV_ADMIN` local mode can also
return bootstrap-admin context for an arbitrary well-formed API key without
verified credential identity (`app/core/auth.py:193-220,293-329`);
`get_auth_context` alone must therefore not be treated as proof of a
verified operator identity.
Grantable JWT scopes are `billing:charge`, `billing:read`, and `tool:invoke`
plus tool-specific invocation; there is no operator/insight read scope, and
API keys bypass scope checks (`app/core/scopes.py:22-48,56-103`).

The enterprise OIDC principal carries verified human identity and groups
(`app/core/oidc_iga.py:69-90,403-491`). Groups map to tool PolicyBundles,
not reporting access (`app/core/oidc_iga.py:497-505,768-823`). The principal
dependency is optional and its enforcement dependency only gates tool calls
(`app/core/auth.py:451-515`). Existing audit and receipt reads use wallet
access or bootstrap-admin access for cross-wallet queries
(`app/routers/audit.py:26-46`; `app/routers/receipts.py:48-77`).

The approved plan's Task 1 says to fail closed and return for authorization
design approval if no suitable existing read role exists. That condition is
met. No new cross-account insight endpoint, bootstrap credential flow, or
authorization change should be implemented under this plan. A wallet-scoped
reader could reuse `require_wallet_access`, but it would not satisfy the
operator-only cross-account report or effective-dated account mapping. A new
read-only operator role and its wallet scope require explicit design approval.

## Mounted routes and capture boundaries

- Core routers include audit, permits, permit requests, receipts, evidence,
  billing, and MCP (`app/main.py:652-674,743-754`). No insight router exists.
  The standard MCP endpoint is included conditionally in the schema
  (`app/main.py:746-753`); the router itself is disabled by default
  (`app/routers/mcp_standard.py:60-68`).
- Middleware is registered at `app/main.py:558-620`: rate limiting, body limit,
  CORS, security headers, then HEAD translation. A prospective ingress event
  must capture before authentication and validation without using untrusted
  header/JSON-RPC IDs as the stable server identity. The legacy MCP path reads
  and parses the body before `_handle_tools_call`
  (`app/routers/mcp.py:551-640`), and its current `request_id` comes from the
  client-supplied JSON-RPC `id` (`app/routers/mcp.py:392-403,576,638`).
  Existing audit request IDs therefore do not establish complete ingress.
- Standard `POST /mcp` authenticates and validates origin before the SDK
  dispatches to the governed `tools/call` handler
  (`app/routers/mcp_standard.py:672-729,913-926`). The deprecated REST
  `/mcp/tools/{service_id}/invoke` path is a third governed entry point
  (`app/routers/mcp.py:4532-4551`). Both have pre-handler denial boundaries
  distinct from the legacy JSON-RPC path.
- The governed replay branch returns before execution
  (`app/routers/mcp.py:1588-1657`). Upstream execution creates a durable
  prepared attempt at `app/routers/mcp.py:2096-2129`, claims dispatch through
  the `before_dispatch` hook at `app/routers/mcp.py:3123-3185`, then completes
  and receipts separately (`app/routers/mcp.py:3186-3201,3359-3390`). These
  are distinct boundaries for prospective attempt and terminal observation.
  Observer failures must be isolated from these business transitions.

## Durable evidence and safe joins

All listed rows are in the SQLModel database. A new reader must select narrow
safe columns, apply authorized wallet predicates in SQL before joining, and
deduplicate `(source, source_id)`; no existing list endpoint provides the
required common snapshot or keyset traversal.

| Source | Verified fields and meaning | Join or limit |
|---|---|---|
| Wallet | `wallet_id`, parent wallet, wallet type, created/updated times (`app/db/models.py:17-80`). | Owner name, email, and metadata are not safe report fields. Parent hierarchy is not a canonical customer account or effective-dated ownership map. |
| Permit and request | Permit issuer/subject wallets, subject key, status, expiry/revocation/issue/update times (`app/db/models.py:759-825`); permit request has issuer/subject wallets, request ID, status and decision times (`app/db/models.py:945-1009`). | Permit request is a request for authority, not automatically a tool execution. Current effective permit status is time-dependent (`docs/failure-semantics.md`, “Permit lifecycle inspection”). |
| Human approval | Wallet, permit, tool, approval ID, status, requested/decided/expiry times (`app/db/models.py:901-943`). | Approval ID links to dispatch or receipt, when present. Raw `reason` and reviewer identity are excluded. |
| Audit | Event ID, wallet, tool, endpoint, policy decision ID, `ok`, created time, sequence (`app/db/models.py:686-719`). | Legacy audit is unavailable in Stage 1. Its request ID is client supplied; metadata/error may contain client idempotency keys or raw strings (`app/routers/mcp.py:1513-1525,4421-4460`). Wallet-less audit rows cannot be attributed to a tenant. |
| Idempotency | Record ID, wallet, endpoint, operation kind, response reference, status code, created/expiry times, ledger entry ID (`app/db/models.py:1045-1093`). | `(wallet, endpoint, key)` is the database identity, but raw key and response JSON are excluded. Effect-free recovery may delete rows (`app/services/idempotency.py:930-1042`), so absence is not proof of no ingress. |
| Dispatch | Attempt ID, idempotency record ID, wallet, permit, approval, key ID, public tool, ledger ID, state, bounded error code and prepared/claim/terminal/refund/budget timestamps (`app/db/models.py:1095-1173`). | One attempt per idempotency record by unique FK. `result_json`, upstream name/origin, request/response hashes and claim hash do not belong in exports. `dispatch_claimed` is a committed send claim, not delivery proof (`app/services/mcp_dispatch_attempts.py:165-177`; `docs/failure-semantics.md`, “The invariant”). |
| Ledger | Entry ID, wallet, action, amount, timestamp, operation key, correlation ID (`app/db/models.py:84-152`). | A governed debit uses the idempotency record ID as `operation_key` (`app/services/mcp_dispatch_attempts.py:269-283`). Verify action, wallet and amount; do not join solely on arbitrary correlation text. Refund is an independent ledger fact. |
| Receipt | Receipt ID, idempotency/dispatch/permit/wallet/ledger/audit links, tool, outcome, bounded reason code, approval ID, created time (`app/db/models.py:829-898`). | Signed gateway accounting; receipt absence can be a crash or earlier denial. Receipt `success` proves a valid response reached the gateway, not downstream effect (`docs/failure-semantics.md`, “Terminal outcomes”). |
| Refund work item | Pending/resolved item is embedded in the idempotency `response_json` and linked to `failed_unrefunded` receipt (`app/services/refund_reconciliation.py:81-101,279-299,340-402`). | There is no standalone refund table. Existing `list_items` joins all failed-refund rows, then filters wallet in Python (`app/services/refund_reconciliation.py:404-464`); do not reuse it for a scoped reader. Parse only allowlisted state fields after an SQL wallet predicate. |

Receipt links are explicit foreign keys except the legacy approval string.
The Stage 1 reader withholds legacy audit rows: `audit_event_id` is not unique
across receipts, and a scoped query cannot prove one original operation without
reading another owner's epoch. Audit-only denials also lack a trusted original
anchor. The reader reports audit as unavailable with `audit_anchor_unverified`.
Refund ledger entries linked to verified debits remain readable, but embedded
refund work-item state in `response_json` is unavailable to this reader.
The existing evidence builder enforces wallet predicates on permit, audit,
ledger and dispatch lookups (`app/trust/evidence.py:127-212`), a pattern to
retain. The Stage 1 root set includes surviving idempotency records and their
verified dispatch and ledger rows without receipts; unanchored audit remains
withheld. Completely unrecorded ingress remains invisible until
prospective capture. Heuristic matches are ambiguous, never silent joins.

## Snapshot, retention, counts, and classification limits

- `app/db/database.py:118-177,245-260` exposes async engines and session
  factories. `get_session` commits on exit (`app/db/database.py:413-431`);
  it is not a read-only repeatable-read snapshot. The reader needs an explicit
  single read transaction/snapshot on PostgreSQL. Cross-store observations
  without a common snapshot must be labelled non-atomic.
- Audit listing uses offset pages and sorts only by created time
  (`app/services/audit_log.py:128-168`), so equal timestamps and late writes
  can duplicate or skip rows. Audit total/grouped counts are SQL-wide, while
  policy reasons scan at most 10,000 recent rows
  (`app/services/audit_log.py:17-20,254-306`). Receipt HTTP pages cap at 200
  and lack time/reason filters (`app/routers/receipts.py:80-107`). The legacy
  exporter takes one 200-row audit/ledger page by default and uses a bootstrap
  key (`scripts/operator_analytics_export.py:42-55,66-112,115-154`). None
  can supply exact insight cohorts.
- `TELEMETRY_RETENTION_HOURS=168` is a separate telemetry setting
  (`app/core/config.py:333-335`). Receipt/audit/idempotency retention is
  unverified; the insight reader must not assume 168 hours or claim complete
  7/30-day ingress from historical rows. Historical `first_observed_evidence`
  and prospective `ingress` cohorts stay separate.
- Durable dispatch states are prepared, claim/sent, and terminal succeeded,
  returned_error, delivery_uncertain or response_rejected
  (`app/services/mcp_dispatch_attempts.py:165-177`). Refund and budget release
  have independent checkpoints (`app/db/models.py:1151-1171`). A refund does
  not prove no downstream effect; a dispatch claim does not prove delivery.
  Unknown states, absent receipts, and contradictory/null times remain visible.
- No per-operation server release, deployment, or allowlisted client-version
  fields were found in these models. Do not backfill them from current build
  metadata. `app/core/build_metadata.py` describes process build provenance,
  not historical operation attribution.

## Migration and test setup

The migration directory is `migrations/versions/`. A read-only AST traversal
of every `revision`/`down_revision` found **43 revisions, one root**
`001_initial`, and **one head** `042_permit_action_binding` with parent
`041_scrub_content_owner_keys` (`migrations/versions/042_permit_action_binding.py:10-11`).
The chain includes the non-ordinal revision `3988bd05deca` between 021 and
023. Reserve any next revision only after checking concurrent branches again.
No migration was run on real data.

`make test` runs `uv run --with-requirements requirements.txt pytest tests/ -q -m "not proof"`;
`make test-all` runs all tests (`Makefile:36-46`). Focused
commands in the approved plan run `pytest tests/test_operation_insights_*.py`.
The shared test fixture defaults to SQLite `./test.db`, in-memory durable
state, and a test bootstrap key (`tests/conftest.py:129-165`); use a unique
temporary database path for new synthetic tests so other jobs remain healthy.
Migration tests use a disposable SQLite database (`tests/test_migrations.py:13-21`).
Actual PostgreSQL process proofs require explicit isolated/empty database and
opt-in flags; the harness refuses non-PostgreSQL, production-like, stale-schema
or populated databases (`Makefile:59-81`; `tests/test_mcp_postgres_multiprocess.py:1-7,117-125`).

## Concurrent checkout observation

The separate historical checkout at `~/Projects/agent-middleware-api` and
its `.claude/worktrees/` were inspected read-only. Three visible Claude
worktrees were clean, detached and last committed between 2026-09-20 and
2026-10-01; none contained an insight branch. Other shared worktrees and
unpublished work were not modified. This observation does not establish that
no unseen concurrent work exists; recheck immediately before editing shared
files or reserving a migration revision.

At this review, open PR #766 proposes a `043` demo-tenant migration and edits
models, authentication, and MCP handling. PR #638 edits permit authorization
and reconciliation; PR #627 edits money-endpoint idempotency. None is an
insight implementation. A future insight migration cannot claim revision
`043` without checking how those branches are resolved.
