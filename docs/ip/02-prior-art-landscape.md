# Prior art landscape

Searched 2026-08-15. This is a positioning search, **not** a professional
patentability search. Commission a formal search from counsel or a search firm
before filing a non-provisional — in particular, published US and PCT
applications in the 18-month blackout window will not appear here, and that is
exactly where competing agent-governance filings from 2025–2026 are sitting.

---

## 1. Daon's agentic-AI portfolio — the closest art

Daon holds three issued US patents forming, in their own description, an
end-to-end agent trust architecture. All three are recent and all three should
go on the IDS.

| Patent | Title / subject | Issued |
| --- | --- | --- |
| **US 12,688,261** | Methods and systems for authorizing invocation of a tool by an autonomous artificial intelligence agent — action-level delegated authorization | **2026-07-21** |
| **US 12,563,045 B1** | Methods and systems for maintaining behavioral integrity of autonomous artificial intelligence agents | **2026-02-24** |
| **US 12,452,035** | Person-agent fidelity — human-to-agent bonding, Baseline Persona Model, drift detection | **2025-10-21** |

Assignee: Daon Technology. Named inventor on '045: Raphael A. Rodriguez.
Counsel should pull the primary records (Google Patents / Patent Public Search)
and the full claim text for all three before relying on any positioning below.

### Why '261 is a serious problem

Per Daon's own description, '261 covers authorizing whether a specific AI agent
may execute an action on a protected tool, service, or API, evaluating the
tool, action, resource, scope, session, and execution environment — and, on
success, generating a **machine-verifiable "delegation artifact"**: a
short-lived token cryptographically bound to action type, resource scope, time
window, **rate limits**, and execution context.

Read that against this repo's permit
(`app/schemas/trust.py:12`, `app/services/permits.py:247`): a short-lived,
signed credential binding subject wallet, subject key, scopes, allowed tools,
budget cap, expiry, nonce, per-tool call limits, and recipient domain.

**The overlap is real but narrower than it first appears — and this correction
is in your favour.** An earlier draft of this document called them "the same
idea" and pronounced permit issuance anticipated or obvious over '261. That was
a categorical legal conclusion drawn from press summaries, which is not a sound
way to reach one. Reported claim 1 of '261 recites elements the permit here does
**not** have.

Preliminary element mapping — **counsel must replace this with a real claim
chart against the issued text**:

| Reported '261 claim 1 element | This repo's permit |
| --- | --- |
| Receive an AI agent's tool-invocation request | Yes — governed invoke |
| Evaluate a **fidelity signal** (agent behaviourally bound to a person) | **Absent.** No person-binding or behavioural model exists |
| Evaluate an **integrity signal** (execution behaviour within expected range) | **Absent.** No runtime behavioural attestation |
| Apply policy rules to the request context | Partly — scopes, tools, caps, expiry, forbidden fields |
| Generate a machine-verifiable delegation artifact with least-privilege constraints | Yes — the signed permit |
| Authorize the invocation | Yes |

So the fair statement is: the **delegation-artifact element** of '261 reads
closely onto the permit, while the fidelity and integrity elements — which
appear to be what makes Daon's combination distinctive — have no counterpart
here. That does not make permit issuance safe to claim, since an examiner could
still combine '261 with a capability-token reference. But it is a materially
weaker anticipation position than "the same idea."

Two instructions for counsel, in order:

1. **Get the issued claim text of '261** (not the press description, not the
   summary above) and build the chart properly.
2. **Still do not anchor an independent claim in permit issuance.** The
   settlement-side mechanisms are better territory regardless of how the '261
   chart comes out, and they do not depend on winning this argument.

### What '261 does not appear to reach

Nothing in Daon's public description addresses the **settlement half** of the
loop:

- reserving and enforcing a spend cap under concurrent access
- binding an idempotency record to a wallet debit so a retry cannot double-charge
- recovering a consistent state after a crash between debit and finalization
- issuing signed, **offline-verifiable evidence of the completed action**, as
  distinct from authorization granted before it

Stated carefully: these are **not identified in the reviewed materials**, which
is not the same as proven absent. Only a reading of the issued claims and
specification can establish that.

Daon's artifact is a permission slip issued *before* the act. The receipt in
this repo is evidence issued *after* it, verifiable by a third party who trusts
neither the agent nor the gateway. That is a different artifact serving a
different party at a different time, and it is where the room is.

---

## 2. Idempotency and exactly-once payment processing

Well-developed public art — Stripe's `Idempotency-Key` header, Airbnb's
published double-payment work, and the general pattern of key + request
fingerprint + stored response.

The pattern itself is unclaimable. Two details in this repo go past it:

- **The charge checkpoint.** `mark_charged()` writes `ledger_entry_id` onto the
  idempotency record *after the debit lands and before finalization begins*
  (`app/services/idempotency.py:379`). Its whole purpose is to make a crashed
  record self-classifying afterwards.
- **Asymmetric repair.** The reconciler treats "no checkpoint, no attempt, no
  receipt" (delete the record; the retry is safe) differently from "checkpoint
  present, receipt exists" (rebuild the replay response *from the receipt's
  actual outcome*) differently again from "checkpoint present, no receipt"
  (do not guess — flag for manual review)
  (`app/services/idempotency.py:408`).

