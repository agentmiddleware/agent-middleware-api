# Invariant Attack Report

**Campaign:** adversarial invariant testing of the governed trust plane
**Target:** the local instance booted by `make quickstart` (strict trust mode,
SQLite, self-serve keys, one invokable governed tool `partner.notes.write` at
2 credits/call), plus a throwaway PostgreSQL instance for engine comparison and
the repo's own two-process crash proof.
**Posture:** local only. Nothing was deleted; the only destructive action was
`kill -9` + restart of the local server (attack 5), which the brief permits.
Full API keys are never shown — every key is redacted to its 8-char prefix.
**Date:** 2026-08-12

This campaign stops proving the system works when everyone behaves nicely and
instead tries to make it break the promises it sells: no double charge, no
overspend, no scope escape, no forgeable receipt, no accounting corruption on
crash, no credential acting beyond its authority. Every attack uses **real
concurrency** (OS threads released from a shared barrier), captures the exact
request and observed response, and gets a single verdict.

## Verdicts

| # | Invariant | Attack | Verdict |
|---|-----------|--------|---------|
| 1 | A retry never double-charges | 10 parallel identical invokes + same-key/different-payload replay | **HELD** |
| 2 | A permit cap contains overspend | 10 parallel distinct-key invokes racing a 7-credit cap | **BROKE** on SQLite / **HELD** on Postgres |
| 3 | A permit authorizes only its named tools | invoke a tool outside `allowed_tools` | **HELD** |
| 4 | A receipt's signed facts cannot be forged | tamper each signed field; verify offline | **HELD** |
| 5 | A crash leaves charge⇔receipt paired, never charged-without-proof, never double | `kill -9` mid-flight + boundary-kill proof | **HELD** |
| 6 | A credential acts only within its authority | invalid/revoked keys, confused deputy, cross-tenant | **HELD** |

**Headline finding — Attack 2 (budget overspend), BROKE on the shipped local
posture.** Ten concurrent invocations with distinct idempotency keys against a
**7-credit** permit (tool costs 2/call, so 3 calls should be the ceiling) **all
succeeded and debited 20 credits** — a ~3× overspend, reproducible. Sequential
enforcement is correct (the 4th sequential call is denied). The root cause is
that the concurrency guard `authorize_and_reserve` relies on
`SELECT … FOR UPDATE` row locking (`app/services/permits.py:427`), and
**SQLAlchemy silently drops `FOR UPDATE` on SQLite** — so the atomic
check-and-reserve degrades to a lost update. The identical race **holds exactly
on PostgreSQL** (3 successes, 7 signed budget denials), confirming this is a
storage-engine gap in the quickstart posture, not a flaw in the invariant logic.
`make quickstart` is also the walkthrough that sells "a permit cap contains
overspend" to a first-time stranger — so the gap sits directly under a headline
claim.

---

## Test environment & reproduction

Boot the real trust plane (identical to `make quickstart`):

```bash
make quickstart            # http://127.0.0.1:8000, strict trust mode, SQLite
export API_URL=http://127.0.0.1:8000
```

Mint a wallet-scoped credential with no pre-shared secret (used by every attack):

```bash
curl -s -X POST "$API_URL/v1/dev-keys/self-provision" \
  -H "Content-Type: application/json" -d '{"agent_id":"attacker"}'
# -> {"sponsor_wallet_id":"spn-…","wallet_id":"agt-…","key_id":"key_…",
#     "key_prefix":"b2a_…","api_key":"b2a_… (shown once)"}
```

The wallet holds 1000 synthetic dev credits. The automated harness that produced
every result below lives in [`scripts/invariant_attacks/`](scripts/invariant_attacks/)
(stdlib only; see its README). Each script provisions its own fresh wallet, so
runs are independent and repeatable.

---

## Attack 1 — Double charging → **HELD**

**Invariant.** A governed invocation is charged at most once. Neither a burst of
identical parallel requests nor a same-key/different-payload replay may produce a
second charge or a second side effect.

**Method.** Issue a permit with a generous cap. Fire **N=10 identical**
`tools/call` requests — same idempotency key, same payload — from 10 OS threads
released simultaneously by a barrier. Then reuse that idempotency key with a
**different** payload.

**Exact request (each of the 10, identical):**

```bash
curl -s -X POST "$API_URL/mcp/messages" -H "X-API-Key: b2a_****" \
  -H "Content-Type: application/json" -d '{
  "jsonrpc":"2.0","id":"atk1","method":"tools/call",
  "params":{"name":"partner.notes.write","arguments":{"text":"atk1 identical-payload"},
    "mcpContext":{"wallet_id":"agt-****","permit_id":"permit-****",
                  "idempotency_key":"atk1-note-shared"}}}'
```

