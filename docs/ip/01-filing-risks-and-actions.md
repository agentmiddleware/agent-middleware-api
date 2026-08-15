# Filing risks and required actions

Four issues that affect whether a patent can be obtained, and where. Each has a
concrete action. Take these to counsel before spending money on claim polish —
a beautiful claim set does not survive a lost novelty date or a defective
inventorship declaration.

---

## 1. The public-disclosure clock is already running

**Status: the source is safe, the marketing is not.**

The repository itself is **private** (GitHub `visibility: private`, created
2026-02-23), so the code is not a printed publication. That is genuinely good
news and it preserves the strongest option.

But the product has a live public site at `https://www.thisisatest.tech`
(declared as the repo homepage), and that site publicly describes:

- Ed25519-signed receipts (`site/index.html`, `site/proof/index.html`)
- offline receipt verification against a published key set
- `/.well-known/trust-keys.json` key distribution
- canonical-JSON signing

Additional public surfaces referenced in-repo: a published live-proof artifact
(`scripts/publish_live_proof.py`), an MCP Registry submission path
(`docs/mcp-registry-submission.md`, `server.json`), and an AgentMarket listing
draft (`docs/agentmarket-listing.md`).

### Why this matters

- **United States** — 35 U.S.C. §102(b)(1) gives a **12-month grace period**
  running from the inventor's own first public disclosure. If the site went
  live in, say, March 2026, a US filing must land before the corresponding date
  in March 2027. The clock started at first disclosure, not at your convenience.
- **Europe, China, Japan, Korea, and most of the rest of the world** — absolute
  novelty. A public disclosure **before** the priority date is a bar with no
  grace period. If the site has been live and describing signed receipts and
  offline verification since before any filing, foreign rights to *that
  disclosed subject matter* may already be gone.

Whether the site's marketing-level description is **enabling** (detailed enough
to teach a skilled person to build it) is a legal judgment and is genuinely
arguable — "we use Ed25519-signed receipts you can verify offline" is a long way
from the canonicalization contract and reconciliation state machine in
[`03-invention-disclosure.md`](03-invention-disclosure.md). The four mechanisms
this package actually claims are, in my reading, **not** disclosed on the public
site at any enabling level. That is the argument to preserve.

### Actions

- [ ] **Establish the first public disclosure date.** Check the deployment
      history for `thisisatest.tech`, the first public proof publication, and
      any registry or marketplace listing that went live. Give counsel exact
      dates and archived copies (Wayback, screenshots).
- [ ] **File a provisional application now**, before further publication. A
      provisional is cheap, and it stops the bleeding on both the US grace
      period and any foreign rights not yet lost.
- [ ] **Freeze new public technical detail** until the provisional is on file.
      Specifically: do not publish the SDK to PyPI, do not complete the MCP
      Registry submission, and do not publish a design-partner-facing writeup
      of the reconciliation or canonicalization mechanisms.
- [ ] **Confirm no SDK package was ever published.** `docs/x-announcement-thread.md`
      says published SDK packages must not be claimed, which suggests none were —
      verify, because a PyPI release of `b2a_sdk` would put the offline verifier
      source (mechanism 4) into the public domain of prior art.

---

## 2. Inventorship, with AI in the loop

**This repository's own commit history is the evidence, and it cuts both ways.**

A substantial share of the commits sit on branches named `claude/*` and
`codex/*` — this work was AI-assisted, extensively and visibly.

The law here is settled on the extremes and unsettled in the middle:

- **Only natural persons can be named inventors.** *Thaler v. Vidal*, 43 F.4th
  1207 (Fed. Cir. 2022) — an AI system cannot be an inventor, full stop.
- **AI-assisted inventions remain patentable**, provided a natural person made a
  *significant contribution* to the conception of each claimed invention.
  USPTO Inventorship Guidance for AI-Assisted Inventions, 89 Fed. Reg. 10043
  (Feb. 13, 2024).
- Under that guidance, "significant contribution" is assessed per claim using
  the *Pannu* factors. Merely recognizing a problem, or merely appreciating a
  useful result from an AI system's output, is **not** enough. Constructing the
  prompt, selecting among alternatives, and directing the design in a way that
  amounts to conception generally **is**.

