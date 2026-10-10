# AMW insight reporting authorization amendment

**Local implementation amendment, 2026-10-10.** This resolves the Task 1 gate
recorded in [the source map](amw-insights-source-map.md): the repository has no
scoped, read-only, cross-wallet operator role. The user approved adding one
with explicit wallet scope, no business writes, and a separate permission for
unknown-wallet aggregate counts. The approved insight specification and six-task
plan otherwise remain in force. This amendment authorizes code and synthetic
tests only. It does not issue credentials, create live grants, configure an
identity provider, run a production migration, enable capture, or publish an
endpoint.

## Principal and grants

- A reporting caller presents **only** `Authorization: Bearer <enterprise
  access token>`. Reuse `parse_enterprise_token` in `app/core/oidc_iga.py` for
  pinned issuer/key/algorithm, audience, expiry and subject verification. The
  identity key is the exact verified `(issuer, subject)` pair; never email,
  group name or an unverified claim. An absent/unconfigured trusted issuer,
  invalid token or missing subject denies access. `X-API-Key`, a simultaneous
  bearer and API key, an internal wallet JWT, a wallet API key, and a bootstrap
  API key do not authenticate the reporting dependency. It must not call
  `get_auth_context`, the optional `get_enterprise_principal`, the IGA
  group-to-tool policy map, or any bootstrap/self-provisioning path.
- After full bearer verification, mark the existing
  `CREDENTIAL_ACCEPTANCE` / `CredentialAcceptance` holder accepted so
  `RateLimitMiddleware` treats a
  valid reporting identity as authenticated even when its requested scope is
  denied. A malformed, untrusted or mixed-header credential leaves that
  holder unaccepted and is rejected without X-API-Key fallback. Keep the
  limiter's hashed presented-token bucket; do not log or persist the raw
  bearer or place it in a response.
- Store reporting authority separately from `APIKeyModel` and JWT scopes:
  `InsightReportingPrincipal` has a unique `(issuer, subject)`, `starts_at`,
  required `expires_at`, nullable `revoked_at`, and an explicit
  `allow_unknown_wallet_counts` boolean, default false.
  `InsightReportingWalletGrant` names one existing wallet and one explicit
  immutable ownership/evidence epoch for that wallet, with a unique
  `(principal_id, wallet_id, ownership_epoch_id)`. It has `starts_at`, required
  `expires_at`, and nullable `revoked_at` for **grant liveness**, plus a
  separate half-open historical `evidence_from` / `evidence_until` interval
  for that epoch. A separate immutable `InsightWalletOwnershipEpoch` record
  defines the wallet, epoch ID, owner boundary and historical interval; the
  grant must reference that record and may only narrow its interval. Current
  `WalletModel` ownership and `AccountMapping` alone cannot establish
  historical access. Before any epoch can authorize evidence, validate that
  the wallet's ownership history is complete and non-overlapping across the
  relevant evidence interval and transfer boundary. An absent, incomplete or
  conflicting epoch withholds the row; never fill a historical gap with the
  wallet's current owner or a retrospective `AccountMapping`. These
  are code/schema definitions with synthetic rows in tests; no grant or epoch
  creation/management HTTP route is part of this work.
  Store dates as UTC using the repository's existing timestamp convention.
- A principal and each requested wallet grant are valid only when their
  identity and shape are valid, `starts_at <= now < expires_at`, and
  `revoked_at is None`. Unknown permission kinds, duplicate/conflicting rows,
  malformed dates, missing wallet references or storage failure deny the
  request. No `*`, parent-wallet inheritance, implicit tenant expansion,
  account-map inference or bootstrap-admin override exists. A revoked or
  expired wallet grant never contributes to scope even when another wallet
  grant is live. The grant's liveness interval never extends its historical
  evidence interval. Missing grants deny, rather than produce an empty report.

## Authorization boundary

- The report request supplies a nonempty, explicit set of wallet IDs; the
  operation inspector also supplies its wallet ID and looks up the operation
  only after that wallet is authorized. The requested set must be a subset of
  the currently valid wallet grants. A route dependency returns a frozen
  `Scope(wallet_ids, authorized_ownership_epochs,
  allow_unknown_wallet_counts)` **only after** authentication and grant
  validation. Each authorized epoch carries the exact wallet, immutable epoch
  ID and bounded evidence interval; a wallet ID alone is insufficient. Scope
  contains no bearer, API key or secret. The reader
  accepts this scope rather than a general `AuthContext` and applies wallet
  and ownership-epoch predicates inside every source query before union, link
  expansion, account mapping, inspection or export. Each operation requires an
  authorization-grade original-operation anchor and unique ownership epoch
  inside an authorized evidence interval **before** raw rows or refs can enter
  the batch. A Stage 1 `first_observed_evidence` timestamp is a cohort label,
  not proof of original ownership: if an old operation has no ingress and its
  first surviving audit/terminal row arrives after a wallet transfer, that
  timestamp cannot assign it to the new epoch. Require trusted original
  operation/epoch provenance; otherwise withhold the raw operation and refs
  with an explicit coverage gap. A late terminal
  event inherits its operation's original epoch, even when its occurrence is
  after a transfer; it never moves to the new owner's report. Null or
  ambiguous anchor/ownership provenance is withheld with an explicit coverage
  gap, not assigned using arrival time or current ownership. `AccountMapping`
  supplies customer attribution only and never grants evidence access. An
  unauthorized operation ID must not become an existence oracle.
