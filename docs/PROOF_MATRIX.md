# Proof Matrix

Which command proves which invariant, and what each one does **not** prove.

The trust plane's differentiator is that its claims are executable: a reviewer
can run one command and watch an invariant hold or fail. This document is the
index of those commands. It is descriptive, not aspirational — every row below
maps to a target in the [`Makefile`](../Makefile) or a job in
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) that exists today.

For the product thesis these proofs defend, see [`WEDGE.md`](../WEDGE.md). For
the claims the project deliberately does not make, see
[`SECURITY_LIMITATIONS.md`](../SECURITY_LIMITATIONS.md).

## Local proofs (no credentials, no external services)

| Command | Proves | Backend |
|---|---|---|
| `make prove-trust-plane` | The full trust loop plus replay and tamper detection — see the breakdown below | Throwaway SQLite |
| `make prove-trust-plane-postgres` | **Migrations only** — see the defect note below | Throwaway SQLite, after migrating PostgreSQL |
| `make red-team-trust-plane` | Ten distinct attacks are each denied with a specific reason code and none produces a debit | Throwaway SQLite |
| `make dogfood-trust-plane` | Exactly-once against a **real durable side effect** (a file on disk), not just a ledger row | Throwaway SQLite |
| `make agent-ops-war-room` | The operator narrative: discovery, provisioning, invoke, replay, self-inspection, denial | Temp SQLite |

### Known defect: `prove-trust-plane-postgres` does not prove PostgreSQL

Recorded here rather than quietly omitted, because the target's name asserts
something it does not do.

`scripts/demo_trust_plane.py` unconditionally sets `DATABASE_URL` to a
throwaway SQLite file inside `configure_environment()`, which runs *before* the
FastAPI app is imported. The operator's `DATABASE_URL` is therefore overwritten
before the application reads it. What `make prove-trust-plane-postgres`
actually does is apply `alembic upgrade head` to the supplied PostgreSQL
database — a genuine and useful migration check — and then run every assertion
on SQLite.

The same defect makes CI's `postgres_trust` job a SQLite run.

Real PostgreSQL coverage in this repository comes from `make
prove-crash-recovery` (the two-process harness fails closed unless the URL is
PostgreSQL) and from the CI suites parameterized by `TEST_POSTGRES_URL`, not
from the demo script. **Fixing this means having `configure_environment()`
respect a caller-supplied `DATABASE_URL` instead of overwriting it** — a small
change, deliberately left out of the documentation change that discovered it,
because it alters what a proof command proves and deserves its own review.

### What `make prove-trust-plane` asserts

One run, in order: sponsor wallet, agent wallet, and wallet-bound key
provisioning; MCP tool discovery; signed permit issuance and verification; active
signing-key metadata exposed without leaking private material; a governed
invoke producing a success receipt linked to a ledger entry; receipt signature
verification; exactly one ledger debit; audit-chain verification and event
linkage; **replay returning the identical receipt with no second debit**;
out-of-scope denial (`permit_tool_not_allowed`) with a signed denial receipt
and no charge; **denial replay returning the same denial receipt**; fail-closed
`permit_required` denial when no permit is supplied; cross-wallet read denied
with 403; a valid evidence bundle; **offline verification of the exported
receipt against the unauthenticated key document, through the SDK verifier
that imports none of the application** — including detection of edited signed
bytes and the separation of a missing key (`unknown_key`) from tampering; and
detection of both a tampered receipt and a tampered audit event.

Replay is therefore already a proven invariant, not a gap — it is asserted here
on both the success and denial paths, again in the dogfood proof against a real
side effect, again across two OS processes by the crash proof, and again under
15 identical concurrent requests by the live conformance suite. During the
in-progress window, overlapping local-tool requests may receive the explicit
`idempotency_in_progress` response; after completion, replay returns the one
receipt.

### The ten attacks in `make red-team-trust-plane`

`permit_required`, `permit_not_found`, `permit_tool_not_allowed`,
`permit_scope_missing`, `permit_budget_exceeded`, `permit_wallet_mismatch`,
`permit_key_mismatch`, `permit_expired`, `permit_revoked`, and
`permit_signature_invalid`. The battery also asserts that no attack debited
either wallet, that a positive-control call afterwards still charges exactly
once, and that the audit chain remains valid throughout.