**Observed.** Exactly **one** of the ten carried a signed receipt; the other
**nine returned `idempotency_in_progress`** (JSON-RPC `-32003`, fail-closed) —
never a second execution:

```
distinct receipt_ids returned: 1   (winners_with_receipt=1, collapsed=9)
notes written (side effect):   1
wallet debited:                2.00 credits   (one ledger debit)
```

Same key + **different** payload:

```json
{"jsonrpc":"2.0","id":"atk1-conflict",
 "error":{"code":-32603,"message":"idempotency_key_reused"}}
```

…with **no** new note and **no** new debit (wallet still 2.00 debited).

**Why it holds.** Two engine-agnostic DB constraints, not an app-level
check-then-act: idempotency dedup is `UNIQUE(wallet_id, endpoint, idempotency_key)`
and the charge is `UNIQUE(wallet_id, operation_key)` with
`operation_key = idempotency_record_id` (`app/db/models.py`), plus a
`with_for_update()` lock on the idempotency row during the debit
(`app/services/billing_engine.py:453`). Concurrent duplicates are collapsed to
`idempotency_in_progress` (`app/routers/mcp.py:802`); a changed payload is caught
by request-hash comparison → `idempotency_key_reused`
(`app/services/idempotency.py:66`).

Reproduce: `python scripts/invariant_attacks/attack1_double_charge.py`.

---

## Attack 2 — Budget / permit overspend → **BROKE** (SQLite) / **HELD** (Postgres)

**Invariant.** Cumulative spend under a permit can never exceed its `max_credits`
cap — even under concurrent invocations racing the spend check.

**Method.** (2a) Sequential boundary: cap=7, cost=2/call — calls 1–3 succeed
(2,4,6 spent), call 4 must be denied. (2b) Concurrency race: fresh cap=7 permit,
**N=10** invocations with **distinct** idempotency keys (so idempotency cannot
collapse them) fired simultaneously.

### 2a Sequential boundary — correct

```
call 1 -> success  charged 2.00  ledger 6ba6…
call 2 -> success  charged 2.00  ledger 80bf…
call 3 -> success  charged 2.00  ledger a4f8…
call 4 -> permit_budget_exceeded  (signed denial receipt, credits_charged "0", ledger_entry_id null)
wallet debited total: 6.00
```

The denial is signed evidence carrying no charge (`outcome:"denied"`,
`reason_code:"permit_budget_exceeded"`), returned in `error.data.receipt`.

### 2b Concurrency race — BROKEN on SQLite

**Exact request (each of the 10, distinct `idempotency_key` and `id`):**

```bash
curl -s -X POST "$API_URL/mcp/messages" -H "X-API-Key: b2a_****" \
  -H "Content-Type: application/json" -d '{
  "jsonrpc":"2.0","id":"atk2b-<i>","method":"tools/call",
  "params":{"name":"partner.notes.write","arguments":{"text":"race <i>"},
    "mcpContext":{"wallet_id":"agt-****","permit_id":"permit-****",
                  "idempotency_key":"atk2b-note-<i>"}}}'
```

**Observed (reproduced across cap/N combinations):**

| cap | N parallel | cap should allow | successes | credits debited | overspent |
|-----|-----------|------------------|-----------|-----------------|-----------|
| 7   | 10        | 3                | **10**    | **20.0**        | **yes**   |
| 2   | 5         | 1                | **3**     | **6.0**         | **yes**   |
| 6   | 8         | 3                | **8**     | **16.0**        | **yes**   |

Every successful response carried a distinct receipt and a distinct ledger entry
(10 receipts, 10 debits for the cap=7 case). The server log shows the contention
leaking through as `sqlite3.OperationalError: database is locked`.

**Root cause — proven, not inferred.** After a cap=6 / N=8 race the permit's own
persisted counter shows a **lost update**:

```
permit.max_credits (db):   6.0
permit.spent_credits (db): 6.0     <- the permit "thinks" 6 was spent
wallet actually debited:   16.0    <- the wallet really lost 16
```

The guard `authorize_and_reserve` locks the permit row and increments
`spent_credits` under that lock (`app/services/permits.py:427-440`):

```python
model = await session.get(PermitModel, permit_id, with_for_update=True)  # row lock
... if model.spent_credits + estimated_credits > model.max_credits: deny
model.spent_credits += estimated_credits
```