- Pin one canonical owner wallet for each source and correlation edge. For
  execution insights, the permit and permit-request owner is the **subject /
  charged wallet**, not an issuer-or-subject union. Dispatch, idempotency,
  ledger, receipt, audit and refund evidence use their verified charged or
  recorded owner wallet; a mismatched or missing owner is withheld and flagged.
  An issuer-only grant cannot expand through a permit ID into another subject
  wallet's dispatch, and an A-only projection never includes B's wallet ID in
  rows, references, errors, JSON or CSV. Do not query permits with
  `issuer_wallet_id IN scope OR subject_wallet_id IN scope` for execution
  evidence. Check owner and epoch at each link, not only at the root.
- `Scope` is a public, constructible value object, so its fields alone are
  never proof of authorization. `authorize_scope` registers the **exact
  returned object** and active transaction identity in a private
  `AsyncSession.info` entry. Before any source query, `read_evidence` requires
  object identity (`is`, not value equality), the same session, and the same
  still-active read-only transaction. A caller-created, copied, widened,
  previous-request or previous-transaction `Scope` fails closed. Clear the
  binding when the transaction ends; do not put a bearer or grant secret in
  either the scope or this registry.
- The dependency and `read_evidence` use one `REPEATABLE READ READ ONLY`
  PostgreSQL transaction. The route or CLI owns this session through both
  calls: `authorize_scope(principal, requested_wallets, include_unknown,
  session) -> Scope` and `read_evidence(scope, window, limits, session) ->
  EvidenceBatch`. The first call is asynchronous and checks the principal and
  requested grants before the first evidence query, using one UTC evaluation
  time for the request. The verified bearer is parsed before the transaction;
  `Scope` never contains it. A report or inspector request does not stream
  data to the caller until its authorization, bounded read and serialization
  complete. The authorization is re-evaluated on each new request; the
  transaction gives one consistent grant/evidence view for an in-flight
  request. Grant-table reads are `SELECT` only. No API-key validation, usage
  counter, business mutation, bootstrap provisioning, credential generation
  or reporting grant mutation occurs on the reporting path.
- `allow_unknown_wallet_counts` is an independent permission, not a synthetic
  wallet ID. It is true in `Scope` only when the active principal explicitly
  has the bit **and** the request asks for unknown-wallet counts. A separate
  bounded aggregation may return counts for rows with no verified wallet;
  it must never return those raw rows, IDs, exact event times, evidence refs,
  tool arguments, payloads, or tenant guesses through `EvidenceBatch`, the
  operation inspector, JSON or CSV. Without this permission, no global
  unknown-wallet query runs: report the field as unavailable/not authorized,
  never zero. Wallet-scoped callers cannot get unknown-wallet raw diagnostics
  regardless of this aggregate permission.
- The report has a distinct `unknown_wallet_aggregate` object with a status
  and nullable count, separate from each `Metric.unknown_count` (which counts
  unknown classifications inside the authorized cohort). To prevent
  differencing exact walletless totals with caller-chosen seconds, aggregate
  only fixed **complete UTC-day** buckets: the 7 or 30 whole days ending at
  `floor_to_UTC_midnight(as_of)`. Include `bucket_start` and `bucket_end` in
  the status-bearing object; never compute a walletless count for a partial
  day or an arbitrary sub-day boundary. Requests that shift `as_of` by seconds
  within the same UTC day produce the same bucket and count. `status=complete`
  permits an exact nonnegative `count`, including a genuine zero. For
  `not_authorized`, `unavailable` or `partial`, `count` is null; none may be
  rendered as zero. `Report` construction and both JSON/CSV serializers reject
  any walletless raw operation, evidence row or evidence reference, even if
  internal prospective events legitimately have `wallet_id=None`. Every
  exported `EvidenceRef`/edge must name a nonnull wallet in the authorized
  scope and be verified against evidence from that same wallet in the scoped
  snapshot; a dangling or cross-wallet reference cannot widen access. Evidence
  with a **known authorized wallet** but no account mapping remains in scope;
  its account attribution stays unknown and it is excluded from eligible
  customer counts rather than discarded or treated as walletless.
