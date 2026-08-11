# AgentMarket.cloud Submission

## Listing Information

**Service Name:** Agent-Native Middleware API
**Category:** MCP authorization and metering infrastructure
**Pricing:** Design-partner pilot; no public SLA or commercial tier is committed

## Listing Content

```markdown
# Agent-Native Middleware API

**Governed control point for autonomous agent tool calls.**

Agent Middleware API authorizes, meters, dispatches, receipts, and audits one
MCP tool call under a wallet-scoped permit.

Canonical loop: `discover -> authenticate -> authorize -> meter -> dispatch -> receipt -> audit -> govern`.

## Capabilities

- **Scoped authority** — signed permits bind wallet, key, tool, budget, and expiry
- **Replay-safe metering** — one gateway debit and dispatch per idempotency key
- **Remote MCP dispatch** — one operator-configured HTTPS Streamable HTTP tool
- **Signed evidence** — receipts link permit, ledger, dispatch state, and audit
- **Explicit uncertainty** — ambiguous post-dispatch failures are signed and not retried

AWI, browser, RAG, sandbox, telemetry, and orchestration code in the repository
is disabled proof-surface scaffolding, not part of this listing.

## Quick Start

```python
from b2a_sdk import AgentMiddlewareClient, PermitRequest

client = AgentMiddlewareClient(
    base_url="https://api.agent-middleware.dev",
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

- [API Reference](https://api.agent-middleware.dev/docs)
- [OpenAPI Spec](https://api.agent-middleware.dev/openapi.json)
- [LLM Docs](https://api.agent-middleware.dev/llm.txt)
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
agent-platform, mcp, awi, billing, telemetry, ai-agents,
langgraph, crewai, autogen, llamaindex, web-automation,
agentic-webs, autonomous-agents, b2a
```

## Contact

- GitHub Issues: https://github.com/PetrefiedThunder/agent-middleware-api/issues
- Email: api@b2a.dev (placeholder)
```
