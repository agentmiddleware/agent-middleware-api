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

## 5. Issue A Signed Tool Permit

Governed MCP calls use a signed permit plus an idempotency key. The permit
binds the agent wallet, the runtime key, the allowed tool, scope, budget, and
expiry.

```bash
export AGENT_KEY_ID=$(echo "$AGENT_KEY_JSON" | jq -r '.key_id')
export PERMIT_JSON=$(
  curl -s -X POST "$API_URL/v1/permits" \
    -H "X-API-Key: $BOOTSTRAP_KEY" \
    -H "Idempotency-Key: permit-research-agent-001" \
    -H "Content-Type: application/json" \
    -d "{
      \"issuer_wallet_id\": \"$AGENT_WALLET_ID\",
      \"subject_wallet_id\": \"$AGENT_WALLET_ID\",
      \"subject_key_id\": \"$AGENT_KEY_ID\",
      \"allowed_tools\": [\"golden-path-echo\"],
      \"scopes\": [\"tool:golden-path-echo:invoke\", \"billing:charge\"],
      \"max_credits\": 50,
      \"expires_at\": \"$(date -u -v+30M +%Y-%m-%dT%H:%M:%SZ)\"
    }"
)

export PERMIT_ID=$(echo "$PERMIT_JSON" | jq -r '.permit_id')
echo "$PERMIT_ID"
```

## 6. Verify Agent-Scoped Access

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

## 7. Simulate Cost Before Acting

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

## 6a. Optional: Attach A Wallet Policy

Operators can constrain the agent wallet before execution:

```bash
curl -X POST "$API_URL/v1/policies" \
  -H "X-API-Key: $BOOTSTRAP_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"wallet_id\": \"$AGENT_WALLET_ID\",
    \"name\": \"golden-path-policy\",
    \"allowed_service_categories\": [\"agent_comms\"],
    \"max_cost_per_action\": 5
  }"
```

If an MCP invocation, billing charge, or planner action violates the active
wallet policy, it is denied before execution or charge and the audit event
includes the `policy_id` and evaluated constraints.

## 7. Invoke Or Discover Tools

Fetch the MCP manifest:

```bash
curl "$API_URL/mcp/tools.json" \
  -H "X-API-Key: $AGENT_API_KEY"
```

For a registered local or persistent MCP service, invoke with wallet context:

```bash
INVOKE_JSON=$(
  curl -s -X POST "$API_URL/mcp/tools/golden-path-echo/invoke" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Idempotency-Key: golden-path-invoke-001" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"golden-path-echo\",
    \"arguments\": {},
    \"mcp_context\": {
      \"wallet_id\": \"$AGENT_WALLET_ID\",
      \"request_path\": \"/golden-path/demo\",
      \"permit_id\": \"$PERMIT_ID\"
    }
  }"
)

export RECEIPT_ID=$(echo "$INVOKE_JSON" | jq -r '.receipt.receipt_id')
echo "$RECEIPT_ID"
```

Replace `golden-path-echo` with a tool from `/mcp/tools.json`.

## 8. Inspect The Operation Record

After a scoped agent invokes a tool, operators can inspect the control-plane record:

```bash
curl "$API_URL/v1/audit/events?wallet_id=$AGENT_WALLET_ID" \
  -H "X-API-Key: $BOOTSTRAP_KEY"
```

The scoped agent key can also inspect its own wallet's audit stream:

```bash
curl "$API_URL/v1/audit/events?wallet_id=$AGENT_WALLET_ID" \
  -H "X-API-Key: $AGENT_API_KEY"
```

Each audit event should let an operator tie the action back to its wallet,
credential source, tool, endpoint, policy decision, request ID or correlation
ID, success flag, error, and metadata such as transport and estimated cost.
Use the policy decision ID to confirm why the action was allowed or denied.

Verify the signed receipt:

```bash
curl -X POST "$API_URL/v1/receipts/verify" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"receipt_id\": \"$RECEIPT_ID\"}"
```

Verify the wallet audit chain:

```bash
curl -X POST "$API_URL/v1/audit/verify-chain" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"wallet_id\": \"$AGENT_WALLET_ID\"}"
```

## 9. Inspect Ledger And Velocity

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
- Control-plane audit records are inspectable with the bootstrap key.
- Operators can inspect the policy decision, audit event, ledger entry, and
  request/correlation ID for the scoped tool call.
- Ledger and velocity endpoints are inspectable with the agent key.
