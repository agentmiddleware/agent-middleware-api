# AgentMarket.cloud Submission

> **Status: paused during customer validation.** This draft must not be
> submitted until one named partner-owned consequential action passes the
> acceptance test in [`30-day-customer-validation.md`](30-day-customer-validation.md).

## Listing Information

**Service Name:** Agent Middleware API
**Category:** Transaction integrity for consequential autonomous actions
**Pricing:** Design-partner pilot; no public SLA or commercial tier is committed

## Listing Content

```markdown
# Agent Middleware API

**Make consequential agent actions transactional.**

Agent Middleware API binds one consequential, retry-sensitive MCP action to
scoped authority, configured consumption, at most one gateway dispatch and
debit, explicit delivery uncertainty, and linked gateway evidence.

Canonical loop: `logical action -> authorize -> reserve allowance -> debit -> claim dispatch -> confirmed outcome | delivery_uncertain -> receipt/audit -> reconcile`.

## Capabilities

- **Scoped authority** — signed permits bind wallet, key, tool, configured credits, and expiry
- **Logical action** — accepted key binds the payload; changed input fails closed
- **One-shot dispatch** — at most one gateway dispatch and debit per logical action
- **Remote MCP dispatch** — one operator-configured HTTPS Streamable HTTP tool
- **Explicit uncertainty** — ambiguous post-dispatch failures are charged,
  signed as `delivery_uncertain`, and never automatically redispatched
- **Linked evidence** — receipts link permit, ledger, dispatch state, and audit
  where applicable; they do not prove the downstream effect

AWI, browser, RAG, sandbox, telemetry, and orchestration code in the repository
is disabled proof-surface scaffolding, not part of this listing.

## Quick Start

```python
from b2a_sdk import AgentMiddlewareClient, PermitRequest

client = AgentMiddlewareClient(
    base_url="https://api.thisisatest.tech",
    api_key="your-api-key",
)

permit = await client.create_permit(
    PermitRequest(...),
    idempotency_key="permit-01",
)
result = await client.invoke_tool(
    "partner.tool",
    {"input": "value"},
    wallet_id="wallet-id",
    permit_id=permit.permit_id,
    idempotency_key="invoke-01",
)
```

## Pricing

No public pricing, free-credit grant, uptime SLA, or compliance commitment is
currently offered. This submission describes a controlled design-partner
pilot.

## Documentation

- [API Reference](https://api.thisisatest.tech/docs)
- [OpenAPI Spec](https://api.thisisatest.tech/openapi.json)
- [LLM Docs](https://api.thisisatest.tech/llm.txt)
- [Security limitations](https://github.com/PetrefiedThunder/agent-middleware-api/blob/main/SECURITY_LIMITATIONS.md)
- [Design-partner guide](https://github.com/PetrefiedThunder/agent-middleware-api/blob/main/DESIGN_PARTNER_GUIDE.md)

## Repository

https://github.com/PetrefiedThunder/agent-middleware-api

## Demo

No public production demo or SLA is promised by this document.
```

## Submission URLs

- AgentMarket.cloud: https://agentmarket.cloud/submit (submit listing)
- MCP Registry: via `server.json` + `mcp-publisher`, gated — see
  [`mcp-registry-submission.md`](mcp-registry-submission.md); there is no
  form-based registration URL
- Smithery.ai: https://smithery.ai (MCP tools registry)

## Tags

```
transaction-integrity, consequential-actions, delivery-uncertainty,
idempotency, mcp, autonomous-agents
```

## Contact

- GitHub Issues: https://github.com/PetrefiedThunder/agent-middleware-api/issues
- Public operator email: intentionally omitted until a monitored address and
  accountable identity pass the launch contact gate. Do not submit this listing
  before those values are configured.
```
