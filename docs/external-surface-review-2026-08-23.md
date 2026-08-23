# External Surface Review — 2026-08-23

Scope: a black-box review of the two **deployed** origins — the Vercel
marketing site and the Railway API — from outside, using only what an
unauthenticated caller can see. Complements `docs/repo-review-2026-07-07.md`,
which reviewed the tree from the inside.

Reality levels follow `AGENTS.md`: verified, partially verified, not verified,
stubbed, demo-only, misleading, contradicted, too early to tell.

This is an analysis document. No application code was changed — the one code
finding it produced was **already fixed on `main` before this review ran**, and
that gap between "fixed in the tree" and "running in production" is the most
actionable thing here.

## 1. The deployed API is 103 commits behind `main` — the headline finding

`/health/dependencies` reports `commit_sha:
098a3ebeecfcfaded1eac89a49e3e9bcf09292d0`. That commit is the merge of PR #265,
dated **2026-08-12**. `main` is at `d47f061` (PR #352), dated **2026-08-23**.
Between them: **103 commits over 11 days**, including several that change
exactly the surfaces this review looked at.

Everything an outside observer can see therefore describes the tree as it stood
on 2026-08-12, not as it stands today. Two concrete consequences appear below
(§2 and §5). The general consequence is worth stating plainly: **external
review of this deployment is not review of this repository**, and any finding
gathered from outside has to be re-checked against `main` before it is treated
as a defect. This review initially failed to do that, and nearly landed a
duplicate fix as a result.

The gap itself is the finding. Nothing in the repo advertises how far the
deployment trails the tree, so the honest health payload — which does disclose
its own commit SHA, to its credit — is the only way to notice, and only if the
reader thinks to resolve that SHA.

## 2. HEAD answered 405 on every GET route — real in production, already fixed on `main`

Observed against the deployment: `curl -I` returned `405 Method Not Allowed`
with `Allow: GET`.

The cause is precise. Starlette's `Route` adds `HEAD` implicitly wherever `GET`
is present; FastAPI's `APIRoute` does not, registering exactly the methods a
route declared. So every `@app.get` endpoint rejected HEAD, `/health` included,
and an uptime monitor doing HEAD probes saw a healthy trust plane as broken.

**This was already fixed on `main`** by PR #348 (2026-08-22), one day before
this review: `app/middleware/head_method.py` rewrites HEAD to GET at the ASGI
boundary and suppresses body frames on the way out, registered at
`app/main.py:591`. The fix is pure-ASGI rather than `BaseHTTPMiddleware`
specifically so streaming responses are dropped chunk-by-chunk instead of
buffered.

**No code change is required. The required action is a deploy.** The
observation was accurate about production and stale about the codebase.

This is distinct from the deliberate 405s at `app/routers/mcp_standard.py:666`
and `app/routers/mcp_public.py:673`, which answer `Allow: POST` for the MCP
transports and are correct in both trees.

## 3. Published receipt cryptography — verified

The receipt at `site/proof/receipt.json` carries a **valid Ed25519 signature**
over its `signing_input` bytes under the `railway-prod-ed25519` key published
in `site/proof/trust-keys.json`. Verified independently during this review:
32-byte key, 64-byte signature, 775-byte signing input, and a single flipped
byte of the signing input is rejected — which is what makes the positive result
mean anything.

The signing input is a **string, not a nested object**. A verifier checks the
exact published bytes rather than a re-serialization, so canonicalization
disagreements cannot silently change what was signed. What it binds is
non-trivial: `permit_id`, `wallet_id`, `tool`, `request_hash`, `response_hash`,
`ledger_entry_id`, `dispatch_attempt_id`, `idempotency_record_id`, `outcome`,
`credits_authorized`, `credits_charged`, `audit_event_id`, `payload_hash`,
`created_at`. The signature covers the economic outcome and the idempotency
record, not merely the fact of a call. That is what separates a receipt from a
log line.

**Already covered in CI** by `tests/test_published_proof.py`, which does this
more thoroughly than an ad-hoc check: it drives the repo's own
`b2a_sdk.receipt_verifier` and the offline `verify_cli`, and adds tamper,
issuer-substitution, and wrong-key rejection cases. Verifying through the
shipped SDK is the right design — it tests the verifier customers actually run,
not a parallel reimplementation that could agree with the receipt while the SDK
disagrees.

Caveat worth stating: the bundle is a committed snapshot generated 2026-08-11,
not a live fetch. The proof page shows *a* real receipt, not a *current* one.
That is fine for a design-partner-stage artifact and is not presented
otherwise, but a reader should not infer present traffic from it.

## 4. Static-site CSP — verified, and unusually strict

`site/vercel.json` sets a CSP with no `'unsafe-inline'` anywhere, plus
`base-uri 'none'`, `object-src 'none'`, and `form-action 'none'`. The last is
aggressive and correct for an origin with no forms: it neuters injected form
targets outright. `img-src 'self' data:` is the single conservative allowance
and is unused by current source.

Stronger than most production sites ship, and committed to the repo rather than
set in a dashboard — so it is reviewable in a diff.

## 5. API auth boundary — verified, but observed against the stale deployment

Discovery, health, and documentation endpoints are unauthenticated and return
only public metadata. Everything touching money, permits, receipts, audit, or
key material requires `X-API-Key` or a bearer token. Failures return structured
JSON error codes rather than HTML or stack traces.

`add_cors_middleware` (`app/main.py:543` on `main`) handles the
credentialed-wildcard trap correctly: with `allow_origins=["*"]` it disables
credentials rather than echoing the caller's `Origin` back alongside
`Access-Control-Allow-Credentials: true`. That combination is a standard way to
hand any website credentialed cross-origin reads, and the code names it.

Per §1, the *observed* surface predates PR #348 ("fix health/HEAD/CORS
truthfulness") and PR #352 ("strip proof-surface archaeology from agent
discovery"), both of which deliberately changed what discovery and health
expose. The endpoint inventory above should be re-derived after the next deploy
rather than carried forward from this pass.

## 6. Operational transparency — verified, and the strongest signal here

`/health/dependencies` volunteers what most services hide: which subsystems are
in simulation mode, that Stripe and the LLM provider are unconfigured, that
lifetime dispatch counts are 4 successes and 1 error, and — via `metric_scopes`
— which counters are process-local and reset on restart versus durable. Both
`enable_proof_surfaces` and `metric_scopes` survive on `main`
(`app/core/health.py`), so this is a durable property, not a stale observation.

Distinguishing in-memory from durable metrics *in the health payload itself* is
rare, and it means a reader cannot mistake a restarted process's zeroed counter
for an absence of traffic. Combined with `WEDGE.md` and
`SECURITY_LIMITATIONS.md` being served as first-class endpoints, the posture is
consistent: the system declines to overstate itself.

The irony of §1 is worth naming — this is the surface that disclosed its own
staleness. The commit SHA in the health payload is what made the 103-commit gap
discoverable at all.

## 7. Minor observations — no action taken

- **Commit SHA in the health response.** A transparency choice, not a leak; the
  repository is public. §1 is the argument for keeping it.
- **`x-hikari-trace` edge identifiers** (`lax1.ez9k` and similar) come from
  Railway's edge, not this application. Not actionable here.
- **No `.git/` exposure, source maps, secrets, stack traces, or third-party
  trackers** were found on either origin. Vercel Analytics is the only external
  connection, and the CSP's `connect-src` restricts it to that one host.

## What this review did not establish

- **Live API behaviour under authentication.** Everything above is either
  unauthenticated observation or code reading. No permit was minted and no
  invocation dispatched, so the runtime trust loop is **not verified** by this
  pass. `docs/repo-review-2026-07-07.md` §1 remains the reference, along with
  its open finding that charge → receipt → audit → idempotency-complete is not
  atomic.
- **Key custody.** The signature verifies against the published key. Nothing
  here speaks to how the private key is stored or who can reach it; see
  `docs/key-management.md`.
- **Anything about `main`'s deployed behaviour.** Per §1, the running code is
  11 days old. This review describes what is deployed, and says so wherever the
  two diverge.
- **Absence of vulnerabilities.** "No security issues found" from the outside
  means the external surface did not reveal any. It is not a pentest and should
  not be cited as one.
