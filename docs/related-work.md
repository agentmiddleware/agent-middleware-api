# Related Work And Claim Evidence

This document maps external literature to the repo's narrow product wedge:

```text
logical action -> authorize -> reserve configured allowance -> debit
-> claim one gateway dispatch -> confirmed outcome | delivery_uncertain
-> linked receipt/audit -> reconcile
```

The sources below are context for design and positioning. They do not by
themselves prove production readiness, compliance, settlement safety,
enterprise suitability, market absence, or customer demand. Repo claims still
need code, tests, docs, or executable evidence. Product-need claims require the
named-prospect evidence in
[`30-day-customer-validation.md`](30-day-customer-validation.md).

For the inward-facing counterpart — repo mechanisms verified against their own
source, with evidence-confidence markers — see
[`docs/invention-inventory.md`](invention-inventory.md).

## Product Boundary

Verified from the current repository workspace:

- The active wedge is transaction integrity for consequential autonomous
  actions in `WEDGE.md`.
- The supported upstream path binds one logical action to delegated authority,
  configured credit or call allowance, one-shot gateway dispatch/debit state,
  explicit `delivery_uncertain`, and gateway evidence.
- Current accounting models fixed per-call credits and call allowance. It is
  not a generalized ledger of deployments, deletions, refunds, or records
  modified.
- Receipts are operator-signed gateway evidence. They do not prove the actual
  downstream effect and are not independently witnessed.
- AWI, browser automation, content generation, oracle crawls, media utilities,
  IoT bridges, red-team services, RTaaS, telemetry auto-PR, and sandbox demos
  are proof surfaces, not the initial product boundary, in `WEDGE.md`.

## 2026 Competitive Boundary

This table records what primary sources show, not a claim that any competitor
is complete, adopted, secure, or commercially sufficient.

