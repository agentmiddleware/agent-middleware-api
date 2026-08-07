# Trust Plane Gap Closure Plan

**Target:** Close P0-P1 gaps identified in competitive analysis
**Timeline:** 6 weeks to production-ready enterprise trust plane
**Owner:** Agent-Middleware-API maintainers

---

## Phase 1: Defense & Hardening (Week 1)

### 1.1 Rate Limiting — P0
**Problem:** No DDoS protection. Consumer stress test fired 50 calls/sec with no throttling.
**Solution:** Token-bucket rate limiter per wallet + global burst protection.

```python
# app/core/rate_limit.py
class RateLimiter:
    """Token-bucket rate limiter backed by Redis.

    Per-wallet: 100 req/min burst, 10 req/s sustained.
    Global: 1000 req/s across all wallets.
    """
    async def check(self, wallet_id: str, key_id: str | None = None) -> bool
    async def record(self, wallet_id: str) -> None
```

**Deliverables:**
- [ ] `app/core/rate_limit.py` — token bucket implementation
- [ ] Redis integration (use existing Redis on Railway)
- [ ] Middleware: `RateLimitMiddleware` in `app/main.py`
- [ ] Headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- [ ] 429 response with `Retry-After`
- [ ] Test: 101st call in 1 minute returns 429

**Est. effort:** 1 day

### 1.2 Security Vulnerability Triage — P0
**Problem:** GitHub Dependabot flagged 7 vulnerabilities (1 critical, 5 high, 1 moderate).
**Solution:** Audit and patch.

**Deliverables:**
- [ ] Review https://github.com/PetrefiedThunder/agent-middleware-api/security/dependabot
- [ ] Update `requirements.txt` for critical + high severity
- [ ] Run full test suite post-update
- [ ] Document any breaking changes

**Est. effort:** 0.5 days

### 1.3 Budget Alerts — P1
**Problem:** Wallets hit zero with no warning. Sponsor has no visibility.
**Solution:** Threshold alerts stored in `BillingAlertModel`.

```python
# app/services/billing.py
async def check_budget_alerts(wallet_id: str):
    """Fire alerts at 80%, 90%, 100% of budget."""
```

**Deliverables:**
- [ ] Alert generation on permit creation (if budget < max_credits)
- [ ] Alert generation on each debit (threshold crossing)
- [ ] `GET /v1/me/alerts` endpoint
- [ ] Webhook delivery of alerts (foundation for Phase 3)

**Est. effort:** 1 day

---

## Phase 2: Enterprise Identity (Week 2-3)

### 2.1 OAuth 2.1 + PKCE — P0
**Problem:** API keys are "toy" auth to enterprise security teams. No SSO/SAML.
**Solution:** Implement OAuth 2.1 authorization server with PKCE.

```
POST /v1/oauth/authorize   → redirect to IdP (Google, GitHub, custom SAML)
POST /v1/oauth/token       → exchange code for access_token + refresh_token
GET  /v1/oauth/userinfo    → identity claims (sub, email, org)
```

**Architecture:**
- Add `OAuthProviderModel` (idp config: client_id, client_secret, authorize_url, token_url)
- Add `OAuthTokenModel` (access_token, refresh_token, expires_at, wallet_id)
- Wallet creation on first OAuth login (auto-provision)
- Existing API keys remain for service-to-service

**Deliverables:**
- [ ] `app/routers/oauth.py` — OAuth 2.1 flows
- [ ] `app/services/oauth.py` — token management
- [ ] `app/db/models.py` — OAuth tables
- [ ] Alembic migration
- [ ] Support: Google OIDC, GitHub OAuth, generic SAML 2.0
- [ ] Test: full PKCE flow with mock IdP
- [ ] Docs: "Enterprise SSO Setup" guide

**Est. effort:** 3 days

### 2.2 JWT Access Tokens — P0
**Problem:** Long-lived API keys = high blast radius.
**Solution:** Short-lived JWTs (15 min access, 7 day refresh).

```python
# app/core/jwt.py
def create_access_token(wallet_id: str, scopes: list[str]) -> str:
    """JWT with exp=900s, iss=agent-middleware-api."""

def verify_access_token(token: str) -> JWTPayload:
    """Verify signature, exp, iss, aud."""
```

**Deliverables:**
- [ ] JWT signing/verification with Ed25519 (reuse existing key)
- [ ] `Authorization: Bearer <jwt>` header support
- [ ] Scope enforcement: `scp` claim checked against permit scopes
- [ ] Token refresh endpoint
- [ ] Test: expired token rejected, valid token accepted

