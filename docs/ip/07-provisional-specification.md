# Provisional application — assembled specification (DRAFT)

> **What this file is.** [`03-invention-disclosure.md`](03-invention-disclosure.md)
> and [`05-abstract-and-figures.md`](05-abstract-and-figures.md) are drafting
> *inputs*, organized for analysis. A provisional application needs one
> continuous written description that satisfies 35 U.S.C. §112(a) — enablement
> and written description — in the order a patent specification is read. This
> file is that assembly, so counsel edits a draft rather than building one from
> parts.
>
> **What this file is not.** It is not a filing, and it is not legal advice.
> Nothing here has been reviewed by a registered practitioner. A provisional
> requires no claims (37 CFR 1.51(c)), so none are included; the claim sets in
> [`04-claim-sets.md`](04-claim-sets.md) are for the non-provisional and are
> reproduced nowhere below.
>
> **Before filing, counsel must:**
>
> 1. **Strip every `file.py:NNN` citation.** They appear throughout in
>    `[[brackets]]` precisely so they can be found and deleted. They exist to let
>    a reviewer verify each statement against the implementation; they are
>    meaningless in a filed specification and they gratuitously identify
>    proprietary internals.
> 2. **Decide what to do with each `[not implemented]` marker.** These mark
>    design intentions that are described but *not reduced to practice*. They are
>    retained deliberately — a provisional may describe unimplemented subject
>    matter to support later claims, but it must not represent it as built.
>    Removing the markers without removing the text would misrepresent the state
>    of the invention.
> 3. **Replace the figure descriptions with actual drawings.** §IV below
>    describes five figures in draftsperson terms. Provisionals may be filed
>    with informal drawings, but they must be filed *with* drawings if the
>    drawings are necessary to understand the subject matter (35 U.S.C. §113).
> 4. **Settle inventorship.** Not addressed anywhere in this package. See
>    [`01-filing-risks-and-actions.md`](01-filing-risks-and-actions.md).
>
> Assembled 2026-08-15 from `03-` and `05-` at their then-current state. If
> either source file changes, this assembly is stale — it is a snapshot, not a
> generated view.

---

## Title of the Invention

**Atomic Budget Reservation and Crash-Consistent Metering for Governed
Tool Invocation by Autonomous Software Agents, with Offline-Verifiable
Transaction Receipts**

*Drafting note: deliberately mechanism-first. A title opening with "authorizing
AI agents" invites the §101 framing discussed in `01-filing-risks-and-actions.md`.
Counsel may prefer something shorter; keep the settlement half in it.*

---

## I. Field

Distributed computing; access control and metered resource consumption for
autonomous software agents invoking external tools over a protocol such as the
Model Context Protocol (MCP); tamper-evident transaction evidence.

---

## II. Background

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

## III. Summary

A gateway mediates agent-to-tool invocations and, for each invocation:

1. **Atomically authorizes and reserves** budget against a signed delegated
   permit, using a single guarded conditional update that enforces the cap at
   the row level and therefore remains correct where advisory row locks do not
   fire. Both reservation paths share this mechanism — the local path and the
   upstream dispatch path.
2. **Checkpoints the debit** on the idempotency record before finalization
   begins, so a later crash leaves a record that classifies itself.
3. **Reconciles** crashed records asymmetrically: never-charged records are
   released for safe retry; charged-but-unfinalized records are repaired from
   the signed receipt's actual outcome; charged records with no recoverable
   evidence are flagged rather than guessed at.
4. **Issues a signed receipt** whose signature covers a canonical serialization
   that embeds a digest of the payload's other fields, and which signs additive
   fields only when present so that schema growth does not invalidate
   historical signatures.
5. **Publishes verification keys** at a well-known location so any third party
   can verify a receipt **offline**, with a status taxonomy that never reports
   a key the verifier does not hold as evidence of tampering.

---

## IV. Brief Description of the Drawings

Five drawings. Descriptions are written for a patent draftsperson; each notes
the section of the detailed description it supports.

**FIG. 1** is a block diagram of the system architecture. *Supports §§V.A–V.F.*

