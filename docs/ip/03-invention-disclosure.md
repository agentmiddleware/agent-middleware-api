# Invention disclosure

Every mechanism below is traced to implementing code in this repository. Where a
detail is a design intention not yet fully implemented, it is marked
**[not implemented]** — counsel must not claim unimplemented subject matter as
reduced to practice, though it may still be described to support later claims.

---

## 1. Field

Distributed computing; access control and metered resource consumption for
autonomous software agents invoking external tools over a protocol such as the
Model Context Protocol (MCP); tamper-evident transaction evidence.

---

## 2. Background and the problem

An autonomous agent invoking a third-party tool creates three failure modes that
existing systems handle separately, and badly in combination.

**(a) Concurrent overspend.** A delegated authorization that carries a spending
cap must enforce that cap across concurrent invocations. The natural
implementation — read the permit, check remaining budget, write the new total —
is a read-modify-write, and two concurrent invocations can both read the same
stale total and both pass the check. Each then writes its own increment, and one
clobbers the other. The cap is exceeded and nothing in the record shows it.

Row locking is the textbook answer, and it is not sufficient. On some engines
(notably SQLite) `SELECT ... FOR UPDATE` parses and executes but takes no lock —
it is a silent no-op. Code that relies on it is correct in staging on PostgreSQL
and wrong in a single-file deployment, with no error to indicate the difference.
*This repository observed exactly that failure under an adversarial concurrency
test before it was fixed.*

**(b) Double debit across a crash.** Invoking a remote tool is not transactional
with the local ledger. The gateway must debit the caller's wallet and dispatch a
network call to a server it does not control. If the process dies between the
debit and the recording of what happened, a retry of the same idempotency key
faces an ambiguous record: an in-progress row with no stored response. Treating
it as "never happened" double-charges. Treating it as "already done" may report
success for a call that was refused, or that never reached the tool.

**(c) Evidence nobody has to trust the issuer for.** A gateway that authorizes,
meters, and bills its own tenants is not a disinterested party. A record it
alone can verify is an assertion, not evidence. The party who needs to check
what happened — an auditor, a counterparty, the human who delegated the
authority — may have no account, no credential, and no network path to the
gateway, and should not need one.

Prior systems address (a) with distributed locks or serializable isolation, (b)
with idempotency keys sharing a transaction with the business operation, and (c)
with signed audit logs. None composes: the remote tool call cannot join a local
transaction, and a signed log the issuer alone can interpret does not solve the
trust problem.

---

## 3. Summary

A gateway mediates agent-to-tool invocations and, for each invocation:

1. **Atomically authorizes and reserves** budget against a signed delegated
   permit, using a single guarded conditional update that enforces the cap at
   the row level and therefore remains correct where advisory row locks do not
   fire.
2. **Checkpoints the debit** on the idempotency record before finalization
   begins, so a later crash leaves a record that classifies itself.
3. **Reconciles** crashed records asymmetrically: never-charged records are
   released for safe retry; charged-but-unfinalized records are repaired from
   the signed receipt's actual outcome; charged records with no recoverable
   evidence are flagged rather than guessed at.
4. **Issues a signed receipt** whose signature covers a canonical serialization
   including a self-referential payload hash, and which signs additive fields
   only when present so that schema growth does not invalidate historical
   signatures.
5. **Publishes verification keys** at a well-known location so any third party
   can verify a receipt **offline**, with a status taxonomy that never reports
   an unreachable or unknown key as evidence of tampering.

---

## 4. Detailed description

### 4.1 The permit

A permit (`app/schemas/trust.py:10`, `app/services/permits.py:247`) is an
Ed25519-signed record binding:

| Field | Constraint expressed |
| --- | --- |
| `issuer_wallet_id` / `subject_wallet_id` | who delegated to whom |
| `subject_key_id` | which credential may exercise it |
| `scopes`, `allowed_tools` | which actions and tools |
| `max_credits`, `spent_credits` | total spend cap and consumption to date |
| `expires_at`, `nonce`, `status`, `revoked_at` | validity window, replay identity, revocation |
| `max_calls_per_tool` | per-tool invocation ceilings |
| `aggregate_value_cap` | cap on cumulative charged value |
| `forbidden_fields` | argument keys the subject may not supply |
| `recipient_domain` | destination restriction |
| `requires_human_approval` | gate before budget moves |

