# MCP Registry Submission

## URL: https://registry.modelcontextprotocol.io/servers

## JSON Payload (copy-paste ready)

Describe only what is mounted in a production-like deployment
(`ENABLE_PROOF_SURFACES=false`). Proof surfaces are frozen and must not be
listed as capabilities — see [`PROOF_SURFACES.md`](PROOF_SURFACES.md).

```json
{
  "name": "Agent Middleware API",
  "description": "Trust plane for governed MCP tool calls: scoped signed permits, wallet metering, replay-safe invocation, signed receipts, and tamper-evident audit chains. Canonical loop: discover -> authenticate -> authorize -> invoke -> meter -> receipt -> audit -> govern.",
  "url": "https://api-service-production-433c.up.railway.app",
  "github": "https://github.com/PetrefiedThunder/agent-middleware-api",
  "categories": [
    "infrastructure",
    "billing",
    "agentic-ai"
  ],
  "verifications": {
    "official": false,
    "repository_verified": true
  },
  "features": {
    "mcp": true,
    "sse": false,
    "stdio": false
  },
  "auth": {
    "type": "api_key",
    "header": "X-API-Key"
  },
  "capabilities": [
    "Governed MCP tool invocation requiring a signed permit and idempotency key",
    "Wallet-scoped identity and operator-provisioned delegated credentials",
    "Ed25519-signed permits binding wallet, key, tool, scope, budget, and expiry",
    "Replay-safe metering: one idempotency key, one dispatch, one debit",
    "Ed25519-signed receipts with request/response hashes and evidence bundles",
    "Per-wallet tamper-evident hash-chain audit with verification endpoint"
  ],
  "mcpEndpoints": {
    "tools": "/mcp/tools.json",
    "messages": "/mcp/messages"
  },
  "discoveryEndpoints": {
    "agentManifest": "/.well-known/agent.json",
    "llmDocs": "/llms.txt",
    "openapi": "/openapi.json"
  },
  "contact": {
    "email": "support@agent-middleware.dev",
    "github": "https://github.com/PetrefiedThunder/agent-middleware-api/issues"
  }
}
```

`sse` and `stdio` are both `false`: the server implements the HTTP/JSON-RPC
tools subset at `/mcp/messages` and nothing else. `/mcp/messages` does not
implement the complete MCP initialization lifecycle, and `/mcp/tools.json` is a
convenience mirror of the MCP-native `tools/list` method rather than a
standard discovery path. Do not advertise a transport or lifecycle the server
does not serve.

---

## Manual Submission Steps

1. Go to: https://registry.modelcontextprotocol.io/servers
2. Click "Add Server" or "Submit"
3. Fill in the fields using the JSON above
4. Submit

## Verification After Submission

After the registry lists your server, agents can discover it via:
```bash
curl https://registry.modelcontextprotocol.io/api/servers/agent-middleware-api
```

---

## Server Metadata File (optional - add to repo root)

You can add a `.mcp.json` file to the repo root:

```json
{
  "name": "Agent Middleware API",
  "description": "Trust plane for governed MCP tool calls: signed permits, wallet metering, replay-safe invocation, signed receipts, and audit chains",
  "url": "https://api-service-production-433c.up.railway.app"
}
```

This helps agents discover the MCP server when cloning the repo. Keep its
description in sync with the payload above; a stale description here is the
kind of drift the discovery honesty tests exist to catch elsewhere.
