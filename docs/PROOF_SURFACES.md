# Proof surfaces — freeze list

**Default policy: do not expand.**

Proof surfaces are demo / workload scaffolding that may exercise the trust
plane but are **not** the product wedge. Production-like deploys keep
`ENABLE_PROOF_SURFACES=false` so these routers are not mounted.

Some AWI HTTP and Phase9 MCP examples now consume permits, metering, receipts,
and audit. That makes those individual examples governed proof workloads; it
does not promote AWI, browser, passkey, DOM, or RAG capabilities into the
supported product surface.

Product wedge: [`WEDGE.md`](../WEDGE.md).  
Remediation context: [`tech-debt-remediation-plan.md`](tech-debt-remediation-plan.md) Phase 6.

## Mount gate

Defined in `app/main.py`:

- `CORE_TRUST_ROUTERS` — always mounted (permits, MCP, receipts, audit, …).
- `DORMANT_TRUST_ROUTERS` — real trust features with no active customer
  demand; mounted **only** when `ENABLE_PROOF_SURFACES=true` (see
  "Dormant trust surfaces" below).
- `PROOF_SURFACE_ROUTERS` — mounted **only** when `ENABLE_PROOF_SURFACES=true`.

Two conditional mounts sit beside the groups:

- `app.routers.dev_keys` always mounts (its handler is runtime-gated and
  fails closed in production) but appears in the OpenAPI schema only when
  `ENABLE_DEV_KEY_SELF_PROVISION=true` — never in production, which refuses
  to boot with that flag.
- `app.routers.webhooks` (Stripe) mounts only when `STRIPE_SECRET_KEY` is
  configured (or proof surfaces are on).

Do not add new routers to `PROOF_SURFACE_ROUTERS` without an explicit product
decision to unfreeze. Prefer deleting unused stubs over growing them.

## `PROOF_SURFACE_ROUTERS` (frozen)

| Module | Surface |
|--------|---------|
| `app.routers.iot` | IoT / MQTT / CoAP bridge |
| `app.routers.telemetry` | Autonomous PM / telemetry |
| `app.routers.media` | Media engine |
| `app.routers.comms` | Agent communications |
| `app.routers.agent_comms_durable` | Durable agent comms |
| `app.routers.factory` | Content factory |
| `app.routers.content_generation` | LLM text generation |
| `app.routers.red_team` | Red-team swarm |
| `app.routers.oracle` | Agent oracle / registry crawl |
| `app.routers.protocol` | Protocol generation |
| `app.routers.rtaas` | Red-Team-as-a-Service |
| `app.routers.sandbox` | Interactive sandboxes |
| `app.routers.sandbox_behavioral` | Behavioral sandbox |
| `app.routers.telemetry_scope` | Multi-tenant telemetry scope |
| `app.routers.broadcast` | Oracle mass-broadcast |
| `app.routers.ai` | Agent intelligence |
| `app.routers.awi` | Agentic Web Interface |
| `app.routers.awi_enhanced` | AWI Phase 9 extras |

Module docstrings on these routers (and related stubs) start with
`PROOF SURFACE — frozen`.

## Simulated output labels

Every response from a simulated surface carries an explicit
`"simulated": true` field, and the OpenAPI summary/description of each
simulated endpoint says so. Simulated output must never be demoed or quoted
as live results, traction, or security evidence.

| Surface | Labeled responses | What is simulated |
|---------|-------------------|-------------------|
| AWI (`awi`, `awi_enhanced`) | `AWIExecutionResponse.simulated` (true unless a live Playwright DOM bridge is attached), `AWIRepresentationResponse.simulated` (true for mock embedding and placeholder screenshot) | Mock action success, fake initial page state, hash-based RAG embeddings, placeholder screenshots |
| Media (`media`) | `ViralHook`, `GeneratedClip`, `ClipGenerationResponse`, `DistributionResult`, `DistributionResponse` (all `simulated: true`); placeholder transcript noted on video status | Random hooks, metadata-only clips, placeholder download/thumbnail URLs, distribution that posts nothing |
| IoT (`iot`) | `BridgeMessageResponse.simulated`, `simulated` on subscribe and protocol translator payloads | MQTT publish that only logs, canned CoAP replies, subscribe URLs with no routes behind them |
| Oracle (`oracle`) | `IndexedAPI`, `RegistrationResult`, `RegistrationResponse`, `VisibilityScore`, `NetworkGraphResponse` (all `simulated: true`) | Hardcoded directory list, synthetic metadata, local-only registration, derived scores and graphs |
| Broadcast (`broadcast`) | `BroadcastJobResponse`, `DiscoveryMetricsResponse`, per-target and job-list `simulated: true` | Hash-sampled delivery status, hash-seeded metrics, manually posted sample events |
| Red team (`red_team`) | `ScanResponse`, `ScanReport`, `VulnerabilityListResponse` (all `simulated: true`) | Modeled scans that send no traffic and attack nothing |
| RTaaS (`rtaas`) | `JobResponse`, job-list entries, vulnerabilities payload (`simulated: true`) | Deterministic hash-of-URL findings; no target contacted |
| Sentinel approvals (`permit_requests`) | `PermitRequestResponse.simulated`, `decided_by="simulation"`, `reason="simulated_auto_approval"` | Auto-approval with no human in the loop when Sentinel is unconfigured (local/dev only; refused in production-like environments) |

