# Exit and export: what you keep if you leave

**Audience:** procurement and platform teams asking the exit question before
they adopt. Everything a customer accumulates while running this gateway is
listed below with its export route, its format, and whether the thing that
checks it afterwards depends on us.

Last updated: 2026-10-20. Routes are from the routers under `app/routers/`;
verifiers are from `b2a_sdk/`. "Independent" means the verifier imports none
of this application and needs no network access to the issuer at verification
time. "First-party" means the check is computed by the running service over
its own database.

## 1. Artifacts

| Artifact | Export route | Format | Verifier | Independent? |
|---|---|---|---|---|
| **Receipts** (signed terminal accounting for every governed call) | `GET /v1/receipts/{id}/portable` (one); `GET /v1/receipts` and `GET /v1/permits/{id}/receipts` (lists) | JSON bundle: `signing_input`, Ed25519 signature, key reference | `b2a_sdk.receipt_verifier.verify_bundle`; CLI `b2a-verify-receipt --bundle receipt.json --keys trust-keys.json` | **Yes.** MIT, depends only on `cryptography`. Needs the issuer key set, fetched once from `/.well-known/trust-keys.json` and pinned. |
| **Issuer key set** | `GET /.well-known/trust-keys.json`, `GET /.well-known/jwks.json` (unauthenticated) | JSON; JWKS | Any JOSE tooling | Yes, once fetched. Key distribution itself is first-party: keys arrive from the origin being audited. Out-of-band pinning is not implemented. |
| **Permits** (signed capabilities) | `GET /v1/permits/{id}`; `GET /v1/permits` | JSON with every signed field plus `signature` and `key_id` | `b2a_sdk.edge_client.LocalPermitValidator`; `POST /v1/permits/verify` | **Yes** for the SDK validator (reconstructs the signed bytes without the application). The route is first-party. |
| **Evidence bundle** per receipt (ledger entry, idempotency record, dispatch attempt, audit event, cross-checked) | `GET /v1/receipts/{id}/evidence` | JSON | Computed by the service | **First-party.** The bundle is the operator's statement about the operator's database. It is the only place the receipt→ledger→attempt linkage can be checked; the portable receipt carries identifiers, not the records. |
| **Audit chain** (signed, hash-linked control-plane events per wallet) | `GET /v1/audit/events`; `GET /v1/audit/summary` | JSON event list with payload hash, previous hash, chain hash, signature, key id | `POST /v1/audit/verify-chain` | **First-party.** The signed bytes are exportable, but no SDK verifier that imports none of the application exists. That verifier is designed and frozen (`docs/PROOF_MATRIX.md`, "Where provability goes next", item 1). |
| **Ledger** (credits, debits, refunds, reservations) | Through receipts, evidence bundles, and wallet routes | JSON | Reconciles against receipts (`refund-{ledger_entry_id}` keys are deterministic) | First-party. An internal credit ledger, not settlement. |
| **Policy bundles** (standing wallet guardrails) | `GET /v1/policies`; `GET /v1/policies/{id}` | JSON | None needed; declarative | Yes, as data. Bundles are not versioned; export captures current state only. |
| **API keys** | Not exportable by design | Only the SHA-256 hash is stored | | Keys are minted, rotated, and revoked at `/v1/api-keys`; a departing customer revokes, they do not export. |
| **Tool catalog** (what the gateway governed) | `GET /mcp/tools.json`, `GET /v1/discover`, `GET /openapi.json` | MCP tools JSON; OpenAPI 3.1 | | Yes, as data. |
| **Traces / spans** | **None exist.** | | | There is no OpenTelemetry instrumentation and no OTLP export. Runtime logging is `structlog` to stdout with a `correlation_id` on unclassified failures. Per-call evidence lives in receipts and evidence bundles, not in a trace store. |
| **Agent definitions, memory stores, eval datasets** | **Not applicable.** | | | The gateway does not define agents, hold memory, or own model evaluation. The repository's own proofs and tests (`tests/`, `scripts/`, `failure_lab/`) are source and travel with the code. |

## 2. What is open and what is source-available

From [`LICENSING.md`](../LICENSING.md):

- **MIT**, embeddable anywhere, forever: `b2a_sdk/` (client, offline receipt
  verifier, permit validator), `awi_sdk/`, `framework_integrations/`,
  `wrappers/*`, `examples/`. The verifiers are MIT on purpose: a receipt is
  only "verifiable without us" if the verifier can live anywhere.
- **Business Source License 1.1**: the core (`app/`, `migrations/`, `scripts/`,
  `tests/`, `docs/`, root files). You may read, run, modify, self-host, and
  fork it, including to keep running it after leaving. The one withheld use is
  offering the core to third parties as a competing hosted service. Each
  version converts to MIT four years after publication.
- Versions published before the license change were MIT and remain so.

Self-hosting the core after exit is therefore a supported outcome, not a
workaround: the deployment is the repository `Dockerfile`, PostgreSQL, and
Redis ([`docs/deploy-railway.md`](deploy-railway.md)), and the schema is
Alembic history under `migrations/`.

## 3. What does not leave, said once more

- No traces, because none are produced.
- No independent audit-chain verifier yet; the chain's signed bytes export,
  the check is first-party.
- No external anchoring: receipts prove what happened, never what did not.
  Nothing is in a transparency log.
- Key distribution is from this origin. A customer who cannot trust the
  origin for keys needs out-of-band pinning, which is frozen until a named
  partner requires it.

## 4. Exit procedure, in order

1. Fetch and pin `/.well-known/trust-keys.json`.
2. Page through `GET /v1/receipts` and fetch `/portable` for each receipt you
   intend to retain; verify a sample offline with `b2a-verify-receipt`.
3. Fetch `GET /v1/receipts/{id}/evidence` for any receipt you may need to
   defend later, while the service is still running. This is the step that
   cannot be done after shutdown.
4. Fetch `GET /v1/audit/events` per wallet and run `POST /v1/audit/verify-chain`
   once more; store both.
5. Export permits and policy bundles as JSON.
6. Revoke every API key at `/v1/api-keys`.
7. Take the database and the repository if you intend to self-host; the BSL
   permits it.
