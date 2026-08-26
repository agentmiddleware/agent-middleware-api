# Information Disclosure Statement candidates

References known to the inventor that are potentially material to
patentability, for disclosure under 37 CFR 1.56 and 1.97.

**Timing.** Under 37 CFR 1.97(b) an IDS is considered without fee or statement
if filed within **any one** of several alternative windows — for a national
application other than a continued prosecution application, within three months
of its filing date; for a national-stage application, within three months of
national-stage entry; or before the mailing of a first Office action on the
merits. These are alternatives, so in practice the no-fee period runs to
whichever of them falls latest. Later filings fall under 1.97(c)/(d) and carry
fees, statements, or both. An IDS must also satisfy the content requirements of
**37 CFR 1.98** and be signed per **37 CFR 1.33(b)**. Confirm the applicable
window with counsel against the actual filing route — and give counsel this list
at engagement, not after filing.

**Duty of candor.** The duty runs to each individual associated with the
application and continues throughout prosecution. If you learn of further art —
including a competitor's published application, or your own further public
disclosure — tell counsel immediately. Withholding known material art risks
unenforceability for inequitable conduct.

---

## A. Patents — highest materiality

| # | Reference | Relevance |
| --- | --- | --- |
| 1 | **US 12,688,261** — Methods and Systems for Authorizing Invocation of a Tool by an Autonomous Artificial Intelligence Agent (Daon), issued **2026-07-21** | **Closest known art.** Action-level delegated authorization producing a short-lived machine-verifiable delegation artifact bound to action type, resource scope, time window, rate limits, and execution context. Directly relevant to the permit structure. |
| 2 | **US 12,563,045 B1** — Methods and systems for maintaining behavioral integrity of autonomous AI agents (Daon), issued **2026-02-24** | Runtime execution monitoring with policy applied at discovery, invocation, and runtime checkpoints. Relevant to the governed-invocation pipeline. |
| 3 | **US 12,452,035** — Person-agent fidelity (Daon), issued **2025-10-21** | Human-to-agent bonding and drift detection. Less directly relevant; disclose for completeness of the portfolio. |

**Action for counsel:** obtain and read the **granted claims** of all three, not
the press summaries. Then order a professional patentability search — the three
Daon patents are what a lay search surfaced, and applications that have not yet
published — generally those under 18 months from their earliest priority date —
are precisely where competing 2025–2026 agent-governance filings will be sitting.

---

## B. Standards and specifications

