# Hard Run Report — thisisatest.tech Trust Plane

**Target (live production):**
- Human site: `https://www.thisisatest.tech/`
- Canonical API: `https://api-service-production-433c.up.railway.app/` (also reachable as `https://api.thisisatest.tech/`)
- Deployed build: `version 1.3.0`, `commit_sha 4c827651a645782cce04d03525aacc241c9e3bc5`, `environment=production`, `production_like=true`

**Run date:** 2026-08-12 (UTC) · **Mode:** adversarial black-box, no operator credentials · **Volume:** dozens of spaced requests, no load/stress, no auth-bypass, no destructive writes. Rate-limit budget stayed healthy throughout (`x-ratelimit-remaining` never below 111/120).

> **Status note (2026-08-17):** this report is a dated snapshot. Since it ran,
> the Railway-generated origin above stopped being publicly routable (it now
> returns 404); the canonical public API base is `https://api.thisisatest.tech/`.
> The GitHub repository referenced throughout is now **private**, so anonymous
> `github.com` fetches return 404. Reproduction commands still work with
> `API=https://api.thisisatest.tech` and operator-granted source access.

**Method:** discovery → runtime truth → authority wall → invoke → receipts/verify → negative-path matrix → fail-open hunt. Every claim below is backed by a real request/response captured live; a copy-pasteable reproduction command is in [Appendix A](#appendix-a--reproduction-commands).

---

## 1. TL;DR

**Did the intended agent journey hold up end to end? Partially — and the break is on the product's headline feature, not its security.**

The security trust boundary is **solid**. Every unauthorized, malformed, forged, or oversized request I threw at it **failed closed** with a sane error. I found **zero fail-open conditions** — nothing accepted what it should have rejected. The "no public self-serve mint" model is genuinely enforced: the entire write journey (wallet → key → permit → invoke) and every read/audit/receipt surface returns `401`/`403`, `POST /v1/dev-keys/self-provision` is `404` in production, forged Stripe webhooks are rejected, token-mint requires a real key, and doc-server path traversal is fully blocked. Runtime truth (`/health/dependencies`) matches the manifest's claims.

**But the agent journey does not hold end to end for its flagship promise: "portable proof, verifiable offline by any third party."** An autonomous agent following the site's own primary documentation (`llms.txt`) to inspect the published live proof hits a **404 dead end on every advertised host**, and the offline key-distribution endpoint the docs and the marketing homepage link to (`/.well-known/jwks.json`) **also 404s**. A third party currently has no reachable signed receipt to verify and is pointed at a non-existent key endpoint.

**The single most important thing to fix:** **Publish the promised proof bundle** at `https://www.thisisatest.tech/proof/receipt.json` + `/proof/trust-keys.json` (referenced verbatim in `llms.txt`), **and fix the `/.well-known/jwks.json` → `/.well-known/trust-keys.json` reference drift** in `docs/signed-quotes.md`, `app/services/quotes.py`, and the marketing homepage. Until then, the "verify it yourself, offline" story — the product's differentiator — cannot be exercised by anyone without an operator key. (Details: [P1-A](#p1-a--the-published-live-proof-is-404-on-every-advertised-host) and [P1-B](#p1-b--well-knownjwksjson-404s-but-three-surfaces-point-agents-at-it).)

---

## 2. Stage-by-Stage Results

The platform's intended loop is `discover → authenticate → authorize → invoke → meter → receipt → audit → govern`. I ran every stage I could reach and hammered the exact wall where operator credentials become mandatory.

### Stage 1 — Discover ✅ reachable, mostly consistent

All discovery surfaces are public and respond:

| Endpoint | Result |
|---|---|
| `GET /.well-known/agent.json` | `200` — manifest, `version 1.3.0`, `authentication.public_self_serve=false` |
| `GET /llms.txt` / `GET /llm.txt` | `200` — identical LLM-readable docs (6296 bytes) |
| `GET /mcp/tools.json` | `200` — **one** tool: `partner.echo` (`requirePermit=true`, `creditsPerCall=1.0`) |
| `GET /.well-known/mcp/tools.json` | `200` — alias, identical body |
| `GET /openapi.json` | `200` — 97 paths |
| `GET /v1/discover` | `200` — capability index |
| `GET /dashboard` | `200` — public status/evidence HTML index |
| `GET /.well-known/awi.json` | `404` — advertised in OpenAPI, not mounted (proof surfaces off) |

The manifest is honest about the auth model — an agent that reads it knows the next step before it gets a `401`:

```
$ curl https://api-service-production-433c.up.railway.app/.well-known/agent.json | jq .authentication
{
  "type": "api_key", "header": "X-API-Key", "public_self_serve": false,
  "bootstrap_docs": "/docs/partner-api-key-bootstrap.md",
  "note": "No public self-serve API key mint. An operator bootstrap/admin key (VALID_API_KEYS)..."
}
```

The advertised doc links (`/docs/partner-api-key-bootstrap.md`, `/WEDGE.md`, `/SECURITY_LIMITATIONS.md`) all resolve `200`. Two drifts found here are written up as [P2-A](#p2-a--canonical_api-disagrees-between-the-two-manifests) (canonical_api disagreement) and [P2-B](#p2-b--v1discover-reports-mcp_tools---while-mcptoolsjson-advertises-partnerecho).

### Stage 2 — Runtime truth ✅ matches manifest claims

`GET /health` → `200 {"status":"healthy","version":"1.3.0","commit_sha":"4c827651..."}`.

`GET /health/dependencies` → `200`, and the runtime state agrees with what the manifest promised:

```json
{ "environment": "production", "production_like": true,
  "enable_proof_surfaces": false, "enable_dogfood_tool": false,
  "dependencies": {
    "postgres": {"status":"up"}, "redis": {"status":"up"},
    "signing_key": {"status":"up","state":"loaded"},
    "upstream_mcp": {"status":"up","public_tool_id":"partner.echo",
                     "upstream_origin":"https://partner-mcp-pilot-production.up.railway.app"},
    "stripe": {"status":"not_configured"}, "llm": {"status":"not_configured"} },
  "simulation_modes": { "agent_comms": true, "human_approval": true, "media_engine": true,
                        "oracle": true, "telemetry_pm": true, ... },
  "runtime_degradation": {"degraded": false} }
```

This is exactly what the manifest's `proof_surfaces` block and `agent_first.proof_surfaces_enabled=false` promise: the wedge (permits/MCP/receipts/audit) is live and non-simulated; every proof surface is off and its simulation flag is exposed for an agent to read. **No drift between claimed and actual runtime posture.** The signing key is loaded, so receipts *can* be produced — which makes the missing published proof ([P1-A](#p1-a--the-published-live-proof-is-404-on-every-advertised-host)) a publishing gap, not a capability gap.

### Stage 3 — Obtain scoped authority ⛔ the wall (by design), verified fail-closed

This is where an operator credential becomes mandatory, and the wall holds on every endpoint. No key → `401`; bogus key → `403`; the self-serve mint endpoint is not mounted in production:

```
POST /v1/dev-keys/self-provision (no key)      -> 404  {"detail":"Not Found"}
POST /v1/billing/wallets/sponsor (no key)      -> 401  {"error":"missing_credentials", ...,"docs":"/docs"}
POST /v1/billing/wallets/sponsor (bogus key)   -> 403  {"error":"invalid_api_key"}
POST /v1/api-keys              (no key)         -> 401  missing_credentials
POST /v1/permits              (no key)         -> 401  missing_credentials
GET  /v1/billing/wallets      (no key)         -> 401  missing_credentials   (no public wallet listing)
GET  /v1/audit/events         (no key)         -> 401  missing_credentials
GET  /v1/signing-keys/active  (no key)         -> 401  missing_credentials
GET  /v1/me/permits           (no key)         -> 401  missing_credentials
```

The `401` body always names the fix (`X-API-Key or Authorization: Bearer header is required`, `"docs":"/docs"`), and the manifest already told the agent `public_self_serve=false`. **This is the documented wall, shown not claimed.** The `404` on `/v1/dev-keys/self-provision` (an endpoint that *is* in `openapi.json`) is a good fail-closed — production simply does not mount the self-provision route — noted as spec drift in [P2-F](#p2-f--openapi-advertises-endpoints-that-404-in-production).

### Stage 4 — Invoke ⛔ auth-gated, and auth runs *before* parsing

Every MCP surface requires a key — including the JSON-RPC discovery calls that `llms.txt` presents as usable:

```
POST /mcp            {"method":"tools/list"}     (no key) -> 401 missing_credentials
POST /mcp            {"method":"initialize"}      (no key) -> 401 missing_credentials
POST /mcp            {"method":"tools/call", partner.echo} (no key) -> 401 missing_credentials
POST /mcp/messages   {"method":"tools/call", partner.echo} (no key) -> 401 missing_credentials
POST /mcp/tools/partner.echo/invoke              (no key) -> 401 missing_credentials
```

Two important properties verified here:

1. **Auth precedes body parsing** — a good security property. Malformed JSON, wrong `Content-Type`, and a ~1 MB oversized body all return `401` with no key (not `400`/`413`), so there is no pre-authentication parsing attack surface:
   ```
   POST /mcp  (no key, body = '{"jsonrpc":"2.0", BROKEN')      -> 401
   POST /mcp  (no key, Content-Type: text/plain, 'not json')   -> 401
   POST /mcp  (no key, ~1MB body)                              -> 401
   POST /mcp  (bogus key, body = '{ BROKEN')                   -> 403 invalid_api_key  (still no dispatch)
   ```
2. Because auth short-circuits everything, **the dispatch-layer error taxonomy (unknown-method `-32601`, unknown-tool, out-of-scope permit denial) is unreachable without a key.** That is the wall for the invoke stage; what I would run past it is in [Section 5](#5-what-could-not-be-reached-without-operator-credentials).

This stage's one drift is a documentation contradiction, not a security issue — `llms.txt` labels MCP auth "Optional" — written up as [P2-C](#p2-c--mcp-is-documented-as-optional-auth-but-is-fully-gated).

### Stage 5 — Meter / Receipt / Verify ⛔ verify gated; public key anchor validated

The signing/verification surfaces split into "public key material" (reachable) and "receipt read/verify" (auth-gated):

```
GET  /.well-known/trust-keys.json                 -> 200   (public — see below)
GET  /.well-known/jwks.json                        -> 404   (referenced by docs+homepage; see P1-B)
POST /v1/receipts/verify {receipt_id}   (no key)  -> 401
POST /v1/receipts/verify {receipt_id}   (bogus)   -> 403
POST /v1/receipts/verify {inline bundle}(no key)  -> 401   (no public/stateless verify path)
POST /v1/permits/verify                 (no key)  -> 401
GET  /v1/receipts/{id}/portable         (no key)  -> 401
GET  /v1/evidence/{id}                  (no key)  -> 401
```

The **public key anchor is cryptographically sound and stable.** `GET /.well-known/trust-keys.json` returns one active Ed25519 key, and I validated it:

```
issuer: https://api.thisisatest.tech | alg: Ed25519 | canon: awi-canonical-json/1
kid: railway-prod-ed25519  status: active
public_key_b64 = Jz0qKne203qeJVhzLD5KG1RbyazNKPYDRJWotdcCUjU=
  -> decodes to exactly 32 bytes (valid Ed25519 public-key length)  ✓
  -> jwk.x (base64url) decodes to the SAME 32 bytes                  ✓
  -> endpoint returned identical kid+key on repeated fetches         ✓ (stable)
```

So the *verifier's key* is real and usable. What I **could not** do without a key: obtain an actual signed receipt to run the tamper matrix (flip fields / swap IDs / confirm rejection). The `verify` endpoint is `401`, the `portable` endpoint is `401`, and the one unauthenticated path to a receipt — the published proof — is `404` ([P1-A](#p1-a--the-published-live-proof-is-404-on-every-advertised-host)). This is the crux gap: **the key to verify with is public, but there is no reachable signed artifact to verify.**

### Stage 6 — Audit / Govern / Revoke ⛔ gated

`GET /v1/audit/events`, `GET /v1/audit/summary`, `POST /v1/audit/verify-chain`, `POST /v1/permits/{id}/revoke`, `DELETE /v1/api-keys/{wallet}/{key}` all sit behind the same auth wall (`401` without a key). Not reachable for a live run without operator credentials; enumerated in [Section 5](#5-what-could-not-be-reached-without-operator-credentials).

---

## 3. Fail-Open Findings (P0)

> **P0 by definition = anything that accepted what it should have rejected.**

**None found.** This is the strongest positive result of the run, and it is evidenced, not assumed. Every one of the following *should* fail closed and *did*:

| Attack | Endpoint | Result | Verdict |
|---|---|---|---|
| Unauthenticated wallet/key/permit creation | `POST /v1/billing/wallets/*`, `/v1/api-keys`, `/v1/permits` | `401` | ✅ closed |
| Self-serve key mint | `POST /v1/dev-keys/self-provision` | `404` (not mounted in prod) | ✅ closed |
| Unauthenticated token mint | `POST /v1/auth/token` (empty / bogus key) | `422` / `401 invalid_api_key` | ✅ closed |
| Forged Stripe webhook (Stripe `not_configured`) | `POST /v1/webhooks/stripe`, `/stripe/identity` | `400 "Missing Stripe signature"` | ✅ closed |
| Unauthenticated MCP invoke of `partner.echo` | `POST /mcp`, `/mcp/messages`, `/mcp/tools/{id}/invoke` | `401` | ✅ closed |
| Inline forged portable receipt to verifier | `POST /v1/receipts/verify {receipt:{...forged...}}` | `401` (auth before verify) | ✅ closed |
| Path traversal to source | `GET /docs/../app/main.py` + encoded/`....//`/suffix variants | all `404` | ✅ closed |
| Header confusion (dup `X-API-Key`, empty value, case-variant, bogus `Bearer`) | `POST /v1/permits` | `401`/`403`, never `200` | ✅ closed |
| Pre-auth parser abuse (malformed / wrong-CT / ~1MB body) | `POST /mcp` | `401` (auth first) | ✅ closed |

Representative evidence:

```
POST /v1/auth/token       {}                       -> 422  {"type":"missing","loc":["body","api_key"]}
POST /v1/auth/token       {"api_key":"bogus..."}   -> 401  {"error":"invalid_api_key"}
POST /v1/webhooks/stripe  {forged checkout event}  -> 400  {"detail":"Missing Stripe signature"}
GET  /docs/..%2f..%2fapp%2fmain.py                 -> 404  {"detail":"Not Found"}
POST /v1/permits (X-API-Key: bogus1, X-API-Key: bogus2) -> 401  (duplicate header treated as absent)
```

The trust boundary the product claims — governed MCP tool invocation gated by operator-issued authority — is **enforced consistently and closed by default.**

---

## 4. Prioritized Findings

Ordering per the brief: consistency drift and agent-experience dead ends first, then the rest. No P0s exist (Section 3), so the highest-severity items are P1 dead ends on the verification path.

### P1-A — The published live proof is 404 on every advertised host

**Category:** agent-experience dead end / broken headline feature. **Severity:** P1 (single most important fix).

`llms.txt` — the site's *primary agent-facing document* — instructs agents, verbatim:

> ### 3. Inspect the Published Live Proof
> The human site publishes one non-sensitive portable `partner.echo` receipt and the matching public-key snapshot:
> ```
> GET https://www.thisisatest.tech/proof/receipt.json
> GET https://www.thisisatest.tech/proof/trust-keys.json
> ```

Both URLs — and every plausible alternate host — return `404`:

```
GET https://www.thisisatest.tech/proof/receipt.json            -> 404 NOT_FOUND (Vercel)
GET https://www.thisisatest.tech/proof/trust-keys.json         -> 404 NOT_FOUND
GET https://www.thisisatest.tech/proof/          (index)       -> 404 NOT_FOUND
GET https://api.thisisatest.tech/proof/receipt.json            -> 404
GET https://agent-middleware-web.vercel.app/proof/receipt.json -> 404
GET https://api-service-production-433c.up.railway.app/proof/receipt.json -> 404
```

**Why this is the top finding.** The product's entire thesis is "autonomy needs receipts" — portable, offline-verifiable proof. The unauthenticated `portable` receipt endpoint is `401`, so the published proof is the *only* way an outside party can obtain a signed receipt to verify. With it missing, the flagship "verify it yourself, offline" demo is unreachable end-to-end. The signing key is loaded and receipts are producible (Stage 2), so this is a **publishing/deploy gap**, not a capability gap — which is exactly why it is worth fixing first: high impact, low effort.

**Fix:** publish the two JSON artifacts at the documented `www.thisisatest.tech/proof/` paths (or correct `llms.txt` to wherever they actually live). Acceptance: `curl https://www.thisisatest.tech/proof/receipt.json` returns a portable bundle whose signature verifies against `/proof/trust-keys.json`.

### P1-B — `/.well-known/jwks.json` 404s, but three surfaces point agents at it

**Category:** consistency drift on the key-distribution path. **Severity:** P1.

The working public key endpoint is `/.well-known/trust-keys.json` (`200`). But `/.well-known/jwks.json` returns `404` — and **three separate surfaces send agents and humans to that non-existent endpoint:**

1. `docs/signed-quotes.md:62-63` — "a quote verifies against the published JWKS (`/.well-known/jwks.json`) without trusting this API's read endpoint."
2. `app/services/quotes.py:28` (code comment) — "a quote is verifiable offline against the published JWKS."
3. **The live marketing homepage** `https://www.thisisatest.tech/` contains a clickable link: `href="https://api-service-production-433c.up.railway.app/.well-known/jwks.json"`.

```
GET /.well-known/jwks.json      -> 404
GET /.well-known/trust-keys.json -> 200  (the real anchor: kid=railway-prod-ed25519)
GET /jwks.json / /.well-known/jwks -> 404 / 404
```

An agent that follows the quote-verification docs, or a human that clicks the homepage "keys" link, lands on a `404` at the core of the offline-verification story. **Fix:** repoint all three references to `/.well-known/trust-keys.json` (or add a `/.well-known/jwks.json` alias — the trust-keys body already embeds a JWK, so serving a standards-shaped JWKS is trivial).

### P2-A — `canonical_api` disagrees between the two manifests

**Category:** consistency drift. **Severity:** P2.

The marketing manifest and the API manifest name **different canonical API hosts**:

```
www.thisisatest.tech/.well-known/agent.json : "canonical_api": "https://api-service-production-433c.up.railway.app"
api ....railway.app  /.well-known/agent.json : "canonical_api": "https://api.thisisatest.tech"
```

Both resolve to the same service, so this is not a dead end — but an agent that picks a canonical base to pin gets a different answer depending on which manifest it read first, which undermines the point of a "canonical" field. Pick one (the branded `api.thisisatest.tech` is the better choice) and make both manifests agree. Related host sprawl: `www` and the API serve **different** `llms.txt` copies (different md5), and the marketing manifest's `human_site` (`agent-middleware-web.vercel.app`) is a *different* origin from the `www` host that actually serves the docs.

### P2-B — `/v1/discover` reports `mcp_tools: []` while `/mcp/tools.json` advertises `partner.echo`

**Category:** consistency drift. **Severity:** P2.

```
GET /v1/discover     -> "mcp_tools": [], "awi_endpoints": []
GET /mcp/tools.json  -> tools: [ { "name": "partner.echo", "requirePermit": true, ... } ]
```

The "expanded capability index" surfaces **zero** callable tools while the authoritative manifest lists one. `llms.txt` does say to treat `/mcp/tools.json` as authoritative and `/v1/discover` as an optional catalog, which mitigates the impact — but an agent that uses the capability index to decide "is there anything to call here?" concludes *no*. Either populate `/v1/discover.mcp_tools` from the same source as `/mcp/tools.json`, or drop the empty array so it doesn't read as an authoritative "none."

### P2-C — MCP is documented as "Optional" auth but is fully gated

**Category:** consistency drift / agent-experience. **Severity:** P2 (fail-*closed*, so security-safe).

`llms.txt` "Endpoints Summary" marks `MCP | /mcp | Optional`, and its "MCP Tool Discovery" section shows `POST /mcp/messages {"jsonrpc":"2.0","method":"tools/list","id":1}` as a discovery call. Live, that exact call returns `401` without a key, as does `initialize` and every other MCP method. Requiring auth is the *right* posture, but the docs say otherwise, so an agent that trusts the "Optional" label wastes a round-trip and may not fall back to the public `/mcp/tools.json`. Fix the label to "Required" and move the JSON-RPC discovery example behind the operator-key prerequisite.

### P2-D — Wildcard CORS on the credentialed control plane

**Category:** hardening. **Severity:** P2 (not a trust-boundary break).

A cross-origin preflight from an arbitrary origin is fully reflected on `/v1/permits`:

```
OPTIONS /v1/permits  (Origin: https://evil.example, ACRM: POST)
  -> 200
     access-control-allow-origin: *
     access-control-allow-methods: DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT
     access-control-max-age: 600
```

Because auth is a request **header** (`X-API-Key`), not a cookie, `ACAO:*` does not by itself leak credentials, and `docs/demo-instance.md` even notes that a wildcard origin disables *credentialed* CORS. Still, reflecting `*` + all methods for any origin on the credentialed control plane is looser than a governance product should ship; restrict it to the known partner/dashboard origins as defense in depth.

### P2-E — Inconsistent auth status codes and error envelopes

**Category:** consistency drift / agent-experience. **Severity:** P2.

The same logical condition returns different HTTP statuses and body shapes across the surface, forcing an agent to handle multiple contracts:

- **Invalid API key** → `403 invalid_api_key` on `/v1/billing/*` and `/mcp`, but `401 invalid_api_key` on `/v1/auth/token`.
- **Invalid key, by length** → a short bogus key (`"bogus"`, `"x"`) returns `401 invalid_api_key`; a longer bogus key (`"bogusbogus"`, `"amw_live_fake000"`, `"amw_dev_fake0000"`) returns `403 invalid_api_key`. Same error label, two statuses, split on key length (~8 chars).
- **Envelope shape** → auth/business errors use `{"detail":{"error":..,"message":..}}`; validation errors use FastAPI's default `{"detail":[{"type":..,"loc":..,"msg":..}]}` (e.g. `422` on `/v1/auth/token {}`).
- `llms.txt`'s error table says "`403` Access denied (cross-tenant)", but `403` is also used for a plain invalid key, blurring the documented meaning.

All fail closed — this is purely about a predictable, single error contract for agents.

### P2-F — OpenAPI advertises endpoints that 404 in production

**Category:** consistency drift. **Severity:** P2.

`openapi.json` lists routes that are not mounted in this production posture, so a client generated from the spec hits `404`:

```
POST /v1/dev-keys/self-provision  (in spec) -> 404 live
GET  /.well-known/awi.json         (in spec) -> 404 live
```

This is correct fail-closed behavior (proof surfaces / self-provision are gated off in prod), but the served OpenAPI doesn't reflect the gating. Either serve an environment-filtered spec or annotate these as environment-conditional.

### Minor observations (P2/P3, no action urgent)

- `HEAD` and `OPTIONS` on `/.well-known/agent.json` return `405` (only `GET` allowed); clients that probe static manifests with `HEAD` get no help.
- `GET /mcp` returns `401` (auth wraps the route) while `GET /mcp/messages` returns a proper `405 Allow: POST`. Inconsistent method-coverage behavior between sibling routes.
- `Accept: application/xml`/`text/html` on `/.well-known/agent.json` is ignored and always returns `application/json` (acceptable for a JSON-only manifest; a `406` would be more correct but this is fine).
- `/v1/discover/tools` and `/v1/discover/awi` are `401`-gated even though the parent `/v1/discover` is public and `llms.txt` labels Discovery "Optional."
- `POST /v1/auth/refresh` with a bogus token returns `401 {"message":"invalid_token: Not enough segments"}`, leaking that the mechanism is JWT (low sensitivity).

---

## 5. What Could Not Be Reached Without Operator Credentials

Everything past the authority wall requires an operator-issued bootstrap/admin key (`VALID_API_KEYS`) to provision a wallet-scoped agent key. Per `docs/partner-api-key-bootstrap.md` there is intentionally **no public mint**, and this run confirmed the wall is closed. The following stages of the intended journey are therefore **blocked by design** and were not exercised live:

| Journey stage | Blocked endpoint(s) | Wall observed |
|---|---|---|
| Obtain scoped authority | `POST /v1/billing/wallets/sponsor`,`/agent`; `POST /v1/api-keys`; `POST /v1/permits` | `401`/`403` |
| Governed invoke + metering | `POST /mcp` / `/mcp/messages` `tools/call partner.echo` | `401` |
| Signed success receipt | `GET /v1/receipts/{id}`, `/portable`, `POST /v1/receipts/verify` | `401`/`403` |
| Idempotency / exactly-once | replay of an invoke with a fixed `Idempotency-Key` | requires a live invoke (gated) |
| Out-of-scope denial receipt | `tools/call` of a non-allowed tool under a permit | requires a permit (gated) |
| Quotes | `POST /v1/quotes`, `GET /v1/me/quotes` | `401` |
| Audit / govern / revoke | `GET /v1/audit/events`, `POST /v1/audit/verify-chain`, `POST /v1/permits/{id}/revoke` | `401` |

**Receipt-tampering test status:** the brief asked to capture a real receipt, verify its signature, then flip fields / swap IDs and confirm rejection. I validated the *public verifier key* (32-byte Ed25519, JWK-consistent, stable) but **could not run the tamper matrix live** — `POST /v1/receipts/verify` is `401`, `GET /v1/receipts/{id}/portable` is `401`, and the published proof is `404`. This is the concrete downstream cost of [P1-A](#p1-a--the-published-live-proof-is-404-on-every-advertised-host)/[P1-B](#p1-b--well-knownjwksjson-404s-but-three-surfaces-point-agents-at-it): with no reachable signed receipt, third-party verification is untestable from outside.

### What I would run next, given an operator key

1. **Full golden path** (`docs/golden-path.md` §2–14): sponsor wallet → agent wallet → agent key → signed permit (`allowed_tools:["partner.echo"]`, `scopes:["tool:partner.echo:invoke","billing:charge"]`, `max_credits`, `expires_at`, `Idempotency-Key`) → `POST /mcp/messages tools/call` → capture the signed receipt.
2. **Receipt integrity / tamper matrix**: `GET /v1/receipts/{id}/portable`, verify Ed25519 over `signing_input` against `trust-keys.json`; then flip `outcome`, mutate `credits_charged`, swap `permit_id`/`receipt_id`, corrupt one signature byte, and re-run `b2a-verify-receipt` + `POST /v1/receipts/verify` — confirm every mutation is rejected.
3. **Idempotency & metering**: replay the identical invoke and assert the receipt ID is unchanged with no second ledger debit (`GET /v1/billing/ledger/{wallet}`); then fire a small handful (3–5) of concurrent duplicates with the same `Idempotency-Key` and confirm exactly-once (single debit, single receipt) — the small-count race check the brief allows.
4. **Governance denials**: invoke a non-allowed tool → expect `permit_tool_not_allowed` with a signed denial receipt; drive `permit_budget_exceeded`, `permit_expired`, and a post-`revoke` `permit_revoked` — verifying each denial's signed `reason_code` per `docs/denial-details.md`.
5. **Cross-tenant isolation**: confirm the agent key can read its own wallet but gets `403` on the sponsor wallet (`docs/golden-path.md` §6).
6. **Audit chain**: `POST /v1/audit/verify-chain` for the wallet, tie the receipt to its `ledger_entry_id` + audit event, and confirm chain-integrity detection.

---

## 6. Acceptance & Reproducibility

- **Evidence or it didn't happen:** every status code and error body above came from a live request on 2026-08-12 against `commit 4c827651`. Raw headers/bodies were captured during the run.
- **"Blocked by design" is shown, not claimed:** each wall is backed by the actual `401`/`403`/`404` and its error body (Sections 3–5).
- **P0s reproducible from the report alone:** there are no P0s; the *absence* is reproducible — re-run any row of the Section 3 table and observe the closed response.
- **P1s reproducible from the report alone:** the two commands in [P1-A](#p1-a--the-published-live-proof-is-404-on-every-advertised-host)/[P1-B](#p1-b--well-knownjwksjson-404s-but-three-surfaces-point-agents-at-it) reproduce the `404`s directly.

### Appendix A — Reproduction commands

```bash
API=https://api-service-production-433c.up.railway.app

# --- P1-A: published proof is a dead end (expect 404 on every host) ---
curl -s -o /dev/null -w "%{http_code}\n" https://www.thisisatest.tech/proof/receipt.json
curl -s -o /dev/null -w "%{http_code}\n" https://www.thisisatest.tech/proof/trust-keys.json
curl -s -o /dev/null -w "%{http_code}\n" https://api.thisisatest.tech/proof/receipt.json

# --- P1-B: jwks 404 vs working trust-keys 200 ---
curl -s -o /dev/null -w "jwks:%{http_code}\n"       "$API/.well-known/jwks.json"        # 404
curl -s -o /dev/null -w "trustkeys:%{http_code}\n"  "$API/.well-known/trust-keys.json"  # 200

# --- No fail-open: the trust boundary is closed (expect 401/403/404/400) ---
curl -s -o /dev/null -w "self-provision:%{http_code}\n" -X POST "$API/v1/dev-keys/self-provision" -H 'Content-Type: application/json' -d '{}'      # 404
curl -s -o /dev/null -w "wallet-nokey:%{http_code}\n"   -X POST "$API/v1/billing/wallets/sponsor"  -H 'Content-Type: application/json' -d '{}'      # 401
curl -s -o /dev/null -w "mcp-invoke:%{http_code}\n"     -X POST "$API/mcp" -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","method":"tools/call","id":1,"params":{"name":"partner.echo","arguments":{"message":"x"}}}'  # 401
curl -s -o /dev/null -w "stripe-forged:%{http_code}\n"  -X POST "$API/v1/webhooks/stripe" -H 'Content-Type: application/json' -d '{"type":"checkout.session.completed"}'  # 400 Missing Stripe signature
curl -s -o /dev/null -w "traversal:%{http_code}\n"      "$API/docs/..%2f..%2fapp%2fmain.py"   # 404

# --- Runtime truth matches manifest ---
curl -s "$API/health/dependencies" | jq '{environment, production_like, enable_proof_surfaces, signing_key: .dependencies.signing_key.state}'

# --- P2-B: capability index vs authoritative tool manifest ---
curl -s "$API/v1/discover"    | jq '.mcp_tools'   # []
curl -s "$API/mcp/tools.json" | jq '.tools[].name'  # "partner.echo"
```

---

*Scope honored: no load/stress or high-volume fuzzing (dozens of spaced requests; rate-limit budget stayed ≥111/120), no auth-bypass or credential-guessing (only clearly-fake tokens to confirm fail-closed behavior), no destructive state changes (no wallets/keys/permits created — the wall returned before any write), English only.*
