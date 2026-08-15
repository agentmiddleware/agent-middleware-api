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
by parties with no stake in this product. Note the evidence level carefully: an
issue report with a reproduction is not the same as a confirmed production
incident, and this document does not have the latter for anyone.

| Evidence | What it establishes | Verification |
|---|---|---|
| [stripe/ai#402](https://github.com/stripe/ai/issues/402), "Agent-level retry creates duplicate charges — no idempotency guard above the tool layer" (open, 2026-05-03) | The strongest single piece of external evidence — though it is an issue report with a reproduction, not a confirmed production incident. The reporter documents that the Stripe SDK's idempotency keys cover *network-level* retries within a session, while agent frameworks retry as a **new invocation with a freshly generated key**, producing duplicate charges. They explicitly conclude the fix belongs "above the tool layer." | **Verified** — issue read directly |
| [OpenBB-finance/OpenBB#7455](https://github.com/OpenBB-finance/OpenBB/issues/7455), "Signed audit receipts for MCP server tool calls (regulatory compliance)" | A production MCP operator asking for signed per-call evidence, and being pointed at a third-party gateway rather than anything native. | **Verified** — issue located |
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
2. What is in protect-mcp's IETF Internet-Draft, and does the receipt format
   have room for a ledger reference? If so, interoperating beats competing.
3. Does `jamjet` bind its budget enforcement to its replay records, or are they
   independent subsystems? This determines whether the bolded row in §4 stays
   true.
4. Do design-partner conversations actually surface duplicate-charge incidents,
   or is stripe/ai#402 an articulate outlier? One partner interview settles it.
5. Would a buyer with an EU AI Act mandate reject a vendor with no compliance
   mapping outright, or accept receipts as one input among several?

---

*Compiled 2026-08-15. Sources verified as marked; unverified rows are labeled
and must not be promoted into customer-facing copy without a check.*