## Crash-consistency proof

```bash
export DATABASE_URL=postgresql+asyncpg://...   # dedicated, EMPTY database
make prove-crash-recovery
```

This starts two independent Uvicorn worker processes against one shared
PostgreSQL database and injects faults at durable commit boundaries. It proves
six things — the first three on the local execution path, the last three on
the governed *remote* dispatch path:

1. **Concurrent invokes serialize.** While worker A is paused mid-side-effect,
   an identical invoke on worker B receives `idempotency_in_progress`. After
   release, the original succeeds, replay returns the identical result, and the
   database shows exactly one tool execution, one debit, and one receipt.
2. **A committed receipt survives worker death.** The worker is killed after
   the receipt commit; replay is blocked until reconciliation repairs the
   record, then returns the *same* receipt id — still exactly one execution,
   debit, and receipt.
3. **An ambiguous side effect fails closed.** The worker is killed after the
   tool side effect but before the receipt. Reconciliation leaves the record
   untouched and reports it in its `needs_review` count rather than repairing
   it, replay stays `idempotency_in_progress`, and nothing is redispatched
   automatically.
4. **A kill past the dispatch checkpoint is charged and signed ambiguous.** The
   worker is killed after the durable `prepared -> dispatched` transition but
   before the remote effect runs. No effect actually landed, and the trust
   plane still cannot prove that, so reconciliation terminalizes the attempt as
   `delivery_uncertain`: the charge is retained, no refund is issued, the permit
   reservation stands, and the signed receipt records the ambiguity.
5. **A kill after the remote effect never redispatches it.** The worker is
   killed once the remote effect is durable but before any terminal result is
   recorded. Reconciliation terminalizes the attempt as `delivery_uncertain`
   and the upstream side-effect count stays at exactly one — the effects table
   permits duplicates on purpose, so a redispatch would be visible as a second
   row rather than hidden by a constraint.
6. **A kill before the checkpoint is refunded, not held.** The worker is killed
   immediately after the debit commits, while the attempt is still `prepared`
   and does not yet name the ledger entry that paid for it. Nothing crossed the
   dispatch boundary, so this is the one post-charge crash the plane can resolve
   in the caller's favour: recovery finds the orphaned debit by its operation
   identity rather than by the attempt's null pointer, refunds it, releases the
   reservation, signs `failed_refunded`, and never contacts the upstream server.
   A second sweep issues no second refund.

Note that (3) is deliberately *not* a recovery. The correct behavior for an
ambiguous post-side-effect crash on the local path is fail-closed manual
review, because the gateway cannot know whether the effect landed. Describing
this proof as "crash recovery" without that qualifier overstates it; the
accurate framing is **crash consistency with reconciliation, and fail-closed
review for ambiguous outcomes**. (4), (5), and (6) are the governed remote path's
answer to the same question: there the durable dispatch state machine can tell
the cases apart. A crash before the checkpoint is provably non-delivered and is
refunded; a crash after it is unknowable and terminalizes into
`delivery_uncertain` instead of waiting for a human — and neither redispatches.

Alongside those six narrative scenarios, a table-driven boundary suite kills a
worker at each of the seven remaining instrumented commit boundaries and pins
the disposition it must leave. Its value is mostly negative: it records that
the local path is deliberately *more* conservative than the remote one. A
provably effect-free local crash is still not released for retry, because the
effect-free sweep is scoped to `operation_kind == "upstream_mcp"`; and a
reservation stranded before any charge stays stranded on a live permit, because
reclaiming it early could let a concurrent request over-spend. Both were
verified against the code rather than inferred from the observed behaviour.

All three remote-path proofs additionally rebuild the full evidence bundle for the
recovered receipt and require every check to pass, so the claim is that the
recovered evidence *verifies*, not merely that a receipt row exists. Each also
re-runs reconciliation and asserts the second sweep is a no-op, and replays the
call to confirm a client retry gets the ambiguous disposition back rather than a
fresh execution.