**FIG. 2** is a flowchart of atomic authorization and reservation. *Supports §V.B.*

**FIG. 3** is a two-panel diagram of the debit checkpoint and asymmetric
reconciliation. *Supports §V.D.*

**FIG. 4** is a two-column diagram of receipt signing and signature-stable
evolution. *Supports §V.E.*

**FIG. 5** is a flowchart of the offline verification status taxonomy.
*Supports §V.F.*

### FIG. 1 — System architecture

Block diagram, left to right:

- **110** Autonomous agent (with framework/SDK)
- **120** Governance gateway, containing:
  - **122** Permit service — authorize and reserve
  - **124** Idempotency service — checkpoint and reconcile
  - **126** Dispatch attempt state machine
  - **128** Receipt service — sign
  - **130** Signing key service (Ed25519)
- **140** Database, containing: **142** permit records, **144** idempotency
  records, **146** dispatch-attempt records, **148** receipts, **150** ledger
  entries, **152** audit chain
- **160** Remote tool server (MCP)
- **170** Well-known key endpoints (`/.well-known/trust-keys.json`,
  `/.well-known/jwks.json`)
- **180** Third-party verifier — **shown with no live connection to 120, 140,
  or 170** — holding a receipt bundle **182** and a **previously retrieved key
  set 184** (a local cache or file obtained at some earlier time)

The absent connections are the point of the figure: the verifier needs no
account, no credential, and no network path to anything at verification time.
Draw the key-set arrow from **170** to **184** as a **dashed line labelled
"earlier, out of band"** — key retrieval happens before verification and is not
part of it. A solid live link from **180** to **170** would contradict the word
"offline" and misdescribe the verifier, which fetches nothing and accepts only
a caller-supplied key set.

### FIG. 2 — Atomic authorization and reservation

Flowchart:

1. **210** Receive invocation request (permit ID, tool, estimated credits)
2. **220** Begin transaction; request row lock on permit — *annotate: "lock
   request may be a no-op on some engines"*
3. **230** Validate — signature, wallet, key, status, expiry, tool allowlist,
   scopes, per-tool count, aggregate cap, forbidden fields
4. **240** Decision: valid? → No → **245** Deny with reason
5. **250** Execute guarded conditional `UPDATE`, showing the predicate inline:
   `SET spent = spent + est WHERE status='active' AND expires_at > now
   AND spent + est <= max`
6. **260** Decision: affected row count == 1?
7. **265** No → refresh row → **270** status changed? → deny `permit_revoked`;
   → **272** expired (`expires_at <= now`)? → deny `permit_expired` with
   expired-at and checked-at; otherwise deny `permit_budget_exceeded` with
   remaining, spent, max — *annotate: "no budget moved"*.
   **Draw all three terminals**, ordered status → expiry → budget, matching the
   code. `expires_at` is a term of the guarded predicate, and the classification
   consults it *before* budget, so a permit that expired mid-flight reports as
   expired rather than as out of money (§V.B).
8. **280** Yes → commit → **290** dispatch invocation

**Both reservation paths use this flow.** The upstream dispatch path performs
the same guarded update at **250** with the same affected-row check at **260**.

It differs on the success branch, and the **ordering matters** — draw it exactly
as the code runs:

> **250** guarded `UPDATE` → **260** affected-row check → **275** insert the
> dispatch-attempt record in `prepared` state and flush → **280** commit →
> **290** dispatch invocation

The insert and flush sit **inside** the transaction, before the commit. Do not
place them after **280**: the reservation and the prepared-attempt creation
occur *within the same database transaction*, and a figure showing the insert
after commit would depict the opposite.

### FIG. 3 — Debit checkpoint and asymmetric reconciliation

*Draw in two panels.*

**Panel A — normal path (vertical):**
**310** create idempotency record → **320** authorize and reserve → **330**
debit wallet, write ledger entry → **340** ⭐ *write `ledger_entry_id`
checkpoint* → **350** dispatch to remote tool → **360** sign receipt → **370**
store response on idempotency record.

