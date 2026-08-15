# Invention Inventory — Verified Against Code

**Status:** engineering verification of a third-party memo. Reviewed at commit
`53e654c`. The source memo ("Invention Inventory Memo", analyst OpenClaw-b6l,
2026-08-14) was written against commit `9e2c99f`.

**This is not a legal document.** Nothing here is a patentability
determination, a prior-art search, a freedom-to-operate opinion, or a claim
construction. It answers one narrower question: *does the source memo describe
the code correctly?* Where it does not, the correction is recorded below so
that counsel drafts from verified evidence rather than from the draft memo.

The novelty commentary in [Novelty pushback](#novelty-pushback) is engineering
opinion offered for triage. It is explicitly not a legal opinion.

## Why this document exists

The source memo's twelve mechanisms are **real** — this is not a fabricated
inventory, and the two strongest entries survive verification cleanly. But a
material fraction of its *named evidence* is wrong: functions attributed to the
wrong module, symbols that do not exist under the cited name, and one
load-bearing mechanism claim that describes an implementation this system does
not use.

That last category is why the corrections matter. A claim drafted from the memo
as written would describe a concurrency mechanism — pessimistic row locking
with a unique-constraint counter — that this codebase deliberately does *not*
implement. Specification defects of that shape are expensive to discover during
prosecution.

## Corrections to the source memo

Thirteen corrections. Wrong names in the "Memo says" column appear deliberately,
so the delta is auditable.

| # | Memo says | Code actually has |
|---|---|---|
| 1 | **INV-003/008: concurrent writers serialized via `wallet_hash_order`, a per-wallet incrementing counter with a database unique constraint** | **`wallet_hash_order` does not exist anywhere in `app/`.** Serialization is `AuditChainHeadModel` (`app/db/models.py:692`) — a per-wallet head row holding `last_seq` and `last_chain_hash` — advanced by *optimistic* conditional `UPDATE ... WHERE last_seq = <observed>` with a 64-attempt retry and flat jittered backoff (`app/services/audit_chain.py:200-300`). The implementation explicitly avoids `SELECT ... FOR UPDATE` so behaviour is identical on SQLite and Postgres. **This is a different mechanism class** — optimistic compare-and-set, not pessimistic locking and not a unique-constraint race |
| 2 | INV-001: `authorize_reserve_and_prepare()` in `app/services/permits.py` | It is in `app/services/mcp_dispatch_attempts.py:344`, alongside `attach_charge` (`:519`) and `complete` (`:641`). `permits.py:426` has `authorize_and_reserve` — a *different* function |
| 3 | INV-003: `sign_audit_event()`, `_rebuild_wallet_hash_chain()` | Neither exists. Actual: `_sign_with_previous` (`audit_chain.py:55`), `audit_payload` (`:20`), `AuditChainVerification` (`:310`), `_assert_same_audit_intent` (`:140`) |
| 4 | INV-004: `_normalize_value()`, `sign_json()`, `_load_signing_key()` in `signing_keys.py` | Actual: `canonical_json` (`signing_keys.py:66`) containing a *nested* `normalize` closure (`:74`); `sign_payload_with_key_id` (`:324`); `_load_private_key` (`:117`); `_decode_private_key` (`:38`) |
| 5 | INV-005: `_reconcile_charge()`, `_create_or_verify_refund_ledger_entry()` | Neither exists. Actual: `RefundReconciliationService` (`refund_reconciliation.py:80`), `_apply_refund` (`:681`), `build_pending_refund_reconciliation` (`:44`), `validate_resolved_claim` (`:408`). The `refund-{ledger_entry_id}` pattern itself **is** real (`:61`, `:276`) |
| 6 | INV-006: `IdempotencyKeyReuseError` | Actual: `IdempotencyConflictError("idempotency_key_reused")` (`idempotency.py:70`) — the memo recalled the *reason string*, not the class |
| 7 | INV-012: `emergency_revoke()` in `api_key_service.py` | The service method is `emergency_revocation` (`api_key_service.py:515`). `emergency_revoke` is the *router* function (`app/routers/api_keys.py:233`), which calls it at `:247` |
| 8 | INV-011: the script "accepts only `DATABASE_PUBLIC_URL` (never private `DATABASE_URL`)" | Both `load_public_database_url` (`scripts/retire_owner_keys.py:54`) and `load_private_database_url` (`:90`) exist; `main()` selects between them via `--private-db` (`:220`). The real property is **no cross-fallback**: each loader reads exactly one variable and refuses to substitute the other. Public rejects `localhost`, `.internal`, and non-global IPs; private requires `.railway.internal` and rejects any query/fragment (blocking asyncpg `?host=` overrides) |
| 9 | INV-004: the receipt links "six evidence types" | `ReceiptResponse` (`app/schemas/trust.py:194-207`) carries **seven** linkage fields. The memo omits `dispatch_attempt_id` (`:195`) — the field binding the receipt to INV-001's state machine, and arguably the most distinctive one |
| 10 | INV-001: "six terminal outcomes" in `docs/failure-semantics.md` | That document tabulates **seven** (`docs/failure-semantics.md:40-56`): `success`, `denied`, `insufficient_funds`, `failed_refunded`, `delivery_uncertain`, `response_rejected`, `failed_unrefunded`. Separately, `_CALL_OUTCOMES` (`upstream_mcp.py:60-68`) lists six *call* outcomes — a different vocabulary at a different layer |
| 11 | INV-001: the reconciler transitions `prepared → failed_refunded` | `failed_refunded` is a **receipt outcome**, not a dispatch state. `DISPATCH_TERMINAL_STATES` (`mcp_dispatch_attempts.py:32-39`) is exactly `{succeeded, returned_error, delivery_uncertain, response_rejected}`. The reconciler completes a stale `prepared` attempt as `state="returned_error"` with `error_code="reconciled_stale_prepared"` (`mcp_dispatch_reconciliation.py:244-252`); the *receipt* then reports `failed_refunded`. The memo conflates two vocabularies |
| 12 | INV-007/009: `agent_money.py` — `charge()` does `SELECT ... FOR UPDATE` with balance check | `AgentMoney.charge` (`agent_money.py:317`) is a thin delegate to `BillingEngine.charge`. The actual `with_for_update()` debit is in `app/services/billing_engine.py:255`, which the memo never cites |
| 13 | INV-005: a duplicate refund "collides on the primary key and the `IntegrityError` is safely absorbed" | **`refund_reconciliation.py` neither imports nor catches `IntegrityError`** — a collision would propagate and roll back. Concurrent repair is serialized by reading the durable work item `with_for_update` (`:512`) plus the process-local `_process_lock` (`:87`, `:492`). The only `IntegrityError` absorption in the money path is on the *charge* side (`billing_engine.py:506`). This correction was raised by an automated reviewer on PR #282: the first version of this document repeated the source memo's claim without verifying it — the same failure mode the document was written to correct |

Line-count approximations in the source memo's appendix were not accurate and
have been regenerated from `wc -l`; see the [appendix](#appendix-mechanism-to-file-map).

## Evidence confidence key

- **Verified** — every cited symbol resolves; the described behaviour matches
  the implementation.
- **Partially verified** — the mechanism exists, but the memo's description or
  evidence needed correction.
- **Not supported** — the described mechanism is not what the code does.

---

## INV-001 — Atomic permit admission with crash-recoverable dispatch state machine

**Evidence confidence: Verified** (after corrections 2, 10, 11)

Four operations commit as one crash-consistent unit: budget reservation under
row lock, permit scope validation, creation of a durable dispatch attempt in
`prepared`, and the debit ledger entry. Its docstring states the invariant
directly — *"every durable reservation has a row the reconciler can compensate,
and a failed transaction leaves neither"*
(`mcp_dispatch_attempts.py:360-366`).

A second boundary, the `dispatched` checkpoint, is written immediately before
the network send. Past that point the system classifies failure as
`delivery_uncertain`: the charge is retained and the call is **never**
redispatched. The reconciler finalizes orphans without redispatch — a stale
`prepared` becomes `returned_error`/`reconciled_stale_prepared` and refunds; a
stale `dispatched` becomes `delivery_uncertain` and stays charged
(`mcp_dispatch_reconciliation.py:228-265`).

The distinguishing property is that the dispatch checkpoint is not a log line
but a database row mutation that **changes refund eligibility**. The system
preserves ambiguity rather than resolving it.

Evidence:

- `app/services/mcp_dispatch_attempts.py` — `authorize_reserve_and_prepare` (`:344`);
  `attach_charge` (`:519`); `mark_dispatched` (`:567`); `complete` (`:641`);
  `DISPATCH_TERMINAL_STATES` (`:32`); `DISPATCH_ACTIVE_STATES` (`:40`);
  `_assert_prepared_match` (`:189`).
- `app/services/upstream_mcp.py` — `_call_tool_once` (`:890`); the
  `before_dispatch` callback and `dispatch_started` flag (`:896-990`);
  `UpstreamMcpError.dispatch_started` (`:98`);
  `UpstreamMcpDeliveryUncertainError` (`:121`).
- `app/services/mcp_dispatch_reconciliation.py` — `_reconcile_active` (`:228`);
  `_finalize_terminal` (`:267`); `_find_operation_debit` (`:360`);
  deterministic audit id `audit-dsp-{sha256_hex(attempt_id)[:32]}` (`:464`).
- `docs/failure-semantics.md` — seven terminal outcomes (`:40-56`); crash
  windows A, B, C, D1, D2, E (`:81-113`), each with a named test.

Note for counsel: the crash-window table cites specific tests per window,
including multi-process kill tests under Postgres. That is unusually strong
enablement evidence.

## INV-002 — DNS pinning with TLS SNI preservation for MCP upstreams

**Evidence confidence: Verified** — every symbol in the source memo resolved
exactly as cited. The best-supported entry in the inventory.

A custom `httpx` transport resolves the upstream hostname once at configuration
time and pins subsequent connections to that address, while preserving the
original hostname in both the HTTP `Host` header and the TLS SNI extension. Any
request whose URL or `Host` header deviates from the configured origin is
refused.

Evidence, all in `app/services/upstream_mcp.py`:

- `validate_upstream_url` (`:325`) — one-time resolution; rejects addresses
  where `not address.is_global` (`:389`).
- `_PinnedAsyncTransport` (`:474`) — `_expected_url` (`:486`),
  `_expected_host_header` (`:487`), `_server_name` for SNI (`:488`),
  `_pinned_address` (`:489`).
- Origin enforcement on every request — `Host` header comparison (`:501`).
- `extensions["sni_hostname"] = self._server_name` (`:508`) with
  `request.url.copy_with(host=self._pinned_address)` (`:511`) — the two halves
  of the mechanism, adjacent.

The pairing is the point: pinning to a raw IP alone breaks TLS virtual hosting
and certificate validation, while re-resolving per request reopens rebinding.

## INV-003 — Per-wallet signed audit chain with optimistic writer serialization

**Evidence confidence: Partially verified** — the chain is real and correctly
described; **the concurrency mechanism in the source memo is Not supported**
and has been rewritten here rather than patched.

An append-only tamper-evident log in which each wallet has its own hash chain.
Each event carries a payload hash, `previous_hash`, `chain_hash`, sequence
number, and an Ed25519 signature.

**Concurrency (corrected).** Writers are serialized through
`AuditChainHeadModel` (`app/db/models.py:692`), one row per wallet, keyed by
`wallet_key` (the wallet id, or `""` for wallet-less events). An append reads
`last_seq` and `last_chain_hash`, signs the successor, then advances the head
with a conditional `UPDATE ... WHERE last_seq = <observed>`. A writer whose
update matches zero rows lost the race and retries against the new head — 64
attempts with flat jittered backoff. The signing key is provisioned *before*
the transaction so signing inside it is pure crypto with no nested DB write.
Deterministic event ids are checked inside the same transaction, so a racing
writer either sees the row now or loses the head update and sees it on retry.

The implementation notes its own design rationale: this avoids
`SELECT ... FOR UPDATE` entirely so the behaviour is identical on SQLite and
Postgres (`audit_chain.py:204-212`). Any claim drafted here must describe
optimistic compare-and-set, not locking.

Evidence:

- `app/services/audit_chain.py` — `append_chained_audit_event` (`:200`);
  `_sign_with_previous` (`:55`); `audit_payload` (`:20`); `_HeadConflict`
  (`:132`); `AuditEventConflictError` (`:136`); `_assert_same_audit_intent`
  (`:140`); `AuditChainVerification` (`:310`).
- `app/db/models.py` — `AuditChainHeadModel` (`:692`).
- `app/routers/audit.py` — `verify_chain` at `POST /v1/audit/verify-chain`
  (`:161`).

> The source memo's `wallet_hash_order` error most likely originated in this
> repository, not with the analyst: the `AuditChainHeadModel` docstring
> previously claimed `FOR UPDATE` locking, contradicting the service that uses
> it. That docstring was corrected in the same change that added this document.

## INV-004 — Multi-evidence cryptographic receipt with deterministic canonicalization

**Evidence confidence: Partially verified** (corrections 4 and 9)

A signed receipt linking **seven** evidence fields, not six
(`app/schemas/trust.py:194-207`): `idempotency_record_id`,
`dispatch_attempt_id`, `permit_id`, `request_hash`, `response_hash`,
`ledger_entry_id`, `audit_event_id`. The receipt proves permit validity,
financial charge, audit-log entry, dispatch identity, and payload integrity in
one artifact.

Canonicalization is load-bearing: `canonical_json` (`signing_keys.py:66`)
normalizes `Decimal` through `.normalize()` and `format(..., "f")`, coerces
naive datetimes to UTC and emits ISO 8601, recursively sorts dict keys, and
serializes with `separators=(",", ":")` and `sort_keys=True`. Without it,
`Decimal("10.00")` and `Decimal("10")` would produce different signature bytes
and crash reconciliation could not reproduce a live receipt.

That reproducibility is asserted, not assumed: the reconciler shares
`_permit_constraints_snapshot` (`mcp_dispatch_reconciliation.py:307`) with the
live path and validates the result through `_assert_receipt_match` (`:656`,
called at `:603` and `:647`), with a named test —
`test_reconciler_constraints_snapshot_matches_live_path`.

Evidence: `app/services/receipts.py` — `ReceiptService` (`:69`),
`create_receipt` (`:208`), `verify_receipt` (`:504`), `_verification_payload`
(`:71`), `_assert_idempotent_match` (`:151`). Signing:
`sign_payload_with_key_id` (`signing_keys.py:324`), `sha256_hex` (`:99`).

## INV-005 — Exact-once refund reconciliation with deterministic entry IDs

**Evidence confidence: Partially verified** (corrections 5 and 13)

Exact-once refunds without a separate idempotency store: the refund ledger entry
id is derived from the original charge id as `refund-{ledger_entry_id}`
(`refund_reconciliation.py:61`, `:276`), so a duplicate refund is a duplicate
primary key rather than a second row.

The deterministic id is the *naming* rule, but it is not what serializes
concurrent repair. Two mechanisms do that, and a claim should rest on them:
the durable work item is read `with_for_update` inside the transaction that
applies the refund (`:512`), so concurrent Postgres workers queue on that row;
and `_process_lock` (`:87`, held across `retry` at `:492`) keeps a single
worker deterministic on SQLite. Proven by
`test_concurrent_refund_reconciliation_is_exactly_once_in_postgres`
(`tests/test_permit_postgres_concurrency.py:736`).

Note what this path does **not** do: `refund_reconciliation.py` neither imports
nor catches `IntegrityError`. A primary-key collision would propagate and roll
the transaction back, not be absorbed. The only `IntegrityError` absorption in
the money path is on the *charge* side, guarding the wallet/operation-key
constraint (`billing_engine.py:506`).

Forged-resolution detection: a work item marked `resolved` is re-validated
against the ledger on every read via `validate_resolved_claim` (`:408`), whose
docstring requires "a resolved claim to be backed by one exact ledger refund"
(`:415`). It is invoked on each read path (`:364`, `:428`, `:488`, `:548`). A
`resolved` claim with no matching refund row is rejected.

Evidence: `RefundReconciliationService` (`:80`); `_apply_refund` (`:681`);
`build_pending_refund_reconciliation` (`:44`); `_parse_item` (`:245`).
Compensation on the dispatch path: `_compensate_returned_error`
(`mcp_dispatch_reconciliation.py:323`) and `_find_operation_debit` (`:360`),
which locates the original debit by `operation_key` even when the crash preceded
`attach_charge`.

## INV-006 — Replay-safe idempotency with request-hash binding

**Evidence confidence: Partially verified** (correction 6)

A record is *identified* by `(wallet_id, endpoint, idempotency_key)` — that is
the uniqueness constraint, with endpoint canonicalization as described below.
The `request_hash` is not part of that identity; it **binds a payload** to the
record, so reusing the identity with a different payload raises
`IdempotencyConflictError("idempotency_key_reused")` (`idempotency.py:67-70`).
Identity decides which record you get; the hash decides whether you are allowed
to have it. That pairing is what blocks payload substitution under a replayed
key. In-progress requests
raise `IdempotencyInProgressError` (`:33`) or block for a bounded wait
(`_wait_for_replay`, `:86`, polled with a caller-supplied timeout at `:124-158`).

Transport independence is enforced in the schema, and this is the sharper part
of the mechanism. Beyond the plain uniqueness constraint on
`(wallet_id, endpoint, idempotency_key)`, a second **expression** unique index
collapses `/mcp/invoke`, `/mcp/messages`, and `/mcp/tools/%/invoke` to a single
canonical endpoint (`app/db/models.py:1004-1015`). One logical call therefore
has one identity — and one debit and one dispatch — across every endpoint
spelling and both worker generations.

## INV-007 — Wallet debit with hard budget cap and hierarchical delegation

**Evidence confidence: Partially verified** (correction 12)

Multi-wallet operations acquire `FOR UPDATE` locks in globally sorted wallet-id
order to prevent deadlocks (`wallet_engine.py:155`, used at `:486` and `:584`).
The debit itself — balance check and atomic decrement under `with_for_update()`
— is in `BillingEngine.charge` (`billing_engine.py:255`), which
`AgentMoney.charge` (`agent_money.py:317`) delegates to.

Child wallets inherit parent TTL: `_effective_expiry` (`wallet_engine.py:99`)
walks the parent chain at runtime, bounded by
`_MAX_WALLET_HIERARCHY_DEPTH = 32` (`:47`), so a parent expiry constrains every
descendant and a cycle or over-deep chain fails closed. `create_child_wallet`
(`:339`) applies inheritance at creation; `reclaim_child_wallet` (`:461`)
returns unspent credits to the parent with ledger entries on both sides.

Ledger operation identity is separately guarded:
`ledger_operation_key_reused` (`billing_engine.py:155`).

## INV-008 — Deterministic audit event IDs

**Evidence confidence: Verified**, but see the merge recommendation below.

`chain_hash` is computed over the previous chain hash and the current payload
hash (`audit_chain.py:91-95`). Event ids for dispatch attempts are derived from
the attempt id — `audit-dsp-{sha256_hex(attempt.attempt_id)[:32]}`
(`mcp_dispatch_reconciliation.py:464`) — so two concurrent reconcilers converge
on one audit identity with no distributed lock. Proven by
`test_concurrent_dispatch_reconcilers_create_one_signed_audit_in_postgres`.

## INV-009 — Crash-consistent ledger behaviour

**Evidence confidence: Partially verified** (correction 12); weakest standalone
entry — see [Novelty pushback](#novelty-pushback).

Composed of: transactional money movement; globally sorted lock acquisition
(`wallet_engine.py:155`); deterministic refund ids (INV-005); the dispatch
checkpoint boundaries (INV-001); and `LedgerEntryModel.balance_after`
(`app/db/models.py:108`), which permits offline balance verification without
replaying all transactions. Credit minting is deduplicated by a `UNIQUE`
constraint on `payment_intent_id`, with only that duplicate-key failure
swallowed so a real payment is never silently dropped
(`stripe_integration.py:491-505`).

## INV-010 — Fail-closed production startup

**Evidence confidence: Verified**; the source memo *understates* it.

`validate_trust_mode_config` (`app/core/trust_mode.py:71`) refuses to boot a
production-like environment unless the full strict posture holds. The memo lists
six checks; the signature accepts **twelve** validated inputs (`:71-85`),
including `static_dev_api_keys`, `enable_dev_key_self_provision`,
`enable_public_mcp_endpoint`, `redis_url`, and `public_url` beyond the six
named. The Ed25519 key is validated structurally, not merely for presence
(`_has_valid_ed25519_private_key`). Violations accumulate into a list and are
reported together rather than failing on the first.

Environment classification is `PRODUCTION_LIKE_ENVIRONMENTS` (`:17`) —
`prod`, `production`, `staging`, `stage`, `preprod`, `pre-production`,
`preview` — with `is_production_like_environment` (`:60`) defaulting closed.
Test matrix: `tests/test_trust_mode_guardrails.py` (330 lines).

## INV-011 — Rolling owner-key retirement

**Evidence confidence: Partially verified** (correction 8)

Two-phase credential retirement for rolling deployments. Phase 1, migration
`025_remove_plaintext_owner_keys`, scrubs legacy `owner_key` columns and sets
empty server defaults so new workers need not supply values, while retaining the
columns so old workers still running mid-rollout remain schema-compatible. Phase
2, `scripts/retire_owner_keys.py`, runs after the platform confirms only new
workers are active: `retire_owner_keys` (`:138`) performs an idempotent scrub,
asserts no non-empty values remain, and revokes refresh-token rows written by
old workers without the later API-key binding.

Credential hygiene is real but differently shaped than the memo describes (see
correction 8): two strict loaders, no cross-fallback, selected by `--private-db`
(`:220`). `OwnerKeyRetirementError` messages never render the URL or any
credential, and the generic `except` path reports only a `connection_kind`
label (`:240-246`).

Race coverage: `tests/test_retire_owner_keys.py` (334 lines) simulates an old
worker writing *after* the migration and asserts the script catches and scrubs
it.

## INV-012 — API key lifecycle management

**Evidence confidence: Partially verified** (correction 7); title does not match
content — see [Novelty pushback](#novelty-pushback).

Keys are stored as SHA-256 hashes with a short prefix retained for
identification; the full key is returned only at creation
(`api_key_service.py:84`, `mask_key` at `api_key_service.py:97`;
`APIKeyModel.key_hash`, `key_prefix`, `rotation_count` at
`app/db/models.py:267-272`). Rotation (`api_key_service.py:338`) optionally
revokes the predecessor and writes `KeyRotationLogModel`
(`app/db/models.py:609`). `emergency_revocation` (`api_key_service.py:515`)
invalidates a wallet's keys immediately.

The anti-proliferation guardrail is narrower than the memo implies: rotation
raises `InvalidRotationRequestError` when `revoke_old` is true but no `key_id`
identifies what to revoke (`api_key_service.py:369-371`). It prevents an
*unresolvable revocation request*, not unbounded key creation generally.

---

## Novelty pushback

Engineering opinion, offered so counsel is not the first to encounter these.
Not a legal opinion, and not a patentability assessment.

**Prioritize INV-001 and INV-002.** These are the two entries whose core
mechanisms have the strongest verified evidence. INV-002 is the only entry that
needed no correction at all; INV-001 required corrections 2, 10, and 11 to its
cited details, but every one was a mislabel in the memo rather than a gap in the
implementation. INV-001 additionally has
enablement support most software patents lack: seven enumerated terminal
outcomes, six labelled crash windows, and a named test per window including
multi-process kill tests under Postgres.

**INV-008 should be merged into INV-003.** The source memo concedes INV-008
"complements INV-003" and separates it only "because the brief calls it out
explicitly" — a drafting-process reason, not a technical distinction. Both rest
on `audit_chain.py` and the same hash construction. Filing them separately
invites an obviousness-type double-patenting objection. Deterministic event ids
are better positioned as a dependent claim.

**INV-009 has no implementation of its own.** Every mechanism it cites belongs
to INV-005 (deterministic refund ids), INV-007 (sorted-order locking), or
INV-001 (checkpoint coupling). Its only distinct artifact is
`balance_after`. As a standalone filing it is a summary of other entries; as a
combination claim it needs an articulated reason the composition is more than
the sum, which the memo does not supply.

**INV-012 is mis-titled and probably the weakest entry.** The title promises
"Dev-Key Production Guardrails" but the body describes ordinary API-key
lifecycle management. The memo's own "closest existing technique" concedes
GitHub personal access tokens are hashed, prefix-exposed, and rotatable — which
is most of the claim. The narrow guardrail that survives (correction 7) is a
small argument-validation check. Note that the genuinely unusual dev-key
posture — `STATIC_DEV_API_KEYS` and `ENABLE_DEV_KEY_SELF_PROVISION` being
*refused at boot* in production-like environments — lives in INV-010's
validator, not in `api_key_service.py`. If this entry is pursued, it should be
re-scoped around that.

**INV-004's canonicalization defense is a priority argument, not a novelty
one.** `canonical_json` is materially RFC 8785 (JCS)-shaped: sorted keys,
minimal separators, normalized numerics. The memo's rebuttal — that the
implementation "predates common library support" — speaks to priority date, not
to distinction over prior art, and it is asserted rather than evidenced. If
pursued, establish the actual first-commit date from `git log` and shift the
emphasis to the seven-field evidence linkage (especially `dispatch_attempt_id`),
which is the part with no obvious analogue.

**INV-003's rewritten mechanism may be stronger than the memo's version.**
Optimistic compare-and-set on a per-wallet head row, chosen specifically so the
same code path is correct on both SQLite and Postgres without `FOR UPDATE`, is a
more specific and more defensible mechanism than the pessimistic locking the
memo described. The correction is not merely a fix; it may improve the entry.

**A cross-cutting caution on framing.** Several entries lean on the claim that
the composition is novel while conceding each component is known. That is a
legitimate position, but it makes the *coupling* the inventive step. For INV-001
the coupling is concrete and identifiable — a durable row mutation that changes
refund eligibility. For INV-009 it is not. Counsel should expect the coupling
itself to carry the claim in every "novel composition" entry.

## Appendix: mechanism-to-file map

Line counts are `wc -l` at commit `53e654c`, replacing the source memo's
approximations. Counts are whole-file totals; most files serve more than one
mechanism, so the column does not sum meaningfully.

| Mechanism | Files | Lines |
|---|---|---|
| INV-001 Dispatch state machine | `app/services/mcp_dispatch_attempts.py` (1035), `mcp_dispatch_reconciliation.py` (771), `upstream_mcp.py` (1072), `permits.py` (1160), `docs/failure-semantics.md` (206) | 4244 |
| INV-002 DNS pinning | `app/services/upstream_mcp.py` | 1072 |
| INV-003 Audit chain | `app/services/audit_chain.py` (550), `signing_keys.py` (382), `app/db/models.py` (1136) | 2068 |
| INV-004 Multi-evidence receipt | `app/services/receipts.py` (590), `signing_keys.py` (382), `app/schemas/trust.py` (376), `mcp_dispatch_reconciliation.py` (771) | 2119 |
| INV-005 Exact-once refund | `app/services/refund_reconciliation.py` (712), `mcp_dispatch_reconciliation.py` (771) | 1483 |
| INV-006 Idempotency | `app/services/idempotency.py` (625), `app/db/models.py` (1136) | 1761 |
| INV-007 Hard budget cap | `app/services/wallet_engine.py` (761), `billing_engine.py` (910), `agent_money.py` (439) | 2110 |
| INV-008 Deterministic audit ids | `app/services/audit_chain.py` (550), `mcp_dispatch_reconciliation.py` (771) | 1321 |
| INV-009 Crash-consistent ledger | `app/services/wallet_engine.py` (761), `billing_engine.py` (910), `stripe_integration.py` (568), `app/db/models.py` (1136) | 3375 |
| INV-010 Fail-closed boot | `app/core/trust_mode.py` (223), `tests/test_trust_mode_guardrails.py` (330) | 553 |
| INV-011 Owner-key retirement | `migrations/versions/025_remove_plaintext_owner_keys.py` (86), `scripts/retire_owner_keys.py` (257), `tests/test_retire_owner_keys.py` (334) | 677 |
| INV-012 API key lifecycle | `app/services/api_key_service.py` (726), `app/routers/api_keys.py` (301), `app/db/models.py` (1136) | 2163 |

## Relationship to `docs/ip/`

`docs/ip/` (added by #280) is the **patent prosecution package**: prior-art
landscape, invention disclosure, claim sets, abstract and figures, IDS
candidates. This document is not a competing package: do not draft a filing
from it, and do not file it as part of the prosecution package. It is an
internal accuracy check, not disclosure material.

It answers a narrower question — *does a third-party memo describe this
code correctly?* — and its output is a corrections table plus evidence-
confidence markers.

Read `docs/ip/` for what to file. Read this for whether a specific cited
mechanism matches the implementation.

**The two prioritize differently, and counsel should know that before
reconciling them.** `docs/ip/README.md` leads with four mechanisms: atomic
budget reservation, exactly-once debit across a crash, signature-stable receipt
evolution, and offline verification with a status taxonomy. This document
prioritizes INV-001 (the dispatch state machine) and INV-002 (DNS pinning with
SNI preservation) on the narrower ground that their *cited evidence* survived
verification best — INV-002 needed no correction at all. Notably, `docs/ip/`
does not carry DNS pinning as a candidate, and this document does not assess
signature-stable receipt evolution. Neither list is wrong; they were built to
answer different questions. Where they disagree about strength, `docs/ip/` is
the one written for filing.

## Related

- [`docs/ip/README.md`](ip/README.md) — the prosecution package this document
  supports rather than replaces.
- [`docs/related-work.md`](related-work.md) — external literature mapped to the
  product wedge, with per-source verification levels.
- [`docs/failure-semantics.md`](failure-semantics.md) — terminal outcomes and
  crash windows underpinning INV-001.
- [`TRUST_MODEL.md`](../TRUST_MODEL.md) — the trust boundaries these mechanisms
  enforce.
