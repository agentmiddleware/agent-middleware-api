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
| 9a | **`draft-farley-acta-signed-receipts`** ([IETF Datatracker](https://datatracker.ietf.org/doc/draft-farley-acta-signed-receipts/)) | **The most material reference added since the first draft of this package.** Ed25519 over JCS-canonicalized JSON, namespaced receipt types, and from `-02` a **`spending_authority`** receipt type plus a Merkle commitment mode — reaching mechanisms 1, 3 and 4 simultaneously. Two qualifications: it is an **individual submission with no IETF standing**, so cite it as one vendor's draft rather than a standards-track document; and pull the **dated revision history**, since which revision first recited `spending_authority` matters more under §102(a)(1) than the draft's existence. Authored by the party behind protect-mcp (item 20a). |

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
| 20e | [microsoft/agent-governance-toolkit](https://github.com/microsoft/agent-governance-toolkit) | Active proposal for independently verifiable compliance receipts. Disclose as a large-vendor entrant in the same space. |

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
