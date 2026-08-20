# Constant Test Loop

Production-ready smoke test for the governed trust plane. Exercises the complete loop:

1. **Permit** → issue scoped permit for governed tool
2. **Invoke** → call the tool with the permit → signed receipt
3. **Meter** → verify ledger debit matches receipt charge
4. **Replay** → same idempotency key → same receipt_id, no second debit
5. **Deny** (optional) → out-of-scope tool is denied with 0 charge

## Local Testing

Against a running quickstart server:

```bash
# Terminal 1: start quickstart
make quickstart

# Terminal 2: run the constant test (auto-provisions its own key)
python scripts/constant_test_loop.py
```

The script self-provisions an agent key via `/v1/dev-keys/self-provision` when no credentials are provided.

## Production Use

Set `CI_SMOKE_AGENT_KEY` for a pre-provisioned agent credential. Optionally provide `CI_SMOKE_WALLET_ID` and `CI_SMOKE_KEY_ID` for faster startup (the script will fetch them from the API if not provided):

```bash
# Provision an agent key once (using bootstrap key) and extract credentials in one pipeline
export BOOTSTRAP_KEY="amw_live_..."

# Extract and set as CI secrets directly from the JSON output (no persistent file)
export CI_SMOKE_AGENT_KEY="$(python scripts/partner_api_key_bootstrap.py \
  --api-url https://api.thisisatest.tech \
  --agent-id ci-smoke-agent \
  --key-name constant-test-loop \
  --budget-credits 5000 \
  --json | jq -r .api_key)"

export CI_SMOKE_WALLET_ID="$(python scripts/partner_api_key_bootstrap.py \
  --api-url https://api.thisisatest.tech \
  --agent-id ci-smoke-agent \
  --key-name constant-test-loop \
  --budget-credits 5000 \
  --json | jq -r .wallet_id)"

export CI_SMOKE_KEY_ID="$(python scripts/partner_api_key_bootstrap.py \
  --api-url https://api.thisisatest.tech \
  --agent-id ci-smoke-agent \
  --key-name constant-test-loop \
  --budget-credits 5000 \
  --json | jq -r .key_id)"

# Or use a restrictive temporary file if needed
KEY_FILE="$(mktemp)"
umask 077
python scripts/partner_api_key_bootstrap.py \
  --api-url https://api.thisisatest.tech \
  --agent-id ci-smoke-agent \
  --key-name constant-test-loop \
  --budget-credits 5000 \
  --json > "$KEY_FILE"
chmod 600 "$KEY_FILE"
export CI_SMOKE_AGENT_KEY="$(jq -r .api_key "$KEY_FILE")"
export CI_SMOKE_WALLET_ID="$(jq -r .wallet_id "$KEY_FILE")"
export CI_SMOKE_KEY_ID="$(jq -r .key_id "$KEY_FILE")"
rm "$KEY_FILE"  # Clean up immediately

# Run the constant test
API_URL=https://api.thisisatest.tech python scripts/constant_test_loop.py
```

## Machine-Readable Bootstrap Output

`partner_api_key_bootstrap.py --json` prints JSON to stdout so the minted key can be piped directly:

```bash
# Pipe to jq to extract the agent API key
BOOTSTRAP_KEY="..." python scripts/partner_api_key_bootstrap.py \
  --api-url https://api.thisisatest.tech \
  --agent-id ci-smoke-agent \
  --key-name test-key \
  --budget-credits 5000 \
  --json | jq -r .api_key

# Or pipe directly to gh secret set
BOOTSTRAP_KEY="..." python scripts/partner_api_key_bootstrap.py \
  --api-url https://api.thisisatest.tech \
  --agent-id ci-smoke-agent \
  --key-name constant-test-loop \
  --budget-credits 5000 \
  --json | jq -r .api_key | \
  gh secret set CI_SMOKE_AGENT_KEY --repo PetrefiedThunder/agent-middleware-api
```

### Security Properties

- Human/status text goes to stderr (never stdout in `--json` mode)
- Bootstrap/admin key is never printed to stdout or stderr
- Agent key is never logged or printed during constant test execution
- All secrets read from environment variables, never hardcoded

## Exit Codes

- `0` — all invariants held
- `1` — invariant failure (test failed)
- `2` — configuration error or network failure

## Tests

```bash
pytest tests/test_constant_test_loop.py -v
```

Covers:
- `--json` mode produces pipeable stdout
- Bootstrap key never leaks to stdout or stderr
- `jq -r .api_key` pipeline works
- Constant test loop runs against local instance
- Self-provisioning when no key provided
- Agent key never logged during execution