The harness refuses to run unless it is safe: it fails closed on a
non-PostgreSQL URL, a production-like `ENVIRONMENT`, a stale Alembic revision,
or any application table that already holds rows, and it takes an advisory lock
so two runs cannot overlap. Without the opt-in environment variables it skips,
so it never interferes with `make test`.

CI runs these in the `postgres_permit_concurrency` job, as two steps against
one PostgreSQL service: the **13** crash-consistency tests in
`tests/test_mcp_postgres_multiprocess.py`, then the **11** row-lock
concurrency tests in `tests/test_permit_postgres_concurrency.py`. That job
installs dependencies with `pip` rather than `uv`, so its step is spelled
inline; the Make target is the operator-facing equivalent, not a literal
copy of the CI step.

## Release gates

| Command | Enforces |
|---|---|
| `make trust-coverage-gate` | 24 focused trust test files at an **80% coverage floor** across 22 named trust-plane control modules |
| `make trust-release-gate` | A 13-file trust suite (including the in-process adversarial pass over the five claims, `tests/test_adversarial_five_claims.py`), then the coverage gate, then the demo proof, then discovery-drift tests, then committed-OpenAPI parity, then simulation-inventory parity |

CI runs `scripts/trust_release_gate.sh` as a dedicated required check
(`trust_release_gate`) so `main` cannot advance past an unproven claim; the
exact branch-protection settings are in
[`trust-release-gate-branch-protection.md`](trust-release-gate-branch-protection.md).
The [stranger test](stranger-test.md) is the human milestone that checks the
same five claims are reachable and checkable from the published docs alone.

## Live suites (against a deployment you operate)

Both write real rows to the target. Point them at staging.

| Command | Proves | Requires |
|---|---|---|
| `make trust-conformance-live` | Golden path; sequential replay; 15 identical concurrent requests exposing one receipt identity or explicit `idempotency_in_progress`, followed by a completed replay and one charge; a changed payload under a reused key conflicting rather than replaying; budget denial; expired and forged permit rejection; receipt and audit-chain verification; tenant isolation against a directly-supplied foreign wallet and permit id | `AGENT_MIDDLEWARE_API_KEY`; set `AGENT_MIDDLEWARE_API_URL` or it defaults to production |
| `make scoped-smoke-loop` | Authority readable for the caller's own wallet; scoped permit issued and carrying a nonce; governed invoke; the debit matching the receipt's own stated cost; replay returning the same receipt and charging nothing further; a changed payload under a reused key refused; an out-of-scope but genuinely registered tool denied and not charged; the portable receipt carrying a signature, key id, and named canonicalization | `AGENT_MIDDLEWARE_API_KEY` holding a **wallet-scoped** key (the loop refuses a bootstrap admin key); `--tool` required off loopback |
| `make adversarial-battery-live` | Wallet isolation, invalid-key rejection, forged-receipt rejection, permit key binding, expired permits, revoked keys, replay idempotency; always revokes keys it minted | `API_URL` (no default, by design) and `BOOTSTRAP_KEY` |

`scoped-smoke-loop` is the one built to run continuously: it needs no admin
credential, so the key it runs on cannot mint keys or read another tenant's
audit trail if the runner holding it is compromised. That is also its limit —
tenant isolation, audit-chain verification, and refund reconciliation are
absent from it precisely because a scoped key must not be able to reach them,
and they stay in `trust-conformance-live` for an operator to run deliberately.
It reports SKIP rather than a false PASS for the out-of-scope denial when the
deployment registers only one tool, since invoking an unregistered name proves
"tool not found" rather than "the permit refused it".

The battery reports SKIP — never a false PASS — for MCP-invocation checks when
the deployment exposes no invokable `golden-path-echo` tool. It does not
exercise over-spend containment.

## What is not proven

Being explicit about the boundary is what makes the proofs worth anything.

- **Exactly-once is gateway-scoped.** A remote tool's side effect is exactly
  once only if that tool honors the forwarded idempotency key. A post-dispatch
  transport failure is signed `delivery_uncertain`, stays charged, and is never
  automatically retried or refunded. The gateway-scoped half of that — no
  redispatch after ambiguity, charge retained, evidence verifiable — is proved
  by a real process kill in `make prove-crash-recovery`; the downstream half
  remains the tool's responsibility and is not proved here.