But `with_for_update()` compiles differently per engine:

```
SQLite   : SELECT permits.permit_id, permits.spent_credits FROM permits
Postgres : SELECT permits.permit_id, permits.spent_credits FROM permits FOR UPDATE
```

On SQLite the row lock is a **silent no-op**, so every concurrent caller reads the
same pre-spend value, all pass the cap check, and their `spent_credits +=`
increments clobber each other — a textbook TOCTOU lost update. (Attack 1 is
immune because it is defended by the ledger `UNIQUE` constraint, which SQLite
*does* enforce; the budget cap has no such constraint.)

**Same race on PostgreSQL — HELD.** Booting a Postgres-backed instance and firing
the identical races:

| cap | N  | successes | budget denials | debited | overspent |
|-----|----|-----------|----------------|---------|-----------|
| 7   | 10 | 3         | 7              | 6.0     | no        |
| 2   | 5  | 1         | 4              | 2.0     | no        |
| 6   | 8  | 3         | 5              | 6.0     | no        |

The real `FOR UPDATE` row lock serializes the check-and-reserve; excess callers
block, re-read the incremented `spent_credits`, and receive signed
`permit_budget_exceeded` denials.

**Recommendation.** The invariant logic is right; the storage engine defeats it.
Either (a) make the quickstart/local posture concurrency-safe — e.g. a
DB-agnostic conditional debit
(`UPDATE permits SET spent_credits = spent_credits + :c WHERE permit_id = :p AND spent_credits + :c <= max_credits`,
enforce via affected-rowcount) or a SQLite `BEGIN IMMEDIATE`/serialized-writer
path — or (b) explicitly document that SQLite caps are sequential-only and gate
the quickstart's "contains overspend" claim accordingly. Option (a) is
preferred: the same code then holds on both engines.

Reproduce: `python scripts/invariant_attacks/attack2_budget.py` and
`attack2_mechanism_sqlite.py`; Postgres control via `attack2_budget_postgres.py`.

---

## Attack 3 — Scope escape → **HELD**

**Invariant.** A permit authorizes only the tools it names; a call for any other
tool is denied with a signed denial receipt, no charge, no side effect.

**Method / exact request.** Issue a permit whose `allowed_tools` is
`["some.other.tool"]`, then invoke `partner.notes.write` with it:

```bash
curl -s -X POST "$API_URL/mcp/messages" -H "X-API-Key: b2a_****" \
  -H "Content-Type: application/json" -d '{
  "jsonrpc":"2.0","id":"atk3","method":"tools/call",
  "params":{"name":"partner.notes.write","arguments":{"text":"atk3"},
    "mcpContext":{"wallet_id":"agt-****","permit_id":"permit-****",
                  "idempotency_key":"atk3-a"}}}'
```

**Observed** — a *signed denial receipt* (nested under `error.data.receipt`):

```json
{"jsonrpc":"2.0","id":"atk3",
 "error":{"code":-32003,"message":"permit_tool_not_allowed",
  "data":{"receipt":{
    "receipt_id":"rcpt-****","tool":"partner.notes.write",
    "outcome":"denied","reason_code":"permit_tool_not_allowed",
    "credits_charged":"0","ledger_entry_id":null,
    "signature":"…","signature_key_id":"quickstart-local-ed25519"},
   "details":{"requested_tool":"partner.notes.write","allowed_tools":["some.other.tool"]}}}}
```

Variants observed the same way, all with **0 charge and 0 notes written**:
empty `allowed_tools` → `permit_scope_missing` (signed denial); an unregistered
tool name → `Tool not found`, denied before any receipt. Enforced in
`_validate_model_for_action` (`app/services/permits.py:489`) and finalized as a
signed denial by `_finalize_governed_denial` (`app/routers/mcp.py`).

Reproduce: `python scripts/invariant_attacks/attack3_scope.py`.

---

## Attack 4 — Forged receipts → **HELD**

**Invariant.** A receipt's signed facts cannot be altered without the independent
offline verifier catching it, and "forged" is reported distinctly from "cannot
verify" (unknown key) — an outage must never read as fraud.

**Method.** Fetch a genuine receipt bundle and the public key set (the key set
needs no credential), verify offline with the shipped `b2a_sdk` verifier (imports
no server code), then tamper each signed fact and re-verify.

```bash
curl -s "$API_URL/v1/receipts/<rid>/portable" -H "X-API-Key: b2a_****" -o bundle.json
curl -s "$API_URL/.well-known/trust-keys.json" -o keys.json
PYTHONPATH=b2a_sdk/src python -m b2a_sdk.verify_cli --bundle bundle.json --keys keys.json
```

