# Product Strategy: Assessment of Five Recommendations

This document works through five strategy recommendations, checks each against
what the repository actually contains, and records what was done about it.

Four of the five needed correction before they could be acted on. That is not
a criticism of the input — it is what happens when strategy advice meets a
codebase whose defining discipline is refusing to overclaim. The corrections
are the most useful part of this document, so they are stated directly rather
than softened.

| # | Recommendation | Verdict |
|---|---|---|
| 1 | Double down on provability | **Adopt, with one correction** — shipped |
| 2 | Own the discovery layer | **Reframe** — the premise contradicts three in-repo disclaimers |
| 3 | Partner on settlement | **Defer** — it is on the freeze list; design-only work done |
| 4 | Address solo-maintainer risk | **Adopt, with corrected funding targets** — shipped |
| 5 | Monitor the MCP roadmap | **Adopt** — the most durable of the five |

### A note on where these came from

These recommendations appear to derive from
[`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md), which was itself generated
by automated analysis. Verifying it against the code turned up **six materially
wrong claims** — including a capability listed in its comparison matrix that
does not exist (a signing-key rotation API), two "missing" features that shipped
long ago, a wrong concurrency mechanism, and a file-size estimate off by roughly
a factor of nine. Those corrections are now recorded at the top of that
document.

This matters beyond bookkeeping: an analysis that overstates what exists and
understates what is missing will generate strategy that aims at the wrong
things, which is a fair description of what happened with recommendations 1
through 3. **Verify the analysis before acting on the strategy derived from
it.** That rule was applied to this document too: an adversarial fact-check of
its own first draft caught six errors, including the `master`-branch claim
corrected in §4 and a false statement about PostgreSQL coverage now recorded as
a defect in [`PROOF_MATRIX.md`](PROOF_MATRIX.md).

---

## 1. Double down on provability

> *Original:* The `make prove-trust-plane` pattern is a genuine differentiator.
> Expand it to cover crash recovery, replay, and Byzantine fault tolerance.

**The core judgment is right.** Executable proof is the differentiator, and it
is under-exposed relative to how good it is. Two of the three named expansions
needed adjustment.

**Replay is already proven** — this was not a gap. `make prove-trust-plane`
asserts that a replayed idempotency key returns the identical receipt with no
second debit, *and* that a replayed denial returns the same denial receipt. It
is proven again by the dogfood proof against a real on-disk side effect, again
across two OS processes by the crash harness, and again under 15 identical
concurrent requests by the live conformance suite, where contenders expose one
receipt identity or fail closed as in progress and a completed replay returns
the winner. Writing "expand the proof to cover replay" into a strategy document
would have been a factual error that any reader of the repository would catch
immediately. The real gap was that this was nowhere summarized.

**Crash recovery was the genuine gap, and it was a packaging gap.** A
two-process PostgreSQL crash harness already existed and ran green in CI, but
had no operator-runnable entry point — a design partner could not run it. That
is now `make prove-crash-recovery`.

One qualification matters and is now documented: one of the three crash
scenarios deliberately does *not* recover. An ambiguous post-side-effect crash
routes to fail-closed manual review with no automatic redispatch, because the
gateway cannot know whether the remote effect landed. The honest name for what
the harness proves is **crash consistency with reconciliation**, not "crash
recovery."

**Byzantine fault tolerance does not apply and should never be claimed.** The
architecture is one API server, one database, and one operator-held signing
key. BFT addresses arbitrary faults among mutually distrusting replicas; there
are no replicas and no consensus here. Worse, claiming it would contradict the
repository's own documentation, which states that audit chains are
tamper-*evident* and that a database administrator who can alter both the data
and its chain metadata is inside the trust boundary.

The substantive idea underneath the BFT suggestion is real, though, and it
survives in better form. The repository has since shipped a portable receipt
bundle, public signing-key metadata, and an offline verifier, converting receipt
checking from a server-side verdict into independently performable signature
verification. Evidence-bundle linkage and audit-chain verification remain
operator-served, and key distribution still trusts the issuing origin unless a
partner pins keys out of band. The honest ladder is single-operator
tamper-evidence today → partner-run portable verification now → external
anchoring only if customer evidence justifies it later.

**Shipped:** portable receipt verification; `make prove-crash-recovery`;
`make trust-conformance-live` and
`make adversarial-battery-live` wrapping two live suites that were previously
runbook-only; and [`PROOF_MATRIX.md`](PROOF_MATRIX.md) mapping every proof
command to the invariant it asserts and — equally important — to what it does
not prove.

---

## 2. Own the discovery layer

> *Original:* `agent.json`, `llm.txt`, and `mcp/tools.json` are standards in the
> making. Propose them to the Agentic AI Foundation before A2A Agent Cards
> absorb the use case.

**This cannot be adopted as written**, because the repository already documents
the opposite about all three files:

- `/.well-known/agent.json` — the code itself states, in three places, that it
  is **not** an A2A Agent Card but this project's own bootstrap convention.
- `llms.txt` — **someone else's proposal** (llmstxt.org). This project adopts
  the path and does not follow the proposal's format. It cannot propose
  stewardship of a format it does not implement.
- `/mcp/tools.json` — documented in code comments as a **convenience mirror** of
  the MCP-native `tools/list` method, on an endpoint that does not implement the
  full MCP initialization lifecycle.

Proposing three file names — two not owned, one self-documented as
non-conformant — would fail this project's own honesty posture on first
contact with a competent reviewer.

The A2A urgency is also overstated: **the ecosystems have already diverged on
the filename.** A2A's current well-known path is `/.well-known/agent-card.json`.
The absorption risk for the name `agent.json` is largely moot.

**But there is a real, defensible asset here — it just isn't the filenames.**
Nothing in the discovery ecosystem specifies that a manifest must be
*continuously true*. Agent Cards, llms.txt, and MCP `tools/list` all describe
shape; none require a server to prove its advertisement matches its runtime
behavior. This project does, and enforces it in CI:

- Every URL in the published bootstrap sequence must return a public 200.
- A tool advertised as really integrated **cannot** be running in simulation —
  the manifest's `simulation` flag is asserted equal to the live runtime value
  that the health endpoint reports.
- Advertised capabilities must equal the actual product capability list, and
  every non-product surface must be labeled as a proof surface.
- Mirrored and aliased payloads must match.

That is the standardizable contribution: a **discovery honesty profile** that
could apply to an Agent Card, an MCP descriptor, or this manifest. It is
complementary rather than competitive, which is also the only winnable position.

**Recommendation: do not approach a standards body yet.** Standards bodies
reward demonstrated adoption. This project has one deployment, no external
adopters, and no prior relationship with any standards body — the term "Agentic
AI Foundation" appears nowhere in the repository outside the quoted
recommendation itself, so any submission would be first contact. A proposal from a single-deployment project reads as premature
and burns that one first impression. Publish the profile and a schema in-repo,
let a design partner's independent deployment supply the adoption evidence, and
approach a body once someone else enforces the same invariants.

**Shipped:** [`discovery-standards-proposal.md`](discovery-standards-proposal.md),
plus two outward-facing overclaims fixed as a prerequisite — the MCP registry
submission advertised an `/mcp/sse` transport and `sse: true` that **no route
implements**, and the repo-root `.mcp.json` still carried pre-wedge "B2A control
plane + AWI" branding. Both would have been handed to the first external
reviewer.

---

## 3. Partner, don't build, settlement

> *Original:* Integrate with x402 for USDC settlement and Payman for fiat rails.
> The trust plane should be rail-agnostic.

**Settlement is on the freeze list.** `WEDGE.md` freezes it explicitly and
forbids claiming production-ready payments; `SECURITY_LIMITATIONS.md` defers it
by design until a design partner requires one. This recommendation is, on its
face, a request to unfreeze a frozen item. **No design partner has asked.**

Two corrections matter more than the verdict.

**First, "partner, don't build" misplaces where the safety lives.** A rail's
signature proves an event is *authentic*. It does not prove the event describes
an *acceptable settlement*. That second gate is enforced entirely by this
repository: the credit amount is re-derived from the rail's own settled fields,
client-supplied metadata must match that derivation exactly or the event is
rejected, and duplicate application is prevented by database UNIQUE constraints
on the rail's identifiers. Adopting a rail does not outsource any of that — it
means re-implementing and re-testing all of it against different semantics. The
existing single rail carries roughly 900 lines of dedicated negative-path tests.
The accurate framing is **partner for the rail, build the verification**, and
the verification is the expensive part.

**Second, the trust plane is not rail-agnostic today.** There is no rail
protocol, no adapter registry, no settlement-events table, and no rail
discriminator. The seam is one concrete Stripe class plus three Stripe-specific
ledger columns, two of which carry UNIQUE constraints. The invariants are
rail-independent; **the implementation is single-rail.** Claiming otherwise
would be the most likely factual error in any settlement document.

Nothing in the repository supports any claim about x402 or Payman — outside
these two strategy documents, those strings, along with USDC and stablecoin,
appear **zero times**. Existing
`blockchain` references are an optional, unimplemented proposal to anchor the
*audit chain's* Merkle root, and have nothing to do with moving money. Reading
them as crypto direction would be a misreading.

**Shipped:** [`settlement-rails.md`](settlement-rails.md) — design-only, inside
the freeze. Its deliverable is a **fifteen-item rail conformance checklist**
that any rail must satisfy, derived from what the Stripe path actually enforces.
The checklist is deliberately the artifact rather than a rail comparison,
because a snapshot of two products' capabilities goes stale while the invariants
do not. It names three gaps the current design does not model at all: settlement
finality and reversibility classes, per-rail denomination, and pull/verify
versus push interaction models.

---

## 4. Address the solo maintainer risk

> *Original:* Document contributor pathways; consider applying to a16z crypto,
> Coinbase Ventures, or the AI Safety Fund for grant funding.

**The risk is real and correctly identified.** `CODEOWNERS` assigns the entire
repository to one person, the history is effectively one human author, PRs are
opened and merged by the same account, and there were no `GOVERNANCE.md`,
`CODE_OF_CONDUCT.md`, or funding declaration of any kind. The bus factor is
one, and for anyone evaluating this for production use that outranks every
feature gap on the roadmap.

Contributor onboarding was actively broken, not merely thin. `CONTRIBUTING.md`
told contributors the default branch was `master`; the default branch is
`main`. A stale, branch-protected `master` does still exist on the remote,
which is precisely what made the reference dangerous rather than merely wrong —
the same stale reference sat in `SECURITY.md`, the roadmap, and the auto-PR
workflow's `base:` field, which would have opened pull requests against that
abandoned branch instead of failing outright. This exact class of staleness has
already caused a production incident: a Railway trigger rebuilt the stale
`master` and crash-looped during an API key rotation.

**The funding advice needs correcting before anyone acts on it.** a16z crypto
and Coinbase Ventures are **venture investors, not grant makers** — they buy
equity and underwrite growth expectations, and both invest along a crypto thesis
this project explicitly does not have. Pitching them would require either
misrepresenting the project or changing it to fit the pitch. The AI Safety Fund
supports safety *research*; this repository's safety-adjacent artifacts are an
operational threat model and an adversarial smoke test, which is engineering
hardening, and reviewers will know the difference.

Better-matched, equity-free sources that fund maintenance directly: the
Sovereign Tech Agency, NLnet/NGI Zero, Alpha-Omega, and GitHub Sponsors or Open
Collective. The honest sequencing is **design-partner revenue first, grants
second, venture capital probably never** for this repository as scoped. One
paying design partner would do more for sustainability — and for proving the
product — than any grant application written before that partner exists.

**Shipped:** [`../GOVERNANCE.md`](../GOVERNANCE.md) stating the bus factor
plainly, with a maintainer path and an explicit fork-friendly continuity plan;
[`../CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md), which several grant programs
require; a "where to start" section in `CONTRIBUTING.md` with concrete entry
points, since there are zero open issues and no `good first issue` labels; the
`master` → `main` corrections across four files; and a PR template reconciled
with the contributor checklist it had drifted from.

