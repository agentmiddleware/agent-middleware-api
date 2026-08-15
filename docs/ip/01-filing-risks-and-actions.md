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

Additional public surfaces, distinguishing what is actually live from what is
only prepared — the distinction matters, because only a *published* artifact
starts a clock:

**Live and public** (treat as disclosures; get first-live dates and archived
copies for each):

- `https://www.thisisatest.tech/proof/`
- `https://www.thisisatest.tech/proof/receipt.json`
- `https://www.thisisatest.tech/proof/trust-keys.json`

Note that `scripts/publish_live_proof.py` is the **generator**, not the
artifact. The disclosure is the published output above, not the script.

**Prepared but not confirmed published** (candidate surfaces, not yet
disclosures): the MCP Registry submission path
(`docs/mcp-registry-submission.md`, `server.json`) — no matching registry entry
appears to exist, and the repo gates publishing behind a disabled endpoint —
and the AgentMarket listing draft (`docs/agentmarket-listing.md`), which the
repo marks as frozen copy. **Confirm each with counsel rather than assuming
either way.**

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
- [ ] **File a provisional application now**, before further publication —
      but understand precisely what it does and does not buy:
      - It **establishes a US filing date** and, filed inside the §102(b)(1)
        grace period, preserves US rights against your own earlier disclosure.
      - It can serve as the basis for a **Paris Convention priority claim** for
        foreign or PCT applications filed within 12 months.
      - It does **not** cure an earlier public disclosure, and it does **not**
        revive foreign rights already lost to absolute novelty. If the site
        disclosed the subject matter before the provisional's filing date, a
        later provisional cannot repair that in absolute-novelty jurisdictions.
      - It only supports what it actually describes. The provisional must
        adequately disclose **each mechanism** later claimed, or the
        non-provisional cannot claim its benefit for that mechanism.
- [ ] **Freeze new public technical detail** until the provisional is on file.
      Specifically: do not publish the SDK to PyPI, do not complete the MCP
      Registry submission, and do not publish a design-partner-facing writeup
      of the reconciliation or canonicalization mechanisms.
- [ ] **Confirm no SDK package was ever published.** `docs/x-announcement-thread.md`
      says published SDK packages must not be claimed, which suggests none were —
      verify, because a PyPI release of `b2a_sdk` would put the offline verifier
      source (mechanism 4) into publicly available prior art.

---

## 2. Inventorship, with AI in the loop

**This repository's own commit history is the evidence, and it cuts both ways.**

A substantial share of the commits sit on branches named `claude/*` and
`codex/*` — this work was AI-assisted, extensively and visibly.

The governing guidance changed recently, and the change is favorable:

- **Only natural persons can be named inventors.** *Thaler v. Vidal*, 43 F.4th
  1207 (Fed. Cir. 2022) — an AI system cannot be an inventor, full stop. This
  is unchanged.
- **The February 2024 guidance has been rescinded.** The USPTO announced
  revised inventorship guidance for AI-assisted inventions on **November 26,
  2025**, published at 90 Fed. Reg. (Nov. 28, 2025), which withdrew the
  February 2024 guidance (89 Fed. Reg. 10043) **in its entirety**.
- **There is no longer a separate standard for AI-assisted inventions.** The
  revised guidance applies ordinary inventorship law — human conception —
  regardless of whether an AI tool was used. AI systems are treated as tools,
  analogous to instruments or research software.
- **The *Pannu* factors no longer apply to the human/AI question.** The USPTO
  concluded that *Pannu*, a joint-inventorship test for multiple natural
  persons, is inapposite where one human uses an AI tool. *Pannu* still governs
  joint inventorship **among human co-inventors**.

**What this means here:** the earlier draft of this document applied the 2024
"significant contribution" and per-claim *Pannu* framing. That framing is
withdrawn. The question is the ordinary one — **who conceived the invention** —
and the fact that the work was AI-assisted does not by itself create a special
burden. That is a materially better position than the 2024 guidance implied.

It does **not** make the conception record unnecessary. Inventorship still has
to be right, an incorrectly named inventor remains a defect that can render a
patent unenforceable, and misstatements to the USPTO still implicate the duty
of candor. But the record you are building is the ordinary one any inventor
builds, not a special AI showing.

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
- [ ] **Decide the licensing posture before filing — with counsel, not by
      default.** An earlier draft of this document suggested Apache 2.0 as the
      more coherent pairing with a patent strategy. That was too glib and is
      arguably backwards: Apache 2.0 §3 grants every recipient a royalty-free
      license to the contributor's patent claims necessarily infringed by the
      contribution, which is precisely the right you would be trying to
      preserve. Its defensive-termination clause only revokes that grant from
      someone who sues over the work; it does not reserve your rights against
      everyone else.
      The real choice is among keeping the code closed, dual licensing, or
      making an intentional and scoped patent grant — and it depends on whether
      the goal is adoption or enforcement. Take it to counsel.
      Changing the license does not retroactively affect copies already
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
