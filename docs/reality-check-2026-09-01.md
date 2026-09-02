# Reality check — live deployment (rev 3.1, 2026-09-01)

**Status:** dated evidence audit of the production deployment at
`api.thisisatest.tech`, built from raw `curl` responses taken 2026-09-01
between 20:25 and 20:32 PT (2026-09-02 03:25–03:32 UTC), plus the repository
and the Railway project that hosts it. Not a legal document, not a valuation
opinion. Companion to
[`data-room-corrections-2026-08-26.md`](data-room-corrections-2026-08-26.md).

**Why this exists.** Two earlier revisions of this check each shipped an
error. Rev 3 was rebuilt from raw responses; rev 3.1 resolves the three open
questions rev 3 could answer from the repository and the hosting project, and
corrects one naming error in rev 3 itself. The corrections log is kept so the
trail is honest.

---

## Corrections log

| Rev | Error | Correction |
| --- | --- | --- |
| 1 | Reported the 120 req/min limit as coming from `agent.json`. | Right number, wrong source. It is declared at `GET /` and enforced via `x-ratelimit-limit: 120` on counted responses. |
| 2 | Retracted the 120 req/min figure as fabricated after finding no rate-limit field in `agent.json`. | The retraction was wrong. Un-retracted; see rev 1. |
| 1, 2 | Wrong date. | It is Tuesday 2026-09-01 (PT). Sept 11 is ten days out. |
| 3 | Titled the product "Pipelock". | Pipelock is a **competitor** in this repository's own research — [`market-research-2026-08.md`](market-research-2026-08.md) §9.2 and [`ip/06-ids-candidates.md`](ip/06-ids-candidates.md) row 22b (luckyPipewrench/pipelock, mediator-signed receipts). The product is Agent Middleware API. Do not let that name reach a buyer document. |
| 3 | Called the identity of `partner-mcp-pilot` "an inference, not a verified fact." | Resolved below (§1). It is verified. |

---

## Resolved in rev 3.1

### 1. `partner-mcp-pilot` is this operator's own service, not a partner

**Verified, three independent ways:**

- **Hosting.** The Railway project `agent-middleware-api` (production
  environment) contains exactly four services: `api-service`, `Postgres`,
  `Redis`, and `partner-mcp-pilot`. The last one owns the domain
  `partner-mcp-pilot-production.up.railway.app` and is configured with the
  variables `APP_MODULE`, `PARTNER_MCP_BEARER_TOKEN`,
  `PARTNER_MCP_ALLOWED_HOSTS`, `RUN_MIGRATIONS_ON_START`.
- **Code.** Those are the exact settings [`app/partner_mcp.py`](../app/partner_mcp.py)
  requires: "Isolated stateless MCP server for the controlled design-partner
  pilot … Select it with `APP_MODULE=app.partner_mcp:app`." It exposes one
  tool, `partner.echo`, which echoes its input.
- **Repository disclosure.** [`DESIGN_PARTNER_GUIDE.md`](../DESIGN_PARTNER_GUIDE.md)
  already says the `partner.echo` evidence fixture "is labeled self-issued
  proof, not customer traction," and
  [`partner-first-tool-runbook.md`](partner-first-tool-runbook.md) says "Never
  describe the smoke server as evidence of partner adoption."

**Consequence.** The 31-succeeded / 1-returned-error durable dispatch history
is operator-issued traffic (`scripts/publish_live_proof.py`,
`scripts/constant_test_loop.py`) against an echo server. It is **Level 6**
evidence — the mechanism runs end to end in production against a real remote
Streamable HTTP upstream — and not Level 7. There is no external caller in
the dispatch history. The word "partner" in `partner.echo` and
`partner-mcp-pilot` is a role label from the runbook, not a company. Do not
put it in a buyer-facing sentence without that gloss.

**Nothing here contradicts the repository.** The repo labels this correctly
everywhere it is mentioned. The risk was only that a pitch written outside the
repo would read the upstream name as a customer. That risk is now closed on
paper; it stays closed only if the pitch copies the repo's language.

### 6. The 120 req/min scope — written down