- Existing business routes retain `get_auth_context` and their current
  authority checks. A reporting bearer alone must fail their authentication
  or authorization. A `Scope` cannot be passed as `AuthContext`, used to mint
  a wallet JWT/API key, invoke a tool, issue/revoke a permit, change grants or
  wallets, refund, or pass a bootstrap-admin check. Holding a separate valid
  business API key is independent authority; no business action is authorized
  *by* a reporting grant. The reporting CLI, when implemented, uses the same
  verifier and grant/reader contract and must not accept a bootstrap key or
  print a token.

## Tests to write before implementation

1. A synthetic, signed trusted-issuer bearer plus two explicit live wallet
   grants reads only those wallets. A third wallet request, absent grant,
   wildcard, parent-wallet ID, changed account mapping and foreign operation
   ID fail before any source query or reveal no existence/detail.
   Transfer a wallet from A to B at a fixed UTC boundary: A's epoch grant
   cannot read B-era roots or refs; B's cannot read A-era roots or refs.
   A terminal linked to an A-epoch operation after the transfer remains A-era
   and invisible to B. Null/overlapping anchor or ownership history withholds
   raw evidence and increments an explicit coverage gap. A changed
   `AccountMapping` cannot change either authorization result. Also seed a
   no-ingress operation whose first surviving evidence appears after transfer:
   without independent proof of its original ownership epoch, neither A nor
   B receives raw rows or refs, and coverage reports the withheld ambiguity.
   Missing or overlapping ownership-history intervals cannot be filled from
   current wallet ownership or `first_observed_evidence` time.
2. Missing/malformed bearer, bad signature, untrusted issuer, wrong audience,
   expired token, absent subject, synthetic signed ID token with client-ID
   audience, internal wallet JWT, wallet API key,
   bootstrap API key, dual bearer/API-key headers and disabled IGA config all
   deny the reporting path before source access and retain the limiter's
   rejected-credential reservation. A valid token with a denied wallet grant
   is authenticated but unauthorized. A token's email/groups cannot
   substitute for exact `(issuer, subject)`; no raw token appears in logs.
3. Not-yet-valid, expired, revoked, duplicate/conflicting or malformed
   principal/wallet grants, missing referenced wallet, and unavailable grant
   storage fail closed. Verify start-inclusive/end-exclusive expiry boundaries
   and a changed grant on the next request. Assert no bootstrap/key creation,
   API-key use count change or business write during a successful read.
4. `include_unknown_wallet_counts` without the separate permission denies;
   omission yields unavailable/not-authorized rather than zero and performs no
   null-wallet query. With permission, only bounded aggregate counts appear;
   raw unknown rows and references never enter scoped evidence, operation,
   JSON, CSV or logs. Assert the status-bearing aggregate is distinct from
   `Metric.unknown_count`; incomplete or unauthorized aggregation has null
   count, while a complete zero stays zero. Construct a report with a
   walletless internal event, operation or evidence reference and assert the
   report and both serializers reject it. A known-wallet unmapped row remains
   present with unknown account attribution. Two `as_of` values a second
   apart within one UTC day yield identical `bucket_start`, `bucket_end` and
   walletless count; a 7/30-day aggregate uses only completed day buckets.
5. Present the reporting bearer alone to representative invocation, API-key
   grant/rotation, wallet mutation, permit mutation, refund and admin-write
   routes. Each fails before its business action. A reporting `Scope` cannot
   satisfy `require_wallet_access`, `require_bootstrap_admin` or JWT scope
   enforcement. Test with development open-admin mode enabled so the reporting
   bearer cannot fall through to bootstrap access.
6. Use a disposable PostgreSQL database to verify that grant validation and
   source pages share one read-only repeatable-read snapshot; a concurrent
   inserted/revoked grant or evidence row cannot widen an in-flight scope.
   A forged, copied or widened `Scope`, or an authentic scope used with a
   different/ended transaction, is rejected before any source query. Recheck
   a revoked grant on the next request. Do not touch a live database.
7. Seed an A-issued/B-subject permit and B-owned dispatch linked by permit ID.
   With only A's issuer wallet grant, the reader returns no B execution,
   B-wallet identifier or foreign evidence reference; it never uses an
   issuer-or-subject predicate. B's subject/charged wallet grant sees the
   operation only when its anchor belongs to B's authorized epoch.

## Release gate

Only synthetic grants and test identities are used during implementation.
Before any production reporting, separately approve the issuer configuration,
grant issuance and revocation process, source database role/replica, schema
migration, export access and retention, and actual wallet assignments. The
OIDC issuer configuration must use a resource/API audience, not an OIDC client
ID audience: the existing parser checks audience but does not distinguish an
ID token from an access token. A synthetic signed ID token with the client
audience must be rejected in tests. The default with no trusted issuer,
verified ownership epochs or grants is denial.
