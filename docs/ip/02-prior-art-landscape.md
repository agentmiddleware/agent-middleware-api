# Prior art landscape

Searched 2026-08-15. This is a positioning search, **not** a professional
patentability search. Commission a formal search from counsel or a search firm
before filing a non-provisional. Note what a search like this structurally
cannot see: US and PCT applications generally do not publish until 18 months
from their earliest effective filing or priority date, so pending applications
filed in 2025–2026 — exactly where competing agent-governance filings would be —
may not be searchable yet. Provisionals and US applications under an eligible
nonpublication request never publish as such; applications abandoned before
publication and those under secrecy order do not either. Not searchable today
is not the same as not prior art later: an application invisible now can still
have prior-art effect once published or issued.

**Search scope actually performed** — state it so counsel can judge the weight
of everything below: public web search for issued US patents and vendor
announcements in agent authorization and governance; review of the standards and
literature already cited in `docs/related-work.md`; and reading of this
repository's implementation. **Not performed:** classification-based searching
(CPC/IPC), USPTO Patent Public Search or EPO/WIPO full-text databases, any
non-English art, any published-application search, and any reading of issued
claim text beyond the abstracts and summaries linked below. The rankings in §7
are engineering judgment about where the mechanisms differ from known art — they
are a starting hypothesis for counsel to test, not a patentability opinion.

**§5 and §6 were added after the first draft**, and §6 in particular is
propagated from repository research (`docs/market-research-2026-08.md`,
`docs/related-work.md`) rather than from a search performed for this document.
The §7 ranking was revised as a result.

---

## 1. Daon's agentic-AI portfolio — the closest art

Daon holds three issued US patents forming, in their own description, an
end-to-end agent trust architecture. All three are recent and all three should
go on the IDS.

