# MCP Registry Submission

## URL: https://registry.modelcontextprotocol.io/servers

## JSON Payload (copy-paste ready)

```json
{
  "name": "Agent Middleware API",
  "description": "The open-source B2A control plane with full MCP + Agentic Web Interface (AWI). Agents discover, simulate, pay, and act securely on any website — without fighting human-designed UIs. Provides billing, telemetry, IoT bridging, agent-to-agent messaging, and AI-powered decision making.",
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
    "Agentic Web Interface (AWI) - arXiv:2506.10953v1 implementation",
    "Billing & wallet management with Stripe integration",
    "Agent-to-agent messaging and transfers",
    "IoT protocol bridging (MQTT, CoAP, Zigbee)",
    "Telemetry and anomaly detection",
    "Behavioral and dry-run sandboxes",
    "LLM-powered decision making and self-healing",
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
  "description": "Open-source B2A control plane with MCP + AWI",
  "url": "https://api-service-production-433c.up.railway.app"
}
```

This helps agents discover the MCP server when cloning the repo.