The standard pattern answers "did I already do this?" The mechanism here answers
"the process died — did money move, and can I reconstruct what the caller should
be told?" Note the outcome-fidelity detail: reconciliation reads
`receipt.outcome` and maps it to the right status code, because replaying a
crashed denial as a bare 200 would tell the client a call succeeded when it was
refused.

Common industry advice is that the idempotency key and the business operation
must share one database transaction. This system cannot take that route — the
tool invocation is a network call to a third-party MCP server and cannot join a
local transaction. The prepared-attempt state machine
(`app/services/mcp_dispatch_attempts.py`) exists precisely because the side
effect is remote and non-transactional, which is why `delivery_uncertain` is a
first-class terminal outcome rather than a failure to be smoothed over.

---

## 3. Capability tokens and attenuated authorization

Macaroons (Google Research), biscuits, SPIFFE/SPIFFE Verifiable Identity
Documents, OAuth 2.0 token exchange (RFC 8693), and Rich Authorization Requests
(RFC 9396) all cover scoped, delegated, caveat-bearing credentials.
`docs/related-work.md` already acknowledges macaroons as design lineage.

Consequence: the *permit as capability token* is old. Its budget-carrying and
budget-**enforcing** behavior under concurrency is the part that is not.

---

## 4. Signed audit logs and hash chains

Certificate Transparency (RFC 6962), Trillian, hash-linked tamper-evident logs
generally, and the constant-size cryptographic evidence structures cited in
`docs/related-work.md`. The audit chain here
(`app/services/audit_chain.py`) is a competent implementation of a known
pattern — treat it as supporting detail in the spec, not as a point of novelty.

---

## 5. Where the room actually is

Ranked by how defensible each looks against the art above:

1. **Atomic guarded reservation under weak isolation** (`app/services/permits.py:426`).
   The single conditional `UPDATE ... WHERE spent + amount <= cap` with a
   `rowcount != 1` denial is a real solution to a real bug — the repo history
   records the overspend being found under concurrency and then fixed. Crucially,
   it stays correct on engines where `SELECT ... FOR UPDATE` is silently a no-op,
   which is a claim limitation grounded in database behavior, not bookkeeping.
   Strongest §101 posture of the four.
2. **Crash-recovery classification of a charged-but-unfinalized operation**
   (`app/services/idempotency.py:408`). Specific problem, specific asymmetric
   solution, no clean analogue found in the searched art.
3. **Offline verification with a status taxonomy that separates a signature
   failure from a key the verifier does not hold**
   (`b2a_sdk/.../receipt_verifier.py`). The "a missing key is never reported as
   tampering" property is a genuine and articulable technical contribution.
   Verifying a signature offline is not. State it in those terms rather than as
   outage detection — the verifier fetches nothing and cannot observe an
   outage (§4.6 of the disclosure).
4. **Signature-stable schema evolution** (`app/services/receipts.py:312`).
   Signing additive fields only when present, so old signatures keep verifying
   as the schema grows, with a fail-closed constrained fallback for the one
   backfilled migration. Narrow, but clean and concrete.

### The combination-claim trap

The prior draft of this package advised emphasizing the "triple integration" of
MCP middleware + budgeted metering + offline receipts. Be careful with that
instinct. A combination of individually known elements is the standard setup for
a §103 obviousness rejection — the examiner picks Daon for authorization, Stripe
for idempotency, and RFC 6962 for signed evidence, and asserts that combining
them is predictable. *KSR* makes that argument easy to make and hard to rebut.

Combination claims are worth having as fallback positions. But each independent
claim should stand on a **specific mechanism that solves a specific technical
problem the art does not address** — not on the assembly. That is what
[`04-claim-sets.md`](04-claim-sets.md) tries to do.

---

## Sources

- [Daon Secures Third Patent Advancing AI Agent Governance in Regulated Industries](https://www.daon.com/resource/daon-secures-third-patent-advancing-ai-agent-governance-in-regulated-industries/)
- [Daon expands AI agent governance patent portfolio — Biometric Update](https://www.biometricupdate.com/202607/daon-expands-ai-agent-governance-patent-portfolio)
- [Daon wins third patent for agentic AI governance — FinTech Global](https://fintech.global/2026/08/07/daon-wins-third-patent-for-agentic-ai-governance/)
- [Daon wins patent for real-time AI agent authorisation — SecurityBrief UK](https://securitybrief.co.uk/story/daon-wins-patent-for-real-time-ai-agent-authorisation)
- [Stripe API — Idempotent requests (`Idempotency-Key`)](https://docs.stripe.com/api/idempotent_requests)
- [Avoiding double payments in a distributed payments system — Airbnb Engineering](https://medium.com/airbnb-engineering/avoiding-double-payments-in-a-distributed-payments-system-2981f6b070bb)
- [Google Patents — US 12,563,045 B1](https://patents.google.com/patent/US12563045B1/en)
- [Macaroons: Cookies with Contextual Caveats — Google Research](https://research.google/pubs/macaroons-cookies-with-contextual-caveats-for-decentralized-authorization-in-the-cloud/)
