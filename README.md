# Agent Middleware API

[![CI](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml)
[![Auto PR](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/auto-pr.yml/badge.svg?branch=master)](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml)

**The FastAPI control plane for agent-native infrastructure.**

**Agent Middleware API** is a production-ready FastAPI service that provides durable state, billing, telemetry, secure tool execution, IoT connectivity, and **AI-powered agent intelligence** for autonomous agents.

It lets agents:

* Send and receive structured messages
* Store persistent state
* Bill and track usage
* Emit telemetry and anomaly alerts
* Execute secure external actions
* **Make autonomous decisions with AI reasoning**
* **Self-heal by diagnosing and fixing issues**
* **Answer natural language queries**
* **Remember and learn from experiences**

Deploy in minutes via Docker or Railway.

---

## Architecture Overview

| Domain                   | Endpoint Prefix   | Durable | Rate Limited | Auth Required |
|--------------------------|-------------------|---------|--------------|---------------|
| Billing                  | `/v1/billing`     | Yes     | Yes          | Yes           |
| Stripe Webhooks          | `/webhooks/stripe`| -       | -            | Yes           |
| Telemetry                | `/v1/telemetry`   | Yes     | Yes          | Yes           |
| Comms                    | `/v1/comms`       | Yes     | Yes          | Yes           |
| IoT Bridge               | `/v1/iot`         | Optional| Yes          | Yes           |
| Security                 | `/v1/security`    | Partial | Yes          | Yes           |
| **Agent Intelligence**   | `/v1/ai`          | Yes     | Yes          | Yes           |

*(Additional modules include programmatic media, content factory, agent oracle, and protocol generation)*

---

## Quick Start (Local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Then open:
- `http://localhost:8000/docs`

---

## Example API Call

```bash
curl -X POST http://localhost:8000/v1/telemetry \
  -H "X-API-Key: test-key" \
  -H "Content-Type: application/json" \
  -d '{"event":"agent_started","agent_id":"demo"}'
```

---

## Billing & Payments (`/v1/billing`)

PostgreSQL-backed wallet system with ACID transactions, Stripe integration, and spend velocity monitoring.

### Wallet Operations

```bash
# Create a wallet
curl -X POST http://localhost:8000/v1/billing/wallets \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"wallet_id": "agent-001", "balance": 10000}'

# Add credits to a wallet
curl -X POST http://localhost:8000/v1/billing/wallets/agent-001/deposit \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"amount": 5000, "description": "Monthly allocation"}'

# Check wallet balance
curl http://localhost:8000/v1/billing/wallets/agent-001 \
  -H "X-API-Key: your-key"
```

### Stripe Fiat Ingestion

```bash
# Prepare a Stripe payment (returns client_secret)
curl -X POST http://localhost:8000/v1/billing/top-up/prepare \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"wallet_id": "agent-001", "amount": 5000}'

# Stripe webhooks are handled automatically at POST /webhooks/stripe
# Credits are allocated when payment_intent.succeeded events arrive
```

### Agent-to-Agent Transfers

```bash
# Transfer credits between wallets
curl -X POST http://localhost:8000/v1/billing/transfer \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "from_wallet_id": "agent-001",
    "to_wallet_id": "agent-002",
    "amount": 1000,
    "memo": "Payment for data processing"
  }'

# Create a child wallet with spend limits
curl -X POST http://localhost:8000/v1/billing/wallets \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "wallet_id": "task-agent-001",
    "parent_wallet_id": "agent-001",
    "max_spend": 500,
    "task_description": "Data indexing",
    "ttl_seconds": 3600
  }'
```

### Service Marketplace

```bash
# Register a service
curl -X POST http://localhost:8000/v1/billing/services \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "service_id": "data-indexer",
    "name": "Data Indexing Service",
    "description": "Fast vector indexing for documents",
    "price_per_call": 50,
    "provider_wallet_id": "provider-001"
  }'

# List available services
curl http://localhost:8000/v1/billing/services \
  -H "X-API-Key: your-key"

# Invoke a service
curl -X POST http://localhost:8000/v1/billing/services/data-indexer/invoke \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"caller_wallet_id": "agent-001", "input_data": {"documents": [...]}}'
```

### Spend Velocity Monitoring

Wallets are automatically frozen if spending exceeds thresholds.

```bash
# Check velocity status
curl http://localhost:8000/v1/billing/wallets/agent-001/velocity \
  -H "X-API-Key: your-key"

# Unfreeze a frozen wallet
curl -X POST http://localhost:8000/v1/billing/wallets/agent-001/unfreeze \
  -H "X-API-Key: your-key"
```

### Configure Stripe & Notifications

```bash
# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PUBLISHABLE_KEY=pk_test_...

# Email alerts (Resend)
RESEND_API_KEY=re_...
ALERT_FROM_EMAIL=alerts@b2a.dev

# Slack notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/...

# Velocity limits (credits)
VELOCITY_HOURLY_LIMIT=1000.0
VELOCITY_DAILY_LIMIT=10000.0
VELOCITY_FREEZE_THRESHOLD=3
```

---

## AI Agent Intelligence (`/v1/ai`)

Powered by LLM integration (OpenAI, Azure OpenAI, Anthropic, Ollama), agents can:

### Autonomous Decision-Making
```bash
curl -X POST http://localhost:8000/v1/ai/decide \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent-001",
    "context": {"tasks": ["process_data", "send_report"], "load": 0.8},
    "options": ["process_data", "send_report", "wait"]
  }'
```

### Self-Healing
```bash
curl -X POST http://localhost:8000/v1/ai/heal \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "issue": "Service returning 500 errors",
    "context": {"error_log": "Connection refused to database"}
  }'
```

### Natural Language Queries
```bash
curl -X POST http://localhost:8000/v1/ai/query \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the current system health?"}'
```

### Agent Memory & Learning
```bash
# Store a memory
curl -X POST http://localhost:8000/v1/ai/memory \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "agent-001", "key": "preference", "value": "dark_mode"}'

# Learn from experience
curl -X POST http://localhost:8000/v1/ai/learn \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "agent-001", "experience": {"action": "retry", "outcome": "success"}}'
```

### Configure LLM Provider

```bash
# OpenAI
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o

# Azure OpenAI
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=gpt-4o

# Ollama (local)
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
```

---

## Python SDK (`b2a-sdk`)

Agents can integrate using the `b2a-sdk` package for automatic usage tracking and billing.

```bash
cd b2a_sdk && pip install -e .
```

```python
from b2a_sdk import B2AClient, monitored, billable, combined

client = B2AClient(
    api_url="http://localhost:8000",
    api_key="your-key",
    wallet_id="agent-001"
)

# Track function usage
@monitored(event_name="data_processing")
def process_data(data: list):
    return [x * 2 for x in data]

# Auto-deduct credits per call
@billable(amount=10)
def call_llm(prompt: str):
    return f"Response to: {prompt}"

# Chain operations with combined billing
@combined(total_amount=100, step_amount=25)
async def complex_task():
    step1 = await client.emit_telemetry(...)
    step2 = await client.get_balance(...)
    return step1 + step2
```

See [`b2a_sdk/README.md`](./b2a_sdk/README.md) for full documentation.

---

## MCP Server (`/mcp`)

Model Context Protocol (MCP) enables agents to discover and call your billable services. Tools are automatically exposed with their schemas and pricing.

### Discover Available Tools

```bash
# Fetch MCP tools manifest
curl http://localhost:8000/mcp/tools.json

# List tools via CLI
cd b2a_sdk && pip install -e . && python -m b2a_sdk.mcp list
```

### Call Tools via JSON-RPC

```bash
# List tools
curl -X POST http://localhost:8000/mcp/messages \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'

# Call a tool
curl -X POST http://localhost:8000/mcp/messages \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "my-service",
      "arguments": {"input": "value"},
      "mcpContext": {"wallet_id": "agent-001"}
    },
    "id": 2
  }'
```

### Create MCP Tools with `@mcp_tool`

```python
from b2a_sdk.decorators import mcp_tool

@mcp_tool(
    service_id="video-generator",
    name="Video Generator",
    description="Generate videos from URLs",
    category="content_factory",
    credits_per_unit=50.0,
    unit_name="video",
)
async def generate_video(url: str, style: str = "cinematic") -> dict:
    """Your tool implementation here."""
    return {"video_url": f"{url}.mp4"}
```

### Generate Standalone MCP Server

```bash
# Generate a standalone Python MCP server
cd b2a_sdk && pip install -e . && pip install mcp httpx
python -m b2a_sdk.mcp standalone --output my_server.py

# Run it
export B2A_API_KEY=your-key
export B2A_WALLET_ID=your-wallet
python my_server.py
```

---

## Deployment (Railway + PostgreSQL)

This repository is deployment-ready for Railway via `Dockerfile` + `railway.json`.

### 1. Create Services

1. Create a Railway project from this repository.
2. Add a PostgreSQL database:
   - Dashboard → + New → Database → PostgreSQL
   - Or CLI: `railway add -n agent-middleware-db`
3. Link the database to your app in the Railway dashboard.

### 2. Deploy via CLI

```bash
railway login
railway init
railway up
```

### 3. Configure Environment Variables

Set these in Railway dashboard or via CLI:

```bash
railway variables set DEBUG=false
railway variables set VALID_API_KEYS=your-key-here,your-other-key
railway variables set STATE_BACKEND=postgres
railway variables set RATE_LIMIT_PER_MINUTE=120
railway variables set CORS_ORIGINS=https://your-app.com

# Stripe (optional - for fiat top-ups)
railway variables set STRIPE_SECRET_KEY=sk_live_...
railway variables set STRIPE_WEBHOOK_SECRET=whsec_...

# Velocity monitoring (optional)
railway variables set VELOCITY_HOURLY_LIMIT=1000.0
railway variables set VELOCITY_DAILY_LIMIT=10000.0
railway variables set VELOCITY_FREEZE_THRESHOLD=3
```

> **Note:** `DATABASE_URL` is automatically injected when you link the PostgreSQL database.

### 4. Verify Deployment

- `GET /health` returns `200`
- `GET /health/dependencies` reports healthy state backend
- `GET /docs` loads OpenAPI UI

### PostgreSQL Connection String

Railway automatically provides `DATABASE_URL` when you add the PostgreSQL addon. To get it manually:

```bash
railway variables get DATABASE_URL
```

---

## Security Model

- API-key based authentication for protected endpoints
- Per-key rate limiting (Redis-backed)
- Durable audit logging (Postgres)
- Configurable CORS (via `CORS_ORIGINS` env var)
- Red-team endpoints (`/v1/security`, `/v1/rtaas`) for adversarial testing
- Memory fallback disabled in production by default

> **Note:** This is not multi-tenant hardened unless deployed with isolated namespaces and database separation.

---

## Durability Model

- **PostgreSQL:** preferred durable state backend for runtime stores.
- **Redis:** distributed rate limiting and backend fallback state store.
- **Memory:** automatic fallback when no persistent backend is configured.

> ⚠ **In production, set `STATE_BACKEND=postgres` to avoid non-durable operation.**

Current durable service stores:
- Billing (`wallets`, `ledger`, `alerts`, `velocity_snapshots`, `services`)
- Comms (`agent registry`, `inbox`, `outbox`)
- Telemetry (`events`, `anomalies`)

---

## Roadmap

- [x] PostgreSQL ledger with ACID transactions
- [x] Stripe fiat ingestion with webhooks
- [x] Agent-to-agent transfers with child wallets
- [x] Service marketplace
- [x] Spend velocity monitoring with auto-freeze
- [x] Python SDK (`b2a-sdk`)
- [x] MCP Server Generator for agent tool exposure
- [ ] Stripe Identity (KYC) for sponsor verification
- [ ] Sandbox engine wired to billing
- [ ] Automated API key rotation for wallets
- [ ] Add comprehensive agent interaction examples and recipes
- [ ] Multi-tenant hardening validations
- [ ] Add SQLite backend support for simpler edge deployments

---

## API Discovery Endpoints

- `GET /`
- `GET /openapi.json`
- `GET /llm.txt`
- `GET /.well-known/agent.json`

---

## Configuration & Development

Use `.env.example` as local template and `.env.production` as production reference.

**Run tests:**
```bash
# API tests
pytest -q

# SDK tests
cd b2a_sdk && pip install -e ".[dev]" && pytest -q
```
*(CI runs on Python 3.11 and 3.12 via GitHub Actions)*

---

## Security & Contributing

Report vulnerabilities using `/SECURITY.md`.
Please read `/CONTRIBUTING.md` before opening pull requests.

## License

MIT License. See `/LICENSE`.