| # | Reference | Relevance |
| --- | --- | --- |
| 4 | Model Context Protocol specification, `modelcontextprotocol.io/specification/2025-11-25` | Normative substrate for tool discovery, JSON-RPC invocation, and authorization expectations. Cited in `docs/related-work.md`. |
| 5 | RFC 8032 — Edwards-Curve Digital Signature Algorithm (EdDSA) | Ed25519, the signature scheme used throughout. |
| 6 | RFC 7517 / RFC 7515 — JSON Web Key, JSON Web Signature | JWK Set served at `/.well-known/jwks.json`. |
| 7 | RFC 8785 — JSON Canonicalization Scheme (JCS) | Closest standardized analogue to the `awi-canonical-json/1` contract. Counsel should note where the implementation **differs** from JCS — decimal normalization and datetime coercion in particular — since those differences are what the canonicalization-version check protects. |
| 8 | RFC 6962 — Certificate Transparency | Hash-linked tamper-evident log structure; relevant to the audit chain (§4.7), which is described as supporting detail, not novelty. |
| 9 | RFC 8693 — OAuth 2.0 Token Exchange; RFC 9396 — Rich Authorization Requests | Scoped, delegated, fine-grained authorization credentials. |
| 9a | **`draft-farley-acta-signed-receipts`** ([IETF Datatracker](https://datatracker.ietf.org/doc/draft-farley-acta-signed-receipts/)) | **The most material reference added since the first draft of this package.** Ed25519 over JCS-canonicalized JSON, namespaced receipt types, and from `-02` a **`spending_authority`** receipt type plus a Merkle commitment mode — reaching mechanisms 3 and 4, and **arguably** mechanism 1. **The mechanism-1 reach is contested and counsel should decide it:** §8.1 of the market research records that `spending_authority` evidences *that spend was authorized within a band*, not that a charge settled exactly once, and mechanism 1 is atomic guarded reservation. On that reading it does not reach mechanism 1 at all. Recorded as contested rather than resolved, because narrowing prior-art reach is a judgement for counsel, not a documentation edit. Two qualifications: it is an **individual submission with no IETF standing**, so cite it as one vendor's draft rather than a standards-track document; and pull the **dated revision history**, since which revision first recited `spending_authority` matters more under §102(a)(1) than the draft's existence. Authored by the party behind protect-mcp (item 20a). |

---

## C. Non-patent literature

| # | Reference | Relevance |
| --- | --- | --- |
| 10 | Birgisson et al., *Macaroons: Cookies with Contextual Caveats for Decentralized Authorization in the Cloud* (Google Research) | Academic lineage for attenuated caveat-bearing credentials, cited as design lineage in `docs/related-work.md`. **Disclose it.** Note the citation shows the reference is in the project's documentation; it does not by itself establish *which individual* knew of it or *when* — counsel should identify the person and date rather than infer knowledge from the repository. |
| 11 | Stripe API documentation, idempotent requests / `Idempotency-Key` | Industry-standard idempotency key plus request fingerprint plus stored response. |
| 12 | Chew, *Avoiding double payments in a distributed payments system*, Airbnb Engineering | Published treatment of exactly-once debit in a distributed payment system. Materially close to Set B; disclose. |
| 13 | *Constant-Size Cryptographic Evidence Structures for Regulated AI Workflows*, arXiv:2511.17118 | Hash-and-sign evidence structures composing with hash chains. Cited in `docs/related-work.md`. |
| 14 | *Creating Characteristically Auditable Agentic AI Systems*, ACM DOI 10.1145/3759355.3759356 | Agent auditability as a system property. Cited in `docs/related-work.md`. |
| 15 | *From Prompt Injections to Protocol Exploits*, arXiv:2506.23260 | Threat taxonomy for LLM-agent ecosystems including protocol-level attacks. Background for the confused-deputy and permit-misuse framing. |
| 15a | **Kung, H.T. & Robinson, J.T., *On Optimistic Methods for Concurrency Control*, ACM TODS 6(2), June 1981, pp. 213–226** (DOI [10.1145/319566.319567](https://dl.acm.org/doi/10.1145/319566.319567)) | The general technique mechanism 1 instantiates: commit conditionally on an observed value and detect the lost race by affected-row count instead of holding a lock. Productized in Hibernate `@Version` and SQLAlchemy `version_id_col`. Disclose it and draft around the **classification of the zero-row outcome** — see §5 of `02-prior-art-landscape.md`. Note this repository contains a second instance of the technique in `app/services/audit_chain.py`, which an examiner may find. |

### C.1 MCP-native governance products

Propagated from [`../market-research-2026-08.md`](../market-research-2026-08.md)
(added by #285), whose rows carry per-claim verification levels. **Not
independently re-verified for this package** — counsel must read the primaries.
All are publicly available and describe systems overlapping the claimed
mechanisms, so all are IDS candidates.

| # | Reference | Relevance |
| --- | --- | --- |
| 20a | [protect-mcp / ScopeBlind gateway](https://github.com/tomjwxf/scopeblind-gateway) | Recorded as **the closest competitor**: a proxy intercepting `tools/call` with per-tool Cedar policy and optional **Ed25519-signed decision receipts verifiable without calling the issuer**. Occupies network-boundary-plus-offline-receipts. No wallet, budget, or charge-once semantics. Author of item 9a. **Establish its public-availability date** — it bears on §102(a)(1) for mechanisms 3 and 4. |
| 20b | [jamjet-labs/jamjet](https://github.com/jamjet-labs/jamjet) | **Enforces budgets** and emits signed receipts with a hash-chained `previousReceiptHash` plus pre/post-execution signatures. Reaches mechanism 1 (budget enforcement in an agent gateway) and mechanisms 3–4. |
| 20c | [sangaraju1988/latch](https://github.com/sangaraju1988/latch) | Python library pairing **idempotency with a budget guardrail**, plus circuit breaker and saga/compensation, with a Redis backend for cross-process idempotency. Closest to Set B; note compensation is a different answer from crash-state classification. No signed receipts. |
| 20d | [TraceAgent](https://www.traceagent.dev/) | Append-only SHA-256 hash-chained receipts. **Verified only that receipts are hash-chained**; issuer signature and offline verifiability are *unverified*. Do not characterize it as offline-verifiable without a primary source. |
| 20e | [microsoft/agent-governance-toolkit](https://github.com/microsoft/agent-governance-toolkit) | **Upgraded 2026-08-25 — no longer a proposal; it ships.** Offline-verifiable decision receipts: **Ed25519 signatures over RFC 8785 (JCS) canonical payloads**, hash-chained via `previousReceiptHash`, verifiable without operator infrastructure ([Tutorial 33](https://github.com/microsoft/agent-governance-toolkit/blob/main/docs/tutorials/33-offline-verifiable-receipts.md), [issue #1499](https://github.com/microsoft/agent-governance-toolkit/issues/1499)). **Now among the most material references in this package**: it reaches mechanisms 3 and 4 using the same Ed25519 signature algorithm and the same receipt-and-hash-chain concepts (its JCS canonicalization is related to, but not identical with, this repo's `awi-canonical-json/1` — see item 7), and it is backed by a large vendor with resources to prosecute. **Establish the publication date of the tutorial and of the merged implementation** — it bears directly on §102(a)(1). Carries **no** ledger, spend, or idempotency construct, so on the materials read it does not reach mechanisms 1 or 2. |

### C.1a Receipt protocols surfaced 2026-08-25

A third research pass ([`../market-research-2026-08.md`](../market-research-2026-08.md)
§9) roughly doubled the known size of this category. **None has been
independently re-verified for this package; counsel must read the primaries.**

The column that matters to this package is the last one. On the materials read,
**every reference below whose primary source was read reaches only the
evidence-side mechanisms (3 and 4) and none reaches the settlement-side
mechanisms (1 and 2)** — Signet (22c) is excluded from that statement, since its
reach is reported through a third party rather than established — which is the same
conclusion [`02-prior-art-landscape.md`](02-prior-art-landscape.md) §7 reached
independently, and it strengthens the recommendation there to file promptly on
the settlement mechanisms and treat the receipt mechanisms as dependent claims.

| # | Reference | Relevance | Reaches |
| --- | --- | --- | --- |
| 22a | *Notarized Agents: Receiver-Attested Confidential Receipts for AI Agent Actions* ("Sello"), [arXiv:2606.04193](https://arxiv.org/html/2606.04193) | **The single most useful reference for counsel in this batch, as a map rather than as art.** A preprint proposing receiver-side signing (COSE_Sign1 over an HPKE-encrypted payload, published to public transparency logs) whose related-work section surveys the receipt protocols listed at 22b-22g below plus `draft-farley-acta` (item 9a). Its own text claims eight; seven distinct names were extracted, so **counsel should read the table directly rather than rely on a count**. Its own §8.4 names coupling to payment/settlement as future work and **explicitly unimplemented**. Give counsel this paper first — it enumerates most of the rows below and is a dated printed publication. | 3, 4 |
| 22b | [Pipelock / PipeLab](https://github.com/luckyPipewrench/pipelock) | Agent firewall emitting **mediator-signed Ed25519 action receipts**, hash-chained and offline-verifiable, from an out-of-process sidecar. Also publishes a signer-position taxonomy (in-process / operator-mediator / third-party witness). Security and egress centre of gravity; no wallet, budget, or charge-once semantics. | 3, 4 |
| 22c | Signet | Bilateral co-signed receipts; encryption key not separated from the signing identity; no transparency-log integration. **Known only through 22a's related-work table — no primary source located.** Counsel should locate the primary before relying on or distinguishing it. | *reported* 3, 4 — **not established**, and excluded from the blanket statement above until a primary source is read |
| 22d | Agent Passport System (APS), attributed to T. Pidlisnyi, 2025 | Four receipt types — ActionReceipt, AuthorityBoundaryReceipt, CustodyReceipt, ContestabilityReceipt — signed by the executing agent. The **AuthorityBoundaryReceipt** is worth reading against the permit-scope claims. Via 22a. | 3, 4 |
| 22e | `draft-nivalto-agentroa` | Egress-gateway signing within the operator's trust domain, with SCITT transparency-log integration. Via 22a. | 3, 4 |
| 22f | Agent Receipts | Platform-signed Ed25519 receipts; signer on the operator side. Via 22a. | 3, 4 |
| 22g | Attested Intelligence | MCP governance proxy with hash-linked continuity chains, distributed point-to-point rather than via public logs. Via 22a — note an "Attested Intelligence" also appears in the §3 "category noise" row of the market research. | 3, 4 |

### C.1b Fabricated citations — do not disclose, and do not rely on

An acquisition-data-room draft (2026-08-26, external compilers) cited three
patents as close-watch prior art, two of them rated a **HIGH** threat. **All three were looked up against Google Patents on 2026-08-25, and each
resolves to a real patent in an unrelated field — none matching the cited title
or assignee.** Treat the mappings below as indicative, not established: they come
from Google Patents rather than USPTO, and a USPTO search for US 2024/0034567 A1
returned no record at all. What is already clear is that the citations do not
support what the draft says they support.

| Cited as | Google Patents result — **indicative, pending USPTO confirmation** |
| --- | --- |
| **US 2024/0089012 A1** — Anthropic, "Cryptographic proof of API consumption" (rated HIGH) | **Turck Holding GmbH**, *"Signal transmission system for transmitting a main process variable and further data between a field device and a superordinate unit."* Industrial automation, HART protocol over optocouplers. Filed 2023-09-06, published 2024-03-14. |
| **US 2024/0034567 A1** — Skyfire, "Receipt-based API billing for AI agents" (rated HIGH) | **Duecker Group GmbH**, *"Angled transfer with roller chain."* A roller-conveyor mechanism. App. 18/032,225, published 2024-02-01. |
| **US 12,300,000 B2** — PayPal, cryptographic receipts for online transactions | **Here Global BV**, *"Method and apparatus for computer-vision-based object motion detection."* Issued 2025-05-13. |

**This is the signature of hallucinated citations**, not transcription drift:
plausible-looking numbers in the right format, paired with titles and assignees
that match the argument being made. A mis-keyed digit produces one wrong
reference; it does not produce three, each landing on an unrelated field, each
conveniently supporting the section it appears in.

**Consequences, in order of seriousness.**

1. **Verify each number against USPTO, then let counsel decide disclosure.**
   The resolutions above come from Google Patents, not USPTO, and a USPTO search
   for **US 2024/0034567 A1** returned no record at all — so treat the
   alternate-assignee mapping as *indicative*, not established, until each
   number, title, assignee and date is confirmed against USPTO. Note also that
   under **37 CFR 1.97(h)** an IDS is not an admission that a listed reference
   is material or is prior art, so a metadata error is not by itself a reason a
   number can never be submitted. What is clear is narrower: do not disclose
   these *as described here*, because disclosing a reference that does not say
   what the disclosure claims it says is worse than omitting it — it misleads
   the examiner and wastes prosecution on art that does not exist.
2. **The threat assessment built on them is void.** The data room rates the
   "Anthropic" and "Skyfire" filings HIGH and lets them drive filing urgency.
   Nothing supports that. Anthropic's actual published portfolio is AI/ML work
   (agentic interface automation, prediction accuracy); nothing matching
   "cryptographic proof of API consumption" was located.
3. **The real search has not been done.** These placeholders may have displaced
   a genuine competitor search rather than summarizing one. The Daon patents in
   §A remain the only corroborated art in this package, and item 1's standing
   instruction — order a professional patentability search — is now the more
   urgent of the two, not the optional one.
4. **Audit the rest of that draft.** Three fabricated citations in one section
   means every other unsourced factual claim in the same document needs a check
   before it reaches counsel or a buyer, including the acquisition comparables.

**Skyfire is nonetheless worth a real search.** [Skyfire Systems,
Inc.](https://www.crunchbase.com/organization/skyfire-systems) is a genuine
company in the adjacent economic lane — a payment network for AI agents, with
programmable wallets, verified agent identity (KYA), and the KYAPay protocol.
That is closer to the *economic* claims here than anything currently in
[`../market-research-2026-08.md`](../market-research-2026-08.md) §3, which does
not track it at all. **No assignee search has been run, so Skyfire's filing
status is unassessed — not a negative result.** Publication timing turns on each
application's **earliest priority date**, not on the company's August 2024
public launch, so the launch date establishes nothing about what is on file. Counsel should run a
proper assignee search on Skyfire Systems, Inc. and on Nevermined and Payman —
by assignee, not by keyword — rather than treating the fabricated cite above as
having covered it.

The same draft cites Daon **US 12,688,261** as "Filed ~2023" where item 1 of this
document records it **issued 2026-07-21**. Reconcile filing date against issue
date before either number is used.

### C.2 Third-party problem reports

These are double-edged and counsel should treat them as such: they evidence a
**long-felt need** (a *Graham v. John Deere* secondary consideration against
obviousness) while also being **printed publications establishing that a person
of ordinary skill was motivated to solve the problem**. Disclose them.

| # | Reference | Relevance |
| --- | --- | --- |
| 21a | [stripe/ai#402](https://github.com/stripe/ai/issues/402) | Agent-level retry creates duplicate charges; SDK-level idempotency keys do not cover it because the framework retries as a new invocation with a fresh key. Concludes the guard belongs above the tool layer. A reproduction, **not** a confirmed production charge. |
| 21b | [langchain-ai/langgraph#7417](https://github.com/langchain-ai/langgraph/issues/7417) | **Confirmed production incident**: managed infrastructure re-dispatches a tool call the caller believes is still running. Duplicated execution and cost — the platform-level instance of the ambiguous-outcome case `delivery_uncertain` models. |
| 21c | [crewAIInc/crewAI#5802](https://github.com/crewAIInc/crewAI/issues/5802) | A second framework documenting the same gap, with a `stripe.charge()`-fires-twice worked example. |
| 21d | [OpenBB-finance/OpenBB#7455](https://github.com/OpenBB-finance/OpenBB/issues/7455) | A production MCP operator requesting signed per-call evidence for regulatory compliance. |

---

## D. The inventor's own disclosures — **disclose these too**

Do not omit these because they are yours. Under 35 U.S.C. §102(b)(1) an
inventor's own prior public disclosure is excepted from prior art in the US only
within the 12-month grace period, and it is **not** excepted at all in absolute-
novelty jurisdictions. Counsel needs the complete list with dates to assess both.

| # | Disclosure | What to provide |
| --- | --- | --- |
| 16 | Public product site, `https://www.thisisatest.tech` | First-live date; archived captures. Describes Ed25519-signed receipts, offline verification, `/.well-known/trust-keys.json`. |
| 17 | Published live-proof artifacts: `https://www.thisisatest.tech/proof/`, `/proof/receipt.json`, `/proof/trust-keys.json` | First-live dates, archived captures, and the published content. Note `scripts/publish_live_proof.py` is the generator, not the disclosure. |
| 18 | MCP Registry / marketplace materials (`server.json`, `docs/mcp-registry-submission.md`, `docs/agentmarket-listing.md`) | **Candidate surfaces, not confirmed disclosures.** No matching MCP Registry entry appears to exist and the repo marks the AgentMarket copy as frozen. Confirm whether either was ever actually submitted or published, and when. |
| 19 | Every design-partner or "stranger test" distribution (`docs/stranger-test.md`, `DESIGN_PARTNER_GUIDE.md`) | Record **every** copy distributed: recipient, date, confidentiality terms, and whether any use, sale, or offer for sale accompanied it. Distribution under NDA **may** not be a public disclosure — but NDA status is not dispositive. Under *Helsinn Healthcare v. Teva* (2019) a sale or offer for sale can trigger the on-sale bar of §102(a)(1) **even when confidential**. Counsel assesses the patent-law consequences; do not treat an NDA as a safe harbour. |
| 20 | Any published SDK package (`b2a_sdk`) | **Verify whether one was ever published.** A public release would place the offline verifier source — the Set C mechanism — into publicly available prior art. |

See [`01-filing-risks-and-actions.md`](01-filing-risks-and-actions.md) §1 for
why this section is the one to resolve first.
