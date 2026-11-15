# Phase 9: Paper-Aligned AWI Enhancements Blueprint

**Based on arXiv:2506.10953v1 Gap Analysis**
**Target: v0.5.0**

---

## Executive Summary

Phase 9 closes the remaining gaps from the AWI position paper, delivering three critical extensions:

| Gap | Component | Strategic Value | Effort |
|-----|-----------|-----------------|--------|
| Passkeys / Biometric Auth | `webauthn_provider.py` | Highest safety/compliance impact | Medium |
| Bidirectional DOM Translation | `awi_playwright_bridge.py` | Highest adoption impact | Medium-High |
| AWI RAG Memory | `awi_rag_engine.py` | Enables long-term agent reasoning | Medium |

**Zero Breaking Changes** — All integrations use extension patterns, not modifications.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FastAPI Application                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                   │
│  │  awi.py     │    │ awi_enhanced│    │  ai.py      │                   │
│  │  (existing) │    │ .py (NEW)   │    │  (existing) │                   │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                   │
│         │                   │                   │                          │
│         ▼                   ▼                   ▼                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Service Layer (Dependency Injection)               │   │
│  ├──────────────┬──────────────┬──────────────┬──────────────────────┤   │
│  │ AWISession   │ AWITaskQueue │ AWIRAGEngine │ WebAuthnProvider     │   │
│  │ Manager      │              │ (NEW)        │ (NEW)                 │   │
│  ├──────────────┴──────────────┴──────────────┴──────────────────────┤   │
│  │ AWIActionVocab │ ProgressiveRep │ AWIPlaywrightBridge (NEW)       │   │
│  │                │ Engine         │                                  │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                    External Integrations                             │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │  │
│  │  │   Redis     │  │  ChromaDB   │  │  WebAuthn   │                 │  │
│  │  │  (sessions) │  │  (vectors) │  │  (FIDO2)    │                 │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                 │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           AWI Action Execution Flow                      │
└─────────────────────────────────────────────────────────────────────────┘

1. Agent sends → POST /v1/awi/execute
                    │
                    ▼
2. AWISessionManager.execute_action()
                    │
        ┌───────────┴───────────┐
        │                       │
   Check Passkey?         Check Preconditions
        │                       │
        ▼                       ▼
   (await verification)    (validate params)
        │                       │
        └───────────┬───────────┘
                    │
                    ▼
3. AWIPlaywrightBridge.translate_to_real_dom()
                    │
                    ▼
4. Execute via Playwright CDP
                    │
                    ▼
5. AWIPlaywrightBridge.translate_from_real_dom()
                    │
                    ▼
6. ProgressiveRepresentationEngine.generate()
                    │
                    ▼
7. AWIRAGEngine.index_session_state()  ← NEW: Store for RAG
                    │
                    ▼
8. Return AWIExecutionResponse
```

---

## New Components Specification

### 1. WebAuthn Provider (`app/services/webauthn_provider.py`)

**Purpose**: FIDO2/WebAuthn passkey authentication for high-risk AWI actions.

#### Class Structure

```python
from typing import Optional
from dataclasses import dataclass
from enum import Enum
import json
import base64
import uuid
from datetime import datetime, timedelta

