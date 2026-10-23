# Exit and export: what you keep if you leave

**Audience:** procurement and platform teams asking the exit question before
they adopt. This page lists the artifacts a customer can take, with each one's
export route, format, and whether the thing that checks it afterwards depends
on us. It is not an exhaustive data inventory; §3 lists what has no export.

Last updated: 2026-10-23. Routes are from the routers under `app/routers/`,
except `/openapi.json`, which FastAPI serves itself. Verifiers are from
`b2a_sdk/`. "Independent" means the verifier imports none of this application
and needs no access to the issuer at verification time. "First-party" means
the check is computed by the running service over its own database.

## 1. Artifacts

Credentials: a wallet-scoped key reads its own wallet's data; bootstrap-admin
keys (the `VALID_API_KEYS` deployment variable) read across wallets and are
held by whoever controls the deployment. `GET /v1/policies` requires an admin
key. `GET /v1/receipts` requires a `wallet_id` or `permit_id` you own unless
the caller is admin, and wallet-less audit events (denials, system events) are
readable only with an admin key. Default rate limit is 120 requests per minute
per key, so a large export is slow: 10,000 receipts at two calls each is about
2.8 hours, and `/evidence` is the expensive call.

| Artifact | Export route | Format | Verifier | Independent? |
|---|---|---|---|---|
| **Receipts** (signed terminal accounting for every governed call) | `GET /v1/receipts/{id}/portable` (one); `GET /v1/receipts` and `GET /v1/permits/{id}/receipts` (lists) | JSON bundle: `signing_input`, Ed25519 signature, key reference | `b2a_sdk.receipt_verifier.verify_bundle`; CLI `b2a-verify-receipt --bundle receipt.json --keys trust-keys.json` | **Yes, in that the verifier imports none of this application and needs no issuer access at verification time.** The key set it checks against still comes from the issuer (next row), so authenticity is the issuer's own claim. See §2 for how to obtain the verifier. |
| **Issuer key set** | `GET /.well-known/trust-keys.json`, `GET /.well-known/jwks.json` (unauthenticated) | JSON; JWKS | Any JOSE tooling | Yes once you hold it. Save the document and pass it with `--keys`; `--issuer` re-fetches it from the origin on every run, and nothing in the SDK pins a key id or fingerprint. Keys arrive from the origin being audited. Out-of-band pinning is not implemented. **Disabled signing keys are dropped from the published set**, and `/portable` answers 409 `receipt_signature_invalid` for receipts signed under one, so a key set saved at onboarding and after each rotation is the only durable record. |
| **Permits** (signed capabilities) | `GET /v1/permits/{id}`; `GET /v1/permits` | JSON with the signed fields plus `signature` and `key_id` | `b2a_sdk.edge_client.LocalPermitValidator`; `POST /v1/permits/verify` | **Yes** for the SDK validator. The signature covers the grant (scopes, tools, `max_credits`, expiry, nonce), **not** `status`, `revoked_at`, or `spent_credits`: those are unsigned operator state in the same JSON. An offline-verified permit shows what was granted, not that it was unrevoked. The route is first-party. |
| **Evidence bundle** per receipt (receipt, permit, ledger entry, a sanitized projection of the dispatch attempt, the audit event, a separate top-level `audit_chain` verification over the wallet's whole chain, and a `checks` list) | `GET /v1/receipts/{id}/evidence` | JSON | Computed by the service (`app/trust/evidence.py`) | **First-party.** It is the operator's statement about the operator's database, and the only place the receipt→ledger→attempt linkage can be checked; the portable receipt carries identifiers, not the records. The idempotency record is not included, only its id on the receipt. If the operator's instance and database are gone you cannot get new bundles, and a saved bundle is only the operator's statement at export time. |
| **Audit chain** (signed, hash-linked control-plane events per wallet) | `GET /v1/audit/events`; `GET /v1/audit/summary` | JSON events with payload hash, previous hash, chain hash, signature, key id | `POST /v1/audit/verify-chain` | **First-party.** The events export, but **not the exact signed bytes**: the signed payload includes the stored `metadata_json` string, which the route returns as a parsed `metadata` object, so a third party cannot recompute the signature from the export. An SDK verifier that imports none of the application is scoped and frozen, and does not exist yet (`docs/PROOF_MATRIX.md`, "Where provability goes next", item 1). |
| **Ledger** (credits, debits, transfers, refunds) | `GET /v1/billing/ledger/{wallet_id}`; also via receipts and evidence bundles | JSON | Reconciles against receipts. Refunds of governed calls use the deterministic entry id `refund-{debit_ledger_entry_id}`; refunds created by the Stripe webhook use random ids and are deduplicated by event id. | First-party. An internal credit ledger, not settlement. **No full export:** the ledger route returns at most the newest 200 entries and cannot be paged, so older entries are reachable only if a receipt links them. A complete copy means the database. Reservations are not ledger rows; they live on the permit (`spent_credits`) and the dispatch attempt's call slot, released by the call path on failure or by the reconciliation sweep when the call path could not. |
| **Policy bundles** (standing wallet guardrails) | `GET /v1/policies`; `GET /v1/policies/{id}` | JSON | None needed; declarative | Yes, as data. Bundles are not versioned; export captures current state only. |
| **Permit requests and signed quotes** | `GET /v1/permit-requests/{id}`; `GET /v1/quotes/{id}` (and the `/v1/me/...` listings) | JSON | None independent | First-party records, including the human decision on a permit request. |
| **Per-invoke human approvals** | **No export route** | Stored in the `human_approvals` table | | Present only in a database copy. |
| **Tool arguments and upstream results** | **No export route** | Stored (`mcp_dispatch_attempts.result_json`, `idempotency_records.response_json`); exported as hashes only (`request_hash`, `response_hash`) | | The evidence bundle deliberately keeps payloads private. They exist only in a database copy. |
| **API keys** | Not exportable by design | Only the SHA-256 hash is stored for database keys | | Wallet keys are revoked per wallet at `/v1/api-keys`. Administrator keys are the `VALID_API_KEYS` variable, not rows; they are removed by whoever controls the deployment's variables. |
| **Tool catalog** | `GET /mcp/tools.json`, `GET /v1/discover`, `GET /openapi.json` | MCP tools JSON; OpenAPI 3.1 | | Yes, as data. |
| **Traces / spans** | **No export route.** Optional OpenTelemetry tracing exists (`app/core/tracing.py`) and is off by default. | OTLP/HTTP to a collector the operator runs | | Nothing here a customer can take. With `OTEL_TRACING_ENABLED` false (the default) or the otel extra absent, no spans are made and no exporter is configured. When on, six spans on the governed path (`http.request`, `mcp.invoke`, `mcp.reserve`, `mcp.dispatch_claim`, `mcp.upstream_dispatch`, `mcp.receipt`) carry only an allowlist of attributes (tool name, outcome state, a hash of the wallet id, the attempt id), so they are not a record of calls you could rebuild from. Runtime logging is `structlog` JSON written to **stderr** from `app/main.py` (the container entrypoint does not merge it into stdout); other modules log through the standard library. Unclassified failures carry a `correlation_id`. Per-call evidence lives in receipts and evidence bundles. |
| **Agent definitions, memory stores, eval datasets** | **Not applicable on the supported deployment.** | | | The core trust plane does not define agents, hold memory, or own model evaluation. Two frozen proof surfaces do. `comms` keeps an agent registry (`GET /v1/comms/agents`) and `ai` keeps per-agent memory (`POST /v1/ai/memory/recall`, newest 1,000 entries per agent); both are in durable state, mount only with `ENABLE_PROOF_SURFACES=true`, which production refuses at boot, and have no purpose-built export. The repository's own proofs and tests travel with the code. |

## 2. What is open and what is source-available

From [`LICENSING.md`](../LICENSING.md):

- **MIT**: `b2a_sdk/` (client, offline receipt verifier, permit validator),
  `awi_sdk/`, `framework_integrations/`, `wrappers/*`, `examples/`. The
  verifiers are MIT on purpose, so they can live anywhere.
- **Business Source License 1.1**: the core (`app/`, `migrations/`, `scripts/`,
  `tests/`, `docs/`, root files). You may read, run, modify, self-host, and
  fork it. The one withheld use is offering the core to third parties on a
  hosted or embedded basis in order to compete with the licensor's products or
  services built on it. Each version converts to MIT four years after
  publication. The Additional Use Grant wording was drafted by the maintainer,
  not by counsel; read the note at the end of `LICENSING.md`.
- Already-published versions released under MIT are irrevocably MIT. The core
  moved from MIT to BSL 1.1 on 2026-10-01 (commit b0692253, whose parent
  3655f6b0 is the last MIT state of `main`). Code running in a hosted
  deployment today is BSL. The newest version tag, `v1.2.0-rc.1` (2026-05-19),
  is MIT; no version tag exists after the change.

**How to get the verifiers.** `b2a_sdk` is not on PyPI. The only published SDK
release, `python-sdk-v0.4.0` (2026-08-07), predates the verifier and contains
neither `receipt_verifier.py`, `verify_cli.py`, nor `LocalPermitValidator`. Install
from a checkout (`pip install -e './b2a_sdk[verify]'`) at a commit from
7afc03ac (2026-08-11) onward, and **keep a copy of `b2a_sdk/` as part of your
exit**, together with the key set.

**Self-hosting.** The license permits it. It is not a supported deployment of
the pilot: `SECURITY_LIMITATIONS.md` states that customer-operated
on-premises deployments are not supported, and `docs/deploy-railway.md`
excludes customer-VPC deployments. You would run it unsupported, without that
runbook's qualification steps. The ingredients are the repository `Dockerfile`,
PostgreSQL, Redis, and the Alembic history under `migrations/`. You also need
a database copy and a signing key (§4, step 7).

## 3. What does not leave, and what is not promised

- No traces, because none are produced.
- No independent audit-chain verifier yet; the check is first-party.
- **The audit chain is tamper-evident, not immutable.** Whoever administers
  the database can delete rows, and whoever holds the signing key can rewrite
  the chain (`SECURITY_LIMITATIONS.md`, `docs/PROOF_MATRIX.md`). A passing
  `verify-chain` at exit is the operator's statement, not an independent
  finding.
- No external anchoring: receipts prove what happened, never what did not.
  Nothing is in a transparency log.
- Key distribution is from this origin. A customer who cannot trust the origin
  for keys needs out-of-band pinning, frozen until a named partner requires it.
- **No deletion controls.** `docs/deploy-railway.md` lists
  retention, deletion, and legal-hold controls among things not yet built. No
  route deletes receipts, ledger rows, audit events, or stored results; the
  only core `DELETE` route is for API keys. Removal means the operator
  deleting the customer's deployment project. No timeline is documented
  (not verified), and provider backups are not addressed.
- No documented procedure, timeline, or commitment for handing over a
  database. It lives in the vendor-managed per-customer project.

## 4. Exit procedure, in order

0. **Quiesce.** Stop traffic. Revoke or let expire live permits
   (`POST /v1/permits/{id}/revoke`). Drain pending refunds
   (`GET /v1/receipts/reconciliation/refunds?status=pending`) and resolve any
   `delivery_uncertain` receipts with the operator and your upstream.
   Exporting while reservations are in flight or refunds are pending captures
   non-terminal state.
1. Save a dated copy of `/.well-known/trust-keys.json`. Better, you saved one
   at onboarding and after each rotation; diff against it now. The SDK pins
   nothing.
2. Page through `GET /v1/receipts` and fetch `/portable` for each receipt you
   intend to keep; verify a sample offline with `b2a-verify-receipt`.
3. Fetch `GET /v1/receipts/{id}/evidence` for any receipt you may need to
   defend later, while the service is running.
4. Fetch `GET /v1/audit/events` per wallet and run `POST /v1/audit/verify-chain`
   once more; store both, remembering §3 on what that result is.
5. Export permits, permit requests, quotes, and policy bundles as JSON.
6. Revoke wallet keys per wallet (`DELETE /v1/api-keys/{wallet_id}/{key_id}` or
   `POST /v1/api-keys/emergency-revoke`). Administrator keys are removed by
   whoever controls the deployment's variables, not through the API.
7. Self-hosting needs two things the API does not give you: a database dump,
   which is arranged with the operator because no self-serve route exists, and
   a signing key. The private signing seed is a deployment secret and is not in
   the dump. Without it you must start a new key id; receipts already issued
   keep verifying against the old key set you saved in step 1.
