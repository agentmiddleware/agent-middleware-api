# Data room corrections (v1.3.0 draft, 2026-08-26)

**Status:** engineering review of the acquisition data room draft compiled by
Cloudy / OpenClaw-b6l / Kimi Claw Desktop. Not a legal document, not a valuation
opinion.

**Why this exists.** The data room is buyer-facing and was assembled outside this
repository, so it did not inherit the claim discipline in
[`../WEDGE.md`](../WEDGE.md) §"What Not To Claim Yet",
[`../AGENTS.md`](../AGENTS.md), or the 2026-08-15 repositioning. Each item below
was checked against the repository or a primary source on 2026-08-25. Items are
ordered by how quickly a buyer's diligence finds them.

One of them (**C5**) is a correction in the room's favour: it discloses a gap
that is not real, and understates the strongest asset in the package.

---

## C1 — The room contradicts itself on whether the product is deployed

| Document | Claim |
| --- | --- |
| Master Index | "v1.3.0 **live in production**", `api.thisisatest.tech`, with a 73-route probe and live health metrics dated 2026-08-25 |
| Code Status, **same day** | "Deployed (Railway): UNKNOWN — **DOWN — 404**"; "the production Railway deployment is not responding" |

Two documents in one room, compiled the same day, disagree on the single
load-bearing fact of a "production-deployed" positioning. Related unresolved
version state, from the same section: the main repo is **1.2.0**, the v1.3.0
tree is a **review clone on branch `fix/button-a11y`**, and "no git tag exists
for v1.3.0."

**Action.** Establish the deployment state, tag v1.3.0, and re-probe before the
room is assembled. If the live probe is stale, the 73-route inventory and the
`/health/dependencies` flag table must be re-dated or withdrawn — both are
presented as current production facts.

## C2 — The opening superlative is banned by our own rules and is falsifiable

The room's one-paragraph position opens: *"The only open-source MCP trust plane
combining signed receipts, permit scoping, idempotency-guard exactly-once
charging, and MCP-native governance."*

Two independent problems.

**It is a superlative a reader can falsify in one search.**
[`../WEDGE.md`](../WEDGE.md) §"What Not To Claim Yet" bars exactly this — "a
superlative that a reader can falsify in one search costs more credibility than
the claim buys." As of 2026-08-25, offline-verifiable signed receipts ship in
`microsoft/agent-governance-toolkit` (Ed25519 over RFC 8785 JCS, hash-chained),
Pipelock, and protect-mcp/ScopeBlind; budgets ship in jamjet and latch; permit
scoping is the subject of Daon US 12,688,261. See
[`market-research-2026-08.md`](market-research-2026-08.md) §9.

**It is a combination claim, in a room that also argues patentability.**
[`ip/02-prior-art-landscape.md`](ip/02-prior-art-landscape.md) §"The
combination-claim trap" warns that a combination of individually known elements
is the standard setup for a §103 obviousness rejection under *KSR*. Leading the
room with "the only … combining" invites precisely that reading from a buyer's
patent counsel.

**Replacement**, which is stronger because it survives the search — and which is
verified in this repository:

> One accepted idempotency key produces at most one gateway dispatch and at most
> one ledger debit — and, for the configured upstream MCP tool, the receipt's
> Ed25519 signature covers the ledger entry, the idempotency record, and the
> dispatch attempt together, so the issuer's statement about authority, money,
> and outcome is one tamper-evident unit rather than three separable assertions.
> No project we surveyed documents that binding.

Code evidence: `ledger_entry_id`, `idempotency_record_id` and
`dispatch_attempt_id` are all inside one signed canonical payload
(`app/services/receipts.py:85,:95,:97`), enforced at write time by
`attach_charge` (`app/services/mcp_dispatch_attempts.py:653`) and by `unique=True`
foreign keys (`app/db/models.py:781-790`). Note `dispatch_attempt_id` is present
only on upstream receipts — the local path mints without one
(`app/routers/mcp.py:1754-1774`) — so cite the three-way binding as an
upstream-path property. Overstating it as universal is the same error as C8.

**Two precision limits this sentence must respect** — both raised in review of
this document and confirmed against the code and tests. A buyer's engineer will
find either one, and the room's credibility rests on precision.