class WebAuthnProvider:
    """WebAuthn/Passkey flow for high-risk AWI actions."""

    class ChallengeStatus(str, Enum):
        PENDING = "pending"
        VERIFIED = "verified"
        FAILED = "failed"
        EXPIRED = "expired"

    @dataclass
    class Challenge:
        challenge_id: str
        session_id: str
        action: str
        challenge: bytes
        status: ChallengeStatus
        created_at: datetime
        expires_at: datetime
        rp_id: str
        user_verification: str = "preferred"

    def __init__(
        self,
        rp_id: str = "localhost",
        rp_name: str = "Agent-Native Middleware",
        timeout_ms: int = 60000,
        challenge_expiry_seconds: int = 300,
    ):
        self._rp_id = rp_id
        self._rp_name = rp_name
        self._timeout_ms = timeout_ms
        self._challenge_expiry = challenge_expiry_seconds
        self._challenges: dict[str, Challenge] = {}
        self._verified_actions: dict[str, datetime] = {}

    async def requires_passkey(self, session_id: str, action: str) -> bool:
        HIGH_RISK_ACTIONS = {
            "checkout", "payment", "transfer_funds", "delete_account",
            "change_password", "modify_billing", "add_payment_method",
            "submit_pii", "export_user_data",
        }
        return action.lower() in HIGH_RISK_ACTIONS

    async def create_challenge(
        self,
        session_id: str,
        action: str,
        user_id: Optional[str] = None,
    ) -> dict:
        challenge_id = str(uuid.uuid4())
        challenge_bytes = os.urandom(32)

        challenge = self.Challenge(
            challenge_id=challenge_id,
            session_id=session_id,
            action=action,
            challenge=challenge_bytes,
            status=self.ChallengeStatus.PENDING,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(seconds=self._challenge_expiry),
            rp_id=self._rp_id,
        )

        self._challenges[challenge_id] = challenge

        return {
            "challenge_id": challenge_id,
            "challenge": base64.urlsafe_b64encode(challenge_bytes).decode("ascii").rstrip("="),
            "rp_id": self._rp_id,
            "rp_name": self._rp_name,
            "timeout": self._timeout_ms,
            "user_verification": "preferred",
            "public_key_cred_params": [
                {"alg": -7, "type": "public-key"},
                {"alg": -257, "type": "public-key"},
            ],
            "exclude_credentials": [],
            "authenticator_selection": {
                "authenticator_attachment": "platform",
                "resident_key": "preferred",
                "user_verification": "preferred",
            },
        }

    async def verify_response(
        self,
        challenge_id: str,
        credential: dict,
    ) -> dict:
        challenge = self._challenges.get(challenge_id)
        if not challenge:
            raise ValueError("Challenge not found")
        if challenge.status != self.ChallengeStatus.PENDING:
            raise ValueError(f"Challenge already processed: {challenge.status}")
        if datetime.utcnow() > challenge.expires_at:
            challenge.status = self.ChallengeStatus.EXPIRED
            raise ValueError("Challenge expired")

        verified = self._verify_credential_signature(challenge, credential)
        if not verified:
            challenge.status = self.ChallengeStatus.FAILED
            raise ValueError("Credential verification failed")

        challenge.status = self.ChallengeStatus.VERIFIED
        verification_key = f"{challenge.session_id}:{challenge.action}"
        self._verified_actions[verification_key] = datetime.utcnow()

        return {
            "verified": True,
            "challenge_id": challenge_id,
            "session_id": challenge.session_id,
            "action": challenge.action,
            "verified_at": datetime.utcnow().isoformat(),
            "expires_in_seconds": 300,
        }

    async def is_action_verified(self, session_id: str, action: str) -> bool:
        verification_key = f"{session_id}:{action}"
        verified_at = self._verified_actions.get(verification_key)
        if not verified_at:
            return False
        if datetime.utcnow() > verified_at + timedelta(minutes=5):
            del self._verified_actions[verification_key]
            return False
        return True


def get_webauthn_provider() -> WebAuthnProvider:
    global _webauthn_provider
    if _webauthn_provider is None:
        _webauthn_provider = WebAuthnProvider(
            rp_id=settings.WEBAUTHN_RP_ID,
            rp_name=settings.WEBAUTHN_RP_NAME,
        )
    return _webauthn_provider
```

---

### 2. Playwright Bridge — Deep Dive

**Purpose**: Bidirectional translation between AWI actions and real browser DOM manipulation.

#### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      AWIPlaywrightBridge Architecture                       │
└─────────────────────────────────────────────────────────────────────────────┘

                        ┌─────────────────────────────┐
                        │   AWIPlaywrightBridge       │
                        │  ┌───────────────────────┐  │
                        │  │ DOM-to-AWI Translator  │  │
                        │  │ - Element extraction   │  │
                        │  │ - Semantic mapping    │  │
                        │  └───────────────────────┘  │
                        │            ▲                │
                        │            │                │
                        │  ┌─────────┴─────────┐      │
                        │  │  AWI Action       │      │
                        │  │  Vocabulary       │      │
                        │  │  Resolver         │      │
                        │  └─────────┬─────────┘      │
                        │            │                │
                        │  ┌─────────▼─────────┐      │
                        │  │ AWI-to-DOM        │      │
                        │  │ Translator        │      │
                        │  │ - Selector gen    │      │
                        │  │ - Event dispatch  │      │
                        │  └───────────────────┘      │
                        └────────────┬────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
                    ▼                ▼                ▼
            ┌───────────┐    ┌───────────────┐   ┌───────────┐
            │ Playwright│    │  CDP Bridge   │   │  Browser  │
            │  (Python) │    │  (optional)   │   │  Context  │
            └───────────┘    └───────────────┘   └───────────┘
```

#### Key Features

