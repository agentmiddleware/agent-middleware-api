# GitHub organization configuration

How the `agentmiddleware` GitHub organization and its repositories are meant to
be configured, what was actually configured when this was audited, and the
exact clicks or commands that close each gap. Written for one maintainer with
admin on everything and no second reviewer.

Audit date: 2026-10-19, updated 2026-10-20 after the repositories were made
public and 2026-10-22 after this repository was unarchived. Re-run the two
scripts below to refresh the repository rows; the organization rows can only
be read in the GitHub UI.

State on 2026-10-22: the 2026-10-20 update of this document recorded this
repository as archived. It was writable again by 2026-10-21 19:15 UTC, when
pull request 842 was opened, and `main` merged ten pull requests between
2026-10-21 22:08 and 2026-10-22 07:04 UTC (842 to 851: site, README and test
work, plus a one-line repository-URL change in `app/routers/well_known.py`
in 842 and a CI step for the site's JavaScript tests in 845). Pull request
850 (merged 06:02 UTC) added the README banner saying the repository is
archived and that development continues in `agent-middleware`; its
description says the repository "stays unarchived for now because site PRs
are still open". After the last merge it was read-only again until about
21:35 UTC on 2026-10-22, when the repository object was last updated and
pushes started succeeding; GitHub records no archive times.
The organization also gained a `.github` repository on 2026-10-20 (profile
README, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md`, and a weekly
Dependabot entry for the `github-actions` ecosystem, though it has no
workflows yet) and an organization ruleset, `main-protect`, that requires a
pull request on the default branch (see the audit table). Everything below
treats this repository as live until the maintainer archives it for good.

## Do these first, in this order

1. **Done 2026-10-20: six of the seven repositories are public**
   (`agent-middleware-public` is still private). That removes the Actions
   minutes bill on standard runners and switched on secret scanning, push
   protection and private vulnerability reporting by itself. The first
   follow-up is settled: every `main` push since 2026-10-20 09:23 UTC (17
   through `9289867` on 2026-10-22) started a named workflow run, and the
   no-name `startup_failure` in [Actions budget](#actions-budget) last fired
   at 2026-10-19 21:28 UTC, so billing was the cause. The second remains:
   this repository's description is fixed; re-read the others (see
   [Repositories](#repositories)).
2. **Apply the repository settings** from a machine where `gh auth status`
   shows your account:

   ```bash
   python scripts/github_repo_settings.py          # dry run, shows drift
   python scripts/github_repo_settings.py --apply
   ```

   "Delete branch on merge" was switched on by hand by 2026-10-22, and a
   pull request (0 approvals) is already required on `main` by the
   organization ruleset `main-protect`, created 2026-10-20 22:09 UTC. What
   the script still reports as drift is the same requirement on the classic
   branch-protection rule, which also carries the required checks; applying
   it is belt and braces, not a new control. Secret scanning is already on.
3. **Clean up the remaining branches** now that "delete branch on merge" is
   on, so they stop accumulating:

   ```bash
   python scripts/github_branch_cleanup.py                 # lists what is fully merged
   python scripts/github_branch_cleanup.py --apply         # deletes only those
   python scripts/github_branch_cleanup.py --stale-days 90 # review the rest by hand
   ```

   Dry run on 2026-10-19: 550 branches, 103 fully merged into `main`, 26
   unmerged with no commit in 90 days, 45 `backup/local-2026-10-07/*` kept
   by prefix. Dry run on 2026-10-20, after about 240 branches had been
   deleted by hand in between: 310 branches (284 by 2026-10-22); 4 fully
   merged (the `--apply` set); 3 unmerged with no commit in 90 days
   (`codex/regengine-governed-mcp-bridge`, `feat/trust-primitives`,
   `codex/trust-readiness-gap-map`); 45 `backup/` kept; the remaining 256
   (the script also skips the protected `master`) are unmerged branches with
   a commit in the last 90 days, nearly all agent-generated. Those need a decision, not a script: either open the
   pull request or delete the branch.

4. **Work through the [organization settings](#organization-settings)
   table.** None of it can be scripted from a repository-scoped token.

## Audit snapshot

### Organization

| Item | Found | Target |
|---|---|---|
| Members | 1 (`PetrefiedThunder`, owner) | Same, until there is a second maintainer |
| Teams | none | A `maintainers` team as soon as a second person joins, so `CODEOWNERS` can name a team instead of a person |
| Repositories | 7 on 2026-10-22: six public (`agent-middleware-api`, `agent-middleware`, `agent-middleware-spec`, `amw-demo`, `amw-paypal-agent-demo`, `.github`) and `agent-middleware-public` still private. This repository's description was fixed; the others were not re-read on 2026-10-22 | `agent-middleware` is where development continues, per the README banner added here by #850; see [Repositories](#repositories) |
| Actions runs on `main` pushes | `startup_failure`, no workflow name, on every `main` push from 2026-10-17 to 2026-10-19, while the repository was private. Since it went public every push run has started: the merges of 2026-10-21 and 2026-10-22 ran green (for example run 39733461851 for `b6f006a`) except two runs that were cancelled, not failed: `7408143` (#847, run 39719715065, where only `test (3.11)` was cancelled 25 minutes in and the other 18 jobs passed) and `9289867` (#848, run 39737949702); both commits' Docker publish runs succeeded | Green push run on every `main` commit |
| Two-factor requirement, base permission, Actions policies, security configuration | Not readable from here | See [Organization settings](#organization-settings) |

### `agent-middleware-api`

| Setting | Found | Target | How |
|---|---|---|---|
| `main` required status checks | 11 contexts, exactly the list in [trust-release-gate-branch-protection.md](trust-release-gate-branch-protection.md); strict (up to date) on | Keep | Already correct |
| `main` admins exempt | No (`enforce_admins` on) | Keep | Already correct |
| `main` force push / deletion | Both blocked | Keep | Already correct |
| `main` conversation resolution | Required | Keep | Already correct |
| `main` requires a pull request | **Off** on the classic rule (still, on 2026-10-22); **On** through the organization ruleset `main-protect` since 2026-10-20 22:09 UTC, 0 approvals | On | Effective already; `github_repo_settings.py --apply` mirrors it onto the classic rule |
| Delete branch on merge | **Off** on 2026-10-19 (why 550 branches had accumulated); **On** by 2026-10-22 | On | Done by hand |
| Auto-merge, update branch | On | Keep | Already correct |
| Web commit sign-off (DCO) | On | Keep | Already correct |
| Secret scanning, push protection | Disabled while private; **enabled** (with validity checks and non-provider patterns) the moment the repository went public on 2026-10-20 | Keep | Already correct; see [Secret scanning](#secret-scanning) |
| Private vulnerability reporting | Enabled | Keep; it is what `SECURITY.md` asks reporters to use | Already correct |
| Dependabot security updates | Enabled | Keep | Already correct |
| Dependabot version updates | One pull request per package, pip and Actions only | Grouped pull requests: weekly for pip (root, SDK and wrappers) and Actions, monthly for the Docker digest and Railway IaC | Done in `.github/dependabot.yml` on this branch |
| `test (3.11)` stalls | `main`'s run for `7408143` (#847) and this branch's run for `fd1c42c` each had `test (3.11)` alone cancelled by the 25-minute job timeout after the suite stopped producing output mid-run. Through CPython 3.11, a sqlite3 cursor whose statement failed keeps that statement attached; destroying the cursor on the event-loop thread while an aiosqlite worker holds the connection mutex in a busy wait freezes the loop | No stall | Fixed on this branch: `app/db/database.py` passes a connection factory whose cursors release a failed statement on the worker thread (a no-op on 3.12+); `tests/test_sqlite_failed_cursor_release.py` reproduces the mechanism |
| Rulesets | None on 2026-10-19. Since 2026-10-20 22:09 UTC the organization ruleset `main-protect` (id 25509458, active, no bypass actors) applies to the default branch: pull request required with 0 approvals, no deletion, no force push. Whether it targets the other repositories too is visible only in Organization → Settings → Rulesets | Keep | – |
| `master` branch | Exists, protected, 9 commits ahead and 1,239 behind `main` on 2026-10-19, last commit 2026-05-22; still present on 2026-10-22 | Deleted | See [Remove master](#remove-master) |
| Security advisory link in issue chooser | Pointed at the old `PetrefiedThunder/` namespace | Organization namespace | Done in `.github/ISSUE_TEMPLATE/config.yml` on this branch |

Why 0 approvals: GitHub does not let an author approve their own pull request.
With one maintainer, requiring 1 approval blocks every merge. Requiring a pull
request with 0 approvals still forces every change through the 11 required
checks, which is the control this repository relies on
([GOVERNANCE.md](../GOVERNANCE.md), "Merge requirements"). Raise the count to 1
and turn on code-owner review the day a second maintainer has commit access.

## Actions budget

### What happened

- Open issue 805 (2026-10-14) reports `startup_failure` on this repository and
  attributes it to an organization billing or policy setting.
- Pull request 816 was opened on 2026-10-15 from a branch named
  `ci/retrigger-main-1014` to retrigger checks after the lock lifted, and its
  title, "ci: refresh requirements.lock and fix PT011 after billing lock"
  (merged 2026-10-17 20:35 UTC), names the lock. So the lock has happened at
  least twice this month.
- The workflow files did not change between the last green push run before
  the lock (`44cd144`, 2026-10-16) and any of the heads that failed to start
  (through `0c3300a` on 2026-10-19), which rules out a broken workflow file.
- The block comes and goes in windows. The same no-name `startup_failure`
  run (GitHub's placeholder when it refuses to start any workflow for an
  event) fired 139 times since 2026-09-15: 27 times between 2026-09-15 22:01
  and 2026-09-16 09:30, 7 times on 2026-10-13, 90 times on 2026-10-14
  (04:45, 09:29 and 18:30 to 21:26), 4 times on 2026-10-17 20:19 to 20:35, 6
  times on 2026-10-19 11:23 to 11:28 and 6 times on 2026-10-19 21:26 to
  21:28 UTC, on push and pull-request events alike, including the push of
  every `main` commit from 2026-10-17 through 2026-10-19 (`7190d17`,
  `50df44a`, `bda6197`, `0c3300a`). Between those windows (for example this
  pull request's runs at 07:33 UTC on 2026-10-19 and from 08:52 UTC on
  2026-10-20) everything starts normally. The API does not expose the
  reason; the run page does, as a banner above the empty job list. Open the
  latest `main` push one and read it:
  <https://github.com/agentmiddleware/agent-middleware-api/actions/runs/39327821138>.
  A spending-limit message confirms the billing explanation; anything else
  changes the fix.
- Until that is settled, every merge into `main` that lands inside a window
  has no push run, and `railway-deploy.yml` will refuse to release it. Check
  the Actions tab after each merge; if the push run is the no-name failure,
  the commit cannot be released until CI has a manual trigger (`ci.yml` has
  no `workflow_dispatch`) or the release gate accepts a re-run.

### Why it kept happening (while the repository was private)

Private repositories pay for Actions minutes. This repository's CI is heavy by
design (every push runs the full release gate), and every Dependabot pull
request runs it too. The numbers stay here because they are also the
wall-clock cost of every pull request.

| Measured on run 2179 (2026-10-16, `main`) | Minutes |
|---|---|
| `test (3.11)`, `test (3.12)`, `test (3.13)` | 12.6 + 17.3 + 10.3 |
| `trust_release_gate`, `postgres_permit_concurrency` | 3.7 + 3.8 |
| `postgres_trust` | 1.8 |
| `lint`, `invariant_attack_proof`, `production_trust`, `secret_scan`, `constant_test_loop` | 0.5 to 1 each |
| `python_sdk` x4, `wrapper_unit` x4 | about 0.5 each |
| Job time per CI run | about 60 |
| Billed per run (each job rounds up to a whole minute) | about 65 |
| Plus `Failure Lab` (fast tier on pull requests, fast and slow tiers on `main`) and `docker-publish` | 3 to 10 |

Between 2026-10-15 and 2026-10-17 there were 80 CI runs (69 ran to
completion, 11 were superseded and cancelled), about 5,000 billed minutes in
three days at the per-job ceilings. The Free plan includes 2,000 minutes a
month for private repositories; Team includes 3,000. Overage on standard
Linux runners is about $0.008 per minute, so a month at the recent cadence
(709 CI runs in the 30 days to 2026-10-19) is roughly 40,000 to 50,000
minutes, or $300 to $400 of overage.

### The decision

**Taken on 2026-10-20: the repository is public.** Public repositories get
unlimited Actions minutes on standard runners, free secret scanning and push
protection, and private vulnerability reporting, and GitHub switched all of
those on by itself at the flip. The repository already carried a
`SECURITY.md` and tests asserting that public surfaces link to
`github.com/agentmiddleware/agent-middleware-api`. Later the same day the
maintainer rewrote the entire history (every commit SHA changed except the
first three commits of 2026-02-23, already identical) to replace
the value of the key removed on 2026-08-06 (#201) and rotated on 2026-08-07
with `***REMOVED***`, replaced `LICENSE` (Business Source License 1.1) with
the Apache License 2.0 in the one new commit on top, `861d46c`, and, per the
2026-10-20 update of this document, archived the repository. It was writable
again by 2026-10-21 19:15 UTC, read-only again after the last merge on
2026-10-22, and writable from about 21:35 UTC that day (pull request 850
says the archive waits for the open site pull requests). The fallout is
listed under [After the history rewrite](#after-the-history-rewrite).

The two options not taken, kept for the record:

- A spending limit on a private repository (Organization Settings → Billing
  and licensing → Budgets and alerts). A $0 limit, the default, is what
  produces the lock.
- Reducing the bill per push: the non-required legs `test (3.13)`,
  `python_sdk (3.13)` and the four `wrapper_unit` jobs are about 15 minutes of
  each run and could be gated on `github.event_name == 'push'`. No longer a
  cost question; still a wall-clock one if pull-request feedback feels slow.

`main` had green push runs again on 2026-10-20 from 09:23 UTC (five of six;
the 11:05 run failed on `test (3.11)`, a real test failure), then the
force-push of the rewritten history at 22:19 UTC produced a run that is red
on `secret_scan` (see below), with the six long jobs cancelled and the other
twelve green. The merges of
2026-10-21 and 2026-10-22 ran green again (a normal merge carries a known
`before` SHA, so its `secret_scan` range is well defined); two runs on
2026-10-22 were cancelled rather than failed: `7408143`, where `test (3.11)`
alone was cancelled 25 minutes after it started, and `9289867`. `ci.yml`
still has no manual trigger, so a cancelled push run is replaced either by
re-running it from the Actions page (the release gate reads the run's current
conclusion) or by the next merge; a `startup_failure` run has no jobs to
re-run.

## After the history rewrite

The 2026-10-20 22:19 UTC force-push replaced every commit on `main` (1,403
of them), added one new commit, `861d46c`, on top, and, as it turned out,
rewrote every other branch too. These were the
consequences; the state on 2026-10-22 is given for each.

- **`secret_scan` failed on `main`'s rewrite push, and its fallback base was
  stale. Fixed on this branch.** The rewrite push carried the old tip
  `2d62e2b` as its `before` SHA and GitHub still served that commit, so
  `scripts/secret_scan_range.sh` emitted `2d62e2b..861d46c`, a range with no
  common ancestor that covered the whole rewritten history (984 commits);
  gitleaks flagged the `***REMOVED***` marker the rewrite had left in the
  2026-08-04 commit of `scripts/stress_test_live.py`, and the "Scan commit
  range for committed secrets" step failed on run 39507256676. Separately,
  the script's pinned verified-clean base for pushes with no usable `before`
  SHA, `dd16051` (#811), stopped existing, so that fallback would have failed
  closed and `test_pinned_verified_base_is_on_this_history` silently skipped
  (it treats a missing pin as a shallow checkout). Normal pushes were
  unaffected: their `before` SHA is an ancestor of the new tip, so the range
  covers only the new commits. On 2026-10-22 a full-history scan of a fresh
  clone (gitleaks 8.21.2, the release CI pins, `--log-opts=--all`, 283
  branches at the time, 1,410 commits scanned) found three findings in two
  places, both non-secrets and now allowlisted in `.gitleaks.toml`: the
  `***REMOVED***` marker above, and a synthetic `amw_demo_secret_value` at
  commit `bd812bab` in the history of the unmerged `devops/demo-key-utm`
  branch (its tip has already replaced the value). `site/hero-receipt-fixes`,
  pushed at 21:51 UTC after the clone, adds one clean commit. `VERIFIED_BASE`
  is re-pinned to `9289867`, the `main` tip that scan covered, and the test
  runs again.
- **Two documents described the old history. Fixed on this branch.** The
  scope note in `.gitleaks.toml` and the "Correction (2026-09-19)" section of
  [api-key-rotation.md](api-key-rotation.md) said the retired key was
  reachable from `main` through commit `9e45009`. Neither is reachable from a
  branch or tag any more (GitHub still serves the old commit by SHA until it
  is garbage-collected or purged). The scope note now records the 2026-10-22
  scan, the
  rotation record keeps the 2026-09-19 section as history and adds a dated
  update, and the comment in `ci.yml`'s `secret_scan` job no longer says a
  full-history scan would always fail.
- **The license documents disagree with `LICENSE`. Still open.** `LICENSE`
  is Apache License 2.0 since `861d46c`; #851 fixed the README badge and the
  #850 banner says "Apache 2.0 (gateway is Fair Source, FSL-1.1)". But
  `LICENSING.md` (the directory table and "What the Business Source License
  allows"), `CONTRIBUTING.md` ("Licensing of contributions"), `GOVERNANCE.md`
  (two places) and the README's own licensing paragraph still say Business
  Source License 1.1 for the core, and "gateway is Fair Source" describes the
  `gateway/` directory of `agent-middleware`, which this repository does not
  have. Decide what `app/` is licensed under and say it in all four files in
  one commit; it decides whether a competitor may host the service.
- **Clones are on dead history; branches are not.** Every one of the 284
  branches on GitHub shares history with the rewritten `main` (checked
  2026-10-22), so pull requests compare normally again; this one showed
  94,797 changed lines only until its branch was rewritten too. Local clones
  and forks taken before 2026-10-20 do not share history and must be
  re-cloned. `github_branch_cleanup.py` was never at risk: a branch with no
  merge base compares as "ahead", so `--apply` cannot delete it.

## Secret scanning

GitHub's secret scanning, push protection, validity checks and non-provider
patterns have been on since the repository went public on 2026-10-20 (they
were off while it was private, where they need the paid Secret Protection
add-on). `scripts/github_repo_settings.py` reports secret scanning and push
protection and would re-enable those two if they were ever switched off;
validity checks and non-provider patterns stay set by hand under the
repository's Code security settings.

Three layers now cover the same risk, and all three stay:

- GitHub push protection rejects a push that contains a known provider
  secret pattern before it lands.
- `.pre-commit-config.yaml` runs gitleaks on the staged diff with the same
  `.gitleaks.toml` and the same gitleaks release as CI, which also catches the
  repository's own low-entropy patterns that GitHub does not know. Install
  once with `pre-commit install`.
- The CI `secret_scan` job scans the working tree and the pushed commit range
  and is a required check on `main`.

Full-history scans are run by hand and recorded in the scope note of
`.gitleaks.toml`; the latest, on 2026-10-22, covered every branch of the
rewritten history and is what `scripts/secret_scan_range.sh` pins its
fallback base to.

Alerts from GitHub's scanner appear under the repository's Security tab. The
2026-08-06 retired key was scrubbed from history on 2026-10-20, so it should
no longer be flagged; if an alert for it was raised before the rewrite, close
it as "revoked" with a link to [api-key-rotation.md](api-key-rotation.md).

## Remove master

`master` is a protected leftover from before the default branch was `main`,
still present on 2026-10-22. On 2026-10-19 it was 1,239 commits behind
`main` (1,258 on 2026-10-22) and carried 9 commits that never reached
`main`; the first command below lists those commits, and
`gh api repos/agentmiddleware/agent-middleware-api/compare/main...master --jq '{ahead_by, behind_by}'`
gives the current counts.
Protected branches cannot be deleted through the branch list, so:

```bash
gh api repos/agentmiddleware/agent-middleware-api/compare/main...master \
  --jq '.commits[] | "\(.sha[0:8]) \(.commit.message | split("\n")[0])"'   # see the 9 commits
gh api -X DELETE repos/agentmiddleware/agent-middleware-api/branches/master/protection
gh api -X DELETE repos/agentmiddleware/agent-middleware-api/git/refs/heads/master
```

`failure-lab.yml` still lists `master` in its triggers; remove it in the same
change that deletes the branch so the workflow does not reference a branch
that no longer exists.

## Organization settings

Everything here is Organization → Settings. The organization-level pages
are not readable or writable through the repository-scoped token this
document was produced with, so it is a checklist, not a script; the
`main-protect` ruleset's rules are the one item visible from the repository
side.

| Page | Setting | Target | Why |
|---|---|---|---|
| Authentication security | Require two-factor authentication for everyone | On | One compromised password is the whole organization |
| Member privileges | Base permissions | Read | New members should not get write everywhere by default |
| Member privileges | Repository creation | Owners only (uncheck public and private for members) | Keeps the repository list deliberate |
| Member privileges | Repository forking | Off for private repositories | Only `agent-middleware-public` is still private; public repositories can always be forked |
| Actions → General | Policies | "Allow agentmiddleware, and select non-agentmiddleware, actions and reusable workflows", with "Allow actions created by GitHub" and "Allow actions by Marketplace verified creators" | Every workflow already pins actions to a commit SHA and the nine actions in use are all `actions/*` or `docker/*`, so nothing in use would be blocked; this stops a future workflow from pulling an action from an unvetted third party (pinning itself is a review rule, not something this policy enforces) |
| Actions → General | Workflow permissions | "Read repository contents and packages permissions"; uncheck "Allow GitHub Actions to create and approve pull requests" | Workflows that need more declare it in their `permissions:` block, as they already do |
| Actions → General | Fork pull request workflows | "Require approval for all external contributors" | Now live: every public repository accepts fork pull requests, and under GitHub's default (approval only for first-time contributors) a fork's workflow run from anyone with a previously merged pull request would start on its own |
| Code security → Configurations | Apply "GitHub recommended" to all repositories, and set it as the default for new repositories | Dependabot alerts, security updates, secret scanning and push protection | One place instead of seven repository pages; also covers the one repository still private |
| Code security → Global settings | Private vulnerability reporting for new public repositories | On | `SECURITY.md` tells reporters to open a private advisory; that only works for non-collaborators when this is on. Already on for `agent-middleware-api` |
| Billing and licensing | Actions budget and alert | A small budget with an alert, no hard stop | No longer the block for standard runners on public repositories; still what would bite if a private repository or larger runner is used later |
| Repositories → Rulesets | `main-protect` (exists since 2026-10-20) | Keep. If it is meant to cover every repository, say so in its repository targets; the required status checks can move there from the classic rule later | One rule for every default branch beats a classic rule per repository |
| Profile | Verified domain | Add `agentmiddleware.dev` (the repository homepage and product site; `api.thisisatest.tech` is only the API host) | Shows the "verified" badge next to the organization |

## Repositories

Run `python scripts/github_repo_settings.py --repo agentmiddleware/<name>` on
each. For a repository without a branch rule, pass `--required-check` once
per check its CI reports, or leave it empty to create the rule with no
required status checks (a pull request with 0 approvals, conversation
resolution, admins included, no force push or deletion).

| Repository | Visibility (2026-10-22) | Notes |
|---|---|---|
| `agent-middleware-api` | Public | This document. Recorded archived on 2026-10-20, writable again by 2026-10-21, read-only again after the last merge on 2026-10-22 and writable from about 21:35 UTC that day; the #850 banner announces the archive the maintainer intends once the open site pull requests land (see the top of this document). Description fixed |
| `agent-middleware` | Public | Where development continues, per this repository's README banner. 45 open issues on 2026-10-20 |
| `.github` | Public | Organization profile README, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md`, and a `dependabot.yml` with a weekly `github-actions` entry (no workflows yet, so nothing to pin) |
| `agent-middleware-public` | **Private** | Still the only private one, and the one whose name says public. Description said "private staging repo" on 2026-10-20. Flip it, rename it or archive it |
| `agent-middleware-spec` | Public | Its README gained an archive banner pointing at `agent-middleware` on 2026-10-22 06:11 UTC (its pull request 4), so it was writable until then; whether it is archived now is not readable from here. `agent-middleware/spec` carries a diverged copy of its `spec/` directory (of the seven shared files only `test-vectors/keys.json` is identical) |
| `amw-demo` | Public | Description read "private until approved" on 2026-10-20 and has not been re-read from here. Security-tab check once |
| `amw-paypal-agent-demo` | Public | Same Security-tab check |

## Stale references still in the tree

Links to the old personal namespace are fixed on this branch:
`.github/ISSUE_TEMPLATE/config.yml` (security-advisory link), `README.md`
(CI badge and clone URL), `TROUBLESHOOTING.md` (bug-report link),
`FINAL_SUMMARY.md` (a pull-request URL; a quoted task prompt on its line 21
still spells the old slug), `app/main.py` (the OpenAPI license URL, with
`docs/openapi.json` regenerated), `b2a_sdk/README.md`, the four framework
READMEs and the three wrapper READMEs that carried the old clone URL (the
CrewAI wrapper's did not), and `docs/GAP_CLOSURE_PLAN.md`,
`docs/agentmarket-listing.md`, `docs/agentmarket-submission.md`,
`docs/awi-adoption-guide.md`, `docs/constant-test-loop.md` and
`docs/deploy-railway.md`. That is 24 `github.com/PetrefiedThunder` URLs in
18 files, plus bare slugs in the last two. GitHub redirects the old URLs, so
nothing was broken; they were wrong in the way a security questionnaire
notices. 661 old-namespace URLs in 49 files remain at this branch's head,
nearly all inside dated records kept as written (`docs/qa/`,
`docs/issue-resolution-2026-10-02/`), plus one each in `LICENSING.md` (part
of the license-document drift above), `tests/test_site_agent_interface.py`
and `server.json`. One is deliberately left:

- `server.json` names the MCP Registry entry `io.github.PetrefiedThunder/...`
  and gives `https://github.com/PetrefiedThunder/agent-middleware-api` as its
  `repository.url`. That is the registry identity the publisher authenticated
  as; changing it is a registry re-submission, not a link fix.

## What this document does not do

- It never deletes anything by itself. Both scripts are dry runs unless
  `--apply` is passed, and the branch cleanup only ever deletes branches with
  zero commits that are not already on `main`.
- It does not change the required-check list. That list is owned by
  [trust-release-gate-branch-protection.md](trust-release-gate-branch-protection.md)
  and the script copies whatever is live.
- It changes `ci.yml` only in a comment (the note above the `secret_scan`
  job's "Scan commit range" step); no job, step or trigger changes. The
  per-push cost reduction above is a separate, reviewable change.
- The one runtime change on this branch is the SQLite connection factory in
  `app/db/database.py` (see the `test (3.11)` row of the audit table). It
  applies to SQLite URLs only, which this project uses for local and test
  databases; PostgreSQL is untouched.
