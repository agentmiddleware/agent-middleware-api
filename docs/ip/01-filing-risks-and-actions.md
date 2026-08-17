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

### Dated evidence from the repository history

The full git history was recovered (the working clone had been shallow) and
gives concrete earliest-possible dates. **These are conservative earliest
bounds, not established disclosure dates.** Commit dates bound publication from
below — content cannot have been published before it was written, and the site
deploys from these commits, so actual publication is at or after each date. They
are not a substitute for the three records that would settle it: Vercel
deployment history, repository access and visibility history, and third-party
archive captures. Treat every §102(b)(1) date below as "no earlier than", and
have counsel confirm each against those sources.

Note also that dates here are given in the commit's local offset unless marked
UTC; the two differ across a day boundary for the earliest entry, which is
exactly the kind of ambiguity a filing date should not inherit.

| Event | Earliest date | Evidence |
| --- | --- | --- |
| First repository commit | 2026-02-22 local (`-08:00`) = **2026-02-23 UTC** | `fb327e4`, authored 2026-02-22T21:33:18-08:00 |
| Repository created on GitHub (private) | 2026-02-23T05:33:55Z | GitHub `created_at` — a distinct event, ~37s after the commit timestamp |
| Marketing site content first committed | **2026-07-29** | `site/index.html` first appears in `1df5999` |
| `thisisatest.tech` first referenced | **2026-08-11** | `5f2233d` |
| Proof artifacts (`site/proof/`) first committed | **2026-08-11** | `5f2233d` |
| Ed25519 / offline verification first described on the site | **2026-08-11** | `5f2233d`, refined in `9e10971` |
| **SDK release published with wheel + sdist** | **2026-08-07** | GitHub release `python-sdk-v0.4.0`, `draft: false`, published 2026-08-07T19:19:14Z |

**Read this as good news, and act on it quickly.** The mechanisms this package
claims were not described on the public site until **2026-08-11** — days, not
months, before this was written. Two consequences:

- The **US** §102(b)(1) clock on that subject matter runs from roughly
  2026-08-11 (or 2026-07-29 for the earlier, more generic marketing copy), so
  the outer US deadline is roughly August 2027.
- **Foreign rights may still be recoverable.** Absolute novelty bars what was
  *publicly disclosed* before the priority date. Only a marketing-level
  description has been public, and only briefly. Whether that description is
  *enabling* for any claimed mechanism is the whole question — and none of the
  four mechanisms is described at an enabling level anywhere public. Filing
  promptly is what preserves the argument; delay is what forecloses it.

### The SDK release is the sharpest item

`python-sdk-v0.4.0` is a **real, non-draft GitHub release** published
2026-08-07T19:19:14Z with two attached artifacts —
`b2a_sdk-0.4.0-py3-none-any.whl` and `b2a_sdk-0.4.0.tar.gz` — each showing
**`download_count: 2`**. The sdist contains the offline verifier source, i.e.
mechanism 4 at a fully enabling level.

Each asset reports `download_count: 2`, so **four downloads in total** across
the two artifacts.

### What the API establishes, and what it does not

Queried against the authenticated GitHub API on 2026-08-15. These are facts, not
inferences, and they narrow the questions below:

| Field | Value | Why it matters |
| --- | --- | --- |
| Release author | `github-actions[bot]` | The release was produced by CI (`.github/workflows/python-sdk-release.yml`), not hand-cut |
| Both asset uploaders | `github-actions[bot]` | Same — the artifacts were built and attached by the workflow |
| `created_at` / `published_at` | 2026-08-07T19:18:40Z / 19:19:14Z | 34 seconds apart; publication was immediate, not staged |
| `updated_at` | 2026-08-07T19:19:14Z | **Identical to `published_at`** — the release has not been edited since it was published |
| `draft` / `prerelease` | `false` / `false` | Not a draft and not marked pre-release |
| `b2a_sdk-0.4.0.tar.gz` | 21,778 bytes, `sha256:46094226f7af6e5e60fc1068535b39db79be7d62bdbeef99753d3d5428e2efd3` | Pins exactly which bytes were published |
| `b2a_sdk-0.4.0-py3-none-any.whl` | 21,168 bytes, `sha256:8263b63aaa06ff395f6d367ca7dba2a1ada5b3f98bca5d24ae3c9b08c5df6e6c` | Same |

Record those two digests. If the enabling-disclosure question is ever litigated
or examined, they are what lets anyone establish *what was in the artifact* on
that date, independently of the current tree.

**One comfortable assumption did not survive.** The earlier draft reasoned that
the four downloads were "most likely CI or the owner." No workflow or script in
this repository downloads its own release assets — the only
`releases/download` reference anywhere in `.github/` or `scripts/` fetches
gitleaks from an external repository. So the mechanical explanation that would
have made the download counts self-evidently benign **is not present in the
tree**. That does not make the downloads third-party; a maintainer pulling the
file by hand, or any authenticated client, would also register. It does mean the
count is unexplained rather than explained, and it should be treated as an open
question rather than a formality.