From [`app/core/rate_limiter.py`](../app/core/rate_limiter.py), now also
documented under "Rate limits" in
[`DESIGN_PARTNER_GUIDE.md`](../DESIGN_PARTNER_GUIDE.md):

| Caller | Bucket | Limit |
| --- | --- | --- |
| Request with `X-API-Key` | one bucket per key value | 120 / 60 s fixed window |
| Request without a key | one shared `anonymous` bucket for the whole deployment | 120 / 60 s |
| `POST /mcp/public` (opt-in, off in production) | per client IP, plus a global cap | 120 per IP, 1,200 global |
| `/`, `/health`, `/.well-known/agent.json`, `/llms.txt`, `/docs`, `/openapi.json`, served markdown | exempt | — |

- No burst allowance. No per-key or per-partner override; a single setting
  (`RATE_LIMIT_PER_MINUTE`) governs the deployment.
- A design partner running several concurrent agents on **one** key shares
  120/min across all of them. Splitting agents across keys gives each key
  its own 120. That is the answer to a buyer engineer's first question.
- `/health/dependencies` is **not** exempt and is counted in the shared
  anonymous bucket, so any unauthenticated caller can consume the budget that
  every other unauthenticated caller of that surface uses. This is a
  low-severity availability finding on a public evidence surface, not a
  security finding. Noted, not fixed here; exempting it trades that for an
  unlimited DB-touching endpoint.
- **Fixed in this revision:** `GET /v1/discover` advertised
  `"burst_allowance": 20`, which nothing implements. It now reports the
  enforced figure, its scope, and `burst_allowance: 0`, derived from the same
  setting the middleware reads.

### 8. Natoma comp — verified as an announcement, single-source on price

