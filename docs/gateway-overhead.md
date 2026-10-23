# Gateway handler time: in-process, SQLite, zero-latency upstream

**Audience:** anyone sizing a latency budget for an agent that calls tools
through this gateway, and reviewers who ask "what does the hop add" (the
compounding question: a 40-step agent run pays the hop 40 times).

This page publishes one measured figure and the method behind it so it can be
reproduced or disputed. **It is the floor of the gateway's own handler work,
not the cost of the hop in production.** §3 lists what is excluded; read it
before quoting the number.

Measured 2026-10-22 on an Apple M4 Pro (14 cores), **under load** (see §4).
Raw results and provenance are committed next to this page in
[`docs/research/gateway-overhead-2026-10-22/`](research/gateway-overhead-2026-10-22/).

## 1. The numbers

Per governed `tools/call` on `POST /mcp/messages` (the legacy endpoint, with a
pre-minted permit), strict trust mode, zero-latency in-process upstream:

| Path | p50 | p95 | n |
|---|---|---|---|
| **First call** (full pipeline: one debit, one receipt, one audit event) | **30–32 ms** | 36–49 ms | 2 × 1,000 |
| **Replay** (same key, stored receipt returned, nothing re-executed) | **4.4–4.7 ms** | 5.0–5.5 ms | 2 × 1,000 |

Two runs back to back, 20 warm-up calls discarded. Ranges are the spread
between the two runs. The p99 and max values are in the raw files but are not
quoted here: p99 varied from 71 to 76 ms and max from 76 to 237 ms between
runs, which is scheduler noise on a loaded machine, not a property of the
gateway.

What the first call pays for, in pipeline order
([`POLICY_ENFORCEMENT.md`](POLICY_ENFORCEMENT.md) §2): API-key hash lookup and
constant-time compare; wallet ownership; tool resolution; idempotency record
creation; permit validation including the Ed25519 signature check; wallet
policy evaluation; the atomic budget reservation and prepared dispatch
attempt (one transaction); the debit; the executor call, inside which the
one-shot dispatch claim commits immediately before the send (the router hands
the claim to the executor as a callback, `mcp.py:2706-2710`); result
canonicalization; receipt signing (Ed25519) and the hash-chained, signed audit
event; idempotency record completion. All of these commits go to the ORM
database, a SQLite file here, in WAL mode with `synchronous=NORMAL`
(`app/db/database.py:141-146`): a commit is a WAL append, and `fsync` happens
at checkpoints, not on every commit.

The replay number is the cost of refusing to do any of that again: key
authentication, the idempotency-record lookup, the permit load with the
permit↔wallet↔key binding re-check and a permit signature verification, and
the stored envelope. No debit, dispatch, receipt, or audit event is written.

## 2. Method

```bash
python scripts/measure_gateway_overhead.py --calls 1000 --warmup 20 --json out.json
```

[`scripts/measure_gateway_overhead.py`](../scripts/measure_gateway_overhead.py)
boots the real application in-process (`httpx.ASGITransport`, no socket), in
strict trust mode with an ephemeral signing key and a throwaway SQLite
database. It registers an upstream-shaped executor that honors the
`before_dispatch` claim callback and returns instantly, provisions a sponsor
wallet, an agent wallet, a wallet-scoped key, and one permit, then times each
HTTP request from the client's side: `N` governed calls with distinct
idempotency keys and arguments, then `N` replays of the same keys.

On this endpoint a JSON-RPC failure comes back as HTTP 200, so the script does
not trust the status code. For every call and replay it asserts a result with
no `error`, `isError` false, and a receipt id; it asserts the `N` first calls
produced `N` distinct receipts, that every replay returned the same receipt id
as its first call, and that the executor dispatched exactly `warmup + N`
times. A measurement that stopped exercising the governed path fails instead of
reporting a flattering number. (An earlier version checked only the HTTP
status. At 1,000 one-credit calls it silently crossed the hourly velocity
guard, `VELOCITY_HOURLY_LIMIT`, and would have timed the frozen-wallet denial
path. The tool is now priced at 0.01 credits to stay under that guard.)

Percentiles are nearest rank, `round(p/100 * (n-1))` over the sorted samples.
With 1,000 samples the p95 is a stable figure and the p99 and max are not.

Stdout carries only the JSON result; the application's startup log lines go to
stderr.

## 3. What this number is not

- **Not the cost of the hop in production.** Excluded: network, TLS, the
  Railway edge, PostgreSQL round trips (each commit becomes a network round
  trip), and Redis rate-limit round trips (the supported deployment has a Redis;
  here the in-memory limiter runs). Production will be slower, by an amount
  this page does not measure.
