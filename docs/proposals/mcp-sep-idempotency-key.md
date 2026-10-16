# Draft SEP: a standard `_meta` idempotency key for `tools/call`

Status: **internal draft. Not submitted, no outreach.** Backlog item #9.
Owner: AMW. Date: 2026-10-11.

> This is a design doc for a possible MCP Specification Enhancement
> Proposal. Spec details marked *(verify)* must be checked against the
> current MCP spec revision before anything is submitted.

## 1. Problem

`tools/call` has no standard way for a client to say "this is the same call
as before". When a response is lost (timeout, dropped stream, client crash),
the client cannot tell whether the tool ran. Retrying can run a paid or
irreversible effect twice. Not retrying can drop work.

Servers and gateways that solve this today each choose their own `_meta` key:

| Implementation | Key | Status |
|---|---|---|
| Agent Middleware (AMW) gateway, inbound and forwarded upstream | `io.agentmiddleware/idempotency_key` | Shipped (`app/routers/mcp_standard.py`, `app/services/upstream_mcp.py`) |
| Flama (vortico/flama#293) | `dev.flama/idempotencyKey` (default, configurable) | Open feature request, milestone 2.3/2.4 |

Two vendor prefixes for the same concept already exist. Without a neutral
name, every client must know every server's key, and every gateway must
translate between them.

## 2. Evidence that the semantics matter

This comes from a black-box test of AMW production on 2026-10-10 by an
outside team (Wallet Of Agents, public thread). They used a capped key and
spent 6 of 1000 credits.

- 10 parallel calls with the same key and same body produced the same
  receipt and exactly one debit. A retry after a client timeout recovered
  the original receipt.
- Same key + different body was rejected, "including 4 of 5 in a parallel
  race". That phrasing is ambiguous, and a repro is tracked separately. The
  ambiguity is the point: the spec must state what happens when mismatched
  bodies race.
- They reported key conflicts as HTTP 200 + JSON-RPC `-32603` (generic
  internal error). On AMW `main` at the time of this draft, conflicts return
  `-32009 idempotency_key_reused` (REST: 409), pinned by
  `tests/test_mcp_idempotency_conflict_surface.py`. Whatever the deployed
  version returned, a generic code makes a conflict indistinguishable from a
  server bug. A standard needs one dedicated code.

## 3. Proposal

### 3.1 Key name

Options, in order of preference:

1. **A spec-owned name**, e.g. `io.modelcontextprotocol/idempotency-key`.
   The spec reserves `_meta` prefixes whose second label is
   `modelcontextprotocol` or `mcp` for its own use *(verify current wording)*.
   A spec-owned name is the only kind that needs no vendor translation. It
   requires the SEP to be accepted.
2. **A neutral community prefix.** No such registry exists today, so this
   would be a new convention, which is weaker than option 1.
3. **Keep vendor names and require configurability.** Flama already plans
   this (a configurable name). It works, but every deployment then needs
   matching configuration.

Recommendation: propose option 1. In the meantime, servers SHOULD accept a
configurable alias list, so `io.agentmiddleware/idempotency_key` and
`dev.flama/idempotencyKey` keep working while the standard name rolls out.

Exact casing (`idempotency-key` vs `idempotencyKey`) follows whatever
convention the spec uses for its existing reserved `_meta` keys *(verify)*.

### 3.2 Value

- A string, 1–128 characters, with no control characters. AMW enforces
  exactly this today (`MAX_CLIENT_IDEMPOTENCY_KEY_LENGTH` and
  `resolve_client_idempotency_key` in `app/services/idempotency.py`; Python SDK). Flama
  requires "bounded-length strings".
- Opaque to the server. Clients SHOULD use ≥ 128 bits of randomness (a
  UUIDv4 or ULID) and MUST NOT encode secrets in it, because the key may
  appear in logs and receipts.
- A malformed key MUST be rejected with `-32602 Invalid params` **before**
  any side effect. A server MUST NOT silently generate a key in place of a
  malformed one, because that would defeat the retry protection the client
  asked for. An *absent* key means a non-idempotent call.

### 3.3 Scope

A key is scoped to **(authenticated caller, tool name)**.

- "Caller" is the server's authenticated principal (API key, OAuth subject,
  or wallet). It is never the transport session: `Mcp-Session-Id` changes
  across reconnects, and a retry after reconnect is the main case this
  feature exists for.
- Two different callers using the same key MUST NOT see each other's
  results. That would leak data across tenants.
