# Agent-Native Middleware API — Demo Configuration

This document describes how to set up a public demo instance.

## Option 1: Railway (Recommended)

1. Fork this repository
2. Create a Railway project from the fork
3. Add PostgreSQL database
4. Set environment variables:

```bash
# Core
DEBUG=false
STATE_BACKEND=postgres
DATABASE_URL=${{PostgreSQL.DATABASE_URL}}

# Authentication (demo keys)
VALID_API_KEYS=demo-key-001,demo-key-002,demo-key-003

# Rate Limits
RATE_LIMIT_PER_MINUTE=60

# CORS
CORS_ORIGINS=https://agentmarket.cloud,https://smithery.ai,*
```

5. Deploy

## Option 2: Docker Compose (Local Demo)

```yaml
version: '3.8'
services:
  api:
    image: ghcr.io/petrefiedthunder/agent-middleware-api:latest
    ports:
      - "8000:8000"
    environment:
      - STATE_BACKEND=memory
      - VALID_API_KEYS=demo-key-001
      - DEBUG=false
      - RATE_LIMIT_PER_MINUTE=60
    volumes:
      - ./demo.db:/app/demo.db
```

Run with:
```bash
docker-compose -f docker-compose.demo.yml up
```

## Demo API Keys (Development Only)

For testing, use these keys:
- `demo-key-001` — Full access, 10,000 credits
- `demo-key-002` — Read-only, 1,000 credits
- `demo-key-003` — Limited, 500 credits

**WARNING: Never use these in production!**

## Testing the Demo

```bash
# Health check
curl https://your-demo-instance/health

# Discovery manifest
curl https://your-demo-instance/v1/discover

# Agent manifest
curl https://your-demo-instance/.well-known/agent.json

# LLM docs
curl https://your-demo-instance/llm.txt
```

## Demo Wallet

Create a demo wallet with initial credits:

```bash
curl -X POST https://your-demo-instance/v1/billing/wallets/agent \
  -H "X-API-Key: demo-key-001" \
  -H "Content-Type: application/json" \
  -d '{"wallet_id": "demo-agent", "parent_wallet_id": "demo-sponsor"}'
```