**Est. effort:** 1.5 days

---

## Phase 3: Observability & Integration (Week 4)

### 3.1 Webhook Delivery — P1
**Problem:** Consumers must poll for events. No push notifications.
**Solution:** Webhook subscription model with signed deliveries.

```python
# app/models/webhook.py
class WebhookSubscriptionModel(SQLModel, table=True):
    subscription_id: str
    wallet_id: str
    url: str
    events: list[str]  # ["permit.created", "receipt.created", "alert.fired"]
    secret: str        # HMAC-SHA256 signing key
    status: str        # active / paused / failed
```

**Delivery format:**
```json
{
  "event_id": "evt-...",
  "event_type": "receipt.created",
  "timestamp": "2026-08-04T22:00:00Z",
  "data": { ...receipt object... },
  "signature": "sha256=<hmac>"
}
```

**Deliverables:**
- [ ] `app/routers/webhooks.py` — CRUD subscriptions
- [ ] `app/services/webhook_delivery.py` — async delivery with retry
- [ ] Event bus: publish on permit create, receipt create, alert fire
- [ ] Retry logic: exponential backoff, max 24h, dead-letter after N failures
- [ ] Test: delivery success, retry on 500, pause on repeated failure

**Est. effort:** 2 days

### 3.2 Dashboard API (Read-Only) — P2
**Problem:** No web UI for wallet inspection.
**Solution:** Read-only dashboard endpoints (UI can be built later).

```python
# app/routers/dashboard.py
GET /v1/dashboard/summary → wallet count, total credits, recent activity
GET /v1/dashboard/wallet/{wallet_id} → balance graph, permit usage, receipt timeline
GET /v1/dashboard/audit-graph → event type distribution over time
```

**Deliverables:**
- [ ] Time-series aggregation queries (daily rollups)
- [ ] Caching layer (Redis) for expensive aggregations
- [ ] CSV export endpoint for compliance
- [ ] Test: aggregation accuracy

**Est. effort:** 1.5 days

---

## Phase 4: Cryptographic Hardening (Week 5)

### 4.1 HSM / KMS Signing Key Storage — P1
**Problem:** Signing key in `TRUST_SIGNING_PRIVATE_KEY_B64` env var = SOC2 failure.
**Solution:** Pluggable key backend supporting AWS KMS, HashiCorp Vault, and local HSM.

```python
# app/core/signing.py (refactored)
class KeyBackend(ABC):
    async def sign(self, payload: bytes) -> tuple[bytes, str]
    async def verify(self, payload: bytes, signature: bytes, key_id: str) -> bool

class EnvKeyBackend(KeyBackend): ...      # current (dev only)
class AWSKMSBackend(KeyBackend): ...      # AWS KMS + asymmetric keys
class VaultTransitBackend(KeyBackend): ... # HashiCorp Vault Transit
class PKCS11Backend(KeyBackend): ...      # YubiHSM, Thales Luna
```

**Deliverables:**
- [ ] Abstract `KeyBackend` interface
- [ ] `AWSKMSBackend` using ` boto3` + KMS Sign API
- [ ] `VaultTransitBackend` using `hvac` client
- [ ] Config: `SIGNING_BACKEND=env|kms|vault|pkcs11`
- [ ] Test: sign/verify round-trip with mock backends
- [ ] Docs: "Production Key Management" setup guide

**Est. effort:** 2.5 days

### 4.2 Key Rotation — P1
**Problem:** No automatic key rotation. Compromised key = permanent exposure.
**Solution:** Graceful rotation with dual-signature verification window.

```python
# Rotation workflow:
# 1. Generate new key pair
# 2. Sign new key with old key (attestation)
# 3. Accept both keys for 7-day window
# 4. After window, old key becomes "retired"
# 5. New receipts signed with new key only
```

**Deliverables:**
- [ ] `POST /v1/admin/signing-keys/rotate` endpoint (admin-only)
- [ ] Dual-key acceptance period (configurable, default 7 days)
- [ ] `SigningKeyModel.status` transitions: active → retiring → retired
- [ ] Backfill: re-sign recent permits with new key (optional)
- [ ] Test: old receipts still verify during window, fail after

**Est. effort:** 1.5 days

---

## Phase 5: Advanced Governance (Week 6)

### 5.1 Permit Delegation — P2
**Problem:** Complex orgs need agent A to delegate to agent B.
**Solution:** Delegated permits with transitive scope.

