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

| Domain              | Endpoint Prefix | Durable | Rate Limited | Auth Required |
|---------------------|----------------|---------|--------------|---------------|
| Billing             | `/v1/billing`  | Yes     | Yes          | Yes           |
| Telemetry           | `/v1/telemetry`| Yes     | Yes          | Yes           |
| Comms               | `/v1/comms`    | Yes     | Yes          | Yes           |
| IoT Bridge          | `/v1/iot`      | Optional| Yes          | Yes           |
| Security            | `/v1/security` | Partial | Yes          | Yes           |
| **Agent Intelligence** | `/v1/ai`   | Yes     | Yes          | Yes           |

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
- Billing (`wallets`, `ledger`, `alerts`)
- Comms (`agent registry`, `inbox`, `outbox`)
- Telemetry (`events`, `anomalies`)

---

## Roadmap

- [ ] Add comprehensive agent interaction examples and recipes
- [ ] Multi-tenant hardening validations
- [ ] Add SQLite backend support for simpler edge deployments
- [ ] Tag `v0.1.0` and publish release notes

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
pytest -q
```
*(CI runs on Python 3.11 and 3.12 via GitHub Actions)*

---

## Security & Contributing

Report vulnerabilities using `/SECURITY.md`.
Please read `/CONTRIBUTING.md` before opening pull requests.

## License

MIT License. See `/LICENSE`.