**Repository visibility: private *now*, history unknown.** The authenticated
GitHub API reports `"private": true` for this repository as of 2026-08-17. That
settles the present state and nothing else — the API exposes only current
visibility, so it cannot tell you whether the repository was public at any point
between 2026-08-07 and now, which is the question that actually matters.

Note also what is *not* evidence: an unauthenticated probe from a sandboxed
environment returned 403 for the API and 404 for the asset, but both requests
traverse an egress proxy, and an unauthenticated request to a private repository
returns 404 regardless. Do not read those codes as a finding in either
direction.

### What still needs a human

1. **Was the repository private for the entire period since 2026-08-07?** It is
   private *today* (API, 2026-08-17), but that says nothing about the interval. A repo
   that was public at any point, even briefly, published these assets. This is
   answerable definitively from the organization or account **audit log**
   (`repo.access` events record every visibility change, with timestamps); the
   API's current `visibility` field cannot answer it retrospectively.
2. **Who performed those four downloads?** GitHub does not expose per-download
   identity for release assets through any public API, so this is not
   machine-answerable. If the account is on an Enterprise plan, the audit log
   retains more; otherwise the honest answer may be that it is unknowable, and
   counsel should plan for that rather than assume a benign answer.
3. **Was any release asset URL shared outside the collaborator set?** Human
   knowledge only — check design-partner correspondence, Slack/email, and any
   place `python-sdk-v0.4.0` was linked. Note that a private-repo asset URL
   requires authentication to fetch, so sharing the URL alone is weaker evidence
   of disclosure than sharing the file.

If all three come back clean this is a non-event. If any does not, an enabling
disclosure of mechanism 4 dates from 2026-08-07 and the analysis above changes.

### Why this matters

- **United States** — 35 U.S.C. §102(b)(1) gives a **12-month grace period**
  running from the inventor's own first public disclosure. If the site went
  live in, say, March 2026, a US filing must land before the corresponding date
  in March 2027. The clock started at first disclosure, not at your convenience.
- **Europe, China, Japan, Korea, and most of the rest of the world** — broadly
  absolute novelty. A public disclosure **before** the priority date is
  generally a bar. If the site has been live and describing signed receipts and
  offline verification since before any filing, foreign rights to *that
  disclosed subject matter* may already be gone.

  **Do not treat that as settled without checking each target country.** Grace
  periods and non-prejudicial-disclosure exceptions vary. The EPC has narrow
  exceptions under Article 55 — evident abuse in relation to the applicant, and
  display at an officially recognised international exhibition — each with a
  six-month window and strict conditions. Japan and Korea have their own grace
  provisions with their own requirements and deadlines. None of these is a
  general-purpose grace period of the US kind, and none should be relied on
  without counsel confirming it applies to *these* disclosures in *that*
  jurisdiction.

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
        grace period, preserves US rights against your own earlier disclosure —
        **but only if a nonprovisional or US-designating PCT application is
        filed within 12 months and expressly claims the provisional's benefit.**
        A provisional is never examined and never matures into a patent on its
        own; it goes abandoned at 12 months. Miss that window and the filing
        date is gone.
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
- [ ] **Establish exactly how and where the SDK has been distributed** — do not
      assume it was never released. `b2a_sdk/README.md` states the package is
      **not** on PyPI but that the `python-sdk-v0.4.0` tag **attaches built
      wheels and sdists to a GitHub release**
      (`.github/workflows/python-sdk-release.yml` builds and publishes them on
      any `python-sdk-v*` tag). That is a real distribution channel carrying the
      offline verifier source — mechanism 4.
      Check all of them: the PyPI index, the git tags, every GitHub release and
      its attached artifacts, and whether any release was ever public. Releases
      on a private repository are not public, so this may well be clean — but it
      is a question to answer with evidence, not an assumption.

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
  2025**, published at **90 Fed. Reg. 54637 (Nov. 28, 2025)**, Federal Register
  Document No. **2025-21457**, which withdrew the February 2024 guidance
  (89 Fed. Reg. 10043) **in its entirety**.
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
burden. On its face that reads as a better position than the 2024 guidance
implied — but treat that as a preliminary reading for counsel to confirm, not a
conclusion you can rely on.

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

- There is a **theoretical implied-license or estoppel risk** if you distribute
  code under a permissive licence and later assert patents covering that same
  code against a recipient. State this accurately: an earlier draft of this
  document said "courts have found implied patent licenses" in this situation.
  **That overstated the authority.** No US case squarely holds that
  distribution under MIT or a similar permissive licence, standing alone,
  creates an implied patent licence. Doctrines like legal estoppel and implied
  licence by conduct exist and are fact-dependent, and a defendant who received
  the code would very likely raise them — but this is an unverified,
  fact-dependent risk to have counsel evaluate, not a settled rule.
- If the repo has been private throughout, that recipient set should be small —
  but note that premise is **assumed, not verified** (see "What still needs a
  human" above; repository visibility history is an audit-log question). The set
  is not necessarily empty either way: design partners, the "stranger test"
  participants (`docs/stranger-test.md`), and anyone given a handoff bundle may
  have received licensed copies.

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