```python
# Delegation chain:
# Sponsor → Agent A (permit: tools=[X], max_credits=100)
# Agent A → Agent B (delegated permit: tools=[X], max_credits=50)
# Agent B can invoke X, spend tracked against Agent A's permit
```

**Deliverables:**
- [ ] `delegated_from_permit_id` field on `PermitModel`
- [ ] Validation: delegated scope ≤ parent scope
- [ ] Budget cascade: child spend debits parent
- [ ] Revocation cascade: revoke parent → all children revoked
- [ ] Test: 3-level delegation chain, revocation propagation

**Est. effort:** 2 days

### 5.2 Merkle Tree Audit Batching — P3
**Problem:** Verifying full audit chain is O(n). Batch verification needed.
**Solution:** Periodic merkle root publication.

```python
# Every hour, compute merkle root of all events since last root
# Publish root to external notary (optional: blockchain anchor)
class AuditMerkleRootModel(SQLModel, table=True):
    root_id: str
    merkle_root: str
    event_count: int
    first_event_id: str
    last_event_id: str
    timestamp: datetime
```

**Deliverables:**
- [ ] Merkle tree construction from event hashes
- [ ] Hourly cron job (or background task)
- [ ] `GET /v1/audit/merkle-roots` endpoint
- [ ] Optional: blockchain anchor (Ethereum L2, ~$0.01/tx)
- [ ] Test: inclusion proof for single event

**Est. effort:** 2 days

---

## Consolidated Timeline

| Week | Focus | Key Deliverables | Risk |
|------|-------|-----------------|------|
| **1** | Defense | Rate limiting, vulnerability patch, budget alerts | Redis dependency |
| **2-3** | Enterprise Identity | OAuth 2.1, JWT tokens, SSO | IdP integration complexity |
| **4** | Observability | Webhooks, dashboard API | Delivery reliability |
| **5** | Crypto Hardening | HSM backends, key rotation | AWS/Vault setup time |
| **6** | Advanced Governance | Delegation, merkle trees | Lower priority — can slip |

---

## Dependency Graph

```
Rate Limiting ─────┐
Vuln Patch    ─────┼──→ Week 1 (parallel)
Budget Alerts ─────┘

OAuth 2.1     ─────┐
JWT Tokens    ─────┼──→ Week 2-3 (OAuth before JWT)
                   │
Webhooks      ─────┼──→ Week 4 (needs OAuth for authZ)
Dashboard     ─────┘

HSM Backend   ─────┐
Key Rotation  ─────┼──→ Week 5 (HSM before rotation)
                   │
Delegation    ─────┼──→ Week 6 (independent)
Merkle Tree   ─────┘
```

---

## Success Criteria

### Week 1
- [ ] `make stress-test` with 100 req/sec → 429 after threshold
- [ ] Dependabot vulnerabilities: 0 critical, 0 high
- [ ] Budget alert fires at 80% spent

### Week 3
- [ ] OAuth login with Google → auto-provision wallet
- [ ] JWT access token expires in 15 min, refresh works
- [ ] API keys still work (backward compat)

### Week 4
- [ ] Webhook receives `receipt.created` within 5 seconds of invoke
- [ ] Dashboard summary loads in <500ms (cached)

### Week 5
- [ ] Signing key stored in AWS KMS, not env var
- [ ] Key rotation completes without downtime
- [ ] Old receipts still verify during grace period

### Week 6
- [ ] 3-level permit delegation works end-to-end
- [ ] Merkle root published hourly, inclusion proof verifies

---

## Resource Requirements

| Resource | Week 1 | Week 2-3 | Week 4 | Week 5 | Week 6 |
|----------|--------|----------|--------|--------|--------|
| Engineer days | 2.5 | 4.5 | 3.5 | 4 | 4 |
| AWS KMS | — | — | — | $1/mo | $1/mo |
| Redis | existing | existing | existing | existing | existing |
| Test IdP | — | mock | mock | — | — |
| Staging env | — | needed | needed | needed | — |

---

## Open Questions

1. **OAuth IdP priority:** Google first? SAML first? Both?
2. **HSM preference:** AWS KMS (managed) or Vault (self-hosted) or YubiHSM (on-prem)?
3. **Webhook retry:** Exponential backoff or linear? Max attempts?
4. **Delegation depth:** Max 3 levels? Unlimited?
5. **Merkle anchor:** Blockchain (cost) or static file (free)?

---

*Plan created 2026-08-04. Review weekly, adjust priorities based on customer feedback.*