Permit issuance is refused when `max_credits` exceeds the issuing wallet's
balance (`permit_budget_exceeds_wallet_balance`) — authority cannot be delegated
that the issuer does not hold.

**As established in [`02-prior-art-landscape.md`](02-prior-art-landscape.md),
this structure is close to Daon US 12,688,261 and is described here as context,
not as a point of novelty.**

### 4.2 Atomic authorization and reservation — mechanism 1

`PermitService.authorize_and_reserve()` (`app/services/permits.py:426`) runs
inside one transaction:

1. Load the permit row requesting a row lock.
2. Validate: wallet match, key match, signature, status, expiry, tool allowlist,
   scopes, per-tool call count, aggregate value cap, forbidden argument fields.
3. **Reserve with a single guarded conditional update:**

```
UPDATE permits
   SET spent_credits = spent_credits + :estimated,
       updated_at    = :now
 WHERE permit_id     = :permit_id
   AND status        = 'active'
   AND spent_credits + :estimated <= max_credits
```

4. If the affected row count is not exactly 1, the reservation lost a race —
   refresh the row and deny with an accurate reason (`permit_revoked` /
   `permit_expired` if the status changed, otherwise `permit_budget_exceeded`
   with remaining, spent, and maximum credits attached). **No budget moved.**

The essential property: *the numbers read during validation are advisory; the
guarded write is the sole authority.* The cap predicate is evaluated by the
database as part of the same statement that performs the increment, so two
concurrent reservations cannot both satisfy it, **regardless of whether the row
lock in step 1 actually engaged**. Correctness no longer depends on the engine's
locking semantics.

The same guarded-update discipline is used for standalone reservation
(`reserve_budget()`, `:709`, which also emits threshold notifications at 80%,
90%, and 100% consumption), for clamped release (`release_budget()`, `:784`),
and for exactly-once release keyed to a dispatch attempt
(`release_dispatch_budget_once()`, `:820`, which closes a crash window that a
plain release leaves open).

A retry wrapper (`_run_with_write_retry`) re-runs the operation on retryable
write conflicts.

### 4.3 Dispatch attempt state machine

Because the tool call is remote and cannot join the local transaction, each
governed invocation carries a durable attempt record
(`app/services/mcp_dispatch_attempts.py`) advancing monotonically through
`prepared → dispatched → {succeeded | failed | delivery_uncertain}`.

`authorize_reserve_and_prepare()` (`:344`) establishes the budget reservation
and the `prepared` row in one atomic step, so a reservation can never exist
without the attempt record that governs its release. Re-entry adopts only an
invariant-equivalent prepared row (`_assert_prepared_match`), and the attempt is
bound to the approval identity that authorized it (`_assert_approval_binding`).

`delivery_uncertain` is a first-class terminal state, surfaced as HTTP 504. The
system declines to assert that a remote side effect did or did not occur when it
cannot know. Remote side effects are exactly-once only when the upstream honors
the forwarded idempotency key — a boundary the system states rather than hides.

### 4.4 Debit checkpoint and asymmetric reconciliation — mechanism 2

`IdempotencyService` (`app/services/idempotency.py`) keys a record on
`(wallet_id, endpoint, idempotency_key)` under a unique constraint, storing a
SHA-256 request fingerprint. Reuse of a key with a different fingerprint is
refused (`idempotency_key_reused`). A concurrent identical request may wait a
bounded interval for the first to finalize rather than failing immediately.

Two mechanisms go past the standard pattern:

**The checkpoint.** `mark_charged()` (`:379`) writes `ledger_entry_id` onto the
idempotency record *immediately after the wallet debit lands and before* the
receipt/audit/complete finalization sequence. Its sole purpose is to make a
crashed record self-classifying.

