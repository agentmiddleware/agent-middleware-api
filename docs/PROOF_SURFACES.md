# Proof surfaces — freeze list

**Default policy: do not expand.**

Proof surfaces are demo / workload scaffolding that may exercise the trust
plane but are **not** the product wedge. Production-like deploys keep
`ENABLE_PROOF_SURFACES=false` so these routers are not mounted.

Product wedge: [`WEDGE.md`](../WEDGE.md).  
Remediation context: [`tech-debt-remediation-plan.md`](tech-debt-remediation-plan.md) Phase 6.

## Mount gate

Defined in `app/main.py`:

- `CORE_TRUST_ROUTERS` — always mounted (permits, MCP, receipts, audit, …).
- `PROOF_SURFACE_ROUTERS` — mounted **only** when `ENABLE_PROOF_SURFACES=true`.

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

## Accept / freeze stubs (no feature work)

Leave as-is; do not “finish” them into product:

| Stub | Location | Note |
|------|----------|------|
| Blob S3 / Vercel | `app/core/blob.py` | Unimplemented backends fall back to local |
| CoAP translator | `app/services/iot_bridge.py` (`CoAPTranslator`) | Stub translator |
| Mock embeddings | `app/services/awi_rag_engine.py` | Deterministic fallback embeddings |
| LLM mock | `app/services/llm.py` | Mock response when `LLM_API_KEY` unset |
| Phase9 MCP stubs | `app/services/mcp_phase9_tools.py` | Registered only when proof surfaces on |

## Deferred (needs product approval — separate PR)

These are currently in `CORE_TRUST_ROUTERS` and are **not** moved by Phase 6:

- `app.routers.kyc`
- `app.routers.planner`

Do not demote them without an explicit product decision.

## Agent rules

1. Do not add features under proof-surface routers or their stub services.
2. Do not enable `ENABLE_PROOF_SURFACES` in production / Railway defaults.
3. Do not advertise AWI / media / IoT / oracle as the product in OpenAPI, README,
   or registry docs.
4. Trust-plane work stays on permits → MCP invoke → meter → receipt → audit.
