# Pilot and production environment checklist

One page tying together every value a paying pilot must set. Copy `.env.example`,
then work this list top to bottom. Anything left at its default keeps the
deployment on local behavior: simulated services, in-memory state, or no keys.

## 1. Identity and boot mode

| Variable | Pilot value | Why |
|---|---|---|
| `ENVIRONMENT` | `production` (or `staging` for a trial) | Anything else disables the production guardrails. A typo (for example `prodution`) still boots with the strict guardrails and the boot error now names the likely intent. |
| `DEBUG` | `false` | `true` with no keys configured authenticates any caller as bootstrap admin. |
| `PUBLIC_URL` | Full public origin, for example `https://api.example.com` | Receipts and manifests must name the real issuer. |
| `PUBLIC_CONTACT_NAME`, `PUBLIC_CONTACT_EMAIL`, `PUBLIC_CONTACT_URL` | Real monitored contact, all three together | Blank is legal locally but reported as `contact_not_configured` on a production-like boot. |

## 2. Signing key (required everywhere, including local)

Generate once per database and reuse on every restart. Changing key material
under an existing `TRUST_SIGNING_KEY_ID` is rejected, so pair a new seed with
a new key ID. Never commit a real seed. Full steps: `docs/key-management.md`.

## 3. Persistence: two knobs, set both

The ORM engine and the key/value state store are configured separately.
A deploy can satisfy one while the money path runs on the other, so set both.

| Variable | Pilot value | Governs |
|---|---|---|
| `DATABASE_URL` | `postgresql://...` (never SQLite) | Wallets, permits, receipts, ledger. SQLite silently drops the row locks these paths rely on, so production-like boots refuse it. |
| `STATE_BACKEND` plus `REDIS_URL` | `STATE_BACKEND=postgres` with the same `DATABASE_URL`, or `redis` with `REDIS_URL` | Durable key/value state. Production-like boots refuse `memory` and `sqlite`. |
| `VALID_API_KEYS` | Real keys from the host secret manager | Empty with `DEBUG=false` fails every authenticated call closed with 403. Empty with `DEBUG=true` on a local boot is open mode: any caller becomes bootstrap admin. |

Strict posture flags (all required on production-like boots):
`TRUST_MODE_ENABLED=true`, `ALLOW_LEGACY_UNPERMITTED_MCP=false`,
`ENABLE_PROOF_SURFACES=false`, `ENABLE_PUBLIC_MCP_ENDPOINT=false`,
`ENABLE_DEV_KEY_SELF_PROVISION=false`, empty `STATIC_DEV_API_KEYS`,
`ENABLE_DOGFOOD_TOOL=false`, `ENABLE_DOGFOOD_SECOND_TOOL=false`,
`ALLOW_PRIVATE_NETWORK_TARGETS=false`, `ALLOW_UNSAFE_HOST_PYTHON_SANDBOX=false`.

`CORS_ORIGINS` ships as `*`. That default is deliberate for a
header-authenticated API (credentialed browser calls stay blocked), but a
production-like boot with `*` now logs a `cors_wildcard_production` warning.
Set an explicit origin list when browser apps are in scope.

## 4. Simulation flags: what each one mocks

Every flag defaults to `true` (mock). Flip one to `false` only after the real
adapter is wired; flipping early raises `NotImplementedError` at the guard
site by design, never a silent stub. A pilot that must show real effects
needs each row below consciously set, not inherited.

| Flag | When `true`, the demo runs on | Real pilot needs |
|---|---|---|
| `SIMULATION_MODE_ORACLE` | Frozen discovery list and synthetic delivery state | Real discovery source |
| `SIMULATION_MODE_RED_TEAM`, `SIMULATION_MODE_RTAAS` | Simulated scans and deterministic hash-derived findings, no traffic sent | Real assessment vendor, reports relabeled from simulated |
| `SIMULATION_MODE_MEDIA_ENGINE` | Metadata-only clips, placeholder transcription | Real media pipeline |
| `SIMULATION_MODE_IOT_BRIDGE` | Publish calls that only log | Real broker at `MQTT_BROKER_URL` |
| `SIMULATION_MODE_TELEMETRY_PM`, `SIMULATION_MODE_AGENT_COMMS`, `SIMULATION_MODE_CONTENT_FACTORY` | Simulated PM, comms, and content output | Real providers |
| `SIMULATION_MODE_PROTOCOL_GEN`, `SIMULATION_MODE_SANDBOX` | Contract-only preview stubs with no side effects | Real adapters |
| `SIMULATION_MODE_HUMAN_APPROVAL` | Auto-approve, marked simulated, local only (production-like boots fail closed instead) | `false` plus the Sentinel trio below |

## 5. Human approval (Sentinel) trio

Real approvals need all three: `SIMULATION_MODE_HUMAN_APPROVAL=false`,
`SENTINEL_API_URL`, and `SENTINEL_API_KEY`. Anything less fails closed:
approval-gated permits cannot be created and gated invokes are denied, with
nothing charged. The boot log now emits a `human_approval_posture` line naming
the effective mode and any missing piece, and `/health/dependencies` reports
the Sentinel entry (`up`, `down`, `not_configured`, `not_used`) without ever
transmitting the key. Budget a human who answers inside
`SENTINEL_APPROVAL_TIMEOUT_SECONDS` (default 300); late decisions are dropped
by the local expiry window because Sentinel never expires them server-side.

## 6. Verify before inviting the buyer

1. Run the preflight: the API exposes a GO/NO GO checklist
   (`app/services/preflight.py`) that fails on missing keys and placeholders.
2. Boot once and read the log: `runtime_posture` (effective simulation map),
   `human_approval_posture`, `cors_wildcard_production` (if present), and
   `trust_mode_permissive` (must be absent).
3. Check health: authenticated `/health/dependencies` shows `simulation_modes`,
   `sentinel`, and `runtime_degradation` (any memory fallback is listed there,
   never hidden).
4. Confirm build provenance: health reports `commit_sha` from Railway metadata
   or the baked image stamp, never from the legacy `BUILD_COMMIT_SHA` variable.

## 7. Known dead dials

`VELOCITY_ALERT_THRESHOLD` is deprecated and read by no check; tuning it
changes nothing. `VELOCITY_FREEZE_THRESHOLD` is live: it counts lifetime
over-limit alerts per wallet before the next over-limit charge freezes it.