**Asymmetric repair.** `reconcile_stuck_records()` (`:408`) processes only
records idle beyond a threshold (default 900s), so in-flight requests are never
touched, and takes three different actions:

| Observed state | Interpretation | Action |
| --- | --- | --- |
| No checkpoint, no attempt, no receipt, effect-free endpoint | Crashed before anything happened | Delete the record; the key is safe to retry |
| Checkpoint present, receipt exists | Debit landed, finalization crashed | Rebuild the replay response **from the receipt's outcome** |
| Checkpoint present, no receipt | Money moved, nothing reconstructable | Leave untouched; count for manual review |
| Checkpoint present, dispatch attempt exists | Remote reconciler owns this | Skip — a generic repair would erase delivery uncertainty |

The second row carries a detail that matters: the rebuilt response is derived
from `receipt.outcome`, mapping `success → 200`, `insufficient_funds → 402`,
`denied → 403`, `delivery_uncertain → 504`, `response_rejected → 502`. A crash
can just as easily interrupt a *denial* as a success. Reconciling every crashed
record as a bare 200 would tell a replaying client its call succeeded when it
was refused.

A complementary path, `abandon()` (`:347`), releases an in-progress record when
a governed invoke stops on a retryable, side-effect-free condition (a human
approval still pending, an approval backend unreachable). It refuses to delete
any record carrying a stored response or a `ledger_entry_id` — if money moved,
the record survives for replay and repair.

### 4.5 The receipt and its signature — mechanism 3

A receipt (`app/services/receipts.py:208`) records one completed governed
invocation: identity, the permit and wallet, the tool, SHA-256 hashes of request
and response, the ledger entry, credits authorized versus charged, outcome and
reason code, the audit event, the approval, the constraints evaluated, and the
linkage to both the idempotency record and the dispatch attempt.

Signing (`app/services/signing_keys.py:324`):

1. Set `alg = "Ed25519"` and `kid = <key id>`.
2. Compute `payload_hash = SHA-256(canonical_json(payload))` and insert it into
   the payload — the signed bytes commit to a digest of themselves.
3. Sign `canonical_json(payload)` with Ed25519.

Canonicalization (`canonical_json`, `:66`) is a named, versioned contract —
`awi-canonical-json/1` — so an independent verifier can state which rules it
implements. Keys sorted, no whitespace, `Decimal` rendered via `normalize()` and
fixed-point formatting, `datetime` coerced to UTC ISO-8601, dicts recursively
sorted. A bundle declaring a different canonicalization version is refused
rather than verified under rules it was not signed with.

**Signature-stable schema evolution.** Optional fields — `reason_code`,
`idempotency_record_id`, `dispatch_attempt_id`, `approval_id`,
`constraints_evaluated` — are included in the signed payload **only when
present**. Verification (`verify_model`, `:558`) mirrors that construction
exactly. The result is that receipts signed before a field existed continue to
verify unchanged after it is added: the system's evidence schema can grow
without a re-signing migration and without silently invalidating history.

One historical migration backfilled an idempotency link onto receipts signed
before linkage existed. Rather than loosening verification generally, a
constrained fallback (`_has_unambiguous_historical_idempotency_link`, `:114`)
retries the legacy payload shape **only** when exactly one idempotency record
points at the receipt and its wallet and request hash both agree. Ambiguous,
absent, mismatched, or dispatch-linked cases fail closed.

`signing_input_for_model()` (`:520`) returns the exact canonical bytes a given
signature covers, branch for branch — and returns `None` when neither branch
verifies, so a receipt that cannot be proven is never exported as evidence.

### 4.6 Key distribution and offline verification — mechanism 4

Public keys are served at `/.well-known/trust-keys.json` and, for standard
tooling, as a JWK Set at `/.well-known/jwks.json`
(`app/routers/well_known.py:619`, `:670`). Neither endpoint will serve an empty
key set with a 200 — an unusable key set is refused rather than published, so a
verifier is never handed a document that would make every receipt look unknown.

