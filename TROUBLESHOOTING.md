# Troubleshooting

Common issues when setting up or running the Agent Middleware API locally.

## Quick-start fails

### `make: command not found`
Install `make` via your system package manager, or run the manual `pytest` equivalent shown in README.md.

### `uv: command not found`
Install uv:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
Then restart your shell or run `source $HOME/.local/bin/env`.

### `ModuleNotFoundError: No module named 'app'`
You are running commands from outside the repo root. `cd` into `agent-middleware-api/` before running `uvicorn` or `pytest`.

---

## Local API startup fails

### `ValueError: TRUST_SIGNING_PRIVATE_KEY_B64 must be a 32-byte Ed25519 seed`
Generate a key and export it:
```bash
python3 -c 'import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())'
export TRUST_SIGNING_PRIVATE_KEY_B64='<output>'
```
Save it in `.env` (gitignored) for reuse across restarts.

### `RuntimeError: Production-like configuration requires durable state`
You set `ENVIRONMENT=production` but used SQLite or left `STATE_BACKEND=sqlite`. Either:
- Switch to `ENVIRONMENT=local` for local development, **or**
- Set `STATE_BACKEND=postgres` and provide a `DATABASE_URL` with `postgresql+asyncpg://`.

### `RuntimeError: ENABLE_PROOF_SURFACES must be false in production`
Set `ENABLE_PROOF_SURFACES=false`. Proof surfaces are for local demos only.

### `alembic.util.exc.CommandError: Can't locate revision identified by '...'`
Your database was created with an older migration set. Run:
```bash
alembic upgrade head
```
Or delete the SQLite file and let it recreate (loses data).

---

## API runs but requests fail

### `404` on `/v1/billing/...` or dry-run endpoints
These are **proof surfaces**. Start the API with `ENABLE_PROOF_SURFACES=true` to access them locally. Do not enable in production.

### `410 Gone` on `POST /v1/billing/top-up`
Direct top-ups are disabled by design. Use `POST /v1/billing/top-up/prepare` to create a Stripe PaymentIntent instead. See README.md "Core API surfaces" and [docs/settlement-rails.md](docs/settlement-rails.md).

### `401 Unauthorized` or `403 Forbidden`
- Check that `X-API-Key` header is present and matches a valid wallet-scoped or bootstrap key.
- Bootstrap keys go in `VALID_API_KEYS` (comma-separated). Wallet keys are created via `POST /v1/api-keys`.
- Wallet-scoped keys can only access their own wallet's permits and receipts.

### `409 Conflict` on permit creation
You reused an `Idempotency-Key` with different payload. Use a fresh UUID for each distinct request, or replay the exact same payload.

### `422 Unprocessable Entity` on MCP invocation
- Verify the permit is valid and not expired.
- Check that the `idempotency_key` in `mcpContext` is unique per invocation (not the same as the permit's idempotency key).
- Confirm the tool name exists in `/mcp/tools.json`.

### `delivery_uncertain` receipt
The upstream MCP server accepted the request but the response was lost in transit. The charge stands. Do not retry automatically — inspect the upstream state manually. See [docs/partner-first-tool-runbook.md](docs/partner-first-tool-runbook.md).

---

## Examples fail

### `ModuleNotFoundError: No module named 'b2a_sdk'`
Install the SDK in editable mode from the repo root:
```bash
python -m pip install -e './b2a_sdk[dev]'
```

### `404 wallet_not_found` in `dry_run_example.py`
The example creates its own wallet — do not edit the script to use a hardcoded wallet ID. Just run it as-is with the API running.

### `404` when running examples against a fresh `make prove-trust-plane` database
`make prove-trust-plane` uses a throwaway SQLite database. The examples need a running server with `ENABLE_PROOF_SURFACES=true`. Start the server separately:
```bash
ENABLE_PROOF_SURFACES=true uvicorn app.main:app
```

---

## Database and migrations

### `pytest` fails with `asyncpg` or PostgreSQL errors
The PostgreSQL concurrency and crash-recovery tests need a real PostgreSQL database. Set `DATABASE_URL` to an empty, dedicated test database:
```bash
export DATABASE_URL=postgresql+asyncpg://user:pass@localhost/b2a_test
```
SQLite-only tests will still pass; PostgreSQL-specific tests skip if unavailable.

### Crash-recovery test hangs or fails
`make prove-crash-recovery` needs a **dedicated, empty** PostgreSQL database. It intentionally kills worker processes. Do not point it at a shared or production database.

---

## Still stuck?

- Read [docs/golden-path.md](docs/golden-path.md) for the complete wallet-scoped HTTP flow.
- Read [docs/partner-first-tool-runbook.md](docs/partner-first-tool-runbook.md) to connect one real upstream tool.
- Check [docs/PROOF_MATRIX.md](docs/PROOF_MATRIX.md) for what each proof command asserts (and what it does not).
- Review [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and `make` targets.

If you believe you've found a bug, use the [bug report template](https://github.com/PetrefiedThunder/agent-middleware-api/issues/new?template=bug_report.yml). For security issues, see [SECURITY.md](SECURITY.md).
