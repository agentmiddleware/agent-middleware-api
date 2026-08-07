# Hyper-Focused Sprints: Trust Plane Gap Closure

**Target:** Production-ready enterprise trust plane
**Sprint cadence:** 2-week sprints
**Team size:** 1-2 engineers
**Total duration:** 8 sprints (16 weeks)

---

## Sprint 0: Foundation & Fidelity (Week 1-2)
**Theme:** Establish CI/CD quality gates before building on top.

| Story | Points | Acceptance Criteria |
|-------|--------|-------------------|
| Fix Dependabot critical + high CVEs | 3 | `pip-audit` passes, CI green |
| Add Postgres service container to CI | 5 | `postgres_trust` job runs in every PR, asyncpg path tested |
| Add `NaiveUTCDateTime` TypeDecorator | 3 | Replaces cursor hook, all datetime columns safe |
| Add `make prove-trust-plane` to CI gate | 2 | Docker postgres:16 + full loop in PR checks |

**Definition of Done:**
- [ ] CI runs `pytest` against both SQLite and PostgreSQL on every PR
- [ ] No open critical/high CVEs in dependencies
- [ ] All datetime writes go through `NaiveUTCDateTime` (no direct `datetime.now()`)

**Risks:** TypeDecorator migration might break existing data migration scripts.

---

## Sprint 1: JWT Modernization (Week 3-4)
**Theme:** Replace long-lived API keys with short-lived tokens.

| Story | Points | Acceptance Criteria |
|-------|--------|-------------------|
| Implement JWT signing/verification | 5 | `app/core/jwt.py` with Ed25519, 15min access / 7day refresh |
| Wire JWT into `get_auth_context()` | 3 | `Authorization: Bearer <jwt>` accepted alongside `X-API-Key` |
| Add `POST /v1/auth/token` endpoint | 3 | Exchange wallet API key → access_token + refresh_token |
| Add `POST /v1/auth/refresh` endpoint | 2 | Refresh token → new access_token (no DB hit) |
| Add `POST /v1/auth/revoke` endpoint | 2 | Revoke refresh token by `jti` |
| Scope enforcement: `require_scope()` | 3 | Decorator `@require_scope("billing:charge")` on routes |

**Definition of Done:**
- [ ] `curl -H "Authorization: Bearer <token>"` works for all existing endpoints
- [ ] `curl -H "X-API-Key: ..."` still works (backward compat)
- [ ] Expired token returns 401 with `token_expired`
- [ ] Missing scope returns 403 with `insufficient_scope`
- [ ] Refresh token rotation: new refresh token issued on each use

**Risks:** JWT library compatibility with Ed25519 (verify `PyJWT[crypto]` supports it).

---

## Sprint 2: OAuth 2.1 + Enterprise SSO (Week 5-6)
**Theme:** Let enterprises bring their own identity provider.

| Story | Points | Acceptance Criteria |
|-------|--------|-------------------|
| Add `OAuthProviderModel` + config | 3 | Google OIDC, GitHub OAuth, generic SAML 2.0 configs |
| Implement `GET /v1/oauth/authorize` | 5 | Initiates PKCE flow, redirects to IdP |
| Implement `POST /v1/oauth/token` | 5 | Exchanges auth code for tokens, auto-provisions wallet |
| Add `GET /v1/oauth/userinfo` | 2 | Returns identity claims from JWT |
| Wallet auto-provisioning on login | 3 | New user → sponsor wallet + 100 credits |
| Link OAuth identity to existing wallet | 3 | Existing wallet owner can bind Google/GitHub account |

**Definition of Done:**
- [ ] Google SSO login → wallet created → can invoke tools
- [ ] GitHub SSO login → wallet created → can invoke tools
- [ ] Existing API key users can link OAuth without losing data
- [ ] SAML 2.0 tested with Okta (or mock SAML server)
- [ ] Refresh token stored in httpOnly cookie option

**Risks:** OAuth redirect URI management in multi-env (dev/staging/prod). PKCE parameter storage across redirects.

---

## Sprint 3: Real-Time Integration (Week 7-8)
**Theme:** Push events to consumers instead of polling.

