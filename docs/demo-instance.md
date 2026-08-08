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

# Trust plane — REQUIRED. Trust mode is on by default and the service will not
# start without a signing seed. Generate one and set it as a Railway variable:
#   python3 -c 'import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())'
# Generate once and keep it; rebinding the same key ID to new material is
# rejected with signing_key_id_public_key_mismatch.
TRUST_SIGNING_PRIVATE_KEY_B64=<strict base64 of exactly 32 raw bytes>
TRUST_SIGNING_KEY_ID=demo-ed25519

# Authentication (demo keys)
VALID_API_KEYS=demo-key-001,demo-key-002,demo-key-003

# Rate Limits
RATE_LIMIT_PER_MINUTE=60

# CORS — a wildcard origin disables credentialed responses. List explicit
# origins if a browser client needs credentials.
CORS_ORIGINS=https://agentmarket.cloud,https://smithery.ai,*
```

5. Deploy

## Option 2: Docker Compose (Local Demo)

This repository does not ship a `docker-compose.demo.yml`; save the following as
that filename first. `TRUST_SIGNING_PRIVATE_KEY_B64` is required — the container
exits at startup without it.

```yaml
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
      - TRUST_SIGNING_KEY_ID=demo-ed25519
      - TRUST_SIGNING_PRIVATE_KEY_B64=${TRUST_SIGNING_PRIVATE_KEY_B64:?generate with python3 -c 'import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())'}
    volumes:
      - ./demo.db:/app/demo.db
```

Run with:
```bash
export TRUST_SIGNING_PRIVATE_KEY_B64=$(python3 -c 'import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())')
docker-compose -f docker-compose.demo.yml up
```

`STATE_BACKEND=memory` keeps no durable state, so a fresh seed per run is fine
here. Anything with a persistent database must reuse one saved seed.

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