Draw a lightning bolt **345** between **340** and **370** labelled "process
failure window."

**Panel B — reconciliation decision tree**, for a record with no stored
response, idle > threshold:

- **380** Dispatch attempt exists? → Yes → **382** skip (remote reconciler owns
  it, preserves delivery-uncertain state)
- **384** Checkpoint present? → No → **386** attempt or receipt exists? → No →
  **387** endpoint effect-free (canonical MCP identity,
  `operation_kind == "upstream_mcp"`)? → Yes → **388** delete record; key safe
  to retry. *The effect-free test is a precondition, not a formality:* deletion
  is confined to the narrow upstream-MCP identity that crashed before any
  budget, debit, attempt, or receipt existed.
- Checkpoint present → **390** receipt exists? →
  - Yes → **392** reconstruct response from `receipt.outcome`; select status
    code (success→200, insufficient_funds→402, denied→403,
    delivery_uncertain→504, response_rejected→502)
  - No → **394** leave unmodified; increment manual-review count

### FIG. 4 — Receipt signing and signature-stable evolution

Two parallel columns showing **two different receipts** — one issued at time T1
and one at time T2, after an optional field was added to the schema. They are
distinct instances, **not the same receipt signed twice**: the T1 receipt keeps
its original signed bytes untouched forever, and only the T2 receipt carries the
new field. Nothing is ever re-signed.

- **410** Receipt fields (T1) → **420** add `alg`, `kid` → **430** compute
  `payload_hash = SHA-256(canonical_json(payload))` **over the payload as it
  stands at this point, before the digest field exists** → **440** insert
  `payload_hash` into the payload → **450** `canonical_json` of the payload
  **now including** `payload_hash` → **460** Ed25519 sign.
  *Annotate 430/440 explicitly: the digest covers the other fields, not itself.*
- Right column repeats with **415** an additional optional field
  (`dispatch_attempt_id`) present.
- **470** Verification block below both, branching: reconstruct payload
  including optional fields **only when present** → **480** T1 receipt verifies
  under original bytes; T2 receipt verifies under extended bytes — *annotate:
  "no re-signing migration"*.
- **490** Constrained legacy fallback, shown as a dashed side branch with its
  gate conditions — exactly one referencing idempotency record; wallet and
  request hash agree; **and the receipt carries no dispatch link** — and a
  **fail-closed** terminal. All three gates are required.

### FIG. 5 — Offline verification status taxonomy

Flowchart with **six distinct terminal states**, drawn so the terminals are
visually distinguishable — this figure exists to show they are not one boolean:

1. **510** Receive bundle + key set
2. **520** Parse → fail → **525** `MALFORMED`
3. **530** Declared canonicalization matches implemented contract? → No →
   **535** `UNSUPPORTED`
4. **540** Read `kid` **from the bundle envelope**; present in key set
   (excluding disabled)? → No → **545** `UNKNOWN_KEY`
5. **550** Verify Ed25519 signature over the signed bytes **as received** →
   fail → **555** `INVALID` — *annotate: "signature did not verify under the
   selected key"*
6. **560** `kid` in signed payload == `kid` used in step 4? → No → **565**
   `MISMATCH`
7. **570** Recompute `payload_hash` over the signed payload **excluding that
   field**; disagrees? → **565** `MISMATCH`
8. **575** Envelope values agree with signed payload values? → No → **565**
   `MISMATCH`
9. **580** `VERIFIED` — return claims **read from signed payload**

**Group the terminals into two families, not one-against-the-rest.** Shade
**555** (`INVALID`) and **565** (`MISMATCH`) together as **integrity failures**
— both are reached only after the verifier has enough input to make a judgment
about the evidence itself. Shade **525** (`MALFORMED`), **535** (`UNSUPPORTED`)
and **545** (`UNKNOWN_KEY`) together as **missing input or capability** — the
verifier is saying "I cannot judge this," not "this is bad."