**Observed (exit code in parentheses — 0 verified / 1 forged / 2 undetermined):**

```
genuine SUCCESS receipt          -> VERIFIED  rcpt-…                                  (0)
genuine DENIAL receipt           -> VERIFIED  rcpt-…                                  (0)
tamper credits_charged 2 -> 0    -> INVALID   signature does not verify over signing_input  (1)
tamper outcome success -> denied -> INVALID   signature does not verify over signing_input  (1)
tamper tool -> evil.tool         -> INVALID   signature does not verify over signing_input  (1)
tamper wallet_id -> agt-attacker -> INVALID   signature does not verify over signing_input  (1)
genuine receipt, unknown kid     -> UNKNOWN_KEY  no published key for kid 'quickstart-local-ed25519'  (2)
```

Every altered signed field is caught; denial receipts are first-class signed
evidence; and a key-server outage yields **UNDETERMINED (2)**, never a false
**INVALID (1)**. Signing covers `receipt_id, permit_id, wallet_id, key_id, tool,
request_hash, response_hash, ledger_entry_id, credits_authorized,
credits_charged, outcome, created_at` (+ conditional `reason_code`, …) over
canonical JSON (`app/services/signing_keys.py`), verified byte-for-byte over
`signing_input` (`b2a_sdk/src/b2a_sdk/receipt_verifier.py`).

Reproduce: `python scripts/invariant_attacks/attack4_forgery.py`.

---

## Attack 5 — Crash consistency → **HELD**

**Invariant.** After an uncontrolled crash + restart: for every operation either
the charge **and** the receipt exist or neither does; never "charged but no
proof" left silently, never a charge recorded twice, never a success receipt
whose ledger entry vanished.

**Architecture (the risk).** The wallet debit + ledger row commit
(`app/services/billing_engine.py:446-505`, atomic together) and the receipt
persist (`app/services/receipts.py:403`) are **separate transactions**, with
`idem.mark_charged` as a breadcrumb between them. So a crash in that window can
leave a committed charge whose receipt is not yet written — recovery is meant to
come from `reconcile_stuck_records`. The user's own pushback is the right one:
*a random `kill -9` can miss the dangerous window.* So this attack uses three
complementary methods.

### 5a Authoritative boundary-kill proof (PostgreSQL) — PASS

The repo ships a two-process proof that injects faults at **named commit
boundaries** and kills a worker there. All three pass (`make prove-crash-recovery`,
26.5s):

```
test_two_processes_serialize_one_governed_side_effect        PASSED  (debit_count==1, receipts==1)
test_receipt_commit_survives_worker_death_and_reconciles     PASSED  (fault after_receipt_commit -> reconciled, same receipt, debit_count==1)
test_post_side_effect_crash_requires_review_without_redispatch PASSED (fault after_tool_side_effect -> debit==1, receipts==(), reconcile flags needs_review==1, NO auto-redispatch)
```

Test #3 is exactly the "charged + side effect but no receipt" state: it is
surfaced as **`idempotency_needs_review`**, never re-run automatically and never
double-charged (`tests/test_mcp_postgres_multiprocess.py`).

### 5b Live `kill -9` mid-flight on the SQLite quickstart instance

A threshold killer polls the live DB and `kill -9`s the server the instant
committed debits cross 10 — so the crash lands amid real charges whose receipts
are still unwritten. Then, after restart, **every** attempted idempotency key is
replayed with its identical payload. Decisive tripwire: total committed debits
must never exceed the number of distinct idempotency keys.

```
at crash:  10 debits, 1 receipt   ->  9 charged-but-no-receipt
           of the 10 debits: 8 checkpointed (mark_charged done), 2 uncheckpointed
                              (crash in the charge->mark_charged sub-window)
replay of 200 keys: 12 interrupted keys -> idempotency_in_progress (record blocks
                    re-execution -> NO second charge); fresh keys execute once
final:     118 debits total (<= 200 distinct keys), 109 success receipts
           double-charged keys (total & per-key): NONE
           success receipts with a missing ledger entry: NONE
```

No double charge, no receipt-without-charge. The interrupted requests return
`idempotency_in_progress` — the client holds no receipt yet, but the surviving
idempotency record makes a second charge impossible.

### 5c Recovery actually runs on the local instance