Keys carry lifecycle status (`active`, `retired`, `disabled`). Rebinding an
existing key ID to different public material is rejected
(`signing_key_id_public_key_mismatch`). Verification against a disabled key
fails closed (`app/services/signing_keys.py:345`), and any decode, key
construction, or signature failure is caught and reported as "not verified"
rather than raised — one corrupt row must not mask tampering behind a 500.

The verifier (`b2a_sdk/src/b2a_sdk/receipt_verifier.py`) requires no network,
no database, and no credential; its only dependency beyond the standard library
is `cryptography`, and the offline path is tested to work with HTTP libraries
entirely absent. Two properties define it:

**Every reported field is read from the signed bytes.** The enclosing bundle is
unauthenticated envelope data and is never a source of truth. A bundle claiming
`receipt_id: X` around a payload signed for `Y` is rejected as `MISMATCH`.

**Failure is never silently "false".** The status taxonomy:

| Status | Meaning |
| --- | --- |
| `VERIFIED` | Signature holds — cryptographic claim |
| `INVALID` | Signature does not hold — cryptographic claim, i.e. tampering |
| `MISMATCH` | Envelope, payload, or caller expectation disagree, no demonstrated signature failure |
| `UNKNOWN_KEY` | Signing key not in the supplied key set |
| `MALFORMED` | Structurally unparseable input |
| `UNSUPPORTED` | Declared algorithm or canonicalization the verifier does not implement |

The distinction is the point. A verifier that collapses these into a boolean
reports a key-server outage identically to a forged receipt, and a caller acting
on that boolean will eventually escalate an availability incident as fraud. Only
`INVALID` asserts tampering; the rest describe missing input or capability.

### 4.7 Supporting: audit chain

Control-plane events are hash-linked and signed (`app/services/audit_chain.py`):
each event carries `previous_hash`, `payload_hash`, and
`chain_hash = SHA-256(previous_hash, payload_hash)`. Concurrent appends detect a
moved chain head and retry. **A known pattern (Certificate Transparency,
Trillian) — include as supporting detail, not as a point of novelty.**

---

## 5. Embodiments

**Primary — hosted governance gateway.** The gateway sits between agent
frameworks and MCP tool servers, holds the signing key, serves the well-known
key endpoints, and returns a receipt with every invocation.

**Self-hosted, single-file deployment.** The same code on SQLite rather than
PostgreSQL. This embodiment is what makes mechanism 1 necessary rather than
merely elegant: the guarded conditional update is the only thing enforcing the
cap when `FOR UPDATE` does not engage. Counsel should keep this embodiment in
the spec — it is direct support for the claim limitation.

**Federated issuers with a shared verifier. [not implemented]** Multiple
independent gateways issue receipts under distinct key IDs; a verifier holding
several key sets checks any of them offline. The key-set and `kid` machinery
supports this; no federated deployment exists.

---

## 6. Advantages

- Spend caps hold under concurrency without depending on engine-specific lock
  semantics.
- A crash between debit and finalization resolves to a known state, or is
  flagged rather than guessed at.
- Evidence is verifiable by parties who trust neither the agent nor the gateway,
  with no account and no network path.
- Evidence schemas can evolve without invalidating historical signatures.
- Verification failures are diagnosable: outages are never reported as fraud.

---

## 7. Known limitations to state honestly

Counsel should know these; overclaiming in a specification creates enablement
and inequitable-conduct exposure, and this repository already documents them
(`SECURITY_LIMITATIONS.md`, `docs/agentmarket-listing.md`).

- **Exactly-once is guaranteed at the gateway debit, not at the remote tool.**
  Remote side effects are exactly-once only if the upstream honors the forwarded
  idempotency key. `delivery_uncertain` exists because that cannot be assumed.
- **The charged-with-no-receipt case is unrecoverable by design.** It is counted
  for manual review, not repaired.
- **Key distribution and issuer identity remain the verifier's trust decision.**
  Offline verification proves a signature, not that the issuer is honest.
- **Private-key rotation is out of band.** `rotate_active_key_metadata()`
  rotates metadata only.
- Settlement, compliance-grade ledger storage, and production readiness for
  arbitrary agent fleets are **not** claimed.