- **Not the real adapter's per-call cost, and not the upstream's time.** The
  executor here costs nothing. The real adapter, on every call, re-validates and
  re-resolves the upstream URL (a fresh DNS lookup, no cache), builds a new
  HTTP client and a new TCP and TLS connection, runs MCP `initialize`, commits
  the dispatch claim, sends `tools/call`, and terminates the session. (Before
  the call-session fix in [`mcp-security-posture.md`](mcp-security-posture.md)
  §3.2 the SDK also issued a `tools/list` after `tools/call` to validate the
  result; it no longer does.) Those are gateway-induced round trips on top of
  the upstream's own time, none of them measured here. The live `/health/dependencies` payload reports aggregate
  `call_metrics` (count, total and max latency) for the real path, without
  percentiles.
- **Not the supported endpoint.** The script measures `POST /mcp/messages`,
  which is marked deprecated in the OpenAPI contract. `POST /mcp`, when
  enabled, mints a permit per call (policy lookup, idempotency begin and
  complete for the mint, a signed permit) and is expected to cost more. That
  was not measured.
- **Not concurrent.** Calls are sequential. Under concurrency calls on one
  wallet contend on the permit row, the wallet rows, and the per-wallet
  audit-chain head. The chain head uses optimistic retry rather than row locks,
  so contention shows up as tail latency and, past the retry budget, as
  retryable errors. Per-wallet throughput, not per-call latency, is the number
  to measure next.
- **Not a deployed-instance measurement.** No script in the repo measures
  per-call latency against a deployed instance: `scripts/stress_test_live.py` is
  an edge-case correctness test and reports only aggregate totals.

## 4. Conditions and provenance

| | |
|---|---|
| Machine | Apple M4 Pro, 14 cores, macOS 26.7 (Darwin 25.6.0), Python 3.12.13 |
| Load | **Not idle.** Load average (1/5/15 min) was 23.5/23.9/30.2 at the start of run 1 and 17.6/22.3/29.3 at run 2, on a machine running many concurrent sessions. Both runs are therefore pessimistic, and their agreement within a couple of milliseconds should not be read as proof of stability. |
| Code | commit `b8f8806c` plus uncommitted changes (`git_dirty` is true in both result files); the measuring script is the version committed with this page |
| Packages | sqlalchemy 2.0.52, aiosqlite 0.22.1, cryptography 50.0.1, httpx 0.28.1, mcp 1.30.0 |
| Posture | strict trust mode; `ENVIRONMENT=local`; `RATE_LIMIT_PER_MINUTE=1000000` with the in-memory limiter; no policy bundles; no per-tool call cap; no approval gate; one key-bound permit; `STATE_BACKEND=memory` |

`STATE_BACKEND=memory` affects only the separate key/value state store, which
the governed call path does not touch. The idempotency records, permit
reservation, dispatch attempt, ledger, receipt, and audit rows all live in the
SQLite database, so their commits are inside the figures. A first call performs
roughly a dozen commits and several dozen SQL statements; a replay performs one
commit. (Counts are from a one-off instrumented run reported during review,
not reproduced by the script.)

## 5. Other latency figures in this repo

These do not agree with this page, and they have not been reconciled:

| Source | Figure | Method |
|---|---|---|
| `site/proof/transcript.json`, `docs/demo-trust-plane-output.md` | p50 67.3 ms, p95 83.7 ms | `POST /mcp/messages`, 100 samples, local tool `trust-plane-echo`, in-process, local SQLite, recorded 2026-09-08; machine and load not recorded |
| `docs/failure-lab.md` | about 90 ms added per call at the median | through the real upstream adapter against an in-process MCP server, so it includes connection setup and the SDK's calls |
| This page | p50 30–32 ms first call, 4.4–4.7 ms replay | stub executor, 1,000 samples, loaded M4 Pro |

The first row is the same endpoint measured with a different tool, a smaller
sample, an earlier commit, and an unrecorded machine, so the gap cannot be
attributed from the repo. Which figure the public site should show is a
decision for its owner; re-recording the transcript with this script's
provenance fields would make them comparable.

## 6. Raw results

[`run1.json`](research/gateway-overhead-2026-10-22/run1.json) and
[`run2.json`](research/gateway-overhead-2026-10-22/run2.json). Both runs:
`"dispatches": 1020` (20 warm-up plus 1,000 measured); replays dispatched
nothing.