1. **AWI-to-DOM Translation**: Convert semantic actions like `search_and_sort` to Playwright commands
2. **DOM-to-AWI Translation**: Extract semantic meaning from DOM for state representation
3. **Selector Optimization**: Generate robust CSS/XPath selectors
4. **State Observation**: Track DOM mutations for accurate state reporting

#### Semantic Patterns

```python
SEMANTIC_PATTERNS = {
    "search_input": {
        "tags": ["input", "textarea"],
        "attributes": ["type~=search", "placeholder~=search", "aria-label~=search"],
    },
    "email_input": {
        "tags": ["input"],
        "attributes": ["type=email", "name~=email", "autocomplete=email"],
    },
    "password_input": {
        "tags": ["input"],
        "attributes": ["type=password"],
    },
    "add_to_cart": {
        "tags": ["button", "a"],
        "attributes": ["aria-label~=cart", "data-action~=add.*cart", "class~=add-to-cart"],
    },
    "checkout": {
        "tags": ["button", "a"],
        "attributes": ["aria-label~=checkout", "class~=checkout"],
    },
    "sort_dropdown": {
        "tags": ["select", "button"],
        "attributes": ["aria-label~=sort", "class~=sort", "role=listbox"],
    },
}
```

#### Action Translation Handlers

```python
async def _handle_search_and_sort(self, session, params):
    commands = []
    query = params.get("query", "")
    sort_by = params.get("sort_by")

    search_element = await self._find_semantic_element(session, "search_input")
    if search_element:
        commands.append(PlaywrightCommand(
            command_type="fill",
            target=search_element.css_selector,
            value=query,
        ))
        commands.append(PlaywrightCommand(
            command_type="press",
            target=search_element.css_selector,
            value="Enter",
        ))

    if sort_by:
        sort_element = await self._find_semantic_element(session, "sort_dropdown")
        if sort_element:
            commands.append(PlaywrightCommand(
                command_type="select",
                target=sort_element.css_selector,
                value=self._get_sort_option_value(sort_by),
            ))

    return commands

async def _handle_add_to_cart(self, session, params):
    cart_element = await self._find_semantic_element(session, "add_to_cart")
    if not cart_element:
        raise ValueError("No add-to-cart element found")

    return [PlaywrightCommand(
        command_type="click",
        target=cart_element.css_selector,
        options={"timeout": 10000},
    )]

async def _handle_fill_form(self, session, params):
    commands = []
    form_data = params.get("data", {})

    for field_name, value in form_data.items():
        field_type = self._infer_field_type(field_name, value)
        element = await self._find_semantic_element(session, field_type)

        if not element:
            element = await self._find_element_by_label(session, field_name)

        if element:
            commands.append(PlaywrightCommand(
                command_type="fill",
                target=element.css_selector,
                value=str(value),
            ))

    return commands
```

---

### 3. AWI RAG Engine

**Purpose**: Vector store + semantic retrieval over past AWI session states.

```python
class AWIRAGEngine:
    @dataclass
    class SessionMemory:
        memory_id: str
        session_id: str
        session_type: str
        action_sequence: list[str]
        page_summaries: list[str]
        key_entities: list[str]
        user_intent: str
        raw_state: dict
        embedding: list[float]
        created_at: datetime
        accessed_at: datetime
        access_count: int = 0

    async def index_session(
        self,
        session_id: str,
        session_type: str,
        action_history: list[dict],
        state_snapshots: list[dict],
    ) -> str:
        memory_id = str(uuid.uuid4())
        action_sequence = [a.get("action", "") for a in action_history]
        page_summaries = [s.get("summary", "") for s in state_snapshots]
        key_entities = self._extract_entities(action_history, state_snapshots)
        user_intent = self._infer_intent(action_sequence, state_snapshots)
        embedding = await self._generate_embedding(
            self._prepare_embedding_text(session_type, action_sequence, page_summaries, key_entities)
        )
        # Store memory...
        return memory_id

    async def search(
        self,
        query: str,
        session_type: Optional[str] = None,
        top_k: int = 5,
        similarity_threshold: float = 0.7,
    ) -> list[dict]:
        query_embedding = await self._generate_embedding(query)
        results = []
        for memory_id, memory in self._memories.items():
            if session_type and memory.session_type != session_type:
                continue
            similarity = self._cosine_similarity(query_embedding, memory.embedding)
            if similarity >= similarity_threshold:
                results.append({
                    "memory_id": memory_id,
                    "session_id": memory.session_id,
                    "user_intent": memory.user_intent,
                    "action_sequence": memory.action_sequence[:5],
                    "similarity_score": similarity,
                    "key_entities": memory.key_entities[:10],
                })
        results.sort(key=lambda x: x["similarity_score"], reverse=True)
        return results[:top_k]
```