Forcing `reconcile_stuck_records(idle_seconds=0)` against the live SQLite DB
returns `repaired=2, needs_review=25`: charged-but-no-receipt records are
**repaired** (when a receipt exists for the ledger entry) or **flagged for
review**, never silently dropped. Crucially, the delete path is restricted to
`operation_kind == "upstream_mcp"` and **excludes local tools**
(`app/services/idempotency.py:444-460`), so a charged local-tool record is never
deleted — it always survives to block re-execution. A ledger-wide query confirms
**0 committed debits were orphaned** (every debit still maps to a surviving
record).

**Verdict: HELD**, with one honestly-scoped caveat that matches the repo's
documented `delivery_uncertain` / manual-review semantics
([`docs/failure-semantics.md`](docs/failure-semantics.md)): immediately after a
crash there is a transient "charged, proof-pending" window during which the
client sees `idempotency_in_progress` rather than a receipt, until the background
reconcile (which runs every 5 min on ≥5-min-idle records) repairs or flags it.
The narrow charge→`mark_charged` sub-window leaves an uncheckpointed-but-charged
local record that is safe from double charge (the record survives and blocks
replay) but is not auto-flagged for review — worth tightening, not a money
invariant break.

Reproduce: `make prove-crash-recovery`;
`python scripts/invariant_attacks/attack5_crash_sqlite.py`; `reconcile_probe.py`.

---

## Attack 6 — Key / credential misuse → **HELD**

**Invariant.** A credential acts only within its own authority — never another
wallet's, never after revocation, never above its scope.

**Method / observed** (each row is one request; none produced a side effect):

| Vector | Request | Result |
|--------|---------|--------|
| Garbage API key | invoke with `X-API-Key: b2a_not_a_real_key…` | `403 invalid_api_key` |
| No credential | invoke with no key | `401 missing_credentials` |
| Confused deputy (wallet A's wallet) | key **B** invokes using key A's permit, claiming wallet A | `wallet_access_denied` |
| Confused deputy (own wallet) | key **B** invokes wallet B but with key A's permit | `permit_wallet_mismatch` |
| Cross-tenant permit issuance | key A issues a permit with `subject_wallet_id` = wallet B | `403 subject_wallet_access_denied` |
| Cross-tenant ledger read | key A reads `GET /v1/billing/ledger/<walletB>` | `403 wallet_access_denied` |
| Audit-plane isolation | key A reads `GET /v1/audit/summary` | `200`, but `by_wallet` shows **only wallet A** |
| Revoked key | `DELETE /v1/api-keys/<walletA>/<keyA>` (`204`), then invoke with key A | `403 invalid_api_key` |

The audit case deserves a note: `GET /v1/audit/summary` returns `200` for a
wallet-scoped key, but the handler self-scopes non-admins to their own wallet
(`app/routers/audit.py:148-152`), so wallet A's summary contains only wallet A's
events even though the instance has processed dozens of events across many
wallets — proper tenant isolation, not an escalation. Permit↔key binding is
enforced by `subject_key_id` and `subject_wallet_id` checks
(`app/services/permits.py:480-489`); revocation flips the key to non-`ACTIVE`,
which `validate_key` filters out (`app/services/api_key_service.py`).

Reproduce: `python scripts/invariant_attacks/attack6_key_misuse.py`.

---

## What this campaign proves — and what it does not

**Proves:** five of the six core trust invariants survived an explicit hostile
test with real concurrency, receipt tampering, crash recovery, and credential
misuse — double-charge, scope escape, receipt forgery, crash accounting, and
credential authority all HELD. The sixth, budget-cap containment, HELD
sequentially and on PostgreSQL but **BROKE under concurrency on the shipped
SQLite/quickstart posture**, with the root cause isolated to `FOR UPDATE` being a
no-op on SQLite.

**Does not prove:** production security. Credits here are synthetic; the quickstart
signing key is local; settlement is not exercised; and the concurrency findings
are storage-engine-specific — the Postgres control run is a spot check, not a
full production-posture audit. Attack 5's exact-boundary coverage rests on the
Postgres two-process proof; the SQLite live-kill is complementary, and a random
`kill -9` still cannot guarantee hitting every microsecond window.

## Recommended next step

Fix Attack 2 first — it is the one broken invariant and it sits under a headline
quickstart claim. Make the permit reserve concurrency-safe on SQLite (DB-agnostic
conditional debit, or a serialized-writer path), then re-run
`attack2_budget.py` against the quickstart instance until the cap holds under a
10-way race, exactly as it already does on PostgreSQL. Re-run the full battery
after the fix to confirm no regression in attacks 1 and 5, which share the
idempotency/ledger machinery.
