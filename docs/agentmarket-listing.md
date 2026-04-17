# AgentMarket.cloud Listing - Technical Specifications

## Product Overview

**Name:** Agent Middleware API
**Category:** Agent Infrastructure / Control Plane
**Pricing Model:** Open Source (Self-hosted) + Enterprise tiers available
**Website:** https://github.com/PetrefiedThunder/agent-middleware-api

---

## Core Capabilities

### MCP Server (Model Context Protocol)
Dynamic MCP server that exposes billable services as discoverable tools.

| Capability | Description |
|------------|-------------|
| Auto-discovery | `GET /mcp/tools.json` returns machine-readable tool manifest |
| JSON-RPC 2.0 | Full MCP protocol support via `POST /mcp/messages` |
| Pagination | `limit`/`offset` query params prevent large payload issues |
| Tool Generator | `python -m b2a_sdk.mcp standalone` creates standalone servers |
| Context Passing | `mcpContext.wallet_id` for billing attribution |

### Agentic Web Interface (AWI)
Based on arXiv:2506.10953v1 - "Build the web for agents, not agents for the web"

| Capability | Description |
|------------|-------------|
| Stateful Sessions | `POST /v1/awi/sessions` with configurable TTL |
| 13 Unified Actions | search_and_sort, add_to_cart, fill_form, login, navigate_to, etc. |
| Progressive Representations | summary, embedding, low-res, full_res, structured |
| DOM Bridge | Bidirectional Playwright integration for real browser control |
| Task Queues | Priority queuing with concurrency limits |
| Human Pause/Steer | `/v1/awi/intervene` for human oversight |

---

## API Endpoints

### Discovery (for autonomous agents)
```
GET /mcp/tools.json           - MCP tool manifest
GET /.well-known/agent.json   - Agent capability manifest
GET /llm.txt                 - LLM-readable documentation
GET /v1/discover              - Full discovery manifest
```

### Billing & Payments
```
POST /v1/billing/wallets                    - Create wallet
GET  /v1/billing/wallets/{id}               - Get balance
POST /v1/billing/wallets/{id}/deposit        - Add credits
POST /v1/billing/transfer                   - A2A transfer
POST /v1/billing/top-up/prepare             - Stripe payment
POST /v1/billing/dry-run/session            - Sandbox simulation
POST /v1/api-keys                           - Create API key
POST /v1/api-keys/rotate                    - Rotate key
```

### AI Agent Intelligence
```
POST /v1/ai/decide                          - LLM-powered decision
POST /v1/ai/heal                            - Self-healing diagnosis
POST /v1/ai/query                           - Natural language query
POST /v1/ai/memory                          - Store memory
POST /v1/ai/learn                           - Learn from experience
```

### AWI Web Control
```
POST /v1/awi/sessions                       - Create session
POST /v1/awi/execute                        - Execute action
POST /v1/awi/represent                      - Get representation
POST /v1/awi/intervene                      - Human pause/steer
GET  /v1/awi/queue/status                   - Queue status
GET  /v1/awi/vocabulary                    - Action vocabulary
```

### Sandbox & Testing
```
POST /v1/sandbox/environments               - Create sandbox
POST /v1/sandbox/execute                   - Execute in sandbox
GET  /v1/sandbox/metrics/{id}              - Sandbox metrics
DELETE /v1/sandbox/environments/{id}        - Cleanup
```

### Telemetry & Monitoring
```
POST /v1/telemetry                          - Emit event
GET  /v1/telemetry/stats/{agent_id}        - Agent stats
GET  /health                                - Liveness
GET  /health/ready                         - Readiness (deps check)
```

---

## MCP Tools (Auto-Exposed)

When you register services, they automatically appear in:

```bash
curl http://localhost:8000/mcp/tools.json
```

Example response:
```json
{
  "tools": [
    {
      "name": "data-indexer",
      "description": "Fast vector indexing for documents",
      "inputSchema": {
        "type": "object",
        "properties": {
          "documents": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["documents"]
      },
      "credits_per_call": 50,
      "category": "indexing"
    }
  ]
}
```

---

## Framework Integrations

### LangChain
```python
from langchain_b2a import B2AClient, get_langgraph_tools
client = B2AClient(api_key="...", wallet_id="...")
tools = get_langgraph_tools(client)
agent = create_react_agent(model, tools)
```

### CrewAI
```python
from crewai_b2a import CrewAIB2ATool
b2a_tool = CrewAIB2ATool(api_key="...", wallet_id="...")
agent = Agent(role="...", tools=[b2a_tool])
```

### AutoGen
```python
from autogen_b2a import B2AFunctionTool
tool = B2AFunctionTool(api_key="...", wallet_id="...")
agent.register_function(tool.get_function_schemas())
```

---

## Deployment Options

| Option | Command |
|--------|---------|
| Docker | `docker run -p 8000:8000 ghcr.io/petrefiedthunder/agent-middleware-api:latest` |
| Railway | `railway up` (one-click deploy) |
| Python | `pip install agent-middleware-api && uvicorn app.main:app` |

### Required Environment Variables
```
VALID_API_KEYS=key1,key2        # Comma-separated API keys
STATE_BACKEND=postgres          # postgres, redis, or sqlite
DATABASE_URL=...                # PostgreSQL connection (if using postgres)
```

### Optional Variables
```
STRIPE_SECRET_KEY=...           # Fiat top-ups
REDIS_URL=...                   # Rate limiting
LLM_PROVIDER=openai            # openai, azure, anthropic, ollama
```

---

## Security Features

- API-key authentication
- Per-key rate limiting (Redis-backed)
- Spend velocity monitoring with auto-freeze
- WebAuthn/passkey for high-risk actions
- KYC verification for sponsor wallets
- Graceful shutdown with connection drain

---

## Observability

- Structured JSON logging (structlog)
- Health endpoints for orchestration
- `/health/ready` checks DB, Redis, MQTT status
- Circuit breaker on LLM calls
- Retry with exponential backoff

---

## Technical Specifications

| Spec | Value |
|------|-------|
| Language | Python 3.11+ |
| Framework | FastAPI 0.115+ |
| State | PostgreSQL (preferred), Redis, SQLite |
| Auth | API Key |
| Protocol | REST + MCP JSON-RPC 2.0 |
| License | Apache 2.0 |
| Docker | Multi-stage, ~200MB |
| Health Check | `/health`, `/health/ready` |

---

## Support & Documentation

- **Docs:** https://github.com/PetrefiedThunder/agent-middleware-api#readme
- **API Reference:** `http://localhost:8000/docs` (Swagger UI)
- **OpenAPI:** `http://localhost:8000/openapi.json`
- **Issues:** https://github.com/PetrefiedThunder/agent-middleware-api/issues