*Draftsperson note:* steps 4 and 6 are deliberately ordered that way — key
selection uses the envelope's `kid`, and the signed payload's `kid` is checked
only after the signature verifies. Do not "correct" the figure to read the
`kid` from the signed payload; that would depict something the system does not
do. See §V.F.

---

## V. Detailed Description

### V.A The permit

A permit [[`app/schemas/trust.py:12`, `app/services/permits.py:247`]] is an
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

> *Drafting note, not specification text:* this structure is close to Daon
> US 12,688,261 and is described here as context, **not** as a point of novelty.
> See [`02-prior-art-landscape.md`](02-prior-art-landscape.md) §1.

### V.B Atomic authorization and reservation

In one embodiment, authorization and reservation
[[`app/services/permits.py:426`]] run inside a single transaction:

1. Load the permit row requesting a row lock.
2. Validate: wallet match, key match, signature, status, expiry, tool allowlist,
   scopes, per-tool call count, aggregate value cap, forbidden argument fields.
3. **Reserve with a single guarded conditional update:**

```sql
UPDATE permits
   SET spent_credits = spent_credits + :estimated,
       updated_at    = :now
 WHERE permit_id     = :permit_id
   AND status        = 'active'
   AND expires_at    > :now
   AND spent_credits + :estimated <= max_credits
```

4. If the affected row count is not exactly 1, the reservation lost a race —
   refresh the row and deny with an accurate reason: `permit_<status>` if the
   status changed, `permit_expired` if it crossed `expires_at`, otherwise
   `permit_budget_exceeded` with remaining, spent, and maximum credits
   attached. **No budget moved.**

The essential property: *the numbers read during validation are advisory; the
guarded write is the sole authority.* The cap predicate is evaluated by the
database as part of the same statement that performs the increment, so two
concurrent reservations cannot both satisfy it, **regardless of whether the row
lock in step 1 actually engaged**.

**The scope of that guarantee is precise, and the specification should say so.**
The guarded predicate covers exactly three things — `status = 'active'`,
`expires_at > :now`, and the budget cap. Those three are enforced independently
of the lock. Everything else validated in step 2 — signature, key match, scopes,
per-tool counts, aggregate value cap, forbidden fields — is protected by the row
lock alone, and therefore *does* depend on the engine's locking semantics.

Expiry is in the predicate for a specific reason worth reciting: an expired
permit deliberately keeps `status = "active"` in storage, because expiry is a
dynamic check rather than a stored state [[`app/routers/me.py:102`]]. A
predicate testing only `status` therefore does not test validity. With
`expires_at` in the predicate, a permit that crosses its expiry between the
read-time check and the guarded write fails the write instead of being reserved
against, and the re-read classifies expiry before budget so the denial reports
`permit_expired` rather than misreporting a permit with budget left as out of
money.

The same guarded-update discipline is used for standalone reservation
[[`reserve_budget()`, `permits.py:709`]], which also emits threshold
notifications at 80%, 90%, and 100% consumption; for clamped release
[[`release_budget()`, `:784`]]; and for exactly-once release keyed to a dispatch
attempt [[`release_dispatch_budget_once()`, `:820`]], which closes a crash
window that a plain release leaves open. A retry wrapper re-runs the operation
on retryable write conflicts.

> *Drafting note:* the general technique here is optimistic concurrency control
> (Kung & Robinson, ACM TODS 6(2), June 1981). What distinguishes this embodiment is that the
> predicate is a **domain cap** rather than an equality test on an observed
> version, that the zero-row outcome is **classified into an actionable reason**
> rather than retried blindly, and that there is **no retry loop** on the
> reservation path. Draft around the classification step. See
> [`02-prior-art-landscape.md`](02-prior-art-landscape.md) §5.

### V.C Dispatch attempt state machine

Because the tool call is remote and cannot join the local transaction, each
governed invocation carries a durable attempt record
[[`app/services/mcp_dispatch_attempts.py`]] advancing monotonically through
`prepared → dispatched → {succeeded | failed | delivery_uncertain}`.

Authorization, reservation, and preparation [[`:344`]] establish the budget
reservation and the `prepared` row in one atomic step, so a reservation can
never exist without the attempt record that governs its release. Re-entry adopts
only an invariant-equivalent prepared row, and the attempt is bound to the
approval identity that authorized it.