- AMW scopes per wallet and endpoint, with the tool and arguments inside the
  request hash. That is equivalent for conflict detection and slightly
  stricter, since a key reused across tools conflicts. Flama scopes per
  caller and tool. The SEP should allow servers to scope *more* strictly,
  never less.

### 3.4 Semantics

For a `tools/call` carrying key `K` from caller `C` for tool `T`, with
`H = hash(canonical arguments)`:

| Stored state for (C, T, K) | Same `H` | Different `H` |
|---|---|---|
| none | Execute. Store (K → H, outcome) atomically with the decision to execute. | n/a |
| in progress | Return an in-progress error (retryable), or wait for completion within server limits. MUST NOT execute again. | Conflict error (§3.5) |
| completed (any outcome, including tool error) | Return the stored result. MUST NOT execute again. | Conflict error (§3.5) |

Requirements:

- **Atomic claim.** Lookup and claim MUST be one atomic operation, including
  across server instances that share a store. Concurrent same-key calls
  produce at most one execution. Flama states the same requirement for its
  `TaskStore`.
- **Race between different bodies.** When N concurrent calls share `K` with
  different `H`, exactly one call MAY win the claim. All others MUST get the
  conflict error, whichever arrived first. Replays of the winner return the
  winner's stored result. This turns "4 of 5 rejected" from an ambiguous
  observation into the specified outcome: one accepted, four conflicts.
- **Outcome-unknown is an outcome.** If the server dispatched the effect and
  cannot tell whether it completed, it SHOULD store and replay that unknown
  state rather than re-execute. AMW calls this `delivery_uncertain`. The
  SEP should standardize only the "do not re-execute" rule, not a state
  vocabulary.
- **Canonical hash.** Arguments are hashed after JSON canonicalization
  (sorted keys, no insignificant whitespace; RFC 8785 JCS recommended).
  Transport framing (the JSON-RPC `id`, `_meta` other than the key) MUST NOT
  affect `H`.

### 3.5 Conflict error

Same key, different arguments, MUST return a **dedicated** JSON-RPC error.
It MUST NOT be `-32603` (internal error) or `-32602` (the request is
well-formed).

```json
{
  "code": -32009,
  "message": "idempotency_key_reused",
  "data": {
    "idempotencyKey": "<echoed key>",
    "expectedArgumentsHash": "sha256:<hex of the stored request hash>",
    "receivedArgumentsHash": "sha256:<hex of this request>"
  }
}
```

- The code value is a placeholder. AMW uses `-32009` today. The SEP should
  ask the spec to allocate one from its reserved range *(verify which range
  the spec allots for protocol-defined errors)*.
- `expectedArgumentsHash` lets a client tell "I changed the body by mistake"
  apart from "someone else is using my key". Disclosing a hash of the
  caller's *own* earlier arguments to that same caller leaks nothing new,
  since scope is per caller. Servers MUST NOT include the stored arguments
  themselves.
- AMW status: for conflicts against a current-format record, AMW's `-32009`
  response carries the hashes as `error.data.expected_request_hash` and
  `error.data.received_request_hash` (snake case; see
  `docs/failure-semantics.md`). Exception: when the stored record predates
  the canonical idempotency scope (a completed pre-canonical record from the
  other transport, or a legacy worker that won a rolling-upgrade insertion
  race), the two hashes were computed differently and are not comparable, so
  AMW returns `-32009` with no `error.data` at all
  (`_begin_governed_mcp_idempotency_scope` in `app/routers/mcp.py`). A
  conforming SEP server in the same position SHOULD likewise omit the hashes
  rather than send values a client cannot compare.

### 3.6 Retention (TTL)

- Servers MUST retain a key at least as long as they advertise. Servers
  SHOULD advertise retention so clients know how long a retry is safe, for
  example via a capability field such as
  `capabilities.tools.idempotency: { "retentionSeconds": 86400 }`
  *(shape to be agreed)*.
- A retry after expiry is a new call. Clients MUST NOT retry with the same
  key past the advertised retention and expect deduplication.
- For task-augmented calls, the key SHOULD live at least as long as the
  task (Flama ties it to `ttlMs`).
- AMW today keeps idempotency records indefinitely. No purge job was found.
  That satisfies any advertised minimum, but storage grows without bound.

### 3.7 Forwarding through gateways

A gateway that calls an upstream MCP server on the caller's behalf:

- SHOULD forward a key upstream, so the upstream can deduplicate a retry
  that comes from the gateway itself.
- MAY derive a new key per upstream (AMW forwards the client key, or a
  derived `act1-…` key for action-bound permits) as long as the derivation
  is deterministic. A deterministic key means a gateway retry reuses it.
- SHOULD record the forwarded key and any upstream-reported request id in
  its own audit evidence. AMW now signs both onto the receipt
  (`constraints_evaluated.upstream_dispatch`, see
  `docs/delivery-uncertain-reconcile-worker.md`). This is what makes
  checking with the provider possible after an outcome-unknown dispatch.

### 3.8 Optional: status lookup by key

To reconcile outcome-unknown calls, a client or gateway must be able to ask
"what happened to K?" without re-executing. Options:

- (a) Re-send `tools/call` with the same key and arguments. On a compliant
  server this is a safe lookup by construction (§3.4). It is the simplest
  option and needs no new method.
- (b) A new read-only method, e.g. `tools/callStatus { name, idempotencyKey }`.

Recommendation: rely on (a) and leave (b) out of scope. (a) works only if
the server is compliant. A gateway must not assume compliance, so AMW
keeps re-sending opt-in per tool.

### 3.9 Non-goals

- Deduplicating effects *inside* the tool (the tool's own downstream APIs).
- Exactly-once delivery. This is at-most-once execution per key with result
  replay.
- Billing semantics. Gateways layer their own debit rules on top.
- Deduplicating calls that carry no key.

## 4. Coordination with Flama (vortico/flama#293)

What #293 says (read 2026-10-11): it is open and has no maintainer
discussion yet. The proposal: a client-supplied key in `_meta`, with a
**configurable name** defaulting to `dev.flama/idempotencyKey`. The issue
names `io.agentmiddleware/idempotency_key` as an example convention to
align with. Keys are scoped per caller and tool, and a match returns the
existing task handle in any state. Lookup and creation are atomic in
`TaskStore`. Reuse with different arguments is rejected (no error code is
named). Keys expire with the task's `ttlMs`, apply only to task-augmented
calls, and **standardizing via a SEP is explicitly out of scope** for
that issue.

Alignment, point by point:

| Topic | Flama #293 | AMW today | This draft |
|---|---|---|---|
| Key name | `dev.flama/idempotencyKey`, configurable | `io.agentmiddleware/idempotency_key`, fixed | Spec-owned name; accept aliases during transition |
| Value bounds | bounded string, else invalid params | 1–128 chars, no control chars, else `-32602` | Same as AMW |
| Scope | caller + tool | wallet + endpoint (tool inside hash) | caller + tool, stricter allowed |
| Concurrency | atomic `TaskStore` claim | DB unique key + one-shot dispatch claim | atomic claim, MUST |
| Mismatched args | rejected, code unspecified | `-32009 idempotency_key_reused` | dedicated code + `expectedArgumentsHash` |
| TTL | task `ttlMs` | indefinite | advertised retention, ≥ task TTL |
| Applies to | task-augmented calls only | all governed calls | all `tools/call`; tasks inherit |

Proposed coordination, **when outreach is approved**. No contact has been
made. Each step needs Christopher's go-ahead.

1. Share this draft with the Flama maintainer as a comment on #293. Ask
   whether they would co-sponsor a SEP with the spec-owned name, keeping
   their configurable alias.
2. Ask Flama to pick a dedicated mismatch error code, ideally the same
   placeholder (`-32009`) until the spec allocates one, so clients see one
   behaviour across both servers.
3. Offer AMW's conflict-surface and parallel-race tests as a cross-
   implementation conformance sketch.
4. Pending a spec-owned name, AMW adds `dev.flama/idempotencyKey` to the
   keys it accepts inbound (small, behind config) and configures the
   forwarded upstream key name per upstream. The forwarded name is
   hard-coded today in `UpstreamMcpAdapter._call_tool_once`.

## 5. Open questions

- Is `-32009` free in the spec's reserved range, or does the spec need a new
  allocation? *(verify)*
- Should the in-progress response wait (long-poll) or return immediately?
  AMW returns `-32005 idempotency_in_progress` immediately on most surfaces.
- Should the canonicalization be mandated (JCS) or left to the server, as
  long as it is stable?
- Where should the retention advertisement live: server capabilities,
  per-tool annotations, or both?
- How does the key interact with the tasks feature for servers that
  support both? *(verify the current tasks spec status)*