| Patent | Title / subject | Issued |
| --- | --- | --- |
| **US 12,688,261** ([Justia](https://patents.justia.com/patent/12688261)) | Methods and systems for authorizing invocation of a tool by an autonomous artificial intelligence agent — action-level delegated authorization | **2026-07-21** |
| **US 12,563,045 B1** ([Google Patents](https://patents.google.com/patent/US12563045B1/en), [OG](https://patentsgazette.uspto.gov/week08/OG/html/1543-4/US12563045-20260224.html)) | Methods and systems for maintaining behavioral integrity of autonomous artificial intelligence agents | **2026-02-24** |
| **US 12,452,035** ([OG](https://patentsgazette.uspto.gov/week42/OG/html/1539-3/US12452035-20251021.html)) | Person-agent fidelity — human-to-agent bonding, Baseline Persona Model, drift detection | **2025-10-21** |

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
  (`app/services/idempotency.py:408`). Note the scoping: this generic reconciler
  **skips any record carrying a dispatch attempt**, because remote MCP attempts
  are owned by `McpDispatchReconciliation`, which retains the bounded upstream
  result and can rebuild the exact replay contract. A generic receipt-only
  repair would discard that result and erase delivery uncertainty.

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

## 5. Optimistic concurrency control — the closest general technique to mechanism 1

This section exists because an earlier draft of this document ranked atomic
guarded reservation first without naming the textbook technique it is an
instance of. Leaving that unstated does not make it go away; it just means an
examiner raises it first.

The general technique is **optimistic concurrency control**: read a value, then
commit conditionally on that value being unchanged, and detect the lost race by
the affected-row count rather than by holding a lock. H.T. Kung and John T. Robinson set out
the model in *On Optimistic Methods for Concurrency Control* (ACM TODS 6(2),
June 1981, pp. 213–226). Every mainstream ORM ships a productized form of it — Hibernate's
`@Version`, SQLAlchemy's `version_id_col` — and conditional `UPDATE ... WHERE`
against an observed value is its ordinary SQL expression.

**This repository contains a second, independent instance of the same
technique**, which counsel should know about before an examiner finds it.
`append_chained_audit_event()` advances a per-wallet audit chain head with
`UPDATE ... WHERE last_seq = <observed>`, checks the affected-row count, and
retries on a lost race — with the implementation explicitly noting it avoids
`SELECT ... FOR UPDATE` so behaviour is identical on SQLite and Postgres
(`app/services/audit_chain.py`, and the `AuditChainHeadModel` docstring at
`app/db/models.py:692`). Two uses of a technique in one codebase say nothing
about the prior art directly — prior art is what §102 and §103 turn on, not the
authors' habits. What it does show is that the technique is a general-purpose
tool reached for wherever a row needs contended advancement, and an examiner
who notices the second instance will read the first as an application of a
known method.

So state the distinction narrowly, because the narrow version is the one that
holds. What OCC as such does not supply:

- the predicate is a **domain cap** (`spent + requested <= max`), not an
  equality test on an observed version or sequence value, so the same statement
  both authorizes and accounts;
- the affected-row count of zero is **classified** into a reason the caller can
  act on — `permit_budget_exceeded` carrying remaining/spent/max so an agent can
  retry smaller, versus `permit_<status>` for a revoked permit — rather than
  being retried blindly as a lost race;
- there is **no retry loop at all** on the reservation path. A classical OCC
  writer retries until it wins; a caller here is denied and told why, because
  spending someone else's budget on a second attempt is not the desired
  behaviour.

Whether that combination clears §103 over Kung/Robinson plus a budgeting
reference is exactly the question for counsel. **Put OCC on the IDS** and draft
around the classification step, not around the conditional `UPDATE`.

---

## 6. MCP-native governance products, and a receipt-format Internet-Draft

**This section is propagated from research this repository performed after the
first draft of this package, and not independently re-verified here.** The
sources and per-claim verification levels live in
[`../market-research-2026-08.md`](../market-research-2026-08.md) and
[`../related-work.md`](../related-work.md), whose rows below are marked
*Verified* by that work — meaning the primary source was read on 2026-08-15.
Counsel must read the primaries before relying on any of it. The reason it
matters here is blunt: **PRs #285 and #288 added this material to the repository
and changed no file in `docs/ip/`**, so the package was ranking mechanisms
against an art landscape that the project had already superseded.

### 6.1 The receipt-format draft

**`draft-farley-acta-signed-receipts`**
([IETF Datatracker](https://datatracker.ietf.org/doc/draft-farley-acta-signed-receipts/))
specifies Ed25519 signatures over JCS-canonicalized JSON with namespaced receipt
types, and from `-02` adds a **`spending_authority` receipt type** and a Merkle
commitment mode.

Read that against this package. Ed25519 over a canonical JSON contract is the
shared substrate of mechanisms 3 and 4; mechanism 3 is additive fields signed
only when present, which is exactly what a namespaced, versioned receipt type is
designed to accommodate; and `spending_authority` is a budget-bearing artifact,
which is mechanism 1's territory. This is the single most material reference
found in the new research and it is **not currently on the IDS**.

Two qualifications, both from `related-work.md` and both important:

1. It is an **individual submission with no IETF standing** — cite it as one
   vendor's draft, not as a standards-track document. It does not carry the
   weight of RFC 8785.
2. Its priority relationship to this work is unestablished. A draft's
   publication date matters under §102(a)(1); which version first recited
   `spending_authority` matters more than the draft's existence. Counsel should
   pull the dated revision history from the Datatracker rather than the current
   text.

### 6.2 The MCP-native competitive set

| Project | What the research records | Bears on |
| --- | --- | --- |
| [protect-mcp / ScopeBlind gateway](https://github.com/tomjwxf/scopeblind-gateway) | Recorded as **the closest competitor**. A proxy intercepting `tools/call`, per-tool Cedar policy, and optional **Ed25519-signed decision receipts verifiable without calling the issuer**. No wallet, budget, or charge-once semantics. Author of the draft in §6.1. | Mechanisms 3 and 4 — a network boundary paired with offline-verifiable receipts is occupied |
| [jamjet-labs/jamjet](https://github.com/jamjet-labs/jamjet) | One `policy.yaml` across hooks, guardrails, MCP gateways and SDKs; **enforces budgets**; signed receipts with a hash-chained `previousReceiptHash` and **pre/post-execution signatures**. | Mechanism 1 (budget enforcement in an agent gateway is not novel) and mechanisms 3–4 |
| [sangaraju1988/latch](https://github.com/sangaraju1988/latch) | Python library, not a proxy: **idempotency, budget guardrail**, circuit breaker, saga/compensation, Redis backend for cross-process idempotency. No signed receipts. | Mechanisms 1 and 2 — idempotency plus budget caps in one library |
| [TraceAgent](https://www.traceagent.dev/) | Append-only receipts with SHA-256 hash chains. **Verified only that receipts are hash-chained**; whether they carry an issuer signature or verify offline is *not verified*. Do not classify as offline-verifiable without a primary source. | Mechanism 3, pending verification |
| [microsoft/agent-governance-toolkit](https://github.com/microsoft/agent-governance-toolkit) | An active proposal for independently verifiable compliance receipts. | Strategic risk; a large vendor entering the same space |

### 6.3 Problem evidence, and why it belongs on the IDS

The research also collected third-party reports of the retry/double-execution
problem: [stripe/ai#402](https://github.com/stripe/ai/issues/402),
[langchain-ai/langgraph#7417](https://github.com/langchain-ai/langgraph/issues/7417)
(a confirmed production incident of a managed platform re-dispatching a tool call
the caller believes is still running),
[crewAIInc/crewAI#5802](https://github.com/crewAIInc/crewAI/issues/5802), and
[OpenBB-finance/OpenBB#7455](https://github.com/OpenBB-finance/OpenBB/issues/7455)
(an MCP operator asking for signed per-call evidence).

These cut both ways and counsel should hear both. They are **evidence of a
long-felt need** — a *Graham v. John Deere* secondary consideration, useful
against an obviousness rejection. They are also **publicly available printed
publications describing the problem**, which is exactly the material an examiner
uses to establish that a person of ordinary skill was motivated to solve it.
Disclose them; do not lean on them as though they only helped.

---

## 7. Where the room actually is

Ranked by how defensible each looks against the art above. **This ranking was
revised after §5 and §6 were added** — the earlier version placed offline
verification third on the strength of a landscape that did not yet include the
competitive set, and it read as more secure than the evidence supports.

1. **Mechanism 2 — crash-recovery classification of a charged-but-unfinalized operation**
   (`app/services/idempotency.py:408`). Specific problem, specific asymmetric
   solution, and still no clean analogue in the searched art — `latch` pairs
   idempotency with saga/compensation, but compensation is a different answer
   from *classifying* a crashed record into never-charged, charged-and-
   reconstructable, or needs-review. This is now the strongest of the four
   because it is the one the new art in §6 does not touch at all.
2. **Mechanism 1 — atomic guarded reservation under weak isolation**
   (`app/services/permits.py:426`, and the upstream dispatch path at
   `app/services/mcp_dispatch_attempts.py:463`). Still a real solution to a real
   bug — the repo history records the overspend being found under concurrency
   and then fixed, twice, on two paths. Correctness on engines where
   `SELECT ... FOR UPDATE` is silently a no-op remains a claim limitation
   grounded in database behaviour rather than bookkeeping, and the §101 posture
   is the best of the four. It moves to second because §5 names the general
   technique it instantiates, and `jamjet` and `latch` both enforce budgets in
   agent tooling. Draft it around the **classification of the zero-row
   outcome**, which is where the distinction actually lives.
3. **Mechanism 3 — signature-stable schema evolution** (`app/services/receipts.py:312`).
   Signing additive fields only when present, so old signatures keep verifying
   as the schema grows, with a fail-closed constrained fallback for the one
   backfilled migration. Narrow, clean and concrete — but check it against the
   namespaced, versioned receipt types in the §6.1 draft before drafting, since
   that is a published approach to the same problem.
4. **Mechanism 4 — offline verification with a status taxonomy that separates
   a signature failure from a key the verifier does not hold**
   (`b2a_sdk/.../receipt_verifier.py`). **Demoted from second on the §6
   evidence.** Offline-verifiable Ed25519 receipts at a network boundary are
   occupied — protect-mcp emits receipts verifiable without calling the issuer,
   and its author has an Internet-Draft for the format. So the claimable
   surface is not "offline verification," which is now table stakes, and not
   "signed receipts at a gateway." What survives is the **six-state taxonomy
   itself**: that a key the verifier does not hold resolves to `UNKNOWN_KEY`
   rather than to a tampering verdict, so a key-distribution failure is never
   reported as fraud. That property is articulable and, on the reviewed
   materials, unaddressed by the competitors — none of the records describes
   what its verifier returns when the key is missing. It is also a much thinner
   claim than the earlier ranking implied. State it as the taxonomy, never as
   outage detection: the verifier fetches nothing and cannot observe an outage
   (§4.6 of the disclosure).

**The honest summary for counsel:** the two mechanisms on the *settlement* side
— crash-recovery classification and cap enforcement — held up against the new
art. The two on the *evidence* side weakened, because the evidence half of this
category filled in during 2026 while this package was being drafted. That is an
argument for filing promptly on the settlement mechanisms and for treating the
receipt mechanisms as dependent claims rather than independent ones.

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
- Kung, H.T. & Robinson, J.T., *On Optimistic Methods for Concurrency Control*, ACM Transactions on Database Systems 6(2), June 1981, pp. 213–226 — [ACM DL](https://dl.acm.org/doi/10.1145/319566.319567), [author PDF](https://www.eecs.harvard.edu/~htk/publication/1981-tods-kung-robinson.pdf), [dblp](https://dblp.uni-trier.de/rec/journals/tods/KungR81.html)
- [`draft-farley-acta-signed-receipts` — IETF Datatracker](https://datatracker.ietf.org/doc/draft-farley-acta-signed-receipts/)
- [protect-mcp / ScopeBlind gateway](https://github.com/tomjwxf/scopeblind-gateway)
- [jamjet-labs/jamjet](https://github.com/jamjet-labs/jamjet)
- [sangaraju1988/latch](https://github.com/sangaraju1988/latch)
- [microsoft/agent-governance-toolkit](https://github.com/microsoft/agent-governance-toolkit)
- [`docs/market-research-2026-08.md`](../market-research-2026-08.md) — competitive set and per-claim verification levels (added by #285)
- [`docs/related-work.md`](../related-work.md) — external literature with per-source verification levels