| Story | Points | Acceptance Criteria |
|-------|--------|-------------------|
| Add `WebhookSubscriptionModel` + CRUD | 3 | `POST /v1/webhooks/subscriptions` |
| Implement async webhook delivery | 5 | Celery/ARQ task queue, exponential backoff |
| Event bus: `permit.created`, `receipt.created` | 3 | Publish on every state change |
| Add HMAC-SHA256 webhook signatures | 2 | `Stripe-Signature` style verification |
| Dead-letter queue for failed deliveries | 3 | After 10 retries, move to DLQ |
| Add `GET /v1/webhooks/deliveries` | 2 | Inspect delivery history |

**Definition of Done:**
- [ ] Consumer registers webhook → receives `receipt.created` within 5s
- [ ] Webhook payload signed with HMAC-SHA256
- [ ] Failed delivery (500 from consumer) retried 3x with backoff
- [ ] DLQ inspectable via API
- [ ] Webhook secret rotatable without losing subscriptions

**Risks:** Need task queue (Redis + Celery or ARQ). Railway free tier might not support persistent workers.

---

## Sprint 4: HSM + Key Rotation (Week 9-10)
**Theme:** Production-grade key management.

| Story | Points | Acceptance Criteria |
|-------|--------|-------------------|
| Abstract `KeyBackend` interface | 3 | `sign()`, `verify()`, `rotate()` methods |
| Implement `AWSKMSBackend` | 5 | KMS Sign API, asymmetric Ed25525519 |
| Implement `VaultTransitBackend` | 3 | HashiCorp Vault Transit engine |
| Implement `LocalHSMBackend` | 3 | PKCS#11 / YubiHSM support |
| Add `POST /v1/admin/signing-keys/rotate` | 3 | Graceful rotation with dual-sig window |
| Key revocation + historical verify | 3 | Old receipts still verify during window |
| Move env var key to dev-only | 2 | Production refuses to start without HSM config |

**Definition of Done:**
- [ ] Signing key stored in AWS KMS (not env var)
- [ ] Key rotation: new key active, old key accepts for 7 days
- [ ] Receipts signed with retired key still verify
- [ ] `SIGNING_BACKEND=kms|vault|pkcs11|env` config
- [ ] SOC2 auditor can verify HSM key custody chain

**Risks:** KMS latency (~50ms/sign) might affect throughput. Need benchmark.

---

## Sprint 5: Advanced Governance (Week 11-12)
**Theme:** Complex organization structures.

| Story | Points | Acceptance Criteria |
|-------|--------|-------------------|
| Permit delegation (1-level) | 5 | Agent A delegates to Agent B, budget tracked |
| Permit delegation (multi-level) | 3 | 3-level chain, revocation cascades |
| Budget cascade: child spend → parent | 3 | Child debit reduces parent permit budget |
| Permit conditions (`if_balance_gt`) | 3 | Conditional permit: "allow only if balance > 50" |
| Time-based permit restrictions | 2 | `allowed_hours: [9, 17]`, `allowed_days: [1,2,3,4,5]` |
| Geo-fencing: `allowed_regions` | 3 | IP geolocation check on invoke |

**Definition of Done:**
- [ ] Sponsor → Agent A → Agent B delegation works end-to-end
- [ ] Revoking parent permit revokes all children
- [ ] Conditional permit denied outside allowed hours
- [ ] Geo-fenced permit denied from blocked region
- [ ] Budget cascade: child spend reflected in parent permit

**Risks:** Geo-fencing requires GeoIP database (MaxMind). Adds dependency.

---

## Sprint 6: Audit Integrity (Week 13-14)
**Theme:** Prove the audit chain hasn't been tampered.

| Story | Points | Acceptance Criteria |
|-------|--------|-------------------|
| Implement Merkle tree construction | 5 | Hourly batch of audit events → merkle root |
| Add `AuditMerkleRootModel` | 2 | Store root + event range |
| `GET /v1/audit/merkle-roots` | 2 | List published roots |
| Inclusion proof generation | 3 | `GET /v1/audit/merkle-proof?event_id=...` |
| Optional: blockchain anchor | 3 | Publish root to Ethereum L2 (~$0.01/tx) |
| Audit retention policies | 2 | 90-day hot, 1-year warm, permanent cold |

**Definition of Done:**
- [ ] Merkle root published every hour
- [ ] Inclusion proof verifies event is in batch
- [ ] Tampered event fails inclusion proof
- [ ] Optional: root anchored on-chain, verifiable via Etherscan
- [ ] Old events moved to cold storage (S3/GCS)

