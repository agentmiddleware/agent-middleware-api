# AgentMarket.cloud Submission

## Listing Information

**Service Name:** Agent-Native Middleware API
**Category:** Infrastructure / Agent Platform
**Pricing:** Free tier (1000 credits/month) + Pay-as-you-go

## Listing Content

```markdown
# Agent-Native Middleware API

**Operational control plane for autonomous agents.**

Agent Middleware API provides identity, billing, discovery, policy, and execution governance for machine-native software tenants.

Canonical loop: `discover -> authenticate -> invoke -> meter -> govern`.

## Capabilities

### Core Infrastructure
- **Identity & Authority** — Wallet-scoped agents, delegated credentials, API-key rotation, KYC hooks
- **Discovery & Negotiation** — MCP, `.well-known/agent.json`, `llm.txt`, OpenAPI, `/v1/discover`
- **Execution Governance** — Tool invocation, planner constraints, service health, simulation state
- **Economics** — Dry-run pricing, spend limits, ledgering, Stripe integration
- **Governance** — Telemetry, audit surfaces, readiness, security posture

### Protocol Support
- **MCP (Model Context Protocol)** — Native tool discovery and execution
- **AWI Standard** — Proof-of-usefulness surface for standardized web automation
- **REST API** — Full REST API for all services

### Proof Surfaces
- **AWI (Agentic Web Interface)** — Web automation without DOM fighting, human pause/steer
- **Agent Communication** — Agent-to-agent messaging, swarm coordination
- **AI Decision Making** — Autonomous decisions, self-healing, natural language queries, memory
- **Sandboxing** — Dry-run and bounded execution environments

### Framework Integrations
- LangGraph ✓
- CrewAI ✓
- AutoGen ✓
- LlamaIndex ✓

## Quick Start

```python
from agent_middleware import B2AClient

client = B2AClient(
    api_url="https://api.agent-middleware.dev",
    api_key="your-api-key",
    wallet_id="your-wallet-id"
)

# Check balance
balance = await client.get_balance()

# Emit telemetry
await client.emit_telemetry("task_completed", {"task": "data_processing"})

# Make AI decision
decision = await client.decide(
    context={"options": ["proceed", "wait", "abort"]},
    options=["proceed", "wait", "abort"]
)
```

## Pricing

| Tier | Price | Credits | Features |
|------|-------|---------|----------|
| Free | $0 | 1000/month | Basic telemetry, messaging |
| Pro | $10/mo | Unlimited | AI decisions, AWI, priority support |
| Enterprise | Custom | Unlimited | Multi-tenant, SLA, dedicated support |

## Documentation

- [API Reference](https://api.agent-middleware.dev/docs)
- [OpenAPI Spec](https://api.agent-middleware.dev/openapi.json)
- [LLM Docs](https://api.agent-middleware.dev/llm.txt)
- [AWI Adoption Guide](https://github.com/PetrefiedThunder/agent-middleware-api/blob/master/docs/awi-adoption-guide.md)
- [Agent Recipes](https://github.com/PetrefiedThunder/agent-middleware-api/blob/master/docs/agent-recipes.md)

## Repository

https://github.com/PetrefiedThunder/agent-middleware-api

## Demo

Public demo instance: https://api.agent-middleware.dev
```

## Submission URLs

- AgentMarket.cloud: https://agentmarket.cloud/submit (submit listing)
- MCP Registry: https://modelcontextprotocol.io/registry (register MCP server)
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
