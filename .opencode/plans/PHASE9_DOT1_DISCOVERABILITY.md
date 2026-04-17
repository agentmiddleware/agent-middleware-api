# Phase 9.1: Agent Discoverability Sprint — Implementation Plan

**Goal**: Make the entire platform (MCP + AWI + Phase 9 features) instantly discoverable by autonomous agents.

**Status of Existing Discovery Surfaces**:
| Surface | Location | Status | Gap |
|---------|----------|--------|-----|
| `/.well-known/agent.json` | `app/routers/well_known.py` | ✅ Exists | Missing Phase 9 capabilities |
| `/v1/discover` | `app/routers/discover.py` | ✅ Exists | Missing Phase 9 endpoints |
| `/mcp/tools.json` | `app/routers/mcp.py` | ✅ Exists | Phase 9 services not registered |
| `llm.txt` | `static/llm.txt` | ✅ Exists | Missing Phase 9 documentation |

---

## Implementation Order

### Phase 1: Update `app/routers/discover.py` (Priority: High)

Add Phase 9 capabilities to the discovery manifest.

**File**: `app/routers/discover.py`

**Changes Required**:

1. Add new `ServiceCapability` entries:
```python
ServiceCapability(
    name="passkey",
    version="1.0",
    description="FIDO2/WebAuthn passkey verification for high-risk AWI actions",
    category="security",
),
ServiceCapability(
    name="dom_bridge",
    version="1.0",
    description="Bidirectional DOM↔AWI translation via Playwright for real browser automation",
    category="automation",
),
ServiceCapability(
    name="rag_memory",
    version="1.0",
    description="Semantic memory over AWI sessions with vector store and retrieval",
    category="intelligence",
),
```

2. Add new MCP tools:
```python
MCPToolInfo(
    service_id="passkey",
    name="create_passkey_challenge",
    description="Create WebAuthn challenge for high-risk action verification",
    category="security",
    credits_per_call=2.0,
    unit_name="challenge",
),
MCPToolInfo(
    service_id="passkey",
    name="verify_passkey",
    description="Verify WebAuthn credential response",
    category="security",
    credits_per_call=1.0,
    unit_name="verification",
),
MCPToolInfo(
    service_id="dom_bridge",
    name="create_dom_session",
    description="Create browser session for DOM automation",
    category="automation",
    credits_per_call=5.0,
    unit_name="session",
),
MCPToolInfo(
    service_id="dom_bridge",
    name="sync_dom",
    description="Execute AWI action via real browser",
    category="automation",
    credits_per_call=3.0,
    unit_name="action",
),
MCPToolInfo(
    service_id="rag_memory",
    name="query_memories",
    description="Semantic search over past AWI sessions",
    category="intelligence",
    credits_per_call=2.0,
    unit_name="query",
),
MCPToolInfo(
    service_id="rag_memory",
    name="get_session_context",
    description="Get relevant context from past sessions",
    category="intelligence",
    credits_per_call=2.0,
    unit_name="context",
),
```

3. Add Phase 9 AWI endpoints:
```python
AWIEndpoint(
    path="/v1/awi/passkey/challenge",
    method="POST",
    description="Create WebAuthn challenge for high-risk action verification",
    action_type="security",
),
AWIEndpoint(
    path="/v1/awi/passkey/verify",
    method="POST",
    description="Verify WebAuthn credential response",
    action_type="security",
),
AWIEndpoint(
    path="/v1/awi/dom/session",
    method="POST",
    description="Create browser session for DOM automation",
    action_type="browser_automation",
),
AWIEndpoint(
    path="/v1/awi/dom/sync",
    method="POST",
    description="Execute AWI action via Playwright",
    action_type="browser_automation",
),
AWIEndpoint(
    path="/v1/awi/rag/query",
    method="POST",
    description="Semantic search over session memories",
    action_type="memory",
),
AWIEndpoint(
    path="/v1/awi/rag/context/{session_id}",
    method="GET",
    description="Get context from past sessions for current session",
    action_type="memory",
),
```

---

### Phase 2: Update `app/routers/well_known.py` (Priority: High)

Enhance `/.well-known/agent.json` with Phase 9 capabilities.

**File**: `app/routers/well_known.py`

**Changes Required**:

1. Update capabilities list:
```python
capabilities=[
    "billing",
    "telemetry",
    "agent_communication",
    "ai_decision_making",
    "mcp_tools",
    "awi_automation",
    "sandbox_testing",
    "passkey_auth",          # NEW
    "dom_bridge",           # NEW
    "rag_memory",            # NEW
],
```

