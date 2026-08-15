# Claim sets — drafting input

**Draft claims for attorney review. Not filing-ready.** Claim drafting is a
practiced legal skill and the scope decisions here have consequences that
survive for twenty years. Treat these as a structured statement of what the
inventor believes is novel, in claim-shaped form, for counsel to rewrite.

**Structure:** 20 claims, 3 independent — which fits the USPTO basic filing fee
without excess-claim surcharges (37 CFR 1.16(h),(i): 3 independent and 20 total
included). If counsel adds independents, budget accordingly.

**Anchoring rationale.** Each independent recites a specific technical mechanism
solving a specific technical problem, per the §101 discussion in
[`01-filing-risks-and-actions.md`](01-filing-risks-and-actions.md). None recites
"authorizing an AI agent" as its point of novelty — that is where Daon
US 12,688,261 sits (see [`02-prior-art-landscape.md`](02-prior-art-landscape.md)).

---

## Set A — Atomic budget reservation under weak isolation (system)

> Drafting note: the point of novelty is the **guarded conditional update whose
> predicate the database evaluates as part of the same statement that performs
> the increment**, plus explicit denial on an affected-row count other than one.
> Limitation 1(e) — correctness independent of whether the lock request engaged
> — is the limitation that distinguishes this from ordinary row locking, and it
> is supported by the SQLite embodiment in §5 of the disclosure. Do not let it
> be amended away.

**1.** A system for enforcing a delegated spending limit on tool invocations by
an autonomous software agent, the system comprising:

one or more processors and a non-transitory memory storing instructions that,
when executed, cause the system to:

- (a) store, in a database, a permit record comprising a subject identifier, a
  set of permitted tool identifiers, a maximum-credit value, a consumed-credit
  value, an expiry time, and a status;
- (b) receive, from an autonomous software agent, a request to invoke a tool,
  the request identifying the permit record and an estimated credit cost;
- (c) within a single database transaction, issue a request to lock the permit
  record and validate the request against the permit record, the validating
  comprising verifying a cryptographic signature over the permit record and
  determining that the identified tool is within the set of permitted tool
  identifiers and that the expiry time has not elapsed;
- (d) responsive to the validating succeeding, execute a **single conditional
  update statement** that both increments the consumed-credit value by the
  estimated credit cost and is conditioned on a predicate, evaluated by the
  database as part of the same statement, requiring that the sum of the
  consumed-credit value and the estimated credit cost not exceed the
  maximum-credit value and that the status be active;
- (e) determine a count of records affected by the conditional update statement,
  wherein the enforcement of the maximum-credit value is effected by the
  predicate of the conditional update statement such that the limit is enforced
  **irrespective of whether the lock requested in (c) was granted by the
  database**;
- (f) responsive to the count being other than one, re-read the permit record,
  deny the request, and return a denial reason distinguishing at least a
  budget-exhausted condition from a status-changed condition, without modifying
  the consumed-credit value; and
- (g) responsive to the count being one, dispatch the tool invocation.

**2.** The system of claim 1, wherein the database is one in which a row-lock
request issued in (c) is accepted without acquiring a lock, and wherein two
concurrent requests referencing the same permit record and each having an
estimated credit cost that individually satisfies but jointly exceeds the
maximum-credit value result in exactly one of the requests being dispatched.

**3.** The system of claim 1, wherein the denial reason returned in (f) further
comprises a remaining-credit value, a consumed-credit value, and the
maximum-credit value, whereby the requesting agent is enabled to determine
whether a reduced-cost request would succeed.

**4.** The system of claim 1, wherein the instructions further cause the system
to re-execute (c) through (g) responsive to detecting a retryable write-conflict
condition raised by the database.

**5.** The system of claim 1, wherein the validating in (c) further comprises
determining that a count of prior invocations of the identified tool under the
permit record does not exceed a per-tool invocation limit stored in the permit
record, and that no argument of the request has a key within a set of forbidden
argument keys stored in the permit record.

**6.** The system of claim 1, wherein the conditional update statement of (d)
and a creation of a dispatch-attempt record in a prepared state are performed
within the same database transaction, such that no reservation of the
consumed-credit value exists without a corresponding dispatch-attempt record.

**7.** The system of claim 1, wherein the instructions further cause the system
to emit a notification responsive to the consumed-credit value crossing each of
a plurality of predetermined fractions of the maximum-credit value.

**8.** The system of claim 1, wherein creation of the permit record is refused
when the maximum-credit value exceeds a balance of an issuing account, whereby
authority exceeding that held by the issuer cannot be delegated.

---

## Set B — Exactly-once debit across process failure (method)

> Drafting note: the novelty is the **checkpoint written between the debit and
> finalization** together with the **asymmetric classification** it enables.
> Claim 9(d) and 9(g) are the pair that matters. The three-way branch in (g) —
> repair, release, refuse-to-guess — should survive amendment; collapsing it to
> two branches gives up the distinguishing feature.

**9.** A computer-implemented method for preventing duplicate charges when a
gateway mediates invocations of a remote tool that cannot participate in a local
database transaction, the method comprising:

- (a) receiving a request comprising an idempotency key and a request payload;
- (b) creating, under a uniqueness constraint on a tuple comprising an account
  identifier and the idempotency key, an idempotency record storing a
  cryptographic digest of the request payload, and responsive to an existing
  record having a differing digest, refusing the request;
- (c) debiting an account of the requester and recording a ledger entry;
- (d) **after the debiting and before commencing a finalization sequence,
  writing an identifier of the ledger entry onto the idempotency record as a
  checkpoint**;
- (e) dispatching the invocation to the remote tool;
- (f) performing the finalization sequence, comprising generating a
  cryptographically signed receipt recording an outcome of the invocation and
  storing a response on the idempotency record; and