---

## 5. Monitor the MCP roadmap

> *Original:* If Anthropic or OpenAI announce native metering, pivot to
> "enhanced verifiability" (receipts, audit chains) rather than competing on
> basic budgeting.

**Adopt this one as written.** It is the most durable of the five, and the
strategic instinct is exactly right: it separates the commoditizable layer from
the defensible one before the market forces the question.

### The split, made concrete

Precision matters here, because the recommendation's word "budgeting" bundles
two things that face very different displacement risk.

**Genuinely commoditizable** — *per-call cost declaration* and the
transport-level plumbing that carries metering context. Today the per-call
price is published as repo-defined `creditsPerCall` / `creditsPerCallExact`
annotations inside MCP's open-ended `annotations` field, mirrored by the public
tools manifest, and the invocation context (`wallet_id`, `permit_id`,
`idempotency_key`) rides in the tool-call envelope's `mcpContext`. If the spec
declares native equivalents, all of that becomes redundant. **Concede this
plainly when it happens**: it would also falsify the "Standard MCP: no metering,
no budget control" row that currently anchors the competitive matrix.

**Not commoditizable, and often mistaken for budgeting** — delegated authority.
Wallet balances, permit budget *reservation* under a row lock, and
organizational spend policy are not per-call cost reporting. A protocol can
declare what a call costs; it does not thereby decide who was authorized to
spend, against whose budget, up to what ceiling, until when. Treating those as
commoditized would overstate the threat and make any pivot look reactive.

