# AWI Adoption Guide — Phase 8

**Based on arXiv:2506.10953v1 — "Build the web for agents, not agents for the web"**

This guide helps website owners and framework authors expose an **Agentic Web Interface (AWI)** that plugs into our middleware — without changing their existing human-facing UI.

---

## What is AWI?

AWI is a standardized, stateful interface layer that lets autonomous agents interact with your website using semantic actions instead of DOM manipulation.

**Benefits:**
- Agents can discover and use your services without reverse-engineering your UI
- Progressive representations let agents request exactly the data they need
- Built-in safety: human pause/steer, KYC verification, wallet billing
- No changes to your human UX required

---

## Quick Start (15 minutes)

### 1. Install the AWI Kit

```bash
pip install agent-middleware-awi
```

### 2. Generate Your AWI Manifest

```bash
# For FastAPI apps
python -m app.tools.awi_manifest_generator \
  --framework fastapi \
  --app-module main:app \
  --output .well-known/awi.json

# For existing OpenAPI specs
python -m app.tools.awi_manifest_generator \
  --openapi-spec openapi.json \
  --output .well-known/awi.json
```

### 3. Add AWI Endpoints to Your App

```python
from fastapi import FastAPI
from agent_middleware.awi import AWIAdapter

app = FastAPI()

# Mount AWI adapter
awi = AWIAdapter(
    middleware_url="https://your-middleware.example.com",
    api_key="your-middleware-api-key"
)
app.mount("/awi", awi.router)

# Serve the manifest
from fastapi.responses import FileResponse
@app.get("/.well-known/awi.json")
async def awi_manifest():
    return FileResponse(".well-known/awi.json")
```

### 4. Configure Security

```python
awi = AWIAdapter(
    middleware_url="https://your-middleware.example.com",
    api_key="your-key",
    require_kyc=True,      # Require KYC-verified wallets
    require_human_approval=["checkout", "purchase"],  # Actions needing approval
)
```

---

## Action Mapping

Map your existing routes to standardized AWI actions:

| AWI Action | Use Case |
|------------|----------|
| `search_and_sort` | Product search |
| `add_to_cart` | Add to shopping cart |
| `checkout` | Complete purchase |
| `fill_form` | Form submission |
| `login` / `logout` | Authentication |
| `navigate_to` | Page navigation |
| `extract_data` | Data scraping |

Example manifest mapping:

```json
{
  "route_mappings": {
    "search_and_sort": "/api/search",
    "add_to_cart": "/api/cart/add",
    "checkout": "/api/checkout",
    "login": "/api/auth/login"
  }
}
```

---

## Progressive Representations

Agents can request exactly the data they need:

```bash
# Get a summary (low bandwidth)
curl -X POST /awi/represent \
  -d '{"session_id": "...", "representation_type": "summary"}'

# Get semantic embedding
curl -X POST /awi/represent \
  -d '{"session_id": "...", "representation_type": "embedding"}'

# Get low-res screenshot
curl -X POST /awi/represent \
  -d '{"session_id": "...", "representation_type": "low_res_screenshot"}'
```

---

## Human Pause/Steer

Agents can pause for human review:

```python
# Agent pauses before destructive action
await client.pause(session_id, reason="Checkout requires human approval")

# Human reviews and approves
curl -X POST /awi/intervene \
  -d '{"session_id": "...", "action": "resume"}'
```

---

## Security Checklist

- [ ] AWI manifest generated and served at `/.well-known/awi.json`
- [ ] API key configured for middleware authentication
- [ ] KYC verification enabled for wallet billing
- [ ] Destructive actions (checkout, purchase) require human approval
- [ ] Rate limiting configured for AWI endpoints
- [ ] Monitoring/logging enabled for AWI sessions
- [ ] MCP fallback configured if AWI is unavailable

---

## Framework Templates

### FastAPI
```python
# examples/awi-fastapi/main.py
from fastapi import FastAPI
from agent_middleware.awi import AWIAdapter

app = FastAPI()
awi = AWIAdapter(middleware_url="https://your-middleware.example.com")
app.mount("/awi", awi.router)
```

### Next.js (coming soon)
```typescript
// awi_sdk/typescript
import { AWIClient } from "@agent-middleware/awi-sdk";

const client = new AWIClient({
  baseUrl: "https://api.example.com",
  apiKey: process.env.AWI_API_KEY!,
});
```

---

## MCP Fallback

If AWI is unavailable, agents fall back to MCP proxy:

```python
from agent_middleware.awi import AWIFallbackAdapter

adapter = AWIFallbackAdapter(
    middleware_url="https://your-middleware.example.com",
    api_key="your-key"
)
```

---

## Support

- GitHub Issues: https://github.com/PetrefiedThunder/agent-middleware-api/issues
- Documentation: https://github.com/PetrefiedThunder/agent-middleware-api#readme
- arXiv Paper: https://arxiv.org/abs/2506.10953