1. **Do not say the linkage is "verifiable offline."** The portable bundle
   (`app/routers/receipts.py:269`) exports `signing_input`, signature and a key
   reference — the three identifiers as *strings*, not the ledger or dispatch
   records. Offline, a holder proves the issuer signed those identifiers
   together untampered; they cannot confirm the named ledger entry actually
   carries the matching `operation_key`, because that row does not travel with
   the bundle. Consistency is enforced at write time and auditable through the
   authenticated evidence bundle. Say **"signed and tamper-evident offline;
   consistency enforced at write time and auditable online."**
2. **"Exactly one" overstates it; "at most one" is the true guarantee.** A crash
   before dispatch reconciles to a refund — zero dispatches, zero net debit. A
   **local** governed tool crashing after its side effect leaves one execution
   and one debit with **no receipt at all**, permanently `needs_manual_review`
   (`test_post_side_effect_crash_requires_review_without_redispatch` asserts
   `receipt_ids == ()`). The guarantee is never a duplicate charge, not always a
   charge — and exactly one receipt on paths that finalize or reconcile, which is
   every upstream path but not that local one.

**Applied repo-wide.** The same "exactly one … and one receipt" phrasing
predated this review in [`../WEDGE.md`](../WEDGE.md) §"Signed receipts are table
stakes now", [`market-research-2026-08.md`](market-research-2026-08.md) §4, and
[`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md) §9. All three now read "at
most one," and `WEDGE.md` carries a gloss defining what "exactly-once" means as
a term of art — the deduplication guarantee, not a promise that every accepted
call is charged.

One instance was deliberately left alone: [`PROOF_MATRIX.md`](PROOF_MATRIX.md)
says "exactly one ledger debit" while enumerating what a single successful proof
run asserts. That is a true statement about an observed happy-path run, not a
universal contract, and narrowing it would misdescribe the proof.

**Why this is the stronger claim for a buyer, not a retreat.** "Never a
duplicate charge" is the property a buyer is actually purchasing, and it is the
one that survives their engineer reading the test suite. "Exactly one" does not:
`test_post_side_effect_crash_requires_review_without_redispatch` falsifies it in
the repository's own CI. A claim a diligence engineer can break in an afternoon
costs more than the breadth it buys — the same reasoning
[`../WEDGE.md`](../WEDGE.md) already applies to uniqueness superlatives.

Keep the survey-scoped form — "no project we surveyed documents this," never
"nobody does." An independent survey (arXiv:2606.04193) found none of the receipt
protocols it names binding receipts to settlement. That is receipt-layer
context, not a test of the debit/idempotency binding — useful, but do not cite
it as proof of the §4 rows.

## C3 — "Independent validation" is the stranger test, and the room's own rules say so

The room's centerpiece is *"independently validated end-to-end by an unaffiliated
third-party agent."* [`../AGENTS.md`](../AGENTS.md) is explicit: *"Do not count
local demos, self-issued public proof, or the stranger test as customer
validation."* An AI agent pointed at our own live API is the stranger test.

The underlying work is real and worth including — an Ed25519 signature verified
against the live published key over the exact 775-byte `signing_input` under
`awi-canonical-json/1` is a checkable engineering fact. The problem is only the
framing: "independently validated" as the room's lead invites the one question
that collapses it — *who is the third party, and what is their stake?*

**Action.** Relabel as **"third-party-agent reproduction of the published
proof"**, move it from the centerpiece to the technical evidence section, and let
the honest gap register's "0 paying customers, no design partner under signed
contract" carry the validation status. The gap register is already correct; the
headline contradicts it.

Note also Pipelock's signer taxonomy (in-process / operator-deployed mediator /
third-party witness): by that classification our receipts are **operator-signed**,
the same tier Pipelock ships and one below third-party witness signing.
`site/llms.txt` already labels the published proof "self-issued." The room should
not imply a higher tier than the repo does.

## C4 — Three cited patents are fabricated. This is the most serious item here.

`Technical Evidence Index` §5.3 lists three close-watch threats, two rated
**HIGH**. All three were resolved against Google Patents on 2026-08-25. **Every
one is a real patent number attached to an invented title and assignee.**

| Cited as | What that number actually is |
| --- | --- |
| **US 2024/0089012 A1** — Anthropic, "Cryptographic proof of API consumption" (HIGH) | **Turck Holding GmbH** — *"Signal transmission system … between a field device and a superordinate unit."* Industrial automation, HART protocol. Published 2024-03-14. |
| **US 2024/0034567 A1** — Skyfire, "Receipt-based API billing for AI agents" (HIGH) | **Duecker Group GmbH** — *"Angled transfer with roller chain."* A roller conveyor. Published 2024-02-01. |
| **US 12,300,000 B2** — PayPal, cryptographic receipts | **Here Global BV** — *"Computer-vision-based object motion detection."* Issued 2025-05-13. |

Only Daon **US 12,688,261** is corroborated by
[`ip/06-ids-candidates.md`](ip/06-ids-candidates.md). The room dates it "Filed
~2023" where that file records **issued 2026-07-21** — reconcile.

**Why this is worse than a citation error.** A mis-keyed digit produces one
wrong reference. It does not produce three, each landing in an unrelated field
(industrial sensors, conveyors, computer vision), each paired with a title and
assignee that happen to support the argument in the section where it appears.
That pattern — correct format, invented content, argument-shaped — is what
hallucinated citations look like. These were not transcribed from a search; they
appear to have been generated.

**What it costs, in order.**

1. **In a buyer's room this is the worst place to be caught.** A patent analyst
   pulls cited art as a matter of routine. Three fabrications in the IP section
   does not read as sloppiness — it raises the question of what else in the room
   was generated rather than verified, and it puts the *genuine* engineering
   evidence under suspicion it does not deserve.
2. **The filing urgency argument is unsupported.** Two HIGH ratings drove the
   "file provisionals immediately" sequencing. Nothing supports them. The
   recommendation may still be right — the Daon art and the grace-period
   deadline are real — but it must be re-argued from evidence that exists.
3. **The competitor patent search has not actually been done.** These
   placeholders occupy the space where a real search would sit. Treat that work
   as outstanding, not complete.
4. **Audit the rest of the draft.** Same-document claims that no one has
   sourced — the acquisition comparables and the ~$110M figure in C7 especially
   — now need checking before a buyer sees them.

**Skyfire is a real company and a real gap.** [Skyfire Systems,
Inc.](https://www.crunchbase.com/organization/skyfire-systems) runs a payment
network for AI agents with programmable wallets, verified agent identity (KYA),
and the KYAPay protocol — genuinely adjacent to the economic claims this product
leads with, and closer to them than anything in
[`market-research-2026-08.md`](market-research-2026-08.md) §3, which does not
track it at all. The fabricated citation created a false impression that Skyfire
had been assessed. It has not been. No published filings were located, which is
expected for a company that launched in August 2024 — applications from around
launch would only begin publishing near February 2026.

**Action.** Strike all three citations. Have counsel run assignee-based searches
on Skyfire Systems, Nevermined, and Payman, and add Skyfire to the competitive
set on its merits. Re-derive the filing recommendation from the Daon art and the
grace-period deadline alone.

## C5 — Gap #4 is not real, and it understates the strongest asset in the package

The room lists, with a two-week ETA:

> "PostgreSQL multiprocess kill test **stubbed** — `_test_call_once` not runnable
> in CI … Invariant 1 not fully proven under true multi-process concurrency",
> and "Adversarial crash-window tests **do NOT run** in GitHub Actions."

**Both statements are false.** Verified 2026-08-25:

- `.github/workflows/ci.yml` contains a step named **"Prove governed MCP across
  two OS processes"** running `tests/test_mcp_postgres_multiprocess.py` with
  `RUN_MCP_MULTIPROCESS_TESTS=1` and `MCP_STRESS_DB_ISOLATED=1` against a
  PostgreSQL service, plus a second step running
  `tests/test_permit_postgres_concurrency.py` with
  `RUN_POSTGRES_CONCURRENCY_TESTS=1`.
- The harness spawns real `uvicorn` subprocesses (`subprocess.Popen`) and kills
  them with `process.kill()` (SIGKILL) at instrumented fault points — a genuine
  two-process crash, not a simulated one.
- There is **no** `assert False` and no `"TODO: implement real debit/call once
  harness"` anywhere under `tests/`.

Tests that already exist and run in CI:

| Test | Boundary proven |
| --- | --- |
| `test_kill_after_dispatch_checkpoint_is_charged_delivery_uncertain:1023` | Kill after the dispatch checkpoint → charged, `delivery_uncertain` |
| `test_kill_after_remote_effect_never_redispatches_the_effect:1086` | Remote effect landed, ack lost → asserts `effect_count == 1`, `debit_count == 1`, `refund_count == 0` |
| `test_kill_between_debit_and_dispatch_refunds_without_dispatching:1143` | Kill before dispatch → refunded, nothing dispatched |
| `test_post_side_effect_crash_requires_review_without_redispatch:947` | Post-effect crash → review, no redispatch |
| `test_receipt_commit_survives_worker_death_and_reconciles:897` | Receipt commit survives worker death |

The room appears to describe only `tests/test_adversarial_five_claims.py` and to
have missed `tests/test_mcp_postgres_multiprocess.py` entirely.

This matters more than a normal register error. **Invariant 4 — ambiguity forbids
redispatch — is the room's most patent-relevant claim, and the room tells a buyer
its proof is stubbed and two weeks away.** It is implemented, it is adversarial,
and it runs on every CI run.

**Measured on this tree, 2026-08-25:**

```
pytest tests/test_delivery_uncertain_replay.py tests/test_governed_persistence.py
  -> 30 passed
pytest tests/test_adversarial_five_claims.py
  -> 17 passed
pytest tests/test_mcp_postgres_multiprocess.py --collect-only
  -> 13 tests collected   (execution requires PostgreSQL; runs in CI)
```

The multiprocess suite **collects cleanly as 13 real parametrized tests** — a
stubbed or `assert False` harness would not. It needs a PostgreSQL service to
execute, which is exactly what the CI job provides.

Note the adversarial suite reports **17 passing tests**, where the room's Code
Status section records "9/9 PASSED". That is a second signal that the room was
compiled against the older 1.2.0 main tree rather than the v1.3.0 review clone
(see C1) — and it understates the evidence again.

**Executed, not merely collected.** The `--collect-only` result above proves the
suite is real, not that it passes. It has since been observed passing: the
`postgres_permit_concurrency` job — the one carrying the "Prove governed MCP
across two OS processes" step — completed **success** against a PostgreSQL
service on this repository's own PR #370 runs
([32910126565](https://github.com/PetrefiedThunder/agent-middleware-api/actions/runs/32910126565)
and [32910910159](https://github.com/PetrefiedThunder/agent-middleware-api/actions/runs/32910910159),
2026-08-25). Cite a job URL, never the collection count, when this is put in
front of a buyer.

**Row-to-test mapping.** Do not mark a failure-state row PROVED IN CI without
naming the test that covers it. All of the below run in the
`postgres_permit_concurrency` job cited above:

| Matrix row | Boundary | Test |
| --- | --- | --- |
| 5 | After dispatch, before acknowledgement | `test_kill_after_dispatch_checkpoint_is_charged_delivery_uncertain`; `test_kill_after_remote_effect_never_redispatches_the_effect` |
| 7 | After durable dispatch commit | `test_kill_after_remote_effect_never_redispatches_the_effect` |
| 8 | After charge commit, before receipt signing | `test_receipt_commit_survives_worker_death_and_reconciles` |
| 10 | Client retries after a terminal outcome | `test_kill_after_remote_effect_never_redispatches_the_effect` — its `_assert_replayed_terminal` step replays the same receipt and asserts the upstream snapshot is unchanged. (**Not** `test_delivery_uncertain_replay_never_redispatches`: that lives in `tests/test_delivery_uncertain_replay.py`, which the `postgres_permit_concurrency` job does not run.) |
| — | Pre-dispatch crash (row 3/4 boundary) | `test_kill_between_debit_and_dispatch_refunds_without_dispatching` |
| — | Local post-effect crash | `test_post_side_effect_crash_requires_review_without_redispatch` |

Rows 1, 2, 6 and 9 have **no** dedicated multiprocess test. Leave their empirical
status as-is; a passing job URL is evidence for the rows named above and for no
others.

**Action.** Strike gap #4, move these tests into the evidence index, and mark
rows 5, 7, 8 and 10 plus Invariant 4 **PROVED IN CI** — citing both the job run
and the row's test from the table above — rather than "Docker manual run,
not in CI." The failure-state matrix's "Empirical Status" column needs the same
correction for rows 5, 7, 8 and 10. Re-run the adversarial count against the
tree the room actually describes.

## C6 — Do not claim a patent position on x402 settlement

`§5.1` claim area 4 is *"FastAPI-native agent middleware with integrated x402
settlement and non-custodial receipt verification."*

Settlement is **frozen**: [`../WEDGE.md`](../WEDGE.md) §"What To Freeze" lists
settlement among the frozen areas, §"What Not To Claim Yet" bars claiming
production payments or settlement, and [`settlement-rails.md`](settlement-rails.md)
is an explicitly frozen analysis. Claiming an IP position on a capability the
product deliberately does not ship is the overclaim category the room's own claim
discipline is meant to prevent — and it is trivially checked against the repo.

**Action.** Drop claim area 4.

More broadly, all four entries in §5.1 are pitched as "novel at intersection" or
"novel stack" — combination claims, per C2.
[`ip/02-prior-art-landscape.md`](ip/02-prior-art-landscape.md) §7 ranks the
**settlement-side** mechanisms first precisely because they stand alone:
**crash-recovery classification of a charged-but-unfinalized operation**
(mechanism 2 in that document's numbering, ranked first) and **atomic guarded
reservation under weak isolation** (mechanism 1, ranked second). Lead §5.1 with
those two, and cite them by name — `02`'s rank order and its mechanism numbers
run opposite to each other, so a bare "(1)" or "(2)" is ambiguous between them.

## C7 — Market comps are unverified and carry the valuation

*"Four cybersecurity-incumbent acquisitions in five months (closest comp:
Snowflake/Natoma, ~$110M)"*, the buyer map, and the
$10-15M / $15-20M / $25M framing rest on comps that are not sourced in the room
and were not verified here.

**Action.** Apply the verification discipline already used in
[`market-research-2026-08.md`](market-research-2026-08.md) — Verified /
Single-source / Unverified, with the source named next to each figure — before
any number goes in front of a buyer. That document's §1 already models this for
market sizing: *"Do not put a dollar figure on a slide without naming the source
next to it."*

## C8 — Scope the crash-semantics claim to the upstream path

The room states the dispatch state machine and `delivery_uncertain` as
product-wide properties. They are not.

- **Upstream MCP path — full machine.** `app/services/mcp_dispatch_attempts.py`
  implements durable `prepared → dispatched → {succeeded, returned_error,
  delivery_uncertain, response_rejected}`, with redispatch after a terminal state
  structurally refused (`:678`).
- **Local governed tools — no machine.** `app/routers/mcp.py:1700-1800` creates no
  attempt row and no dispatch checkpoint, and mints its receipt without
  `dispatch_attempt_id`. A crash after the debit lands in permanent
  `needs_manual_review` (`app/services/idempotency.py:762-765`). It fails closed —
  no double charge — but there is no local `delivery_uncertain`.

**Action.** Qualify every crash-semantics claim with *for the configured upstream
tool*. `README.md:96` already does this correctly and is the model to copy. This
is also the honest answer to the room's own downstream-idempotency question: the
guarantee is at-most-one **gateway** dispatch plus refusal to redispatch an
ambiguous invocation — not effect-once in an arbitrary upstream tool, which
`WEDGE.md` explicitly refuses to claim.

---

## Summary

| # | Item | Direction | Blocking? |
| --- | --- | --- | --- |
| C1 | Deployed vs. 404 contradiction | Must resolve | **Yes** |
| C2 | "The only … combining" superlative | Remove | **Yes** |
| C3 | "Independent validation" framing | Relabel | **Yes** |
| C4 | Three unverifiable patent citations | Source or drop | **Yes** |
| C5 | Gap #4 is false | **Correct in our favour** | No, but costly |
| C6 | x402 settlement patent claim | Drop | **Yes** |
| C7 | Unverified comps | Verify | Before pricing |
| C8 | Crash semantics scope | Qualify | **Yes** |

The underlying asset is stronger than the room's framing of it. The economic
binding is real, verified in code, and unmatched in the surveyed field; the crash
semantics are proven by adversarial multi-process kill tests in CI. Both survive
diligence. The superlatives, the unverifiable citations, and the internal
contradictions do not — and they are what a buyer will find first.

*Compiled 2026-08-25 against commit state at review time. Every code reference
above was checked directly. **Competitive** references are recorded with their
verification level in [`market-research-2026-08.md`](market-research-2026-08.md)
§9; the C4 patent citations were resolved against Google Patents and are recorded
in [`ip/06-ids-candidates.md`](ip/06-ids-candidates.md) §C.1b; the USPTO and
37 CFR authorities cited above are primary sources, not survey rows. No single
section records all of them.*