Both reservation paths perform the identical guarded update of §V.B with the
same affected-row check. A lost race denies with `permit_budget_exceeded` (or
`permit_<status>`) and creates **no prepared attempt**, so it leaves nothing to
compensate.

`delivery_uncertain` is a first-class terminal state, surfaced as HTTP 504. The
system declines to assert that a remote side effect did or did not occur when it
cannot know. Remote side effects are exactly-once only when the upstream honors
the forwarded idempotency key — a boundary the system states rather than hides.

### V.D Debit checkpoint and asymmetric reconciliation

An idempotency service [[`app/services/idempotency.py`]] keys a record on
`(wallet_id, endpoint, idempotency_key)` under a unique constraint, storing a
SHA-256 request fingerprint. Reuse of a key with a different fingerprint is
refused (`idempotency_key_reused`). A concurrent identical request may wait a
bounded interval for the first to finalize rather than failing immediately.

Two mechanisms go past the standard pattern.

**The checkpoint.** The charge-marking step [[`:379`]] writes `ledger_entry_id`
onto the idempotency record *immediately after the wallet debit lands and
before* the receipt/audit/complete finalization sequence. Its sole purpose is to
make a crashed record self-classifying.

**Asymmetric repair.** Reconciliation [[`:408`]] processes only records idle
beyond a threshold (default 900 seconds), so in-flight requests are never
touched, and takes four different actions:

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

A complementary path [[`abandon()`, `:347`]] releases an in-progress record when
a governed invocation stops on a retryable, side-effect-free condition (a human
approval still pending, an approval backend unreachable). It refuses to delete
any record carrying a stored response or a `ledger_entry_id` — if money moved,
the record survives for replay and repair.

### V.E The receipt and its signature

A receipt [[`app/services/receipts.py:208`]] records one completed governed
invocation: identity, the permit and wallet, the tool, SHA-256 hashes of request
and response, the ledger entry, credits authorized versus charged, outcome and
reason code, the audit event, the approval, the constraints evaluated, and the
linkage to both the idempotency record and the dispatch attempt.

Signing proceeds [[`app/services/signing_keys.py:324`]]:

1. Set `alg = "Ed25519"` and `kid = <key id>`.
2. Compute `payload_hash = SHA-256(canonical_json(payload))` over the payload
   **as it stands before the digest field is added**, then insert the digest
   into the payload [[`:338`]].
3. Sign `canonical_json(payload)` — now including `payload_hash` — with Ed25519.

The digest therefore covers **the other signed fields, not itself**; a
self-referential digest is not computable. The verifier mirrors this by
stripping `payload_hash` before recomputing
[[`b2a_sdk/src/b2a_sdk/receipt_verifier.py:406`]] and reporting `MISMATCH` on
disagreement. Its function is a redundant integrity check *inside* the
signature: it detects a payload whose fields were altered in some way that
preserved the signature bytes, and gives a verifier a cheap consistency check it
can perform before doing curve arithmetic.

Canonicalization [[`canonical_json`, `signing_keys.py:66`]] is a named,
versioned contract — `awi-canonical-json/1` — so an independent verifier can
state which rules it implements: keys sorted, no whitespace, `Decimal` rendered
via `normalize()` and fixed-point formatting, `datetime` coerced to UTC
ISO-8601, dicts recursively sorted. A bundle declaring a different
canonicalization version is refused rather than verified under rules it was not
signed with.

**Signature-stable schema evolution.** Optional fields — `reason_code`,
`idempotency_record_id`, `dispatch_attempt_id`, `approval_id`,
`constraints_evaluated` — are included in the signed payload **only when
present**. Verification [[`verify_model`, `receipts.py:558`]] mirrors that
construction exactly. The result is that receipts signed before a field existed
continue to verify unchanged after it is added: the evidence schema can grow
without a re-signing migration and without silently invalidating history.

