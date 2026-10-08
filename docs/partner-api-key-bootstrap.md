# Design-partner API key bootstrap (gated)

There is **no public self-serve API key mint**. Discovery (`/.well-known/agent.json`,
`/llm.txt`, `/mcp/tools.json`) is open; authenticated calls return `401` until an
**operator** provisions a wallet-scoped key.

## Roles

| Credential | Source | Use |
|------------|--------|-----|
| Bootstrap / admin key | Host secret `VALID_API_KEYS` (Railway/env) | Create wallets and issue DB keys only |
| Agent API key | `POST /v1/api-keys` (shown once) | All agent permits / MCP / billing calls |

Never put bootstrap keys in partner chat, marketing pages, or agent prompts.
Never commit `VALID_API_KEYS` to git.

## Operator flow (live API)

```bash
export API_URL="${PUBLIC_URL:-https://api.thisisatest.tech}"
export BOOTSTRAP_KEY=...   # from secret manager / Railway variables — not a demo string

# One-shot provisioner (prints agent key once to stdout):
uv run --with-requirements requirements.txt \
  python scripts/partner_api_key_bootstrap.py \
  --api-url "$API_URL" \
  --sponsor-name "Partner Co" \
  --agent-id "partner-agent-001" \
  --budget-credits 1000
```

Optional bounds on what you mint (all default to unlimited):

- `--daily-limit 250` — daily spend cap (credits) on the agent wallet
- `--expires-in-days 30` — key stops authenticating after this many days
- `--max-uses 1000` — key stops authenticating after this many successful
  authentications (enforced server-side)

On partial failure, re-run with the IDs printed to stderr:

```bash
uv run --with-requirements requirements.txt \
  python scripts/partner_api_key_bootstrap.py \
  --api-url "$API_URL" \
  --sponsor-wallet-id "$SPONSOR_WALLET_ID" \
  --agent-wallet-id "$AGENT_WALLET_ID"
```

Hand the **agent** key (and wallet id) to the partner over a secure channel.
Revoke when the engagement ends:

```bash
curl -X DELETE "$API_URL/v1/api-keys/$AGENT_WALLET_ID/$KEY_ID" \
  -H "X-API-Key: $BOOTSTRAP_KEY"
```

## Manual equivalent

Same steps as [`golden-path.md`](golden-path.md) §2–4:

1. `POST /v1/billing/wallets/sponsor` with bootstrap key  
2. `POST /v1/billing/wallets/agent` with bootstrap key  
3. `POST /v1/api-keys` for the agent wallet with bootstrap key  
4. Partner uses the returned `api_key` as `X-API-Key` thereafter  

## What agents should do on 401

1. Re-read `/.well-known/agent.json` → `authentication` (`public_self_serve: false`).  
2. Stop — do not invent keys or hit random mint endpoints.  
3. Ask the human operator for a wallet-scoped key (this doc).

## 401 versus 403: how to read a refused key

The gateway splits credential problems from permission problems, which
differs from the convention many HTTP clients expect (bad credentials
usually mean 401):

- `401 missing_credentials` — no credential was sent at all. Send
  `X-API-Key` or `Authorization: Bearer <token>`.
- `401 invalid_token` (and related `invalid_refresh_token`,
  `no_active_api_key`, `unbound_access_token`) — the Bearer token is
  malformed, expired, or its issuing API key was revoked.
- `403 invalid_api_key` — a well-formed API key was sent, but it is not
  a live credential. Treat this exactly like a 401: do not retry with
  the same key, do not escalate it to a permission problem, and ask the
  operator for a fresh key. SDK retry logic must never loop on this.
- `403 wallet_access_denied`, `403 admin_access_denied`, `403
  insufficient_scope` — the credential is valid but not allowed to do
  this. A different key or a wider scope is needed, not a retry.

## Related

- [`DESIGN_PARTNER_GUIDE.md`](../DESIGN_PARTNER_GUIDE.md)
- [`golden-path.md`](golden-path.md)
- [`deploy-railway.md`](deploy-railway.md) (`VALID_API_KEYS` posture)
