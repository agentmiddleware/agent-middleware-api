# Abstract and figures

## Abstract

> 37 CFR 1.72(b): a single paragraph, 150 words maximum. Drafted to describe the
> mechanisms rather than the application domain — an abstract that opens with
> "authorizing AI agents" invites the §101 framing discussed in
> [`01-filing-risks-and-actions.md`](01-filing-risks-and-actions.md).

**Draft (146 words — recount with `wc -w` after any edit; 37 CFR 1.72(b) caps it at 150):**

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

---

## Figures

Five drawings. Descriptions are written for a patent draftsperson; each notes
the specification section it supports.

### FIG. 1 — System architecture

*Supports §4.1–§4.6 of the disclosure.*

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
"offline" and misdescribe `receipt_verifier.py`, which fetches nothing and
accepts only a caller-supplied key set.

### FIG. 2 — Atomic authorization and reservation

*Supports claim 1; §4.2.*

Flowchart:

1. **210** Receive invocation request (permit ID, tool, estimated credits)
2. **220** Begin transaction; request row lock on permit — *annotate: "lock
   request may be a no-op on some engines"*
3. **230** Validate — signature, wallet, key, status, expiry, tool allowlist,
   scopes, per-tool count, aggregate cap, forbidden fields
4. **240** Decision: valid? → No → **245** Deny with reason
5. **250** Execute guarded conditional `UPDATE`, showing the predicate inline:
   `SET spent = spent + est WHERE status='active' AND spent + est <= max`
6. **260** Decision: affected row count == 1?
7. **265** No → refresh row → **270** status changed? → deny `permit_revoked`;
   otherwise deny `permit_budget_exceeded` with remaining, spent, max —
   *annotate: "no budget moved"*.
   Do **not** draw a `permit_expired` terminal here: expired permits keep
   `status = "active"`, so this re-read cannot produce that reason (§4.2).
   It becomes reachable only if `expires_at` is added to the guarded predicate
   and the classification — **[not implemented]**.
8. **280** Yes → commit → **290** dispatch invocation

### FIG. 3 — Debit checkpoint and asymmetric reconciliation

*Supports claims 9–14; §4.4. The most important figure — draw it in two panels.*

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
  **388** delete record; key safe to retry
- Checkpoint present → **390** receipt exists? →
  - Yes → **392** reconstruct response from `receipt.outcome`; select status
    code (success→200, insufficient_funds→402, denied→403,
    delivery_uncertain→504, response_rejected→502)
  - No → **394** leave unmodified; increment manual-review count

### FIG. 4 — Receipt signing and signature-stable evolution

*Supports claims 18–19; §4.5.*

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
  gate conditions (exactly one referencing idempotency record; wallet and
  request hash agree) and a **fail-closed** terminal.

### FIG. 5 — Offline verification status taxonomy

*Supports claims 15–20; §4.6.*

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

Shade **555** distinctly from **525**, **535**, **545**, **565** and add a
legend: "cryptographic claim" vs. "missing input or capability."

*Draftsperson note:* steps 4 and 6 are deliberately ordered that way — key
selection uses the envelope's `kid`, and the signed payload's `kid` is checked
only after the signature verifies. Do not "correct" the figure to read the
`kid` from the signed payload; that would depict something the code does not
do. See §4.6 of the disclosure.
