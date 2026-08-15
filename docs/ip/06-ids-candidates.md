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
Daon patents are what a lay search surfaced, and published applications in the
18-month blackout window are precisely where competing 2025–2026 agent-governance
filings will be sitting.

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
| 19 | Any design-partner or "stranger test" distribution (`docs/stranger-test.md`, `DESIGN_PARTNER_GUIDE.md`) | Recipients, dates, and whether under NDA. Distribution under NDA is not a public disclosure; distribution without one may be. |
| 20 | Any published SDK package (`b2a_sdk`) | **Verify whether one was ever published.** A public release would place the offline verifier source — the Set C mechanism — into publicly available prior art. |

See [`01-filing-risks-and-actions.md`](01-filing-risks-and-actions.md) §1 for
why this section is the one to resolve first.