---

## New Endpoints

### Passkey Endpoints

```
POST   /v1/awi/passkey/challenge   Create WebAuthn challenge
POST   /v1/awi/passkey/verify      Verify credential response
```

### DOM Sync Endpoints

```
POST   /v1/awi/dom/session         Create browser session
DELETE /v1/awi/dom/session/{id}   Destroy browser session
POST   /v1/awi/dom/sync            Execute AWI action via Playwright
GET    /v1/awi/dom/state/{id}      Get DOM state representation
```

### RAG Endpoints

```
POST   /v1/awi/rag/index           Index completed session
POST   /v1/awi/rag/query           Semantic search over memories
GET    /v1/awi/rag/context/{id}   Get context for current session
```

---

## Integration Points

### 1. Register router in `main.py`

```python
from .routers import awi_enhanced

app.include_router(awi_enhanced.router)
```

### 2. Wire into AWISessionManager

```python
# In execute_action() - ADD passkey check
async def execute_action(self, request: AWIExecutionRequest) -> AWIExecutionResponse:
    webauthn = get_webauthn_provider()
    if await webauthn.requires_passkey(session_id, request.action.value):
        if not await webauthn.is_action_verified(session_id, request.action.value):
            return AWIExecutionResponse(
                status="passkey_required",
                error="This action requires biometric verification. "
                      "Call POST /v1/awi/passkey/challenge first.",
            )
    # ... rest of execution
```

### 3. Wire into AWIRAGEngine after execution

```python
# After action completes in AWISessionManager
rag = get_awi_rag_engine()
await rag.index_session(
    session_id=session_id,
    session_type=classify_session_type(session),
    action_history=session.action_history,
    state_snapshots=session.representation_history,
)
```

---

## File Structure

```
app/
├── services/
│   ├── webauthn_provider.py        # NEW - WebAuthn/Passkey flow
│   ├── awi_playwright_bridge.py     # NEW - Bidirectional DOM translation
│   ├── awi_rag_engine.py           # NEW - Vector store + retrieval
│   ├── awi_session.py              # MODIFIED - add passkey check
│   └── awi_task_queue.py           # MODIFIED - add passkey status
│
├── routers/
│   ├── awi.py                      # (existing)
│   └── awi_enhanced.py             # NEW - all Phase 9 endpoints
│
├── schemas/
│   ├── awi.py                      # (existing)
│   └── awi_enhanced.py             # NEW - Pydantic models
│
└── core/
    ├── config.py                    # MODIFIED - add Phase 9 settings
    └── dependencies.py              # MODIFIED - add singletons
```

---

## Configuration

```python
# core/config.py additions
WEBAUTHN_RP_ID: str = "localhost"
WEBAUTHN_RP_NAME: str = "Agent-Native Middleware"
PLAYWRIGHT_HEADLESS: bool = True
PLAYWRIGHT_BROWSER_TYPE: str = "chromium"
RAG_VECTOR_STORE_PATH: str = "./data/awi_vectors"
RAG_EMBEDDING_MODEL: str = "text-embedding-3-small"
```

---

## Implementation Order

### Sprint 1: WebAuthn Provider
1. `app/services/webauthn_provider.py`
2. Add schemas to `app/schemas/awi_enhanced.py`
3. Create endpoints in `app/routers/awi_enhanced.py`
4. Wire into `AWISessionManager.execute_action()`
5. Add configuration to `core/config.py`
6. Write unit tests

### Sprint 2: Playwright Bridge
1. `app/services/awi_playwright_bridge.py`
2. Implement action translation handlers
3. Implement DOM-to-AWI extraction
4. Add DOM session endpoints
5. Wire into `behavioral_sandbox.py`
6. Write integration tests

### Sprint 3: RAG Engine
1. `app/services/awi_rag_engine.py`
2. Implement embedding generation
3. Implement vector storage
4. Add RAG query endpoints
5. Wire into `ProgressiveRepresentationEngine`
6. Write tests

---

## Success Criteria

| Metric | Target |
|--------|--------|
| New endpoints | 8 (2 passkey, 4 DOM, 2 RAG) |
| Code coverage | >90% for new components |
| Backward compatibility | 100% (no breaking changes) |
| Performance impact | <5ms added latency |
