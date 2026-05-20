# RegEngine Governed MCP Bridge Demo

This demo proves the RegEngine operator review read path can be exposed as a
governed MCP tool without giving an agent raw, unmetered access to RegEngine.

The bridge tool is:

- `regengine.agent_reviews.list`
- read-only
- marked `requiresPermit` in MCP discovery
- charged as one `platform_fee` query per successful invocation
- idempotent through the MCP trust plane
- receipted and audit-chain verifiable

## Local Proof

Run:

```bash
make demo-regengine-bridge-check
```

The proof uses a throwaway SQLite database and a stubbed in-process RegEngine
response. It does not call production RegEngine. The script verifies:

1. MCP discovery exposes `regengine.agent_reviews.list` as permit-required.
2. A wallet-scoped runtime key can invoke the tool only with a signed permit.
3. A successful call receives a signed receipt and exactly one ledger debit.
4. Replaying the same idempotency key returns the same receipt without a second
   RegEngine fetch or duplicate charge.
5. A wrong-scope permit is denied before the RegEngine fetch and receives a
   zero-charge denial receipt.
6. The wallet audit chain remains valid.

For a human-readable run:

```bash
make demo-regengine-bridge
```

For a machine-readable proof artifact:

```bash
python scripts/demo_regengine_bridge.py --assert --json
```

## Live Configuration

The adapter defaults to:

```text
REGENGINE_API_URL=https://regengine-production.up.railway.app
```

Set `REGENGINE_API_KEY` when the target RegEngine deployment requires an API
key. The adapter sends it as `X-API-Key`.

The public MCP call does not accept a caller-supplied base URL. Operators own
the target RegEngine deployment through environment configuration so an agent
cannot redirect the bridge to an arbitrary host.

## Trust Boundary

The bridge does not persist RegEngine data and does not mutate evidence,
reviews, or ledger records inside RegEngine. It is a governed read adapter:
the local MCP trust plane owns authorization, metering, receipt signing,
idempotency replay, and audit evidence for the agent-to-tool action.
