# Agent Middleware API

[![CI](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml)
[![Auto PR](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/auto-pr.yml/badge.svg?branch=master)](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/auto-pr.yml)

**The FastAPI control plane for agent-native infrastructure.**

**Agent Middleware API** is a production-ready FastAPI service that provides durable state, billing, telemetry, secure tool execution, and IoT connectivity for autonomous agents.

It lets agents:

* Send and receive structured messages
* Store persistent state
* Bill and track usage
* Emit telemetry and anomaly alerts
* Execute secure external actions

Deploy in minutes via Docker or Railway.

---

## Architecture Overview

| Domain        | Endpoint Prefix | Durable | Rate Limited | Auth Required |
|---------------|----------------|----------|--------------|---------------|
| Billing       | `/v1/billing`   | Yes      | Yes          | Yes           |
| Telemetry     | `/v1/telemetry` | Yes      | Yes          | Yes           |
| Comms         | `/v1/comms`     | Yes      | Yes          | Yes           |
| IoT Bridge    | `/v1/iot`       | Optional | Yes          | Yes           |
| Security      | `/v1/security`  | Partial  | Yes          | Yes           |

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

## Deployment (Railway)

This repository is deployment-ready for Railway via `Dockerfile` + `railway.json`.

### 1. Create Service

1. Create a Railway project from this repository.
2. Use this repository root as the service root (contains `Dockerfile`).

CLI alternative:
```bash
railway login
railway init
railway up
```

### 2. Configure Environment Variables

Recommended baseline:
- `DEBUG=false`
- `VALID_API_KEYS=<comma-separated-keys>`
- `RATE_LIMIT_PER_MINUTE=120`
- `STATE_BACKEND=postgres` (Required for production durability)
- `STATE_NAMESPACE=agent_middleware`
- `DATABASE_URL=<Railway Postgres connection string>`
- `REDIS_URL=<Railway Redis connection string>`

### 3. Verify Deployment

- `GET /health` returns `200`
- `GET /health/dependencies` reports healthy state backend
- `GET /docs` loads OpenAPI UI

---

## Security Model

- API-key based authentication for protected endpoints
- Per-key rate limiting (Redis-backed)
- Durable audit logging (Postgres)
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
