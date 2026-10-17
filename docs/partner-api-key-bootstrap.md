# Design-partner API key bootstrap (gated)

Free sandbox demo keys are available at
[the demo page](https://www.thisisatest.tech/demo-key/) with no account.
Production keys are issued to design partners. Production authenticated calls
return `401` until an operator provisions a wallet-scoped key.

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

1. For sandbox testing, get a free demo key at https://www.thisisatest.tech/demo-key/.
2. For production access, ask the design partner's operator for a wallet-scoped key.

## Related

- [`DESIGN_PARTNER_GUIDE.md`](../DESIGN_PARTNER_GUIDE.md)
- [`golden-path.md`](golden-path.md)
- [`deploy-railway.md`](deploy-railway.md) (`VALID_API_KEYS` posture)