**The durable moat** — the evidence layer. Ed25519-signed receipts binding
request and response hashes to a permit, a ledger entry, and an audit event;
evidence bundles that verify those linkages in one call; per-wallet hash-chained
audit with tamper, truncation, and broken-link detection; and idempotency with
payload binding, where a reused key carrying a changed payload conflicts rather
than replaying.

The asymmetry is the whole point: **a protocol can standardize how a budget is
expressed far more easily than it can standardize proof that a specific call
happened, cost what it claimed, and was authorized by a specific party.**
Metering answers "how much is left." Verifiability answers "prove what
happened." Only the second survives a spec change, because the first is a
number a protocol can carry natively while the second requires signing keys,
persistence, and a chain.

### What would actually break

Very little, and this is worth knowing in advance. The current surface
implements only `tools/list` and `tools/call` — no `initialize` lifecycle, no
resources, no prompts, no OAuth, no stdio. If MCP standardized metering fields,
the change would be adapting the envelope the gateway reads: the fields move
from repo-defined extensions to spec-defined ones. Receipts, evidence bundles,
ledger linkage, and audit chains are untouched, because MCP has no notion of
any of them.

That makes this a **rename-and-adapt event, not an existential one** — provided
the receipt and audit layers stay independent of the transport that triggers
them. They currently are: the trust facade is protocol-neutral, with MCP as the
only live adapter.

