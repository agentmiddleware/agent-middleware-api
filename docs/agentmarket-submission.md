# AgentMarket.cloud Submission

> **Status: pre-publication draft — do not submit.** The listing requires a
> monitored public contact and a live, enabled standard MCP endpoint that has
> passed the registry preflight. See
> [MCP Registry Submission](mcp-registry-submission.md).

## Listing Information

**Service Name:** Agent Middleware API
**Category:** MCP authorization and metering infrastructure
**Pricing:** Design-partner pilot; no public SLA or commercial tier is committed

## Listing Content

```markdown
# Agent Middleware API

**MCP authorization gateway for agent-to-tool actions.**

Agent Middleware API authorizes one configured upstream MCP tool under a
wallet-scoped permit. One accepted idempotency key permits at most one gateway
dispatch and wallet debit; signed receipts and audit evidence record the
terminal gateway outcome.

Canonical loop: `discover -> authenticate -> authorize -> invoke -> meter -> receipt -> audit -> govern`.

## Capabilities

- **Scoped authority** — signed permits bind wallet, key, tool, budget, and expiry
- **Replay-safe metering** — at most one gateway debit and dispatch per accepted idempotency key
- **Remote MCP dispatch** — one operator-configured HTTPS Streamable HTTP tool
- **Signed evidence** — receipts link permit, ledger, dispatch state, and audit
- **Explicit uncertainty** — ambiguous post-dispatch failures are signed and not retried

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
- [Security limitations](https://api.thisisatest.tech/SECURITY_LIMITATIONS.md)
- [Design-partner guide](https://api.thisisatest.tech/DESIGN_PARTNER_GUIDE.md)

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
mcp, model-context-protocol, mcp-gateway, agent-authorization,
idempotency, replay-protection, usage-metering, signed-receipts,
agent-governance
```

## Contact

- GitHub Issues: https://github.com/PetrefiedThunder/agent-middleware-api/issues
- Public operator email: intentionally omitted until a monitored address and
  accountable identity pass the launch contact gate. Do not submit this listing
  before those values are configured.
