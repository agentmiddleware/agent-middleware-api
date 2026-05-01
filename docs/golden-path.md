# Golden Path: Wallet-Scoped Agent Tool Call

This is the canonical production-beta flow. It proves that a developer can
provision money, issue a scoped key, let an agent act, and inspect the result.

The flow uses a bootstrap/admin key only for provisioning. The agent uses a
DB-created key scoped to its own wallet.

## Prerequisites

Start the API with a local bootstrap key:

```bash
export VALID_API_KEYS=dev-bootstrap-key
export DATABASE_URL=sqlite+aiosqlite:///./test.db
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Set shell helpers:

```bash
export API_URL=http://localhost:8000
export BOOTSTRAP_KEY=dev-bootstrap-key
```

## 1. Confirm Discovery

```bash
curl "$API_URL/.well-known/agent.json"
curl "$API_URL/llm.txt"
curl "$API_URL/mcp/tools.json"
```

## 2. Create A Sponsor Wallet

```bash
SPONSOR_JSON=$(
  curl -s -X POST "$API_URL/v1/billing/wallets/sponsor" \
    -H "X-API-Key: $BOOTSTRAP_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "sponsor_name": "Acme Beta",
      "email": "billing@example.com",
      "initial_credits": 10000,
      "require_kyc": false
    }'
)

export SPONSOR_WALLET_ID=$(echo "$SPONSOR_JSON" | jq -r '.wallet_id')
echo "$SPONSOR_WALLET_ID"
```

## 3. Provision An Agent Wallet

```bash
AGENT_JSON=$(
  curl -s -X POST "$API_URL/v1/billing/wallets/agent" \
    -H "X-API-Key: $BOOTSTRAP_KEY" \
    -H "Content-Type: application/json" \
    -d "{
      \"sponsor_wallet_id\": \"$SPONSOR_WALLET_ID\",
      \"agent_id\": \"research-agent-001\",
      \"budget_credits\": 1000,
      \"daily_limit\": 250
    }"
)

export AGENT_WALLET_ID=$(echo "$AGENT_JSON" | jq -r '.wallet_id')
echo "$AGENT_WALLET_ID"
```

## 4. Issue A Wallet-Scoped Agent API Key

```bash
AGENT_KEY_JSON=$(
  curl -s -X POST "$API_URL/v1/api-keys" \
    -H "X-API-Key: $BOOTSTRAP_KEY" \
    -H "Content-Type: application/json" \
    -d "{
      \"wallet_id\": \"$AGENT_WALLET_ID\",
      \"key_name\": \"research-agent-runtime\",
      \"expires_in_days\": 30
    }"
)

export AGENT_API_KEY=$(echo "$AGENT_KEY_JSON" | jq -r '.api_key')
echo "$AGENT_API_KEY"
```

Store this key securely. It is shown once.

## 5. Verify Agent-Scoped Access

The agent key can read its own wallet:

```bash
curl "$API_URL/v1/billing/wallets/$AGENT_WALLET_ID" \
  -H "X-API-Key: $AGENT_API_KEY"
```

The same key should not read the sponsor wallet:

```bash
curl -i "$API_URL/v1/billing/wallets/$SPONSOR_WALLET_ID" \
  -H "X-API-Key: $AGENT_API_KEY"
```

Expected result: `403 Forbidden`.

## 6. Simulate Cost Before Acting

```bash
DRY_RUN_JSON=$(
  curl -s -X POST "$API_URL/v1/billing/dry-run/session" \
    -H "X-API-Key: $AGENT_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"wallet_id\": \"$AGENT_WALLET_ID\"}"
)

export DRY_RUN_SESSION_ID=$(echo "$DRY_RUN_JSON" | jq -r '.session_id')

curl -X POST "$API_URL/v1/billing/dry-run/charge" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"wallet_id\": \"$AGENT_WALLET_ID\",
    \"service\": \"telemetry_pm\",
    \"units\": 1,
    \"description\": \"Estimate anomaly review cost\",
    \"dry_run_session_id\": \"$DRY_RUN_SESSION_ID\"
  }"
```

## 7. Invoke Or Discover Tools

Fetch the MCP manifest:

```bash
curl "$API_URL/mcp/tools.json" \
  -H "X-API-Key: $AGENT_API_KEY"
```

For a registered local or persistent MCP service, invoke with wallet context:

```bash
curl -X POST "$API_URL/mcp/tools/{service_id}/invoke" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"{service_id}\",
    \"arguments\": {},
    \"mcp_context\": {
      \"wallet_id\": \"$AGENT_WALLET_ID\",
      \"request_path\": \"/golden-path/demo\"
    }
  }"
```

Replace `{service_id}` with a tool from `/mcp/tools.json`.

## 8. Inspect Ledger And Velocity

```bash
curl "$API_URL/v1/billing/ledger/$AGENT_WALLET_ID" \
  -H "X-API-Key: $AGENT_API_KEY"

curl "$API_URL/v1/billing/wallets/$AGENT_WALLET_ID/velocity" \
  -H "X-API-Key: $AGENT_API_KEY"
```

## Success Criteria

- Agent discovery endpoints respond.
- Sponsor and agent wallets are created.
- Agent API key authenticates.
- Agent API key can access only its own wallet.
- Dry-run simulation returns a cost estimate.
- MCP manifest is available.
- Ledger and velocity endpoints are inspectable with the agent key.