2. Add Phase 9 endpoints:
```python
endpoints={
    "api_base": "/v1",
    "discovery": "/v1/discover",
    "mcp": "/mcp",
    "awi": "/v1/awi",
    "awi_passkey": "/v1/awi/passkey",
    "awi_dom": "/v1/awi/dom",
    "awi_rag": "/v1/awi/rag",
    "billing": "/v1/billing",
    "telemetry": "/v1/telemetry",
    "comms": "/v1/comms",
    "ai": "/v1/ai",
    "health": "/health",
},
```

3. Add Phase 9 pricing info:
```python
"phase9": {
    "passkey": {
        "description": "WebAuthn/FIDO2 biometric verification",
        "credits_per_verification": 1.0,
    },
    "dom_bridge": {
        "description": "Real browser automation via Playwright",
        "credits_per_session": 5.0,
        "credits_per_action": 3.0,
    },
    "rag_memory": {
        "description": "Semantic memory and context retrieval",
        "credits_per_query": 2.0,
        "credits_per_index": 1.0,
    },
},
```

---

### Phase 3: Update `static/llm.txt` (Priority: Medium)

Add comprehensive Phase 9 documentation.

**File**: `static/llm.txt`

**New Section to Add** (after AWI section):

```markdown
## Phase 9: Advanced AWI Features

### Passkey Authentication

For high-risk actions (checkout, payment, account deletion), use WebAuthn passkey verification:

```bash
# 1. Create challenge
POST /v1/awi/passkey/challenge
{"session_id": "...", "action": "checkout"}

# 2. Client uses navigator.credentials.get() with challenge
# 3. Verify response
POST /v1/awi/passkey/verify
{"challenge_id": "...", "credential": {...}}

# 4. Now execute the high-risk action
POST /v1/awi/execute
{"session_id": "...", "action": "checkout"}
```

High-risk actions requiring passkey:
- checkout, payment, transfer_funds
- delete_account, change_password
- modify_billing, submit_pii

### DOM Bridge (Real Browser Automation)

Interact with ANY website using Playwright:

```bash
# Create browser session
POST /v1/awi/dom/session
{"target_url": "https://shop.example.com"}

# Execute AWI action via real browser
POST /v1/awi/dom/sync
{"session_id": "...", "action": "search_and_sort", "parameters": {"query": "laptop"}}

# Get DOM state
GET /v1/awi/dom/state/{session_id}
```

### RAG Memory

Semantic search over past AWI sessions:

```bash
# Index a session
POST /v1/awi/rag/index
{"session_id": "...", "session_type": "shopping", "action_history": [...]}

# Query past sessions
POST /v1/awi/rag/query
{"query": "shopping for laptops last week", "top_k": 5}

# Get context for current session
GET /v1/awi/rag/context/{session_id}
```

---

### Phase 4: Update `app/routers/mcp.py` (Priority: Medium)

Register Phase 9 services in MCP tool registry.

**File**: `app/routers/mcp.py`

**Changes Required**:

The MCP tool generation uses `get_mcp_generator()`. We need to ensure Phase 9 services are registered in the service registry.

Option A: Auto-discover from service registry (preferred)
Option B: Manual registration in `mcp_generator.py`

**Recommended**: Create a new file `app/services/mcp_phase9_tools.py` that registers Phase 9 services:

```python
"""Phase 9 MCP tool registrations."""

from app.services.service_registry import get_service_registry

def register_phase9_tools():
    registry = get_service_registry()

    # Passkey tools
    registry.register_local(
        service_id="passkey_create_challenge",
        name="Create Passkey Challenge",
        func=_create_challenge,
        input_model=ChallengeRequest,
        output_model=ChallengeResponse,
    )

    registry.register_local(
        service_id="passkey_verify",
        name="Verify Passkey",
        func=_verify_passkey,
        input_model=VerifyRequest,
        output_model=VerifyResponse,
    )

    # DOM Bridge tools
    registry.register_local(
        service_id="dom_create_session",
        name="Create DOM Session",
        func=_create_dom_session,
        input_model=DOMSessionRequest,
        output_model=DOMSessionResponse,
    )

    registry.register_local(
        service_id="dom_sync",
        name="Sync DOM Action",
        func=_dom_sync,
        input_model=DOMSyncRequest,
        output_model=DOMSyncResponse,
    )

    # RAG tools
    registry.register_local(
        service_id="rag_query",
        name="Query Memories",
        func=_query_memories,
        input_model=RAGQueryRequest,
        output_model=RAGQueryResponse,
    )

    registry.register_local(
        service_id="rag_context",
        name="Get Session Context",
        func=_get_context,
        input_model=SessionContextRequest,
        output_model=SessionContextResponse,
    )
