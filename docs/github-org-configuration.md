# GitHub organization configuration

How the `agentmiddleware` GitHub organization and its repositories are meant to
be configured, what was actually configured when this was audited, and the
exact clicks or commands that close each gap. Written for one maintainer with
admin on everything and no second reviewer.

Audit date: 2026-10-19, updated 2026-10-20 after the repositories were made
public. Re-run the two scripts below to refresh the repository rows; the
organization rows can only be read in the GitHub UI.

## Do these first, in this order

1. **Done 2026-10-20: the repositories are public.** That removes the
   Actions minutes bill on standard runners and switched on secret scanning,
   push protection and private vulnerability reporting by itself. Two
   follow-ups: watch the push run of the next `main` merge (if the no-name
   `startup_failure` in [Actions budget](#actions-budget) recurs on a public
   repository, billing was not the cause), and fix the descriptions that
   still say "private" on public repositories (see
   [Repositories](#repositories)).
2. **Apply the repository settings** from a machine where `gh auth status`
   shows your account:

   ```bash
   python scripts/github_repo_settings.py          # dry run, shows drift
   python scripts/github_repo_settings.py --apply
   ```

   This turns on "delete branch on merge" and the pull-request requirement on
   `main` (0 approvals, see below). Secret scanning is already on.
3. **Clean up the 550 branches** once "delete branch on merge" is on, so they
   stop accumulating:

   ```bash
   python scripts/github_branch_cleanup.py                 # lists what is fully merged
   python scripts/github_branch_cleanup.py --apply         # deletes only those
   python scripts/github_branch_cleanup.py --stale-days 90 # review the rest by hand
   ```

   Dry run on 2026-10-19: 550 branches; 103 fully merged into `main` (the
   `--apply` set); 26 unmerged with no commit in 90 days (oldest from
   2026-04-17, mostly `feat/*-pg` and `codex/*` work that never landed); 45
   `backup/local-2026-10-07/*` kept by prefix; the remaining 375 are unmerged
   branches from the last 90 days, nearly all agent-generated. Those need a
   decision, not a script: either open the pull request or delete the
   branch. The 26 stale ones are the first batch to decide on.

4. **Work through the [organization settings](#organization-settings)
   table.** None of it can be scripted from a repository-scoped token.

## Audit snapshot

### Organization

| Item | Found | Target |
|---|---|---|
| Members | 1 (`PetrefiedThunder`, owner) | Same, until there is a second maintainer |
| Teams | none | A `maintainers` team as soon as a second person joins, so `CODEOWNERS` can name a team instead of a person |
| Repositories | 6. Since 2026-10-20 five are public; `agent-middleware-public` is still private. Three public repositories still describe themselves as private | Decide which repository is the product repository and fix the descriptions; see [Repositories](#repositories) |
| Actions runs on `main` pushes | `startup_failure`, no workflow name, on every `main` push from 2026-10-17 to 2026-10-19. Scheduled, Dependabot and most pull-request runs succeed | Green push run on every `main` commit; confirm on the first merge after going public |
| Two-factor requirement, base permission, Actions policies, security configuration | Not readable from here | See [Organization settings](#organization-settings) |

### `agent-middleware-api`

| Setting | Found | Target | How |
|---|---|---|---|
| `main` required status checks | 11 contexts, exactly the list in [trust-release-gate-branch-protection.md](trust-release-gate-branch-protection.md); strict (up to date) on | Keep | Already correct |
| `main` admins exempt | No (`enforce_admins` on) | Keep | Already correct |
| `main` force push / deletion | Both blocked | Keep | Already correct |
| `main` conversation resolution | Required | Keep | Already correct |
| `main` requires a pull request | **Off** | On, 0 approvals, code-owner review off | `github_repo_settings.py --apply` |
| Delete branch on merge | **Off** (why 500+ branches exist) | On | `github_repo_settings.py --apply` |
| Auto-merge, update branch | On | Keep | Already correct |
| Web commit sign-off (DCO) | On | Keep | Already correct |
| Secret scanning, push protection | Disabled while private; **enabled** (with validity checks and non-provider patterns) the moment the repository went public on 2026-10-20 | Keep | Already correct; see [Secret scanning](#secret-scanning) |
| Private vulnerability reporting | Enabled | Keep; it is what `SECURITY.md` asks reporters to use | Already correct |
| Dependabot security updates | Enabled | Keep | Already correct |
| Dependabot version updates | One pull request per package, pip and Actions only | Grouped weekly pull requests; Docker digest, SDK, wrappers and Railway IaC covered | Done in `.github/dependabot.yml` on this branch |
| Rulesets | None | None needed; the classic rule above covers `main` | – |
| `master` branch | Exists, protected, 9 commits ahead and 1,239 behind `main`, last commit 2026-05-22 | Deleted | See [Remove master](#remove-master) |
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
- Commits on 2026-10-15 are titled "retrigger checks after billing lock
  lifted"; pull request 816 (merged 2026-10-17) is titled "after billing
  lock". So the lock has happened at least twice this month.
- The workflow files did not change between the last green push run
  (`44cd144`, 2026-10-16) and the current head, which rules out a broken
  workflow file.
- The block comes and goes in windows. The same no-name `startup_failure`
  run (GitHub's placeholder when it refuses to start any workflow for an
  event) fired 139 times since 2026-09-15, clustered on 2026-10-14
  19:54 to 21:26, 2026-10-17 20:19 to 20:35, 2026-10-19 11:23 to 11:28 and
  2026-10-19 21:26 to 21:28 UTC, on push and pull-request events alike,
  including the push of every `main` commit since 2026-10-17. Between those
  windows (for example this pull request's runs on 2026-10-19 07:30 and
  2026-10-20 08:50) everything starts normally. The API does not expose the
  reason; the run page does, as a banner above the empty job list. Open the
  latest one and read it:
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
| `test (3.11)`, `test (3.12)`, `test (3.13)` | 12.5 + 17.3 + 10.3 |
| `trust_release_gate`, `postgres_permit_concurrency` | 3.7 + 3.8 |
| `postgres_trust`, `lint`, `invariant_attack_proof`, `production_trust`, `secret_scan`, `constant_test_loop` | about 1 each |
| `python_sdk` x4, `wrapper_unit` x4 | about 0.5 each |
| Job time per CI run | about 60 |
| Billed per run (each job rounds up to a whole minute) | about 75 |
| Plus `Failure Lab` (fast tier on pull requests, slow tier on `main`) and `docker-publish` | 3 to 10 |

Between 2026-10-15 and 2026-10-17 there were about 30 CI runs, which is over
2,000 billed minutes in three days. The Free plan includes 2,000 minutes a
month for private repositories; Team includes 3,000. Overage on standard
Linux runners is about $0.008 per minute, so a month at the recent cadence is
roughly 10,000 to 15,000 minutes, or $65 to $105 of overage.

### The decision

**Taken on 2026-10-20: the repository is public.** Public repositories get
unlimited Actions minutes on standard runners, free secret scanning and push
protection, and private vulnerability reporting, and GitHub switched all of
those on by itself at the flip. The repository already carried the BUSL
license, a `SECURITY.md`, and tests asserting that public surfaces link to
`github.com/agentmiddleware/agent-middleware-api`. The commit history is now
public too, including the 2026-08-06 key that was rotated dead the next day
and is deliberately published in [api-key-rotation.md](api-key-rotation.md);
every other historical finding is allowlisted synthetic material
(`.gitleaks.toml`).

The two options not taken, kept for the record:

- A spending limit on a private repository (Organization Settings → Billing
  and licensing → Budgets and alerts). A $0 limit, the default, is what
  produces the lock.
- Reducing the bill per push: the non-required legs `test (3.13)`,
  `python_sdk (3.13)` and the four `wrapper_unit` jobs are about 15 minutes of
  each run and could be gated on `github.event_name == 'push'`. No longer a
  cost question; still a wall-clock one if pull-request feedback feels slow.

`main` still has no green push run for `railway-deploy.yml` to gate on.
`ci.yml` has no manual trigger, so merge the next pull request (this one will
do) and confirm its push run is green before preparing a release.

## Secret scanning

GitHub's secret scanning, push protection, validity checks and non-provider
patterns have been on since the repository went public on 2026-10-20 (they
were off while it was private, where they need the paid Secret Protection
add-on). `github_repo_settings.py` reports them and would re-enable them if
they were ever switched off.

Three layers now cover the same risk, and all three stay:

- GitHub push protection rejects a push that contains a known provider
  secret pattern before it lands.
- `.pre-commit-config.yaml` runs gitleaks on the staged diff with the same
  `.gitleaks.toml` and the same gitleaks release as CI, which also catches the
  repository's own low-entropy patterns that GitHub does not know. Install
  once with `pre-commit install`.
- The CI `secret_scan` job scans the working tree and the pushed commit range
  and is a required check on `main`.

Alerts from GitHub's scanner appear under the repository's Security tab.
Expect the 2026-08-06 retired key to be flagged from history; close that
alert as "revoked" with a link to [api-key-rotation.md](api-key-rotation.md).

## Remove master

`master` is a protected leftover from before the default branch was `main`. It
is 1,239 commits behind and carries 9 commits that never reached `main`.
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

Everything here is Organization → Settings. None of it is readable or
writable through the repository-scoped token this document was produced
with, so it is a checklist, not a script.

| Page | Setting | Target | Why |
|---|---|---|---|
| Authentication security | Require two-factor authentication for everyone | On | One compromised password is the whole organization |
| Member privileges | Base permissions | Read | New members should not get write everywhere by default |
| Member privileges | Repository creation | Owners only (uncheck public and private for members) | Keeps the repository list deliberate |
| Member privileges | Repository forking | Off for private repositories | Only `agent-middleware-public` is still private; public repositories can always be forked |
| Actions → General | Policies | "Allow agentmiddleware, and select non-agentmiddleware, actions and reusable workflows", with "Allow actions created by GitHub" and "Allow actions by Marketplace verified creators" | Every workflow already pins actions to a commit SHA; this stops a future workflow from pulling an unpinned third-party action |
| Actions → General | Workflow permissions | "Read repository contents and packages permissions"; uncheck "Allow GitHub Actions to create and approve pull requests" | Workflows that need more declare it in their `permissions:` block, as they already do |
| Actions → General | Fork pull request workflows | "Require approval for all external contributors" | Now live: every public repository accepts fork pull requests, and a fork's workflow run would otherwise start on its own |
| Code security → Configurations | Apply "GitHub recommended" to all repositories, and set it as the default for new repositories | Dependabot alerts, security updates, secret scanning and push protection | One place instead of six repository pages; also covers the one repository still private |
| Code security → Global settings | Private vulnerability reporting for new public repositories | On | `SECURITY.md` tells reporters to open a private advisory; that only works for non-collaborators when this is on. Already on for `agent-middleware-api` |
| Billing and licensing | Actions budget and alert | A small budget with an alert, no hard stop | No longer the block for standard runners on public repositories; still what would bite if a private repository or larger runner is used later |
| Profile | Verified domain | Add `thisisatest.tech` (the repository homepage) | Shows the "verified" badge next to the organization |

## Repositories

Run `python scripts/github_repo_settings.py --repo agentmiddleware/<name>` on
each. For a repository without a branch rule, pass `--required-check` once
per check its CI reports, or leave it empty to require only a pull request.

| Repository | Visibility (2026-10-20) | Notes |
|---|---|---|
| `agent-middleware-api` | Public | This document |
| `agent-middleware` | Public | 45 open issues. Description still says "pre-release, private": fix it. If it is the successor of this repository, say so in both READMEs; if not, archive one of them |
| `agent-middleware-public` | **Private** | The only one left private, and the one whose name says public. Description still says "private staging repo". Flip it or rename it so the name is true |
| `agent-middleware-spec` | Public | Confirm secret scanning and private vulnerability reporting are on (GitHub enables them on public repositories, but check the Security tab once) |
| `amw-demo` | Public | Description still says "private until approved": fix it. Same Security-tab check |
| `amw-paypal-agent-demo` | Public | Same Security-tab check |

## Stale references still in the tree

These point at the old personal namespace. GitHub redirects them, so nothing
is broken, and they are listed here rather than changed on this branch:

- `README.md` CI badge and clone URL, `TROUBLESHOOTING.md` bug-report link,
  `docs/awi-adoption-guide.md`, `docs/agentmarket-listing.md`, the framework
  and wrapper READMEs, `b2a_sdk/README.md` release links, and the LICENSE URL
  in `app/main.py`.
- `server.json` names the MCP Registry entry `io.github.PetrefiedThunder/...`.
  That is the registry identity the publisher authenticated as; changing it is
  a registry re-submission, not a link fix. Leave it.

## What this document does not do

- It never deletes anything by itself. Both scripts are dry runs unless
  `--apply` is passed, and the branch cleanup only ever deletes branches with
  zero commits that are not already on `main`.
- It does not change the required-check list. That list is owned by
  [trust-release-gate-branch-protection.md](trust-release-gate-branch-protection.md)
  and the script copies whatever is live.
- It does not change `ci.yml`. The per-push cost reduction above is a
  separate, reviewable change.
