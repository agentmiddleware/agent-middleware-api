# Agent Middleware API — MCP / AgentMarket Listing (honest wedge)

**Status:** Submission paused during customer validation. This is bounded draft
copy, not evidence of listing approval, market demand, or a live partner. Do not
pitch AWI, RAG, sandbox, oracle, telemetry, or media as the product.

---

## Value Proposition / Tagline

**"Make consequential agent actions transactional."**

Credible wedge: transaction integrity for one consequential, autonomous,
retry-sensitive action. One logical action binds scoped authority and configured
consumption to at most one gateway dispatch and debit, explicit
`delivery_uncertain` that is never automatically redispatched, and linked
gateway evidence. Remote side effects are
exactly once only when the upstream independently honors the forwarded
idempotency key.

Canonical loop:

```text
logical action → authorize → reserve allowance → debit → claim dispatch
→ confirmed outcome | delivery_uncertain → receipt/audit → reconcile
```

Not a full agent middleware platform.

---

## Target Audience

- Platform / AI infra / security teams with consequential autonomous writes
- Teams that currently keep an action read-only or human-gated because
  duplicate or ambiguous execution matters
- Design partners who can bring **one** retry-sensitive staging mutation, an
  authoritative effect lookup, and an engineer

Not yet a fit for: production settlement, compliance-grade ledger, universal
IAM replacement, or broad agent-framework governance.

---

## Competitive Differentiation

- Stable logical-action identity with changed-input conflict
- One-shot gateway dispatch/debit and explicit `delivery_uncertain`
- Bounded configured authority consumption linked to execution-time evidence
- Signed receipts and wallet-scoped audit chains as supporting evidence
- Self-hostable; proof surfaces (AWI/RAG/sandbox/etc.) stay labeled and off
  by default (`ENABLE_PROOF_SURFACES=false`)

---

## Product Overview

| Field | Value |
|-------|--------|
| Name | Agent Middleware API |
| Category | Transaction integrity for consequential autonomous actions |
| Product | Durable logical-action, dispatch, debit, and uncertainty state |
| Mechanism | Authority → logical action → one dispatch → outcome/uncertainty → evidence |
| Pricing | Controlled design-partner pilot; no public tier or SLA committed |
| Repo | https://github.com/PetrefiedThunder/agent-middleware-api |

---

## Core Capabilities (product)

| Capability | Discovery |
|------------|-----------|
| MCP tools manifest | `GET /mcp/tools.json` |
| Governed invoke | `POST /mcp/messages` (permit + metering + receipt) |
| Permits | `/v1/permits` |
| Receipts / evidence | `/v1/receipts`, `/v1/evidence` |
| Wallet metering | `/v1/billing` |
| Audit chain | `/v1/audit` |
| Agent bootstrap | `/.well-known/agent.json`, `/llm.txt`, `/WEDGE.md` |

Dogfood (local): `make dogfood-trust-plane` registers `partner.notes.write`.
Live Railway lists ops-registered tools only (empty until a real tool is
registered).

---

## Explicitly Not Product (proof surfaces)

Do **not** list these as marketplace features in registry copy:

- AWI / Playwright DOM / passkey / RAG memory
- Telemetry auto-PR, agent comms, AI decide/heal
- Oracle crawls, media factory, IoT bridges, red-team / RTaaS, sandboxes

See [`WEDGE.md`](../WEDGE.md) and [`SECURITY_LIMITATIONS.md`](../SECURITY_LIMITATIONS.md).

---

## Support

- GitHub Issues on this repository
- Design-partner path: [`DESIGN_PARTNER_GUIDE.md`](../DESIGN_PARTNER_GUIDE.md)
- Remaining deploy/docs debt: [`docs/tech-debt-remediation-plan.md`](tech-debt-remediation-plan.md)

---

## Registry submission checklist

- [ ] Tools list matches live `/mcp/tools.json` (no stub marketplace names)
- [ ] Description matches wedge one-liner above
- [ ] Links resolve: `/WEDGE.md`, `/SECURITY_LIMITATIONS.md`, `/llm.txt`
- [ ] `ENABLE_PROOF_SURFACES=false` called out for production-like deploys
- [ ] Optional submit **after** Phase 2 live honesty (tools gate) is verified