### Monitoring triggers

Watch for, and treat each as a prompt to re-read this section:

1. A metering, budget, or cost field entering the MCP specification.
2. Any signed-receipt, attestation, or evidence primitive entering MCP or A2A —
   **this is the one that matters.** Native metering is survivable; a native
   evidence layer would compete directly with the defensible half.
3. A first-party gateway from a major model vendor bundling authorization and
   metering.
4. MCP registry or discovery gaining runtime-truth or honesty semantics, which
   would overlap the discovery profile in recommendation 2.

### The pre-committed response

If native metering ships: **do not compete on cost declaration.** Adopt the
spec's fields, delete the repo-defined annotations, keep the delegated-authority
layer, and re-anchor positioning on evidence — "prove what happened," not
"report what it costs."

That prerequisite has now shipped. An authorized wallet can export a portable
receipt bundle, any third party can fetch public signing-key metadata without a
credential, and the SDK verifier checks the bundle offline without calling the
issuing application. The quickstart and stranger test also require a forged
bundle to fail distinctly from an unknown key.

The remaining trust limitation is key distribution, not signature checking:
the verifier still learns the issuer's keys from the same TLS origin being
audited unless the partner pins them out of band. The next milestone is
therefore customer-run verification of a partner-owned action, not another
first-party proof surface.

If a native *evidence* primitive ships, the response is different and harder:
compete on depth — chain verification, evidence bundles, reconciliation, and
crash consistency — or align with the standard and differentiate on
enforcement. Decide that when it happens; do not pre-commit to a fight that may
not be winnable.

---

## What actually matters, in order

Pulling the five together, ranked by leverage rather than by how they were
presented:

1. **Get one design partner.** It resolves the funding question, supplies the
   adoption evidence that makes the standards work credible, and is the only
   listed trigger that legitimately unfreezes settlement. Four of the five
   recommendations are gated on it, directly or indirectly.
2. **Recruit a second maintainer.** The bus factor is the largest non-technical
   risk and the single highest-value contribution available.
3. **Have a design partner perform independent verification.** The portable
   bundle, unauthenticated signing-key metadata, and offline verifier are
   shipped. What remains unverified is whether a partner engineer can use them
   on a partner-owned action and values the resulting receipt enough to keep the
   gateway in the invocation path.
4. **Keep the receipt layer transport-independent.** The cheap insurance that
   makes recommendation 5's contingency a rename rather than a rewrite.
5. **Publish the discovery honesty profile in-repo.** Cheap, already enforced,
   and it establishes priority without spending a first contact.
6. **Leave settlement frozen** until item 1 forces it, then work the checklist.

The consistent theme across all five corrections: this project's actual moat is
that its claims are executable and its limitations are written down. Every
recommendation got stronger when it was made *more* honest, not less — the
crash proof is more compelling with its fail-closed caveat, the discovery story
is more defensible as an honesty profile than as a land grab, and the settlement
note is more useful as a conformance checklist than as a partnership
announcement. Strategy that erodes that discipline would cost more than any
individual initiative could return.