One historical migration backfilled an idempotency link onto receipts signed
before linkage existed. Rather than loosening verification generally, a
constrained fallback [[`_has_unambiguous_historical_idempotency_link`,
`receipts.py:115`]] retries the legacy payload shape **only** when exactly one
idempotency record points at the receipt and its wallet and request hash both
agree. Ambiguous, absent, mismatched, or dispatch-linked cases fail closed.

A signing-input accessor [[`:520`]] returns the exact canonical bytes a given
signature covers, branch for branch — and returns `None` when neither branch
verifies, so a receipt that cannot be proven is never exported as evidence.

### V.F Key distribution and offline verification

Public keys are served at `/.well-known/trust-keys.json` and, for standard
tooling, as a JWK Set at `/.well-known/jwks.json`
[[`app/routers/well_known.py:619`, `:670`]]. Neither endpoint will serve an
empty key set with a 200 — an unusable key set is refused rather than published,
so a verifier is never handed a document that would make every receipt look
unknown.

Keys carry lifecycle status (`active`, `retired`, `disabled`). Rebinding an
existing key ID to different public material is rejected
(`signing_key_id_public_key_mismatch`). Verification against a disabled key
fails closed [[`signing_keys.py:345`]], and any decode, key construction, or
signature failure is caught and reported as "not verified" rather than raised —
one corrupt row must not mask tampering behind a 500.

The verifier [[`b2a_sdk/src/b2a_sdk/receipt_verifier.py`]] requires no network,
no database, and no credential; its only dependency beyond the standard library
is a cryptography library. Two properties define it.

**Every reported claim value is read from the signed bytes.** The enclosing
bundle is unauthenticated envelope data and is never a source of truth for
reported values. A bundle claiming `receipt_id: X` around a payload signed for
`Y` is rejected as `MISMATCH`.

One exception, stated precisely because it bounds the property above: the `kid`
used to **select** the verification key is read from the envelope [[`:289`]];
the signed payload's `kid` is compared against it only *after* the signature
verifies [[`:397`]]. The consequence is that an envelope relabelled with a
different *published* `kid` resolves to `INVALID` rather than `MISMATCH`,
because the wrong key is selected and the signature fails before the cross-check
runs — even though the signed payload was never touched. Selecting the key from
the parsed signed payload instead would close that gap and make the taxonomy
exact. **[not implemented]** — see §VIII.

**Failure is never silently "false".** The status taxonomy:

| Status | Meaning |
| --- | --- |
| `VERIFIED` | Signature holds — cryptographic claim |
| `INVALID` | The signature did not verify under the selected key — a cryptographic claim. Payload modification is one possible cause; a relabelled envelope is another |
| `MISMATCH` | Envelope, payload, or caller expectation disagree, no demonstrated signature failure |
| `UNKNOWN_KEY` | Signing key not in the supplied key set |
| `MALFORMED` | Structurally unparseable input |
| `UNSUPPORTED` | Declared algorithm or canonicalization the verifier does not implement |

The distinction is the point. A verifier that collapses these into a boolean
reports "I do not hold that key" identically to a forged receipt, and a caller
acting on that boolean will eventually escalate a key-distribution problem as
fraud. `INVALID` is the only status that asserts a signature failure; the rest
describe missing input or capability.

Two precisions the specification should not let drift:

- **The verifier never observes an outage itself.** It accepts a
  caller-supplied key set and performs no retrieval, so a key-server fetch
  failure happens *before* verification is invoked and is reported by whatever
  fetched the keys. What the verifier contributes is that a key it does not hold
  resolves to `UNKNOWN_KEY` rather than to a tampering verdict. That is the
  claimable property; "detects outages" is not.
- **`INVALID` is not exclusively a payload-modification signal**, because of the
  envelope-`kid` selection path described above.

### V.G Supporting: audit chain

Control-plane events are hash-linked and signed
[[`app/services/audit_chain.py`]]: each event carries `previous_hash`,
`payload_hash`, and `chain_hash = SHA-256(previous_hash, payload_hash)`.
Concurrent appends detect a moved chain head — via a conditional update
predicated on the observed head, with retry — and do not rely on row locking.