Keep simulated scans and metrics out of security pitches and traction
claims.

## Accept / freeze stubs (no feature work)

Leave as-is; do not “finish” them into product:

| Stub | Location | Note |
|------|----------|------|
| Blob S3 / Vercel | `app/core/blob.py` | Unimplemented backends fall back to local |
| CoAP translator | `app/services/iot_bridge.py` (`CoAPTranslator`) | Stub translator |
| Mock embeddings / RAG | `app/services/awi_rag_engine.py` | In-memory only; ChromaDB initialization fails closed and the legacy `rag` / `chromadb` extras are no-ops while the Dependabot alert for [GHSA-f4j7-r4q5-qw2c](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c) reports no patched release |
| LLM mock | `app/services/llm.py` | Mock response when `LLM_API_KEY` unset |
| Phase9 MCP stubs | `app/services/mcp_phase9_tools.py` | Registered only when proof surfaces on |

## Superseded productionization roadmap

The April 2026 productionization roadmap in GitHub issues #33–#40 predates the
exactly-once MCP permit wedge. It is superseded by this freeze decision:

- #33–#39 must not be treated as engineering commitments while their AWI,
  oracle, comms, IoT, telemetry, scanner, and media surfaces remain frozen.
- #40's foundation and persistence work that supports the trust plane may stay;
  its broad "productionize every service" direction is not current strategy.
- #54's AWI bridge split is deferred with the frozen browser surface. Avoid a
  large mechanical refactor until a supported user path requires that code.

Unfreezing any item requires a narrow product decision, a tenant and threat
model, and a vertical slice that consumes the permit → invoke → meter → receipt
→ audit loop. Historical issue text is not approval to unfreeze a surface.

## Dormant trust surfaces (`DORMANT_TRUST_ROUTERS`)

Product decision (2026-08 teardown follow-up): the public production surface
is the wedge — sponsor/agent wallets, ledger, charge, permits, MCP invoke,
receipts, evidence, audit, policies, discovery. Trust features beyond that
are **dormant**: real code kept warm, unmounted and unadvertised until a
named customer needs them (see AGENTS.md, "Current Company Phase").

| Module / router | Surface |
|-----------------|---------|
| `app.routers.auth` (dormant) | JWT exchange (`/v1/auth/*`) — second auth story; wedge contract is `X-API-Key` |
| `app.routers.kyc` (dormant) | Stripe Identity KYC |
| `app.routers.planner` (dormant) | Budget optimizer |
| `app.routers.billing.expansion_router` (dormant) | Child/swarm wallets, transfers, top-ups, marketplace, velocity status, dry-run sandbox |

They mount via `app.main.mount_dormant_trust_surfaces` when
`ENABLE_PROOF_SURFACES=true`. Unlike proof surfaces they are not demo
scaffolding, so they carry no freeze marker and their tests stay in the fast
core loop (marked `dormant` by `tests/conftest.py`, which mounts the routes
for those modules). The service layer underneath (transfers, velocity
enforcement, KYC checks on charge paths) stays active — only the HTTP
surface gates.

Re-promoting one to `CORE_TRUST_ROUTERS` requires the unfreeze evidence bar
in AGENTS.md: a named active prospect, a concrete tool, a documented
workflow blocker, a committed owner and date.

## Agent rules

1. Do not add features under proof-surface routers or their stub services.
2. Do not enable `ENABLE_PROOF_SURFACES` in production / Railway defaults.
3. Do not advertise AWI / media / IoT / oracle as the product in OpenAPI, README,
   or registry docs.
4. Trust-plane work stays on permits → MCP invoke → meter → receipt → audit.
