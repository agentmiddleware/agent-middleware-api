# MCP Registry Submission

## URL: https://registry.modelcontextprotocol.io/servers

## JSON Payload (copy-paste ready)

```json
{
  "name": "Agent Middleware API",
  "description": "Operational control plane for autonomous agents: identity, billing, discovery, policy, and execution governance for machine-native software tenants. Canonical loop: discover -> authenticate -> invoke -> meter -> govern.",
  "url": "https://api-service-production-433c.up.railway.app",
  "github": "https://github.com/PetrefiedThunder/agent-middleware-api",
  "categories": [
    "infrastructure",
    "billing",
    "telemetry",
    "agentic-ai"
  ],
  "verifications": {
    "official": false,
    "repository_verified": true
  },
  "features": {
    "mcp": true,
    "sse": true,
    "stdio": false
  },
  "auth": {
    "type": "api_key",
    "header": "X-API-Key"
  },
  "capabilities": [
    "MCP Server (Model Context Protocol) with auto-discovery",
    "Wallet-scoped identity and delegated credentials",
    "Billing, dry-run pricing, and ledgering with Stripe integration",
    "Policy-constrained execution and planner optimization",
    "Telemetry, audit surfaces, and readiness checks",
    "Behavioral and dry-run sandboxes",
    "Agentic Web Interface (AWI) proof surface",
    "Agent-to-agent messaging and transfers",
    "WebAuthn/passkey for high-risk actions",
    "RAG memory over AWI session history"
  ],
  "mcpEndpoints": {
    "tools": "/mcp/tools.json",
    "messages": "/mcp/messages",
    "sse": "/mcp/sse"
  },
  "discoveryEndpoints": {
    "agentManifest": "/.well-known/agent.json",
    "llmDocs": "/llm.txt",
    "openapi": "/openapi.json"
  },
  "contact": {
    "email": "support@agent-middleware.dev",
    "github": "https://github.com/PetrefiedThunder/agent-middleware-api/issues"
  }
}
```

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
  "description": "Operational control plane for autonomous agents",
  "url": "https://api-service-production-433c.up.railway.app"
}
```

This helps agents discover the MCP server when cloning the repo.