```

Then call `register_phase9_tools()` at app startup in `main.py`.

---

### Phase 5: Create Example Agent (Priority: Low)

Demonstrate discovery + usage flow.

**File**: `examples/agent_discovery_example.py`

```python
"""
Example: Agent discovers platform and uses Phase 9 features.

Demonstrates:
1. Fetch discovery manifest
2. Register for MCP tools
3. Use passkey-protected checkout
4. Query past sessions via RAG
"""

import httpx

BASE_URL = "https://api.example.com"

async def agent_workflow():
    # 1. Discover capabilities
    async with httpx.AsyncClient() as client:
        manifest = await client.get(f"{BASE_URL}/v1/discover")
        print(f"Discovered {len(manifest['capabilities'])} capabilities")

    # 2. Create AWI session
    session = await client.post("/v1/awi/sessions", json={
        "target_url": "https://shop.example.com",
        "max_steps": 50,
    })

    # 3. Try checkout (requires passkey)
    result = await client.post("/v1/awi/execute", json={
        "session_id": session["session_id"],
        "action": "checkout",
    })

    if result["status"] == "passkey_required":
        # 4. Get passkey challenge
        challenge = await client.post("/v1/awi/passkey/challenge", json={
            "session_id": session["session_id"],
            "action": "checkout",
        })

        # 5. Client-side verification (simulated)
        credential = simulate_webauthn_flow(challenge)

        # 6. Verify passkey
        await client.post("/v1/awi/passkey/verify", json={
            "challenge_id": challenge["challenge_id"],
            "credential": credential,
        })

        # 7. Retry checkout
        result = await client.post("/v1/awi/execute", json={
            "session_id": session["session_id"],
            "action": "checkout",
        })

    # 8. Query past shopping sessions
    memories = await client.post("/v1/awi/rag/query", json={
        "query": "laptop shopping",
        "top_k": 3,
    })

    print(f"Found {len(memories['results'])} similar past sessions")
```

---

## File Changes Summary

| File | Change Type | Lines Changed |
|------|-------------|---------------|
| `app/routers/discover.py` | Update | +60 lines |
| `app/routers/well_known.py` | Update | +25 lines |
| `static/llm.txt` | Update | +80 lines |
| `app/services/mcp_phase9_tools.py` | New | ~150 lines |
| `app/main.py` | Update | +5 lines |
| `examples/agent_discovery_example.py` | New | ~100 lines |

---

## Testing Strategy

1. **Unit Tests** (`tests/test_discovery.py`):
```python
async def test_discover_includes_phase9():
    response = await client.get("/v1/discover")
    capabilities = response.json()["capabilities"]

    assert any(c["name"] == "passkey" for c in capabilities)
    assert any(c["name"] == "dom_bridge" for c in capabilities)
    assert any(c["name"] == "rag_memory" for c in capabilities)

async def test_agent_json_includes_phase9():
    response = await client.get("/.well-known/agent.json")
    manifest = response.json()

    assert "passkey_auth" in manifest["capabilities"]
    assert "dom_bridge" in manifest["capabilities"]
    assert "rag_memory" in manifest["capabilities"]
```

2. **Integration Test**:
```python
async def test_full_agent_discovery_flow(client):
    # 1. Discover
    manifest = await client.get("/v1/discover")
    assert manifest["version"] == "0.5.0"

    # 2. Get MCP tools
    tools = await client.get("/mcp/tools.json")
    phase9_tools = [t for t in tools["tools"]
                    if t["category"] in ["security", "automation", "intelligence"]]
    assert len(phase9_tools) >= 6

    # 3. Use llm.txt
    llm = await client.get("/llm.txt")
    assert "passkey" in llm.text.lower()
    assert "dom bridge" in llm.text.lower()
```

---

## Success Criteria

| Metric | Target |
|--------|--------|
| Discovery endpoints updated | 3 surfaces |
| Phase 9 capabilities in manifest | 3 new |
| Phase 9 MCP tools registered | 6 new |
| llm.txt Phase 9 coverage | 100% |
| Tests passing | +10 new |
| Backward compatibility | 100% |

---

## Implementation Effort

- **Estimated Time**: 2-3 hours
- **Risk**: Low (only extending existing surfaces)
- **Breaking Changes**: None
