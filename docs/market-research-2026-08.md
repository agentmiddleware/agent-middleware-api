# Market Research: MCP Governance And Metering (2026-08)

**Date:** 2026-08-15
**Scope:** External market sizing, problem evidence, and the MCP-native
competitive set for the wedge defined in [`../WEDGE.md`](../WEDGE.md).

> ## Provenance and verification discipline
>
> This document originated as an external research brief, not as repo-verified
> analysis. Before committing it, each load-bearing claim was checked against a
> primary source. The result is recorded per claim in the **Verification**
> columns below, using the same levels as
> [`related-work.md`](related-work.md):
>
> - **Verified** — checked against the primary source named in the row.
> - **Single-source** — the claim exists, but rests on one vendor's report or
>   one project's own marketing. Usable as context, not as evidence.
> - **Unverified** — carried over from the brief and not independently checked.
>   Do not put an unverified row into customer-facing copy.
>
> Three claims in the original brief were **wrong or misleading** and are
> corrected in [§5](#5-corrections-to-the-original-brief). One of them —
> the claim that no competitor pairs a network boundary with offline-verifiable
> receipts — was load-bearing for positioning, and its correction changes the
> recommended pitch.

---

## 1. Market Sizing

| Metric | Value | Source | Verification |
|---|---|---|---|
| MCP market, 2025 | USD 1.20B | [SNS Insider, MCP Market 2026–2035](https://www.snsinsider.com/reports/model-context-protocol-market-10725) | Single-source |
| MCP market, 2035 (projected) | USD 28.36B | same | Single-source |
| CAGR 2026–2035 | 37.22% | same | Single-source |
| Security & governance sub-segment CAGR | 44.56% | attributed to the same report | **Unverified** — the headline figures were confirmed, the sub-segment split was not |
| MCP servers in the wild | 5,800+ | ecosystem trackers | Unverified |
| MCP clients | 300+ | ecosystem trackers | Unverified |
| Monthly MCP SDK downloads | 97M+ | ecosystem trackers | Unverified |

**How to use this section.** Every figure here comes from a single analyst
firm or from uncited ecosystem trackers. Treat it as evidence that the category
is *taken seriously by analysts*, not as a sized addressable market. Do not put
a dollar figure on a slide without naming SNS Insider next to it.

Two weaker claims survive, and they are not equally strong. **Single-source:**
SNS Insider frames governance and security as the fastest-growing part of MCP
tooling — one firm, not a consensus, and the sub-segment figure behind it could
not be confirmed at all. Do not say "analysts consistently find." **Directly
observable:** the competitive set in §3 went from near-empty to crowded inside
roughly six months. That one needs no market model and is the one to lean on.

---

## 2. Problem Evidence

The failure this repo exists to prevent — an agent framework retrying a
timed-out tool call and producing a second charge — is reported and reproduced
by parties with no stake in this product. Note the evidence level carefully.
When first compiled, this section had no confirmed production incident for
anyone; the 2026-08-15 second pass (§8) found two first-hand ones — a
LangGraph Cloud re-execution incident with 2–3x duplicated work and cost, and
a practitioner report of quadruplicated side effects — though still **no
confirmed production incident of a duplicated payment charge specifically**.
Keep that last distinction; it is the one a skeptical buyer will probe.

| Evidence | What it establishes | Verification |
|---|---|---|
| [stripe/ai#402](https://github.com/stripe/ai/issues/402), "Agent-level retry creates duplicate charges — no idempotency guard above the tool layer" (open, 2026-05-03) | The strongest single piece of external evidence — though it is an issue report with a reproduction, not a confirmed production incident. The reporter documents that the Stripe SDK's idempotency keys cover *network-level* retries within a session, while agent frameworks retry as a **new invocation with a freshly generated key**, producing duplicate charges. They explicitly conclude the fix belongs "above the tool layer." | **Verified** — issue read directly |
| [OpenBB-finance/OpenBB#7455](https://github.com/OpenBB-finance/OpenBB/issues/7455), "Signed audit receipts for MCP server tool calls (regulatory compliance)" | A production MCP operator asking for signed per-call evidence, and being pointed at a third-party gateway rather than anything native. | **Verified** — issue located |
| [langchain-ai/langgraph#7417](https://github.com/langchain-ai/langgraph/issues/7417), "Long tool calls (~180s+) silently re-executed from checkpoint on LangGraph Cloud" (open, 2026-04-05) | **A confirmed production incident of the mechanism.** On LangGraph Cloud (Plus tier, EU), tool calls exceeding ~180s are silently re-dispatched from checkpoint while the original still runs — "both the original and the duplicate complete successfully, resulting in 2–3x redundant work and cost." Consistent across langgraph 1.1.3–1.1.6. No visible maintainer fix. This is duplicated *execution and cost*, not a confirmed duplicated payment charge. | **Verified** — issue read directly, 2026-08-15 |
| [crewAIInc/crewAI#5802](https://github.com/crewAIInc/crewAI/issues/5802), "Tool re-execution on task retry has no idempotency guard — duplicate payments, emails, trades possible" (open, 2026-05-14) | A second major framework with the same gap, with reproduction steps: any `@tool` function re-runs on task retry with no mechanism to detect prior completion; the worked example is `stripe.charge()` firing twice. Cites #7417 as production confirmation that "in-memory dedup doesn't survive worker re-dispatch." | **Verified** — issue read directly, 2026-08-15 |
| [CrewAI community thread](https://community.crewai.com/t/at-least-once-tool-calls-retries-can-double-fire-your-side-effecting-tools-in-a-crew/7697) (2026-07-31) | A first-hand practitioner incident: "this one cost us real duplicate side effects before we caught it" — one request fired a send-email step four times through layered coordinator/worker retries, producing "two tickets, two emails, two rows, **and nothing in the transcript says so**." Side effects, not charges — but that closing phrase is the evidence gap this product's receipts exist to close, stated unprompted by a stranger. | **Verified** — thread read directly, 2026-08-15 |
| Practitioner writing on idempotency in agentic tool calling | Frames this as a distributed-systems problem the agent layer imported without the corresponding patterns. | Unverified — the specific essay cited in the brief was not located |
| Vendor commentary on retry-driven cost amplification | Agents retrying on data-layer timeouts multiply per-step cost. | Unverified |

**Why stripe/ai#402 matters more than the rest.** It is a third party,
independently, describing the exact mechanism in
[`ELEVATOR_PITCH.md`](../ELEVATOR_PITCH.md)'s ten-second pitch — and arriving
at the same architectural conclusion, that the guard has to sit above the tool.
It is the one citation strong enough to use in a design-partner conversation.
It does **not** establish that anyone will pay for a gateway to fix it.

---

## 3. MCP-Native Competitive Set

The existing [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md) compares this
system against Stripe, AWS IAM, Okta, and Vault — general-purpose incumbents.
That comparison is still useful for architecture, but it is no longer the
competitive reality. The nearer competitors are MCP-native and recent.

| Project | What it is | Nearest overlap | Verification |
|---|---|---|---|
| [protect-mcp / ScopeBlind gateway](https://github.com/tomjwxf/scopeblind-gateway) | stdio proxy in front of an MCP server. Intercepts `tools/call`, evaluates Cedar + JSON policy per tool, emits optional Ed25519-signed decision receipts verifiable without calling the issuer. MIT, shadow mode by default, IETF Internet-Draft for the receipt format. | **The closest competitor.** Network boundary + per-tool policy + offline-verifiable Ed25519 receipts. No wallet, budget, or charge-once semantics. | **Verified** |
| [jamjet-labs/jamjet](https://github.com/jamjet-labs/jamjet) | Open-source safety layer: one `policy.yaml` across hooks, guardrails, MCP gateways, and SDKs; blocks unsafe calls, requires approval, enforces budgets, audits, replays. Signed receipts with a hash-chained `previousReceiptHash` and pre/post-execution signatures. | Policy portability + HITL approval + budget enforcement + chained signed receipts. Broader surface, many framework adapters. | **Verified** |
| [sangaraju1988/latch](https://github.com/sangaraju1988/latch) | MIT Python **library** (decorators/wrappers, not a proxy): idempotency, circuit breaker, timeout, budget guardrail, saga/compensation. Redis backend for cross-process idempotency; OpenAI and LangChain adapters. | Idempotency + budget caps, in-process. **No signed receipts.** | **Verified** |
| [TraceAgent](https://www.traceagent.dev/) | Append-only audit receipts with SHA-256 hash chains, authority trails linking actions to approving humans, one-click compliance exports mapped to EU AI Act / Colorado AI Act / ISO 42001. Zero-config for MCP tool calls. | Audit and compliance evidence. No metering or charge-once semantics. | **Verified** (from vendor site) that receipts are hash-chained. **Not verified**: whether they carry an issuer signature or can be verified offline without the vendor — a hash chain alone is neither. Do not classify TraceAgent as offline-verifiable without a primary source. |
| [microsoft/agent-governance-toolkit](https://github.com/microsoft/agent-governance-toolkit) | Policy enforcement, zero-trust identity, sandboxing, reliability engineering; an active proposal for independently verifiable compliance receipts. | A large vendor moving into verifiable receipts. Strategic risk more than a current competitor. | **Verified** |
| Tork Governance MCP Server | PII detection, policy enforcement, compliance receipts, kill switch, HITL. | Security-focused governance. | Unverified |
| SecureAuth Agent Authority | Enterprise IAM for agents: OAuth 2.1, CIBA HITL, anomaly detection, revocation. | Identity, upstream of this product. Not a competitor. | Unverified |
| AGA MCP Server, AgentMesh, Agent Receipts, MCPTotal, Pomerium, SGNL | Assorted MCP security gateways and receipt tools named in adoption guides. | Category noise; individually unassessed. | Unverified |

---

## 4. Where This Product Actually Sits

The brief claimed the unique intersection was *idempotency + metering +
offline-verifiable receipts at a network boundary*. Verification does not
support that, because protect-mcp already occupies the boundary-plus-receipts
half of it.

What survives is narrower and, usefully, matches
[`WEDGE.md`](../WEDGE.md) as already written:

| Dimension | Here | protect-mcp | jamjet | latch | TraceAgent |
|---|---|---|---|---|---|
| Enforces at a network boundary | ✅ | ✅ (stdio proxy) | ✅ (adapters + gateway) | ❌ (in-process library) | ✅ |
| Per-tool policy / scope | ✅ (signed permits) | ✅ (Cedar) | ✅ (policy.yaml) | ❌ | ❌ |
| Offline-verifiable signed receipts | ✅ | ✅ | ✅ | ❌ | ⚠️ hash-chained; issuer signature and offline key distribution **not verified** |
| Hash-chained audit | ✅ (per-wallet) | ❌ | ✅ | ❌ | ✅ |
| Budget enforcement | ✅ (wallet ledger) | ❌ | ✅ (caps) | ✅ (guardrail) | ❌ |
| Idempotency / no duplicate execution | ✅ | ❌ | ✅ (replay) | ✅ | ❌ |
| **Debit bound to the idempotency record** | ✅ | ❌ | ❓ **not verified** — budgets and replay are documented as separate features, with no stated binding | ❌ | ❌ |
| **Ambiguous post-dispatch outcome is a distinct, receipted state** | ✅ | ❌ | ❌ | ❌ | ❌ |
| Human-in-the-loop approval | ✅ (permit requests) | ❌ | ✅ | ❌ | ✅ (authority trail) |
| Compliance framework mapping | ❌ (deliberate) | ❌ | ❌ | ❌ | ✅ |

Read down the bolded rows. Several projects have receipts; several have
budgets; several have idempotency. The cell **no surveyed project is documented
as occupying** is that *one accepted idempotency key produces exactly one ledger
debit and one receipt, and the record linking them is a single persisted chain*
— plus the refusal to silently redispatch when the outcome is genuinely unknown
(`delivery_uncertain`, per `ELEVATOR_PITCH.md`).

**That is a scope statement, not an exclusivity claim, and the difference
matters.** jamjet enforces budgets *and* replays runs; whether it binds the two
is unresolved (§7, question 3) and its public docs describe them as independent
features. Absence of documentation is not evidence of absence. So the defensible
sentence is "no project we surveyed documents this," never "nobody does" — the
same discipline `WEDGE.md` applies to every other superlative.

That is a smaller claim than "the only gateway with receipts." It is also the
one this codebase can actually demonstrate, with `make prove-trust-plane`.

---

## 5. Corrections To The Original Brief

Recorded rather than silently edited, matching the convention at the top of
[`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md).

| Claim in the brief | Verified reality |
|---|---|
| "No one owns that exact cell" — idempotency + metering + offline-verifiable receipts at a boundary | **Overclaim, and load-bearing.** protect-mcp is a proxy with per-tool Cedar policy and Ed25519 receipts verifiable without calling the issuer. Boundary + offline receipts is taken. The defensible claim is the *economic* half: a debit bound to the idempotency record. |
| "JamJet ADK" as a product name | **Conflation.** The project is `jamjet-labs/jamjet`, a general open-source agent safety layer; Google ADK is one of many framework adapters, not the product. |
| "Signed offline receipts ❌" for latch | Directionally right but for the wrong reason — latch has no receipts *at all*, signed or otherwise. It is a reliability library, not an evidence layer. It is also not a governance competitor: it competes for the *engineer's build-vs-buy decision*, which is a different fight. |
| Market sizing presented as established fact | Traces to one analyst report (SNS Insider). The headline figures check out as that firm's published numbers; the 44.56% governance sub-segment CAGR could not be confirmed at all. |

---

## 6. Strategic Implications

### Real advantages

1. **The problem has third-party production evidence.** stripe/ai#402 is
   someone else describing this failure and concluding the fix belongs above
   the tool layer.
2. **Identity is not contested.** SecureAuth, Okta, and Auth0 own who may call.
   This product answers what happened and what it cost — downstream, and
   complementary. `ELEVATOR_PITCH.md` already refuses the IAM framing.
3. **The one-tool constraint reads as honest, not limited,** in a market where
   buyers are governing one critical tool rather than ten.
4. **Executable proof is differentiated** in a field of marketing claims.
   `make prove-trust-plane` needs no credentials and no trust in the vendor.

### Real risks

1. **protect-mcp is closer than the brief suggested,** is MIT-licensed, is
   already integrated with Microsoft Autogen, and has an IETF Internet-Draft
   for its receipt format. A draft standard for receipts is the more serious
   threat: if the receipt format standardizes elsewhere, receipts become table
   stakes and only the ledger semantics differentiate.
2. **Microsoft is in the category.** `agent-governance-toolkit` has an open
   proposal for independently verifiable compliance receipts. Assume the
   evidence layer commoditizes.
3. **latch wins the default build-vs-buy.** Free, MIT, `pip install`, no
   operational surface. The honest answer is that a library the agent can
   bypass is not a boundary, and an in-process cache is not evidence — but that
   argument has to be made explicitly, and it only wins when the buyer needs
   evidence rather than reliability.
4. **Compliance positioning is absent, deliberately.** TraceAgent maps to EU AI
   Act, Colorado AI Act, and ISO 42001. `WEDGE.md` forbids compliance-grade
   claims and that prohibition should stand. The available move is a bounded
   FAQ answer — receipts are one input an auditor may accept, the operator's
   auditor decides — not a compliance page.
5. **Category language is exhausted.** "Trust plane" and "governance gateway"
   are occupied, as `WEDGE.md` already notes. Differentiation has to come from
   the debit, not the vocabulary.

### Positioning consequences

The subheadline proposed in the brief — *"the only MCP gateway that meters by
the call, prevents double-charges on retry, and returns a signed receipt you
can verify without us"* — contains a superlative that verification does not
support and that `ELEVATOR_PITCH.md`'s closing section forbids. The
receipt-you-can-verify-without-us part is true but no longer exclusive.

The version that is both differentiated and defensible drops the superlative
and leads with the debit:

> One agent action, one debit — no matter how many times the agent retries.
> Verify the receipt without us.

See [`../WEDGE.md`](../WEDGE.md) and [`../ELEVATOR_PITCH.md`](../ELEVATOR_PITCH.md)
for the copy as adopted, and `site/compare/` for the public comparison page
built from §3 and §4.

---

## 7. Open Questions

1. Does the 44.56% governance sub-segment CAGR exist in the SNS Insider report,
   or was it interpolated? Do not repeat it until someone reads the report.
2. ~~What is in protect-mcp's IETF Internet-Draft, and does the receipt format
   have room for a ledger reference?~~ **Answered 2026-08-15 — yes on both
   counts, and the draft has moved into spending evidence. See §8.**
3. Does `jamjet` bind its budget enforcement to its replay records, or are they
   independent subsystems? This determines whether the bolded row in §4 stays
   true.
4. Do design-partner conversations actually surface duplicate-charge incidents,
   or is stripe/ai#402 an articulate outlier? **Partially advanced 2026-08-15:**
   stripe/ai#402 is not an outlier — §2 now has a confirmed production
   re-execution incident (langgraph#7417), a second framework with the same gap
   (crewai#5802), and a first-hand quadruplicated-side-effect report. Still
   open: whether any of it converts to willingness to pay. Only a partner
   conversation settles that.
5. Would a buyer with an EU AI Act mandate reject a vendor with no compliance
   mapping outright, or accept receipts as one input among several?
6. Does the demand exist? The instrument for answering is now written:
   [`partner-interview-script.md`](partner-interview-script.md), with a
   pre-committed decision rule so five interviews produce a verdict rather
   than an argument.

---

## 8. Second-Pass Findings (2026-08-15)

A follow-up research pass on the two §7 questions that could be answered from
primary sources. Everything below is **Verified** — read directly.

### 8.1 The protect-mcp receipt draft, read

The draft is
[draft-farley-acta-signed-receipts](https://datatracker.ietf.org/doc/draft-farley-acta-signed-receipts/)
("Signed Decision Receipts for Machine-to-Machine Access Control"), author Tom
Farley of ScopeBlind. Three findings, in descending order of strategic weight:

1. **The draft has moved into economic evidence.** Revision -02 adds a
   `scopeblind:spending_authority` receipt type with required `amount` and
   `currency` (ISO 4217) fields, plus optional `category` and a coarse
   `utilization_band` (`low`/`medium`/`high`/`exceeded`) chosen deliberately to
   evidence budget compliance without disclosing budget ceilings. The closest
   competitor is no longer only signing access decisions — it is standardizing
   *spend* evidence. What it still does **not** define is anything binding a
   debit to an idempotency record: `spending_authority` evidences that spend
   was authorized within a band, not that a specific charge settled exactly
   once. The §4 differentiating row stands, but its neighbourhood is being
   built on, and faster than §6 risk 1 assumed.

2. **There is room for a ledger reference — two mechanisms.** Receipt types are
   namespaced strings (`protectmcp:*`, `scopeblind:*`, `blindllm:*`), so a
   custom namespace (e.g. `agentmiddleware:governed_invoke`) carrying
   ledger-entry and idempotency-record identifiers is structurally possible
   today without touching the draft. -02 also adds a Merkle-tree "Commitment
   Mode" for selective disclosure, and algorithm agility (EdDSA — the same
   Ed25519 this repo already uses — plus ML-DSA-65 and ES256). A future
   receipt-type registry is mentioned as a MAY; none exists yet. So the §7
   hypothesis holds: **interoperating is structurally cheap** — emitting our
   receipts as a namespaced type under this format would cost a serializer,
   not a redesign.

3. **"IETF Internet-Draft" needs a qualifier wherever we cite it.** It is an
   individual submission, explicitly "not endorsed by the IETF," with no
   working-group adoption. That cuts both ways: the standardization threat in
   §6 risk 1 is real but earlier-stage than "IETF draft" connotes, and any
   interop bet is a bet on one vendor's draft, not on a standards process.

### 8.2 The problem in production

Section 2's table now carries the detail; the shape of the upgrade:

| Before this pass | After |
|---|---|
| One issue report with a reproduction (stripe/ai#402) | That, **plus** a confirmed production incident of silent retry re-execution with 2–3x cost (langgraph#7417, LangGraph Cloud, open since April with no visible fix), a second major framework with the same documented gap and a `stripe.charge()`-fires-twice reproduction (crewai#5802), and a first-hand practitioner report of one request producing four sends |
| Mechanism plausible | Mechanism confirmed at platform level: managed infrastructure re-dispatches work the caller believes is still running — exactly the ambiguous-outcome case `delivery_uncertain` exists for |

Two disciplines to keep. First: still **no confirmed production incident of a
duplicated payment charge**. Redundant compute cost and quadruplicated emails
are production facts; a double-charged customer remains, on public evidence, a
reproduction. Second: none of this is demand evidence. It is now very hard to
argue the problem is theoretical; it remains unproven that anyone pays a
vendor to solve it rather than patching their own tool layer — the community
thread's author fixed it with idempotency keys and moved on.

### 8.3 What this changes

- **The pitch gains a platform-level citation.** "Your framework's own cloud
  may re-dispatch a call you think is still running" (langgraph#7417) is
  stronger in a design-partner conversation than a hypothetical retry — and it
  lands on `delivery_uncertain`, the part of the wedge no surveyed competitor
  documents.
- **The practitioner quote is the receipt argument verbatim**: "nothing in the
  transcript says so." Candidate for `/compare/` or the pitch, cited.
- **Interop vs. compete is now a live, cheap experiment — and the experiment
  has been run.** `examples/acta_receipt_interop.py` transcodes the published
  proof receipt into an `agentmiddleware:governed_invoke` receipt in the
  draft's envelope (JCS canonicalization, Ed25519, `issuer_id`=`kid`), with
  the original signed bundle embedded and independently verifiable — the
  signature covers the exact `signing_input` bytes, and the wrapper's
  `issuer` label is checked against the issuer bound to the key material in
  the trust-keys snapshot rather than trusted on its own — and the
  ledger/idempotency linkage carried as first-class fields. Cost measured:
  ~200 lines plus tests, no trust-plane changes. Whether to *ship* it stays a
  product call; the cost side is now a fact, not an estimate.
- **§6 risk 1 escalates**: the receipt-format neighbour added spend evidence
  within two draft revisions. If a registry lands, economic receipt types
  become table stakes the way signatures did.

---

*Compiled 2026-08-15; second pass appended the same day. Sources verified as
marked; unverified rows are labeled and must not be promoted into
customer-facing copy without a check.*
