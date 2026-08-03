# Agent Middleware API — MCP / AgentMarket Listing (honest wedge)

**Status:** Freeze this copy for registry submissions until the trust-plane
loop is the only advertised product. Do not pitch AWI, RAG, sandbox, oracle,
telemetry, or media as the product.

---

## Value Proposition / Tagline

**"Authorize one agent action. Charge it once. Prove what happened."**

Credible wedge: exactly-once permits and receipts for metered MCP calls.

Canonical loop:

```text
discover → authenticate → authorize → invoke → meter → receipt → audit → govern
```

Not a full agent middleware platform.

---

## Target Audience

- Platform / AI infra teams with internal agents calling MCP-style tools
- Teams that need wallet budgets, scoped permits, replay-safe retries, and
  signed receipts before tools run
- Design partners who can bring **one** real internal tool to the proxy

Not yet a fit for: production settlement, compliance-grade ledger, universal
IAM replacement, or broad agent-framework governance.

---

## Competitive Differentiation

- Closed-loop credit + delegated authority for internal agent tool calls
- Scoped signed permits with economic idempotency (retry ≠ double charge)
- Signed receipts + wallet-scoped audit chain on governed MCP invoke
- Self-hostable; proof surfaces (AWI/RAG/sandbox/etc.) stay labeled and off
  by default (`ENABLE_PROOF_SURFACES=false`)

---

## Product Overview

| Field | Value |
|-------|--------|
| Name | Agent Middleware API |
| Category | MCP trust plane / governed tool metering |
| Product | Exactly-once permits + receipts for metered MCP |
| Mechanism | Permit → governed invoke → wallet charge → receipt → audit |
| Pricing | Self-hosted open source; design-partner / enterprise by arrangement |
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
