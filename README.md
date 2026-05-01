# Agent Middleware API

[![CI](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml)
[![Auto PR](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/auto-pr.yml/badge.svg?branch=master)](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml)
![Version](https://img.shields.io/badge/Version-v1.1.0-blue)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green)
![License](https://img.shields.io/badge/License-Apache%202.0-blue)
![Tests](https://img.shields.io/badge/Tests-517%20passing-brightgreen)
![MCP](https://img.shields.io/badge/MCP-Native-orange)
![AWI](https://img.shields.io/badge/AWI-v1.0- purple)
![Docker](https://img.shields.io/badge/Docker-Ready-blue)
![Stars](https://img.shields.io/github/stars/PetrefiedThunder/agent-middleware-api?style=social)

> **Production beta — agent-discoverable, not production complete.** Built on arXiv:2506.10953v1.

**The FastAPI control plane for agent-native infrastructure — MCP + AWI powered.**

### Current Implementation Status

This repository is a production-beta control plane, not a finished production
platform. The wallet/key auth path, billing ledger, MCP discovery, health checks,
golden-path flow, and core API contracts are executable and tested. Several
larger product pillars intentionally default to simulation mode and return
synthetic data until their real integrations land:

- agent oracle
- red-team swarm
- RTaaS
- media engine
- IoT bridge
- autonomous telemetry PM
- agent comms
- content factory

Agents and operators should inspect `GET /health/dependencies` and the
`SIMULATION_MODE_*` environment flags before assuming an endpoint performs real
external work. Public arbitrary Python execution is disabled by default. Set
`BEHAVIORAL_SANDBOX_PYTHON_BACKEND=docker` to run Python in an unprivileged
Docker container; `ALLOW_UNSAFE_HOST_PYTHON_SANDBOX=true` is a
local-development escape hatch and is not a production sandbox.

### For Autonomous Agents

Agents can immediately discover and use this platform:

```bash
# Auto-discover MCP tools
curl http://localhost:8000/mcp/tools.json

# Auto-discover agent capabilities
curl http://localhost:8000/.well-known/agent.json

# Auto-read documentation
curl http://localhost:8000/llm.txt
```

### For Framework Developers

```python
# LangChain
from agent_middleware import B2AClient, get_langgraph_tools
client = B2AClient(api_key="...", wallet_id="...")
tools = get_langgraph_tools(client)

# CrewAI
from agent_middleware import CrewAIB2ATool
crewai_tools = [CrewAIB2ATool(api_key="...", wallet_id="...")]
```

**Agent Middleware API** is a FastAPI production-beta service that provides
agent-discoverable contracts for durable state, wallet-scoped billing,
telemetry, sandboxed tool workflows, IoT connectivity, and agent intelligence.
Some domains are implemented as simulations until their production integrations
are wired up.

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
* **Control real web browsers with semantic actions**
* **Use passkey authentication for high-risk operations**
* **Search past sessions semantically**

**Deploy in minutes via Docker or Railway.**

Deploy in minutes via Docker or Railway.

### Production Beta Docs

- [Production beta roadmap](docs/production-beta-roadmap.md)
- [Threat model](docs/threat-model.md)
- [Golden-path wallet-scoped agent flow](docs/golden-path.md)

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
| **Agentic Web Interface** | `/v1/awi`         | Yes     | Yes          | Yes           |
| **Behavioral Sandbox**    | `/v1/sandbox`     | Yes     | Yes          | Yes           |

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

## 🚀 Get Started in 5 Minutes (Agents & Developers)

### Option 1: Docker (Recommended)

```bash
docker run -p 8000:8000 \
  -e VALID_API_KEYS=your-api-key \
  -e STATE_BACKEND=sqlite \
  ghcr.io/petrefiedthunder/agent-middleware-api:latest
```

### Option 2: Python

```bash
pip install agent-middleware-api
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Option 3: One-Line Agent Test

```bash
# Test MCP tool discovery (for autonomous agents)
curl http://localhost:8000/mcp/tools.json | jq '.tools[0]'

# Test AWI session creation
curl -X POST http://localhost:8000/v1/awi/sessions \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://example.com", "max_steps": 10}'
```

### For Autonomous Agents

Agents can auto-discover this platform at:
- `GET /mcp/tools.json` — MCP tool manifest
- `GET /.well-known/agent.json` — Agent capability manifest
- `GET /llm.txt` — LLM-readable documentation

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

### KYC Identity Verification (`/v1/kyc`)

Require identity verification for sponsor wallets before allowing fiat top-ups.

```bash
# Create sponsor wallet with KYC required
curl -X POST http://localhost:8000/v1/billing/wallets/sponsor \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "sponsor_name": "Acme Corp",
    "email": "billing@acme.com",
    "initial_credits": 10000,
    "require_kyc": true
  }'

# Check KYC status
curl http://localhost:8000/v1/kyc/status/{wallet_id} \
  -H "X-API-Key: your-key"

# Create Stripe Identity verification session
curl -X POST http://localhost:8000/v1/kyc/sessions \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "wallet_id": "{wallet_id}",
    "return_url": "https://yourapp.com/kyc-callback",
    "document_type": "passport"
  }'
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

### API Key Management (`/v1/api-keys`)

Secure API key rotation for wallet authentication.

```bash
# Create a new API key
curl -X POST http://localhost:8000/v1/api-keys \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"wallet_id": "agent-001", "key_name": "production"}'

# List API keys for a wallet
curl http://localhost:8000/v1/api-keys/agent-001 \
  -H "X-API-Key: your-key"

# Rotate an API key
curl -X POST http://localhost:8000/v1/api-keys/rotate \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"wallet_id": "agent-001", "key_id": "key_abc123", "revoke_old": true}'

# Emergency revocation (compromised wallet)
curl -X POST http://localhost:8000/v1/api-keys/emergency-revoke \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"wallet_id": "agent-001", "reason": "security_incident"}'

# Get rotation audit logs
curl http://localhost:8000/v1/api-keys/agent-001/logs \
  -H "X-API-Key: your-key"
```
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

# KYC Verification
KYC_REQUIRED_FOR_TOPUP=false  # Set to true to enforce KYC before fiat top-ups
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

## Safe Exploration (Dry-Run Sandbox)

Agents can safely test billing operations without affecting real wallet balances or triggering velocity monitoring.

### Session-Based Simulation

```python
from b2a_sdk import B2AClient
from b2a_sdk.decorators import billable

b2a = B2AClient(api_key="key", wallet_id="agent-001")

@billable(b2a, wallet_id="agent-001", service_category="content_factory", units=10.0)
async def generate_video(url: str):
    return {"url": url}

# Simulation - no real charges
async with b2a.simulate_session(wallet_id="agent-001") as sim:
    await generate_video("https://example.com/video.mp4")
    print(f"Cost: {sim.total_cost}")  # 500 credits
    print(f"Would succeed: {sim.would_succeed}")  # True

# Real execution
await generate_video("https://example.com/video.mp4")  # Real deduction
```

### Single-Shot Estimation

```python
# Quick price check without session overhead
estimate = await b2a.get_dry_run_estimate(
    "agent-001",
    "content_factory",
    units=10.0,
)
print(f"Would cost: {estimate['credits_would_charge']} credits")
```

### API Endpoints

```bash
# Start a simulation session (15 min TTL)
POST /v1/billing/dry-run/session
{"wallet_id": "agent-001"}

# Simulate charges within session
POST /v1/billing/dry-run/charge
{"wallet_id": "agent-001", "service": "content_factory", "units": 10.0, "dry_run_session_id": "..."}

# End session and get summary
DELETE /v1/billing/dry-run/session/{session_id}

# Commit simulated charges to real billing
POST /v1/billing/dry-run/session/{session_id}/commit

# Revert (discard) simulated charges
POST /v1/billing/dry-run/session/{session_id}/revert
```

---

## Behavioral Sandbox Engine (Phase 6)

**Authenticated tool-behavior testing with safe dry runs, mocked backends, and optional Docker isolation.**

The behavioral sandbox is not a general-purpose code execution platform. Python
dry runs return synthetic execution metadata by default. Real Python execution
requires `BEHAVIORAL_SANDBOX_PYTHON_BACKEND=docker`, which runs code with no
network, dropped capabilities, a read-only filesystem, resource limits, and an
unprivileged user. Direct host Python subprocess execution is blocked unless
`ALLOW_UNSAFE_HOST_PYTHON_SANDBOX=true` is set for local development, and that
mode must not be treated as production isolation.

### Features

- **Python dry-run simulation** by default
- **Docker backend** for container-bounded Python execution
- **Opt-in unsafe host Python subprocess mode** for local development only
- **MCP tool sandboxing** with mocked responses
- **HTTP proxy mode** for API testing
- **Redis-backed state isolation** per environment

### API Endpoints

```bash
# Create a sandbox environment
curl -X POST http://localhost:8000/v1/sandbox/behavioral/environments \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"environment_type": "python_subprocess", "name": "test-env"}'

# Execute a tool in sandbox
curl -X POST http://localhost:8000/v1/sandbox/behavioral/execute \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"env_id": "...", "tool_name": "my_tool", "tool_input": {"code": "print(42)"}, "dry_run": true}'

# Get sandbox state
curl http://localhost:8000/v1/sandbox/behavioral/environments/{env_id} \
  -H "X-API-Key: your-key"

# Cleanup sandbox
curl -X DELETE http://localhost:8000/v1/sandbox/behavioral/environments/{env_id} \
  -H "X-API-Key: your-key"
```

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

## External AWI Adoption Kit — Phase 8

**Turn any website into an agent-native platform in <30 minutes.**

Website owners can now expose a full **Agentic Web Interface (AWI)** that works seamlessly with this middleware.

### One-command adoption

```bash
pip install agent-middleware-awi
python -m agent_middleware generate-awi --framework fastapi
```

The kit includes:

- Automatic `/.well-known/awi.json` manifest generator
- Python + TypeScript SDKs
- FastAPI / Next.js reference templates
- Zero-breaking-change adapter (AWI runs alongside your existing human UI)
- Full security & task-queue integration

**Documentation:** [docs/awi-adoption-guide.md](docs/awi-adoption-guide.md)

This directly implements the vision from **arXiv:2506.10953v1** — we no longer force agents to fight human-designed interfaces.

---

## Agent Discoverability (Phase 9)

**Making agents find and use this platform automatically.**

### Discovery Endpoints

Agents discover services through machine-readable endpoints:

```bash
# Main discovery manifest
GET /v1/discover

# Standard agent manifest
GET /.well-known/agent.json

# MCP tools manifest
GET /mcp/tools.json

# LLM-readable docs
GET /llm.txt
```

### Framework Integrations

Drop-in integrations for popular agent frameworks:

| Framework | Package | Docs |
|-----------|---------|------|
| LangGraph | `agent_middleware` | [`README.langgraph.md`](framework_integrations/README.langgraph.md) |
| CrewAI | `agent_middleware` | [`README.crewai.md`](framework_integrations/README.crewai.md) |
| AutoGen | `agent_middleware` | [`README.autogen.md`](framework_integrations/README.autogen.md) |
| LlamaIndex | `agent_middleware` | [`README.llamaindex.md`](framework_integrations/README.llamaindex.md) |

```python
# One-line integration
from agent_middleware import B2AClient, get_langgraph_tools

client = B2AClient(api_key="...", wallet_id="...")
tools = get_langgraph_tools(client)  # Ready for LangGraph!

agent = create_react_agent(model, tools)
```

### SDKs

```bash
# Python
pip install agent-middleware-api

# TypeScript
npm install @b2a/sdk
```

See [`docs/agent-recipes.md`](docs/agent-recipes.md) for examples.

---

## Agentic Web Interface (AWI) — Phase 7

**Based on arXiv:2506.10953v1 — "Build the web for agents, not agents for the web"** ([Lù et al., 2025, CC BY 4.0](https://arxiv.org/abs/2506.10953))

We believe agents should not be forced to adapt to human-designed UIs and DOM trees. Instead, we provide a full **Agentic Web Interface (AWI)** layer that implements the paper's six guiding principles:

- **Stateful sessions** (`awi_session.py`)
- **13 standardized higher-level actions** (`awi_action_vocab.py`)
- **Progressive representations** (summary, embedding, low-res, etc.)
- **Agentic task queues** with concurrency limits and human pause/steer
- Human-centric intervention endpoint (`/v1/awi/intervene`)

This makes our middleware the first open-source **MCP + AWI control plane** — websites can expose an AWI that our platform consumes, while agents get a clean, safe, standardized interface.

### Create an AWI Session

```bash
# Create a stateful AWI session
curl -X POST http://localhost:8000/v1/awi/sessions \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://example.com", "max_steps": 100}'
```

### Execute Standardized Actions

```bash
# Execute a higher-level action
curl -X POST http://localhost:8000/v1/awi/execute \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "awi-abc123",
    "action": "search_and_sort",
    "parameters": {"query": "laptops", "sort_by": "price"}
  }'
```

### Request Progressive Representations

```bash
# Get exactly what you need
curl -X POST http://localhost:8000/v1/awi/represent \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "awi-abc123",
    "representation_type": "summary"
  }'
```

### Human Pause/Steer

```bash
# Pause session for human review
curl -X POST http://localhost:8000/v1/awi/intervene \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "awi-abc123", "action": "pause", "reason": "Review needed"}'

# Resume after review
curl -X POST http://localhost:8000/v1/awi/intervene \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "awi-abc123", "action": "resume"}'
```

**Endpoints:** `/v1/awi/sessions`, `/v1/awi/execute`, `/v1/awi/represent`, `/v1/awi/intervene`, `/v1/awi/queue/status`, `/v1/awi/vocabulary`

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

### SQLite for Edge/Local Deployments

For simpler edge deployments or local development, use SQLite:

```bash
# SQLite (zero infrastructure, file-based)
railway variables set STATE_BACKEND=sqlite
railway variables set SQLITE_URL=./data/state.db
```

SQLite backend provides durable state without requiring PostgreSQL or Redis infrastructure.

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

> **Note:** Multi-tenant hardening validations are available in `app/core/tenant_validation.py` for production deployments requiring strict tenant isolation.

---

## Durability Model

- **PostgreSQL:** preferred durable state backend for runtime stores.
- **Redis:** distributed rate limiting and backend fallback state store.
- **Memory:** automatic fallback when no persistent backend is configured.

> ⚠ **In production, set `STATE_BACKEND=postgres` to avoid non-durable operation.**

Current durable service stores:
- Billing (`wallets`, `ledger`, `alerts`, `velocity_snapshots`, `services`)
- Comms (`agent registry`, row-keyed `inbox` and `outbox` messages)
- Telemetry (`events`, `anomalies`)

Billing responses keep legacy numeric fields and also include `*_exact` decimal
string companions for programmatic reconciliation, for example `balance_exact`,
`amount_exact`, and `period_debits_exact`.

---

## Roadmap

- [x] PostgreSQL ledger with ACID transactions
- [x] Stripe fiat ingestion with webhooks
- [x] Agent-to-agent transfers with child wallets
- [x] Service marketplace
- [x] Spend velocity monitoring with auto-freeze
- [x] Python SDK (`b2a-sdk`)
- [x] MCP Server Generator for agent tool exposure
- [x] Stripe Identity (KYC) for sponsor verification
- [x] Automated API key rotation for wallets
- [x] Sandbox engine wired to billing
- [x] Behavioral Sandbox Engine (safe dry runs, mocked MCP sandboxing)
- [x] Full Agentic Web Interface (AWI) control plane
- [x] External AWI Adoption Kit (Python/TS SDKs, manifest generator, adapter)
- [x] Add comprehensive agent interaction examples and recipes
- [x] Multi-tenant hardening validations
- [x] Add SQLite backend support for simpler edge deployments
- [x] Agent discoverability (discovery endpoints, framework integrations)

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