**Risks:** Blockchain anchoring adds cost and complexity. Optional = can skip for MVP.

---

## Sprint 7: Dashboard & Self-Service (Week 15-16)
**Theme:** Developers need a UI to understand their trust plane.

| Story | Points | Acceptance Criteria |
|-------|--------|-------------------|
| Dashboard API: `/v1/dashboard/summary` | 3 | Wallet count, total credits, recent activity |
| Dashboard API: wallet detail view | 3 | Balance graph, permit usage, receipt timeline |
| Dashboard API: audit graph | 2 | Event type distribution over time |
| CSV export for compliance | 2 | `GET /v1/dashboard/export?format=csv` |
| Read-only HTML dashboard | 5 | Static site, fetches from dashboard API |
| Real-time websocket for alerts | 3 | WebSocket push on new alert/receipt |

**Definition of Done:**
- [ ] Dashboard loads in <500ms (cached aggregations)
- [ ] Wallet detail shows balance over 30 days
- [ ] Receipt timeline with tool breakdown
- [ ] CSV export accepted by Excel/Google Sheets
- [ ] WebSocket alert arrives within 1s of event

**Risks:** Frontend framework choice (vanilla JS vs React). Keep it simple.

---

## Sprint 8: Hardening & Performance (Ongoing / Week 17-18)
**Theme:** Production reliability under load.

| Story | Points | Acceptance Criteria |
|-------|--------|-------------------|
| Load test: 1000 req/s sustained | 5 | No 500s, p99 < 200ms |
| Chaos test: Redis outage | 3 | Rate limiter fail-closed, no data loss |
| Chaos test: DB failover | 3 | Automatic reconnect, in-flight requests retry |
| Penetration test: OWASP Top 10 | 5 | No critical findings |
| Documentation: Security whitepaper | 3 | Architecture, threat model, controls |
| SOC2 Type II readiness audit | 8 | Auditor engagement, evidence collection |

**Definition of Done:**
- [ ] Load test report published
- [ ] Chaos test report: no unhandled exceptions
- [ ] Pen test report: all critical/high findings fixed
- [ ] Security whitepaper in `docs/SECURITY.md`
- [ ] SOC2 auditor engaged, evidence collected

**Risks:** SOC2 timeline is 3-6 months. Sprint 8 is "readiness" not "certification."

---

## Sprint Dependency Graph

```
Sprint 0 (Foundation)
    │
    ├──→ Sprint 1 (JWT) ──→ Sprint 2 (OAuth)
    │                           │
    │                           └──→ Sprint 3 (Webhooks)
    │                                   │
    │                                   └──→ Sprint 7 (Dashboard)
    │
    ├──→ Sprint 4 (HSM) ──→ Sprint 6 (Audit)
    │                           │
    │                           └──→ Sprint 8 (Hardening)
    │
    └──→ Sprint 5 (Governance) ──→ Sprint 8 (Hardening)
```

---

## Velocity Assumptions

- **Sprint capacity:** 20-25 story points (1 engineer)
- **Buffer:** 20% for bugs, reviews, context switching
- **Total:** ~150 story points over 8 sprints

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| OAuth IdP integration complexity | High | High | Start with Google OIDC only, add SAML later |
| KMS latency impacts throughput | Medium | Medium | Benchmark early, add caching if needed |
| Railway worker limits for webhooks | Medium | High | Use external queue (Upstash, Redis Cloud) |
| SOC2 auditor findings | Medium | High | Pre-audit self-assessment in Sprint 7 |
| Team member unavailable | Low | High | Document everything, pair on complex stories |

---

## Tracking Template

Each sprint uses this format:

```markdown
## Sprint N: [Theme]

### Sprint Goal
[One sentence]

### Stories
| # | Story | Points | Owner | Status |
|---|-------|--------|-------|--------|
| 1 | ... | 3 | @name | Done |

### Daily Standup Notes
- Day 1: ...
- Day 2: ...

### Sprint Review
- Demo: ...
- Feedback: ...

### Sprint Retrospective
- What went well: ...
- What to improve: ...
- Action items: ...
```

---

*Plan created 2026-08-04. Review and adjust after each sprint.*