| Nearby category | Primary-source evidence | Positioning consequence |
| --- | --- | --- |
| Agent identity and lifecycle | [Microsoft Entra Agent ID](https://learn.microsoft.com/en-us/entra/agent-id/) documents agent identities, owners/sponsors, lifecycle governance, access packages, Conditional Access, protection, and OAuth integration. | Integrate enterprise IAM; do not present identity as the wedge. |
| Tool policy at the gateway | [Amazon Bedrock AgentCore Policy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-getting-started.html) places Cedar allow/deny evaluation at a gateway and demonstrates parameter-aware refund limits. | Generic tool authorization and policy are supporting controls, not standalone differentiation. |
| MCP identity-aware access | [Aembit MCP Identity Gateway](https://docs.aembit.io/ai-guide/mcp/identity-gateway/) proxies MCP, evaluates identity-aware access policy, exchanges downstream credentials, and exposes activity visibility. | Do not compete on credential brokering or access policy alone. |
| Broad agent gateway | [Portkey Agent Gateway](https://portkey.ai/blog/agent-gateway/) advertises per-agent/team/user access, budget and usage limits, traces, guardrails, load balancing, and automatic fallbacks. | Broad gateway, observability, and generic reliability are crowded. For consequential writes, the wedge hypothesis is the opposite failure rule: preserve post-dispatch uncertainty and refuse unsafe automatic redispatch. |
| Continuous governance evidence | [Vanta AI Governance](https://www.vanta.com/resources/introducing-ai-governance-from-vanta) describes continuous policy evidence and labels the AI-governance layer early access. | Treat GRC evidence as an adjacent integration surface, not an uncontested product category or a validated buyer request. |
| Signed execution-receipt format | [XAIP Receipts](https://datatracker.ietf.org/doc/draft-xkumakichi-xaip-receipts/) defines an individual Internet-Draft for signed agent tool-call records and explicitly says it has no IETF endorsement or formal standards standing. | Never claim that portable signed agent receipts are unique, standardized, or adopted merely because a draft exists. |
| Open receipt tooling | [Obsigna / Agent Receipts](https://github.com/agent-receipts/obsigna) publishes an open receipt protocol, Go/TypeScript/Python SDKs, signing daemon, and MCP proxy. | Receipt format and signing alone are not the wedge. Repository existence is not adoption or independent validation. |

The market-gap statement remains a hypothesis: these sources prominently cover
identity, authorization, budgets, gateways, observability, governance evidence,
and receipt formats. They do not prove that ambiguity-safe execution is absent
from every product. Customer discovery must establish whether integrated
logical-action, non-redispatch, and reconciliation semantics solve a problem
buyers will pay to keep inline.

## Source Map

| Pillar | Source | Why it matters here | Verification level |
| --- | --- | --- | --- |
| AWI | [Build the web for agents, not agents for the web](https://arxiv.org/abs/2506.10953) | Foundation for the AWI proof surface and the idea that agents need machine-native interfaces. | Verified external source; README claim is repo-verified. |
| AWI | [WebArena](https://arxiv.org/abs/2307.13854) | Empirical context for web-agent failure on human-oriented sites. | Verified external source; repo benchmark alignment is not verified. |
| MCP | [Model Context Protocol specification](https://modelcontextprotocol.io/specification/2025-11-25) | Normative substrate for MCP discovery, tools, JSON-RPC, authorization, and trust-and-safety expectations. | Verified external source; implementation conformance is partially verified by tests. |
| MCP | [Introducing the Model Context Protocol](https://www.anthropic.com/news/model-context-protocol) | Primary-source launch framing for MCP as a standard connector layer. | Verified external source. |
| MCP | [Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp) | Useful context for why governance, metering, and tool-result discipline matter as MCP tool counts scale. | Verified external source; no repo performance claim implied. |
| Payments and wallets | [How Agentic AI Will Reshape Payments](https://www.imf.org/en/publications/imf-notes/issues/2026/04/22/how-agentic-ai-will-reshape-payments-575560) | Institutional framing for authorization, settlement, compliance, and resilience in agent-mediated payments. | Verified external source; repo payment readiness is not verified. |
| Payments and wallets | [Agent Wallets: How AI Agents Spend Money](https://eco.com/support/en/articles/14839403-agent-wallets-how-ai-agents-spend-money) | Practitioner taxonomy for bounded authority, scoped keys, and policy-constrained spend. | Verified external source; use as market context. |
| Authorization | [API Tokens: A Tedious Survey](https://fly.io/blog/api-tokens-a-tedious-survey/) | Practitioner comparison of token approaches relevant to scoped signed permits. | Verified external source; repo token design remains custom. |
| Authorization | [Macaroons](https://research.google/pubs/macaroons-cookies-with-contextual-caveats-for-decentralized-authorization-in-the-cloud/) | Academic lineage for attenuated, caveat-bearing authorization credentials. | Verified external source; permits are inspired-by, not macaroons-compatible. |
| Audit and evidence | [Constant-Size Cryptographic Evidence Structures for Regulated AI Workflows](https://arxiv.org/abs/2511.17118) | Context for hash-and-sign evidence structures that compose with hash chains. | Verified external source; regulated-workflow claims are not verified. |
| Audit and evidence | [Creating Characteristically Auditable Agentic AI Systems](https://dl.acm.org/doi/10.1145/3759355.3759356) | Context for agent auditability as a first-class system property. | Partially verified externally; DOI/title found, full ACM page not verified here. |
| Threat model | [From Prompt Injections to Protocol Exploits](https://arxiv.org/abs/2506.23260) | Threat taxonomy for LLM-agent ecosystems, including protocol-level vulnerabilities. | Verified external source. |
| Threat model | [Design Patterns for Securing LLM Agents against Prompt Injections](https://arxiv.org/abs/2506.08837) | Design-pattern context for prompt-injection resistance when agents use tools. | Verified external source. |
| Governance | [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework) | Governance vocabulary for enterprise and public-sector risk conversations. | Verified external source; compliance is not claimed. |
| Problem evidence | [stripe/ai#402 — agent-level retry creates duplicate charges](https://github.com/stripe/ai/issues/402) | Third-party issue report, with a reproduction, of the exact failure this wedge exists to prevent: agent frameworks retry as a new invocation with a fresh idempotency key, so SDK-level keys do not cover it. Concludes the guard belongs above the tool layer. | Verified external source; read directly 2026-08-15. It is a reported reproduction, **not** evidence that a duplicate charge reached production, and it establishes the problem rather than demand for this product. |
| Problem evidence | [langchain-ai/langgraph#7417 — long tool calls silently re-executed on LangGraph Cloud](https://github.com/langchain-ai/langgraph/issues/7417) | Confirmed production incident of the retry-re-execution mechanism: managed infrastructure re-dispatches a tool call the caller believes is still running, "2–3x redundant work and cost." Platform-level instance of the ambiguous-outcome case `delivery_uncertain` models. | Verified external source; read directly 2026-08-15. Duplicated execution and cost in production — not a confirmed duplicated payment charge. |
| Problem evidence | [crewAIInc/crewAI#5802 — tool re-execution on retry has no idempotency guard](https://github.com/crewAIInc/crewAI/issues/5802) | A second major framework documenting the same gap, with reproduction steps and a `stripe.charge()`-fires-twice worked example. | Verified external source; read directly 2026-08-15. Reproduction, not a production charge incident. |
| Receipt formats | [draft-farley-acta-signed-receipts](https://datatracker.ietf.org/doc/draft-farley-acta-signed-receipts/) | The protect-mcp/ScopeBlind receipt format: Ed25519 over JCS-canonicalized JSON, namespaced receipt types, and (from -02) a `spending_authority` type plus Merkle commitment mode. Structurally open to a custom `agentmiddleware:*` receipt type carrying ledger and idempotency references — see `market-research-2026-08.md` §8.1. | Verified external source; read directly 2026-08-15. **Individual submission with no IETF standing** — cite it as one vendor's draft, not as a standards-track document. |
| Competitive set | [`market-research-2026-08.md`](market-research-2026-08.md) | MCP-native competitors, market sizing, and the verification level of each claim. Records that signed offline-verifiable receipts are no longer differentiating. | Repo document; per-claim verification levels stated inline. |

## Claim Evidence Matrix

| Public claim | Repo evidence | Reality level |
| --- | --- | --- |
| The product wedge is transaction integrity for consequential autonomous actions, not a broad agent platform. | `WEDGE.md` defines the wedge, qualification test, and non-core proof surfaces. | Verified as repo positioning; customer need not verified. |
| Agents can discover machine-readable interfaces. | `README.md` points agents to `/.well-known/agent.json`, `/llm.txt`, `/mcp/tools.json`, and `/openapi.json`; discovery drift tests exist in `tests/test_discovery_drift.py`. | Verified. |
| Signed permits bind wallet, key, tool, scope, budget, expiry, and nonce. | `app/services/permits.py` creates signed permits and validates wallet, key, tool, scope, budget, expiry, and signature; `tests/test_permits.py` covers valid and invalid cases. | Verified. |
| Governed MCP requires permits and idempotency in strict trust mode. | `app/routers/mcp.py` enforces permit and idempotency checks for governed calls; `tests/test_mcp_trust_mode.py` covers missing permit, missing idempotency, wrong key, wrong wallet, and wrong tool. | Verified. |
| One accepted logical action rejects changed payload and does not reacquire a committed gateway dispatch claim. | `app/routers/mcp.py` raises `idempotency_key_reused`; `McpDispatchAttemptService.claim_dispatch` in `app/services/mcp_dispatch_attempts.py` owns the claim; `tests/test_idempotency.py` and `tests/test_mcp_upstream_governed.py` cover replay, payload conflict, losing claims, and non-redispatch. | Verified on covered paths. |
| A post-claim ambiguous result becomes charged `delivery_uncertain` and is replayed without redispatch. | `app/services/mcp_dispatch_reconciliation.py` terminalizes dispatched ambiguity; `tests/test_mcp_dispatch_reconciliation.py` covers timeout/crash cases and `tests/test_mcp_upstream_governed.py` covers ambiguous response replay. | Verified on covered paths; downstream effect remains unknown. |
| Successful governed invokes charge the wallet and emit signed receipts. | `app/routers/mcp.py` charges through `AgentMoney`, records audit, and creates receipts; `tests/test_demo_trust_plane.py` and `tests/test_agent_ops_war_room_demo.py` assert success receipts and replay behavior. | Verified. |
| Denied governed attempts are auditable and can produce denial receipts when a permit record exists. | `app/routers/mcp.py` creates denial receipts for invalid scoped attempts with an existing permit; strict-mode tests assert denial audit events. | Verified. |
| Receipts are signature-verifiable. | `app/services/receipts.py` signs and verifies receipt payloads; `tests/test_receipts.py` detects receipt tampering. | Verified. |
| A valid receipt proves the actual downstream effect. | `CONTEXT.md`, `WEDGE.md`, and receipt portability tests limit the claim to operator-signed gateway evidence. | Contradicted if claimed. |
| Receipt evidence is independently witnessed. | The service executes, signs, and publishes its own key material; no external witness or transparency log is in the supported path. | Not implemented. |
| Authority consumption is generalized across arbitrary action units. | Current permits reserve configured credits or call allowance; no general deployment/deletion/refund/effect-unit model exists. | Contradicted if claimed. |
| Wallet audit events are signed and hash-linked. | `app/services/audit_chain.py` signs audit events and verifies payload hash, previous hash, signature, and chain hash; `tests/test_audit_chain.py` detects tampering. | Verified. |
| Wallet keys can inspect only their own trust ledger records. | `app/routers/me.py`, `app/routers/receipts.py`, and `app/routers/audit.py` enforce wallet-scoped access; `tests/test_me_trust_ledger.py` covers cross-wallet exclusion. | Verified. |
| Payment settlement is production-ready. | `WEDGE.md` explicitly says not to claim production-ready payments or settlement. | Contradicted if claimed. |
| Ledger storage is compliance-grade. | `WEDGE.md` explicitly says not to claim compliance-grade ledger storage. | Contradicted if claimed. |
| Universal policy enforcement across every agent framework exists. | `WEDGE.md` explicitly says not to claim universal policy enforcement across every agent framework. | Contradicted if claimed. |

## How To Use These Sources

- Use AWI sources to explain proof surfaces, not the core wedge.
- Use MCP sources to justify why this repo sits at the tool boundary.
- Use wallet/payment sources to explain configured spend controls, while
  avoiding production settlement or generalized authority-unit claims.
- Use Macaroons and token literature to explain the authorization lineage of
  scoped permits without claiming compatibility.
- Use audit/evidence sources to explain an adjacent ecosystem, not to claim
  receipt-format ownership, independent witnessing, or customer demand.
- Use threat-model sources to keep prompt injection, protocol exploit, replay,
  confused deputy, unsafe tool execution, and cross-tenant leakage in scope.
- Use NIST as governance vocabulary, not as proof of certification or
  compliance.

## Current Evidence Slice

`GET /v1/receipts/{receipt_id}/evidence` answers one operator question:

> Given a receipt ID, can I verify the receipt signature, permit signature,
> audit-chain linkage, ledger linkage, and wallet-scoped access in one call?

This strengthens transaction-linked gateway evidence without proving the
downstream effect or turning the receipt format into the product wedge.