- **Verified.** Snowflake announced a definitive agreement to acquire Natoma
  (enterprise MCP platform for AI agents) on 2026-05-27:
  [Snowflake press release](https://www.snowflake.com/en/news/press-releases/snowflake-announces-intent-to-acquire-natoma-providing-secure-connectivity-for-the-agentic-enterprise/),
  [The Register, 2026-05-28](https://www.theregister.com/ai-ml/2026/05/28/snowflake-buys-natoma-to-help-freeze-out-rogue-agents/5248062).
  The Register: "Financial terms of the acquisition were not announced."
- **Single-source on the figure.** The ~$110M number comes from
  [Start with Identity](https://startwithidentity.com/blog/2026-05-27-snowflake-to-acquire-natoma-mcp-agent-governance/),
  which attributes it to Snowflake's quarterly filing: "total consideration
  at roughly 110 million dollars, mostly in stock with the remainder cash."
  Not checked against the filing itself here.
- **How to cite it.** "Snowflake/Natoma, announced 2026-05-27; consideration
  reported at ~$110M per Snowflake's quarterly filing (secondary source)."
  To promote it to Verified, read the 10-Q for the quarter ended 2026-07-31
  and quote the line. Until then it stays a comp, not a valuation anchor —
  the [`data-room-corrections-2026-08-26.md`](data-room-corrections-2026-08-26.md)
  C7 discipline applies.

### 5. `provider.website` — located; needs a URL only the operator can choose

- The manifest's `provider` block is not in the repository. It is built from
  the `PUBLIC_CONTACT_NAME`, `PUBLIC_CONTACT_EMAIL`, and `PUBLIC_CONTACT_URL`
  environment variables on the Railway `api-service`
  ([`app/core/public_contact.py`](../app/core/public_contact.py)).
- The validator is fail-closed: all three must be set together, the URL must
  be absolute HTTPS on a routable public domain, and it must **not** be the
  API's own domain (it is expected to point at a booking service). A
  product-owned Calendly or Cal.com link satisfies it; a homepage on
  `thisisatest.tech` does not.
- **Action, ~5 minutes, operator-only:** set `PUBLIC_CONTACT_URL` on
  `api-service` to a product-owned booking link, redeploy, and re-read
  `/.well-known/agent.json`. Not done here: choosing the link is a business
  decision, and the change is a production configuration edit.

### 7. "MCP gateway" wording — the gap is a flag, not missing code

- `POST /mcp`, a spec-compliant stateless Streamable HTTP endpoint served by
  the official MCP SDK transport (`initialize`, version negotiation, `ping`,
  JSON-RPC framing), already exists behind `ENABLE_STANDARD_MCP_ENDPOINT`.
  It is default-off and off in production; that is why the manifest labels
  `/mcp/messages` `legacy_project_transport` and omits `mcp` from
  `endpoints`.
- When the flag is on, `agent.json`, `/v1/discover`, and
  `/v1/discover/tools` all advertise `/mcp` automatically
  ([`app/routers/well_known.py`](../app/routers/well_known.py),
  [`app/routers/discover.py`](../app/routers/discover.py)).
- **Recommendation:** enable it in production rather than soften the README
  title. The wording change costs credibility; the flag flip costs a
  verification pass against the checklist in
  [`partner-first-tool-runbook.md`](partner-first-tool-runbook.md) and the
  standard-MCP tests. Until it is on, any buyer-facing "MCP gateway" sentence
  carries the manifest's own qualifier.

---

## What is verified — raw responses, public, no auth

**Service state (`/health/dependencies`, 2026-09-02T03:32Z)**

- `status: healthy`, `environment: production`, `production_like: true`,
  version 1.3.0, commit `2880ca706d2f…`, `build_provenance: "stamped"` — the
  field the 8/27 audit flagged as missing is present.
- Postgres, Redis, upstream MCP, signing key all `up`. Rate limiter backend
  `redis`, `using_memory_fallback: false`. Durable state did not fall back to
  memory.
- `enable_proof_surfaces: false` — unchanged from the 8/27 tenant-isolation
  finding.
- Durable dispatch history: `succeeded: 31`, `returned_error: 1`,
  `reconciliation_backlog: 0`, `stale_active: 0`,
  `unfinalized_terminal: 0`.
- Process-local call counter: `calls_total: 0` since the current process
  started. The 31/1 is historical; nothing has hit the gateway since the last
  restart or deploy.
- Exactly one upstream tool: `partner.echo` at
  `https://partner-mcp-pilot-production.up.railway.app` (see §1).

**Rate limiting (`/` and live headers)**

- Declared at `GET /`: `"rate_limits":{"requests_per_minute":120}`.
  Enforced: `x-ratelimit-limit: 120`, `x-ratelimit-remaining: 119`,
  `x-ratelimit-reset: 48` observed on `/health/dependencies`. Scope: §6.

**Commercial posture (`/.well-known/agent.json`)**

- `pricing.model: "controlled_design_partner_pilot"`, `public_pricing: false`,
  `public_sla: false`, "Credits and credentials are provisioned by an
  operator."
- `authentication.public_self_serve: false` — "No public self-serve API key
  mint. An operator bootstrap/admin key (VALID_API_KEYS) provisions wallets
  and DB-scoped agent keys."
- `/v1/billing/pricing` returns 401 without a key. Pricing is not
  inspectable from outside.

**Integration surface (`agent.json`) — what a buyer's engineer sees in hour one**

- `mcp_json_rpc_status: "legacy_project_transport"` — "does not implement the
  standard MCP initialization lifecycle." No `endpoints.mcp` key (§7).
- Python SDK `release_artifact_only`, source 0.5.0 ahead of tag
  `python-sdk-v0.4.0`, not on PyPI. TypeScript SDK `not_published`.
- LangGraph / CrewAI / AutoGen / LlamaIndex: `in_repo_wrapper` each.
- `try_it`: `make prove-trust-plane`, local SQLite, self-described as "a
  reproducible proof, not a production or settlement claim." Well
  calibrated; keep that language.
- `provider.website`: `https://calendly.com/regengine/30min` — a RegEngine
  link on the manifest of a product presented as standalone (§5).

---

## Reality Ladder

Scale: 0 idea → 2 math → 4 historical → 6 paper/sandbox → 7 limited real
world → 9 scaled real world.

| Claim | Level | Basis |
| --- | --- | --- |
| Trust-plane mechanism runs in production | 6 | Live, durable state, provenance-stamped, reproducible local proof. Level 7 requires a confirmed external caller. |
| 31/1 dispatch history via `partner-mcp-pilot` | **6** (was "6 or 7 — unresolved") | Operator-owned echo service in the same Railway project (§1). 0 calls since last restart. |
| "Standard MCP gateway" | 2–3 as deployed; 6 in code | `POST /mcp` exists and is tested but is off in production (§7). |
| Rate limiting works | 7 | Enforced on live public responses; scope documented (§6). |
| Competitive / IP urgency | 1 | Fabricated citations caught 2026-08-26; patent search not redone. |
| Natoma comp (~$110M) | 4 (announcement verified; price single-source) | §8. |
| "Active buyer process" | Unknown | Live conversations vs. unopened data room — still the largest lever. |

---

## Per-unit economics

The manifest settles the near-term question: this is a controlled
design-partner pilot with operator-provisioned credits. The commercial unit
today is a **design-partner account**, hand-negotiated. Per-call metering
exists in the infrastructure (`/v1/billing/charge`, ledger, wallets) but is
not the current commercial vehicle. A pitch must not imply a self-serve
metered model that `public_self_serve: false` contradicts on the public
manifest.

No price points are recorded here and none are invented. The Sept 11
economics question is narrow: what would the next design partner pay, and
for what.

---

## Phase-transition check — verified constraints only

- **120 req/min, per key, no override.** One partner running N agents on one
  key gets 120 total. The lever is issuing more keys, which is operator work
  (next bullet). Write the per-key answer into the first call.
- **Operator-provisioned keys and credits.** Trivial at 1–3 partners. Becomes
  the "human attention per unit" bottleneck well before compute does, and it
  is also the rate-limit lever above.
- **Non-standard MCP transport in production.** Every integration today
  needs a project-specific JSON-RPC client — a per-partner cost. The standard
  endpoint exists; the phase transition is the first partner who insists on a
  standard client, and it is a flag flip plus verification, not a build (§7).
- **Proof surfaces off.** Correctly deprioritized on 8/27. Revisit trigger:
  the first partner requesting contractual tenant-isolation assurance —
  plausibly partner #2, not #50.
- **0 calls since restart, and no external caller ever.** "Live partner
  usage" cannot carry weight in a pitch on its own. It needs a named party or
  fresh volume from a key the operator did not issue to itself.

---

## Remaining backlog (2026-09-01 → Sept 11), ranked by decision value per hour

Items 1, 6, and 8 from rev 3 are closed above. Item 5 and item 7 are located
and need an operator decision each.

1. **Answer the buyer-pipeline question** — live conversations or unopened
   data room. Zero cost, biggest unknown.
2. **Get one real prospect to react to a concrete price.** A single "yes,
   roughly, if it does X" is Level 7 and outweighs another week of internal
   audit.
3. **Set `PUBLIC_CONTACT_URL` on `api-service`** to a product-owned booking
   link and redeploy (§5). ~5 minutes; removes a diligence tripwire.
4. **Decide on `ENABLE_STANDARD_MCP_ENDPOINT=true` in production** (§7).
   Recommended. Verification pass, then the "MCP gateway" wording is true as
   deployed.
5. **Re-run the competitor patent search properly.** Fabricated citations
   already cost credibility once.
6. **Promote the Natoma figure to Verified** by quoting the 10-Q, or keep the
   "reported" phrasing from §8.
7. **Purge "Pipelock" from any pitch copy** that inherited it from rev 3.
8. Continue the 8/27 audit priorities in parallel (FAQ, 403 table, script
   production-confirmation). This list does not replace them.

---

## Honest read

The infrastructure holds up better under raw inspection than the first two
revisions showed: durable state, provenance stamped, rate limiting enforced
and now documented, a `try_it` block that describes itself with unusual
honesty, and a standard MCP endpoint already written and waiting on a flag.
The one open evidence question is closed, and the answer is the conservative
one: the best usage data is self-issued, Level 6, and the repository already
said so. The gaps that remain are commercial and cheap: one pipeline state
only the operator knows, one contact URL, one flag, and one comp figure that
needs a primary source. None of them needs a swarm. Items 1 and 2 need the
operator, and nothing in this repository can supply them.
