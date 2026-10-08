# Agent Middleware API — Demo Configuration

This document describes how to set up a public demo instance.

## Option 1: Railway (Recommended)

1. Fork this repository
2. Create a Railway project from the fork
3. Add PostgreSQL database
4. Set environment variables:

```bash
# Core. Railway boots refuse an unset ENVIRONMENT (the injected RAILWAY_*
# variables mark a hosted runtime). Any value other than a local one
# (local, dev, test, ci, ...) is production-like — "demo" included — and
# engages every production guardrail in app/core/trust_mode.py, so the rest
# of this block is written to satisfy them.
ENVIRONMENT=production
DEBUG=false
STATE_BACKEND=postgres
DATABASE_URL=${{PostgreSQL.DATABASE_URL}}
# Postgres schemas come from Alembic, never create_all; this runs
# `alembic upgrade head` before uvicorn on a fresh database.
RUN_MIGRATIONS_ON_START=true
# This demo's own public HTTPS origin; unset, the OpenAPI servers entry falls
# back to the first-party instance.
PUBLIC_URL=https://your-demo-instance

# Trust plane — REQUIRED. Trust mode is on by default and the service will not
# start without a signing seed. Generate one and set it as a Railway variable:
#   python3 -c 'import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())'
# Generate once and keep it; rebinding the same key ID to new material is
# rejected with signing_key_id_public_key_mismatch.
TRUST_SIGNING_PRIVATE_KEY_B64=<strict base64 of exactly 32 raw bytes>
TRUST_SIGNING_KEY_ID=demo-ed25519

# Authentication. Every VALID_API_KEYS entry is a bootstrap-admin
# (full-control) credential — see "Demo API Keys" below. Generate one:
#   python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
VALID_API_KEYS=<generated random value>

# Rate Limits
RATE_LIMIT_PER_MINUTE=60

# CORS — the credential-less wildcard is the documented default (see
# SECURITY_LIMITATIONS.md, "CORS Posture"). A wildcard disables credentialed
# responses for every origin, so do not mix it with named origins: set an
# explicit list instead (no `*`) only if a browser client needs credentials.
CORS_ORIGINS=*
```

`ENABLE_PROOF_SURFACES`, `ALLOW_LEGACY_UNPERMITTED_MCP`, and the other
development escape hatches must stay at their off defaults; a production-like
boot refuses them. The full variable reference is
[deploy-railway.md](deploy-railway.md#required-production-variables).

5. Deploy with the release-context upload in
   [deploy-railway.md](deploy-railway.md#canonical-deploy-path)
   (`scripts/prepare_railway_release.py` + `railway up`). The production
   `Dockerfile` copies a `.build_commit_sha` stamp that is gitignored and
   written by that script, so a plain build of the fork's GitHub source
   fails.

## Option 2: Supported Local Demo

Use [the local quickstart](quickstart.md) for the wallet → permit → invoke →
receipt workflow:

```bash
make quickstart
```

The quickstart binds loopback only, configures its SQLite database and durable
state, and persists the database and signing seed together under
`data/quickstart/`. Reuse that saved signing seed on every restart; do not
regenerate it while keeping signed data. Follow the quickstart's self-provision
step to obtain a wallet-scoped key and its governed invocation examples.

The former ad hoc Compose recipe is retired: its memory-state setting and
unused database mount did not configure the trust database. Hosted demo setup
and operator bootstrap below apply to Option 1; local callers should use the
complete quickstart flow above.

## Demo API Keys

There are no tiered demo keys. Every `VALID_API_KEYS` entry is a
bootstrap-admin credential with full control of every wallet
(`app/core/auth.py` grants it `is_bootstrap_admin`); there is no read-only or
credit-limited variant. Keep it in Railway variables, never hand it to demo
users, and never reuse a guessable value like `demo-key-001`.

To give someone limited access, use the bootstrap key once to mint a
wallet-scoped key (`POST /v1/api-keys`), bounded by its agent wallet's budget —
see [partner-api-key-bootstrap.md](partner-api-key-bootstrap.md).

## Testing the Demo

```bash
# Health check
curl https://your-demo-instance/health

# Discovery manifest (production-like boots require a key for tool catalogs)
curl -H "X-API-Key: $BOOTSTRAP_KEY" https://your-demo-instance/v1/discover

# Agent manifest
curl https://your-demo-instance/.well-known/agent.json

# LLM docs
curl https://your-demo-instance/llm.txt
```

## Demo Wallet

Create a sponsor wallet, a funded agent wallet, and a wallet-scoped agent key
in one step (the agent key is printed once):

```bash
BOOTSTRAP_KEY=<your VALID_API_KEYS value> \
uv run --with-requirements requirements.txt \
  python scripts/partner_api_key_bootstrap.py \
  --api-url https://your-demo-instance \
  --sponsor-name "Demo Sponsor" \
  --agent-id demo-agent \
  --budget-credits 1000
```

## Reset and key hygiene on a shared demo host

Demo state does not expire on its own. Permits, idempotency records, and
spent budgets persist, so handing one long-lived host to prospect after
prospect leaks prior runs into each new trial (a repeated call replays the
old receipt instead of executing fresh). Between prospects, reset:

1. Revoke every wallet-scoped key you issued: `DELETE
   /v1/api-keys/{wallet_id}/{key_id}` revokes one key,
   `POST /v1/api-keys/emergency-revoke` revokes every key on a wallet.
2. Rotate the bootstrap key itself per [api-key-rotation.md](api-key-rotation.md).
3. For a fully clean slate, rebuild the host from scratch (fresh database
   plus fresh signing seed and bootstrap key) rather than reusing state.
   The local equivalent is `make quickstart QUICKSTART_ARGS="--reset"`
   (see [quickstart](quickstart.md#starting-over)). Until a rebuild is
   automated, run steps 1 and 2 on a schedule (for example nightly) so a
   stale wallet or spent permit never greets the next prospect.

## Vocabulary note: "sandbox" is not the trial

The `/v1/sandbox` API and `app/services/sandbox.py` are puzzle environments
for testing agents (pattern, navigation, mock API, adversarial), not a
trial environment for buyers. When talking to prospects, call the trial a
demo instance or trial workspace, and leave "sandbox" for the puzzle API.