- (g) subsequently, for an idempotency record having no stored response and
  having been idle for at least a threshold duration, determining a repair
  action **by reference to presence of the checkpoint**, comprising:
  - (i) responsive to the checkpoint being absent and no dispatch-attempt record
    and no receipt referencing the idempotency record existing, deleting the
    idempotency record such that a subsequent request bearing the same
    idempotency key is processed as a new request;
  - (ii) responsive to the checkpoint being present and a receipt referencing
    the idempotency record existing, storing on the idempotency record a
    reconstructed response **derived from the outcome recorded in the receipt**,
    including a status code selected according to that outcome; and
  - (iii) responsive to the checkpoint being present and no such receipt
    existing, leaving the idempotency record unmodified and incrementing a count
    of records requiring manual review.

**10.** The method of claim 9, wherein the outcome recorded in the receipt is
one of a plurality of outcomes comprising at least a success outcome, a denial
outcome, an insufficient-funds outcome, and a delivery-uncertain outcome, and
wherein the status code selected in (g)(ii) differs among said outcomes, whereby
a request that was denied prior to the process failure is not reported to a
retrying requester as having succeeded.

**11.** The method of claim 9, further comprising, responsive to the invocation
halting on a condition that is retryable and free of side effects, deleting the
idempotency record only when it has neither a stored response nor the checkpoint
of (d).

**12.** The method of claim 9, wherein the determining in (g) excludes any
idempotency record referenced by a dispatch-attempt record, such records being
reconciled by a state machine that preserves a delivery-uncertain terminal
state.

**13.** The method of claim 9, further comprising, responsive to receiving a
second request bearing the same idempotency key while the first is in progress,
awaiting finalization of the first request for a bounded interval and returning
the stored response upon its availability.

**14.** The method of claim 9, wherein the threshold duration in (g) is selected
to exceed a maximum expected duration of an in-flight invocation, such that
records of invocations still in progress are not subjected to the repair action.

---

## Set C — Offline verification with a diagnostic status taxonomy (CRM)

> Drafting note: two limitations carry this claim — reading every reported field
> **from the signed bytes** rather than the envelope, and returning a status
> that **distinguishes a cryptographic failure from an unavailable or unknown
> key**. Verifying an Ed25519 signature offline is not novel; refusing to let an
> outage present as tampering is the contribution.

**15.** A non-transitory computer-readable medium storing instructions that,
when executed by one or more processors, cause the processors to verify a
transaction receipt without network access, by:

- (a) receiving a receipt bundle comprising an envelope, a signed payload, a
  signature, and a declared canonicalization identifier, and receiving a key set
  mapping key identifiers to public keys;
- (b) responsive to the declared canonicalization identifier not matching a
  canonicalization contract implemented by the instructions, returning a status
  of unsupported without evaluating the signature;
- (c) serializing the signed payload according to said canonicalization
  contract, and verifying the signature over the resulting bytes using a public
  key selected from the key set by a key identifier **read from the signed
  payload**;
- (d) responsive to the verification succeeding, returning a verified status
  together with one or more claim values, **each such claim value being read
  from the signed payload and not from the envelope**;
- (e) responsive to a value in the envelope conflicting with a corresponding
  value in the signed payload, returning a mismatch status; and
- (f) returning a status selected from a plurality of statuses that
  distinguishes at least (i) a failure of the signature to verify, from (ii) an
  absence of the identified key from the key set, from (iii) a structural
  malformation of the bundle, wherein only status (i) indicates modification of
  the payload.

**16.** The medium of claim 15, wherein the instructions execute without a
network connection, without a database connection, and without a credential of
the issuer of the receipt.

**17.** The medium of claim 15, wherein the canonicalization contract comprises
sorting object keys, emitting no insignificant whitespace, rendering decimal
values in a normalized fixed-point form, and rendering timestamps in a
coordinated-universal-time representation.

**18.** The medium of claim 15, wherein the signed payload comprises a digest
computed over the signed payload itself, such that the signature commits to a
self-referential digest of the payload.

**19.** The medium of claim 15, wherein the signed payload omits each of a
plurality of optional fields that are absent, and wherein the verifying
reconstructs the signed payload by including each said optional field only when
present, whereby a receipt signed prior to introduction of a said optional field
continues to verify without re-signing.

**20.** The medium of claim 15, wherein the key set is obtained from a document
retrieved from a well-known location of an issuer, and wherein a key having a
disabled lifecycle status is excluded from the key set prior to said selecting.

---

## Fallback: combination claim

Hold this in reserve — as a continuation, or as an amendment if the independents
above are rejected over art the formal search turns up. **Do not lead with it.**
A combination of individually known elements is the standard predicate for a
§103 obviousness rejection under *KSR*.

> A governed invocation gateway comprising: a permit service that atomically
> authorizes and reserves budget per claim 1; a metering service that binds an
> idempotency record to a wallet debit by the checkpoint of claim 9(d); and a
> receipt service that issues signed evidence verifiable per claim 15 by a party
> possessing no credential of the gateway — wherein a single tool invocation by
> an autonomous agent produces exactly one debit and exactly one item of
> independently verifiable evidence, notwithstanding concurrent invocations,
> client retries, or failure of the gateway process between the debit and the
> recording of the outcome.

---

## Claims deliberately not drafted

- **Permit issuance / scoped delegation artifacts** — Daon US 12,688,261. See
  [`02-prior-art-landscape.md`](02-prior-art-landscape.md).
- **Hash-linked signed audit logs** — Certificate Transparency, Trillian.
- **Idempotency key plus request fingerprint plus stored response** — Stripe and
  general industry practice.
- **Federated multi-issuer verification** — described as an embodiment but
  **not implemented**; do not claim as reduced to practice.