> *Drafting note:* a known pattern (Certificate Transparency, Trillian).
> Include as supporting detail, **not** as a point of novelty. Note also that
> this is a second instance of the optimistic-concurrency technique used in
> §V.B; see [`02-prior-art-landscape.md`](02-prior-art-landscape.md) §5.

---

## VI. Embodiments

**Primary — hosted governance gateway.** The gateway sits between agent
frameworks and MCP tool servers, holds the signing key, serves the well-known
key endpoints, and returns a receipt with every invocation.

**Self-hosted, single-file deployment.** The same code on SQLite rather than
PostgreSQL. This embodiment is what makes the guarded conditional update
necessary rather than merely elegant: it is the only thing enforcing the cap
when `FOR UPDATE` does not engage. **Keep this embodiment in the specification —
it is direct support for the lock-independence limitation.**

**Federated issuers with a shared verifier. [not implemented]** Multiple
independent gateways issue receipts under distinct key IDs; a verifier holding
several key sets checks any of them offline. The key-set and `kid` machinery
supports this; no federated deployment exists.

---

## VII. Advantages

- Spend caps hold under concurrency without depending on engine-specific lock
  semantics.
- A crash between debit and finalization resolves to a known state, or is
  flagged rather than guessed at.
- Evidence is verifiable by parties who trust neither the agent nor the gateway,
  with no account and no network path.
- Evidence schemas can evolve without invalidating historical signatures.
- Verification failures are diagnosable: a missing key is never reported as
  fraud.

---

## VIII. Known limitations

Retained deliberately. Overclaiming in a specification creates enablement and
inequitable-conduct exposure, and this repository already documents these
(`SECURITY_LIMITATIONS.md`).

- **Exactly-once is guaranteed at the gateway debit, not at the remote tool.**
  Remote side effects are exactly-once only if the upstream honors the forwarded
  idempotency key. `delivery_uncertain` exists because that cannot be assumed.
- **The charged-with-no-receipt case is unrecoverable by design.** It is counted
  for manual review, not repaired.
- **Key distribution and issuer identity remain the verifier's trust decision.**
  Offline verification proves a signature, not that the issuer is honest. The
  verifier retrieves nothing and therefore cannot distinguish a key-server
  outage from any other reason its key set lacks a `kid`.
- **Key selection reads the envelope, not the signed payload.** A bundle
  relabelled with a different published `kid` yields `INVALID`, not `MISMATCH`,
  so `INVALID` cannot be read as "the payload was modified" without
  qualification. Closing this is a small code change — **do it before filing**
  if the stronger claim is wanted.
- ~~**The lock-independent budget guarantee does not extend to expiry.**~~
  **Closed.** `expires_at > :now` is a term of the guarded update on both
  reservation paths, and the re-read classifies expiry before budget. See §V.B.
  No known gap remains in the reservation mechanism.
- **Private-key rotation is out of band.** The rotation routine rotates metadata
  only.
- Settlement, compliance-grade ledger storage, and production readiness for
  arbitrary agent fleets are **not** claimed.

---

## Abstract

> 37 CFR 1.72(b): a single paragraph, 150 words maximum. Not required for a
> provisional; included because the non-provisional will need it and it is
> easier to refine early. **146 words — recount with `wc -w` after any edit.**

A gateway mediates tool invocations by autonomous software agents while
enforcing a delegated spending limit, deduplicating retries that carry an
idempotency key, and producing verifiable evidence. Budget is reserved by a
single conditional update whose limit predicate the database evaluates as part
of the same statement that performs the increment, so concurrent invocations
cannot jointly exceed the limit irrespective of whether a requested row lock was
granted; an affected-row count other than one yields a denial identifying
whether budget or permit status caused it. An identifier of the ledger entry is
written to the idempotency record after the debit and before finalization, so a
record left unfinished by a process failure is classified as never charged, as
charged and reconstructable from a signed receipt, or as requiring review. The
receipt verifies offline against a published key, returning a status
distinguishing signature failure from an unavailable key.