An incorrectly named inventor is not a formality. It is a defect that can render
a patent unenforceable, and misstatements to the USPTO implicate the duty of
candor.

### Actions

- [ ] **Build a conception record now, while memory is fresh.** For each of the
      four claimed mechanisms, write down: what problem you identified, what
      design decisions you made, what alternatives you rejected and why, and
      what you directed rather than accepted. The atomic-reservation mechanism
      is a good example to start with — the repo history shows an adversarial
      test found the concurrency overspend
      (`e8bf861 test(invariants): ... budget cap overspends under concurrency`)
      and a decision followed about how to fix it
      (`25897fd fix(permits): enforce budget cap atomically`). That sequence,
      and who drove it, is exactly what counsel needs.
- [ ] **Tell counsel the work was AI-assisted, explicitly and early.** Do not
      let them find out from the branch names at deposition. Counsel who knows
      up front can draft the declarations correctly; counsel who is surprised
      later has a much harder problem.
- [ ] **Preserve the full git history.** The clone used to prepare this package
      was shallow (135 commits, truncated). The complete history, including
      branch names and authorship, is inventorship evidence — do not squash or
      rewrite it.

---

## 3. §101 / *Alice* eligibility is the likeliest rejection

Authorization, metering, and billing are exactly the subject matter examiners
map onto abstract ideas — "certain methods of organizing human activity" and
"fundamental economic practice." A claim that reads *authorize an agent, meter
its spending, issue a receipt* invites a §101 rejection on sight, and the
"do it on a computer, for AI agents" framing does not rescue it.

The defense is to anchor every independent claim in a **specific technical
improvement to computer functionality** — the *Enfish* / *McRO* line, and
notably *Finjan* and *Ancora* for security-adjacent mechanisms.

That is why [`04-claim-sets.md`](04-claim-sets.md) anchors the independents in:

- correctness of a spend cap **under concurrent access**, on engines where
  advisory row locks do not fire (a database-behavior problem, not a
  bookkeeping one);
- recovery of a **known-consistent state after a process crash mid-transaction**
  (a durability problem);
- a verification procedure whose reported status **distinguishes cryptographic
  failure from resource unavailability** (a correctness-of-diagnosis problem).

Each of those is a concrete problem arising *from* computer systems, with a
concrete technical solution — not a business practice with a computer bolted on.

### Action

- [ ] Tell counsel plainly: **do not draft the independents around "authorize
      and bill an AI agent."** That framing is both the §101 exposure and the
      place Daon's art is strongest (see below).

---

## 4. MIT licensing and prior distribution

`LICENSE` is MIT (© 2026 Christopher Sellers).

MIT contains **no express patent grant** — unlike Apache 2.0 §3 — so it does not
by its terms license your patents to recipients. But two exposures remain:

- Courts have found **implied patent licenses** where a licensor distributes
  code under a permissive license and later asserts patents covering that same
  code against recipients. The scope is unsettled, but the risk is real for
  anyone who actually received the code.
- Because the repo is private, that recipient set should be small. It is not
  necessarily empty: design partners, the "stranger test" participants
  (`docs/stranger-test.md`), and anyone given a handoff bundle may have received
  licensed copies.

### Actions

- [ ] **Enumerate everyone who received the code**, under what terms, and when.
- [ ] **Decide the licensing posture before filing.** If patent protection is
      the goal and the code is going public later, Apache 2.0 with its express
      grant and defensive-termination clause is the more coherent pairing than
      MIT. Changing the license does not retroactively affect copies already
      distributed under MIT.
- [ ] Have counsel review whether any design-partner agreement already grants
      rights that would undercut an assertion.

---

## Suggested sequence

1. **This week** — pin down the first public disclosure date; start the
   conception record; freeze new public technical detail.
2. **Within 2–4 weeks** — engage counsel; file a provisional covering all four
   mechanisms. The disclosure in this package is detailed enough to support one.
3. **Within 12 months of the provisional** — convert to a non-provisional with
   claims refined against whatever art the search turns up, and decide on PCT
   based on what foreign rights survive issue #1.
