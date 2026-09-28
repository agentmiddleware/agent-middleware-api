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

Off loopback the loop refuses to start without `--tool` and `--tool-args`
(or `$CI_SMOKE_TOOL` / the equivalent flags). This is deliberate, not a
papercut:

- **Tool selection.** `partner.echo` and `partner.notes.write` are tried in
  order when present, but which tool a monitor invokes on every run is an
  operator's decision, not the registry ordering's.
- **Payload.** Arguments derived from a tool's `inputSchema` satisfy its
  declared *shape*, not its *semantics*, and the derivation fills required
  fields from types, defaults, and the **first enum member** — which for a
  consequential tool could be `delete`. Schema validity is not evidence of
  safety. Pass `--tool-args '{}'` if the tool genuinely needs no arguments;
  the point is that it be a decision.

The permit is sized from the selected tool's advertised
`annotations.creditsPerCall` rather than a fixed cap, so pointing the loop at
a pricier tool does not fail with `permit_budget_exceeded` on a healthy
deployment.

```bash
python scripts/constant_test_loop.py \
  --api-url https://api.thisisatest.tech \
  --tool partner.echo \
  --tool-args '{"text": "constant test loop"}'
```

Routine monitoring flags have environment equivalents, so a CI job can be
configured without putting its credential in argv:

| Flag | Environment variable |
|---|---|
| `--api-url` | `API_URL` |
| `--tool` | `CI_SMOKE_TOOL` |
| `--other-tool` | `CI_SMOKE_OTHER_TOOL` |
| `--tool-args` | `CI_SMOKE_TOOL_ARGS` (a JSON object) |

A flag beats the corresponding variable when both are set. A malformed
`CI_SMOKE_TOOL_ARGS` — invalid JSON, or valid JSON that is not an object —
exits 2 as a configuration error rather than 1, so a payload typo never
looks like the trust plane failing.

## Opt-in Retry Evidence

`--retry-evidence-output` adds a deliberately manual proof to one constant-loop
run. The generated permit has `max_calls_per_tool` set to one and
`allow_identical_repeats` enabled. The script then verifies all of the
following before it creates the evidence file:

1. The first call succeeds, has one debit, and has valid receipt-to-dispatch
   evidence.
2. Replaying the exact same idempotency key returns the unchanged receipt and
   dispatch attempt without changing permit spend or debit count.
3. Repeating the approved payload with a fresh key is denied with
   `permit_max_calls_exceeded`, a signed zero-charge receipt, no ledger link,
   and no dispatch link.

The proof is not a scheduled CI mode. It makes one billable upstream dispatch
and leaves a permit and receipts on the selected deployment, so production use
requires explicit owner approval. It also requires `CI_SMOKE_AGENT_KEY`; proof
mode never self-provisions a credential.

The target, tool, and canonical payload SHA-256 must be repeated as CLI
confirmations. They intentionally have no environment-variable fallback. The
target is a credential-free API origin with no path, query, or fragment, and
the evidence path must be a new `.json` file in an existing directory.

```bash
TARGET=https://api.thisisatest.tech
TOOL=partner.echo
TOOL_ARGS='{"text":"approved retry proof"}'
PAYLOAD_SHA256="$(python3 -c \
  'import json,sys; from scripts.constant_test_loop import retry_proof_payload_sha256; print(retry_proof_payload_sha256(json.loads(sys.argv[1])))' \
  "$TOOL_ARGS")"

python3 scripts/constant_test_loop.py \
  --api-url "$TARGET" \
  --tool "$TOOL" \
  --tool-args "$TOOL_ARGS" \
  --retry-evidence-output retry-proof.json \
  --confirm-retry-target "$TARGET" \
  --confirm-retry-tool "$TOOL" \
  --confirm-retry-payload-sha256 "$PAYLOAD_SHA256"
```

The evidence file is created exclusively with mode `0600`. It contains the
origin, tool name, payload digest, permit policy, receipt/dispatch/ledger
identifiers, and zero-delta assertions. It omits credentials, wallet and key
identifiers, raw payloads, idempotency keys, and raw provider responses. The
dispatch linkage is gateway evidence; it does not independently prove that a
downstream system applied a side effect exactly once.

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
  --key-only)"   # or --json | jq -r .api_key

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