- **Audit chains are tamper-evident, not immutable.** An administrator who can
  alter both the database and its chain metadata is inside the trust boundary.
  Append-only storage and external anchoring are not implemented.
- **Receipt signatures are independently verifiable; the rest of verification
  is still first-party.** A receipt exported via
  `GET /v1/receipts/{receipt_id}/portable` can be checked by anyone against the
  unauthenticated `/.well-known/trust-keys.json`, using
  `b2a_sdk.receipt_verifier`, which imports none of this application and needs
  no network. That closes the "no independent offline verifier" gap for
  signatures. Three limits remain, and they are not small:
  - **Key distribution is first-party.** Keys are fetched over TLS from the
    issuing origin, so an attacker controlling that origin can serve a key set
    that validates forged receipts. Out-of-band key pinning is not
    implemented.
  - **No transparency log.** Receipts prove what happened, never what did not.
    A plane can issue a receipt to one party and omit it from another's
    listing, and no verifier can detect that.
  - **`/v1/audit/verify-chain` and the evidence bundle remain first-party.**
    Those are computed by the operator over the operator's database; only the
    receipt signature travels.

  See [agent-accountability.md](agent-accountability.md) for the full list of
  what a receipt does and does not prove.
- **There is no Byzantine fault tolerance, and the term does not apply.** The
  architecture is one API server, one database, and one operator-held signing
  key. BFT addresses arbitrary faults among mutually distrusting replicas;
  there are no replicas and no consensus here. The honest goal is
  single-operator tamper-evidence today, with independent verification as the
  named next step.
- **The crash proof covers instrumented boundaries, not arbitrary failure.**
  Faults are injected at specific durable commit points. It does not prove
  survival of a kill at an arbitrary instruction, database crash or failover,
  or multi-node high availability. All twelve instrumented fault points are now
  reached by a test: five by the narrative scenarios above, and the remaining
  seven by a table-driven boundary suite that pins the disposition a kill at
  each commit boundary must leave. What is still not proven is a kill at an
  *arbitrary* instruction — only at the instrumented boundaries.
- **`make prove-trust-plane` runs on SQLite with a hardcoded demo signing
  seed.** It proves the logic, not the production posture. No target re-runs
  these assertions against PostgreSQL — see the defect note above. PostgreSQL
  behavior is covered instead by `make prove-crash-recovery` and the
  `TEST_POSTGRES_URL` suites in CI; production configuration is enforced
  separately by the `production_trust` CI job.
- **Tenant isolation is application-layer.** PostgreSQL row-level security is
  not implemented and no public multi-tenant isolation guarantee is made.

## Where provability goes next

Ordered by how much each would strengthen the differentiator per unit of work.

1. **Extend the offline verifier to permits and audit events.** Receipts are
   done — `b2a_sdk.receipt_verifier` verifies an exported receipt against the
   published key document with no running server, and `make prove-trust-plane`
   asserts it. Permits and audit-chain events are still checked only by the
   operator, so the same treatment for them is now the highest-leverage item:
   an export carrying the exact signed bytes, plus verifier support.
2. **Out-of-band key distribution.** Offline signature verification is only as
   strong as the key set it runs against, and today that is fetched from the
   origin being audited. Key pinning, or publication through an independent
   channel, is what makes the verifier meaningful against a compromised
   issuer.
3. **Exercise the remaining crash fault points.** The harness already
   instrumented boundaries are all covered as of 2026-08-15; what remains is
   coverage of failure modes the harness cannot inject at all — database crash
   or failover, and multi-node high availability.
4. **External anchoring or append-only storage**, which is what would let the
   project retire the "tamper-evident, not immutable" caveat.
5. **KMS-backed signing custody**, designed in
   [`docs/key-management.md`](key-management.md) but not implemented.

Items 4 and 5 are frozen by [`WEDGE.md`](../WEDGE.md) until a design partner
requires them. They belong on a roadmap, not in product copy.
