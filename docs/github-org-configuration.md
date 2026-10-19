# GitHub organization configuration

How the `agentmiddleware` GitHub organization and its repositories are meant to
be configured, what was actually configured when this was audited, and the
exact clicks or commands that close each gap. Written for one maintainer with
admin on everything and no second reviewer.

Audit date: 2026-10-19. Re-run the two scripts below to refresh the repository
rows; the organization rows can only be read in the GitHub UI.

## Do these first, in this order

1. **Unblock GitHub Actions on the organization account.** Pushes to `main`
   since 2026-10-17 produced no CI run, only a `startup_failure` run with no
   workflow name. `railway-deploy.yml` refuses to prepare a release for a
   commit without a green push run, so `main` is unreleasable until this is
   fixed. See [Actions budget](#actions-budget) for the cause and the choice
   to make.
2. **Apply the repository settings** from a machine where `gh auth status`
   shows your account:

   ```bash
   python scripts/github_repo_settings.py          # dry run, shows drift
   python scripts/github_repo_settings.py --apply
   ```

   This turns on "delete branch on merge" and the pull-request requirement on
   `main` (0 approvals, see below), and tries to enable secret scanning.
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
| Repositories | 6: `agent-middleware-api` (private), `agent-middleware` (private, 54 open issues), `agent-middleware-public` (private despite the name), `agent-middleware-spec` (public), `amw-demo` (public), `amw-paypal-agent-demo` (public) | Decide which repository is the product repository; see [Repositories](#repositories) |
| Actions runs on `main` pushes | `startup_failure`, no workflow name, since 2026-10-17 20:19 UTC. Scheduled and Dependabot runs still succeed | Green push run on every `main` commit |
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
| Secret scanning, push protection | **Disabled** | Enabled where the plan allows; otherwise the gitleaks pre-commit hook plus the CI `secret_scan` job | `github_repo_settings.py --apply`, see [Secret scanning](#secret-scanning) |
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
- By 2026-10-19 07:30 UTC the block had cleared: the pull request that adds
  this document started all 20 checks normally. The lock is intermittent,
  which is the point: it returns whenever the month's minutes run out.

### Why it keeps happening

Private repositories pay for Actions minutes. This repository's CI is heavy by
design (every push runs the full release gate), and every Dependabot pull
request runs it too.

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

### The choice

Pick one. The first is the only option that costs nothing and removes the
problem rather than budgeting for it.

1. **Make `agent-middleware-api` public.** Public repositories get unlimited
   Actions minutes on standard runners, free secret scanning, free push
   protection, and private vulnerability reporting. The repository already
   carries the BUSL license, a `SECURITY.md`, and tests that assert the public
   surfaces link to `github.com/agentmiddleware/agent-middleware-api`, so this
   was the plan. Before flipping: run
   `gitleaks detect --config .gitleaks.toml --log-opts=--all` on a fresh clone
   and confirm the only findings are the allowlisted ones recorded in
   `.gitleaks.toml` (the 2026-08-06 key was rotated dead the next day and is
   deliberately published in [api-key-rotation.md](api-key-rotation.md)).
   Visibility: repository Settings → General → Danger Zone → Change
   visibility.
2. **Set a spending limit and leave it private.** Organization Settings →
   Billing and licensing → Budgets and alerts: create an Actions budget with
   "stop usage when reached" off (or a limit you can afford) and an alert at
   75%. A limit of $0, the default, is what produces the lock. Check the
   current month under Billing → Usage, product "Actions".
3. **Reduce the bill per push** (works with either of the above). The
   non-required legs `test (3.13)`, `python_sdk (3.13)` and the four
   `wrapper_unit` jobs are about 15 minutes of each run; gating them on
   `github.event_name == 'push'` keeps them on `main` and drops them from pull
   requests. The two required `test` legs are the other 30 minutes and would
   need test parallelization to shrink. Not done on this branch: it changes
   what runs on pull requests and belongs in its own reviewed change.

Whichever you pick, after the block clears, `main` still has no green push
run for `railway-deploy.yml` to gate on. `ci.yml` has no manual trigger, so
merge the next pull request (this one will do) and confirm its push run is
green before preparing a release.

## Secret scanning

GitHub's own secret scanning and push protection are off on this repository.
On a private repository they require the Secret Protection add-on; on a public
one they are free. `github_repo_settings.py --apply` tries to enable both and
prints GitHub's refusal if the plan does not allow it.

Until then the controls are:

- `.pre-commit-config.yaml` now runs gitleaks on the staged diff with the same
  `.gitleaks.toml` and the same gitleaks release as CI. Install once with
  `pre-commit install`. This is the local equivalent of push protection.
- The CI `secret_scan` job scans the working tree and the pushed commit range
  and is a required check on `main`.

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
| Member privileges | Repository forking | Off for private repositories | Matches `allow_forking: false` already set on the private repositories |
| Actions → General | Policies | "Allow agentmiddleware, and select non-agentmiddleware, actions and reusable workflows", with "Allow actions created by GitHub" and "Allow actions by Marketplace verified creators" | Every workflow already pins actions to a commit SHA; this stops a future workflow from pulling an unpinned third-party action |
| Actions → General | Workflow permissions | "Read repository contents and packages permissions"; uncheck "Allow GitHub Actions to create and approve pull requests" | Workflows that need more declare it in their `permissions:` block, as they already do |
| Actions → General | Fork pull request workflows | "Require approval for all external contributors" | Relevant the day a repository is public |
| Code security → Configurations | Apply "GitHub recommended" to all repositories, and set it as the default for new repositories | Dependabot alerts, security updates, secret scanning and push protection where the plan allows | One place instead of six repository pages |
| Code security → Global settings | Private vulnerability reporting for new public repositories | On | `SECURITY.md` tells reporters to open a private advisory; that only works for non-collaborators when this is on |
| Billing and licensing | Actions budget and alert | See [Actions budget](#actions-budget) | The current block |
| Profile | Verified domain | Add `thisisatest.tech` (the repository homepage) | Shows the "verified" badge next to the organization |

## Repositories

Run `python scripts/github_repo_settings.py --repo agentmiddleware/<name>` on
each. For a repository without a branch rule, pass `--required-check` once
per check its CI reports, or leave it empty to require only a pull request.

| Repository | Visibility | Notes |
|---|---|---|
| `agent-middleware-api` | Private | This document |
| `agent-middleware` | Private | 54 open issues. Created 2026-10-04 as "pre-release, private". If it is the successor of this repository, say so in both READMEs; if not, archive one of them |
| `agent-middleware-public` | Private | The name says public and the description says "private staging repo". Rename or flip visibility so the name is true |
| `agent-middleware-spec` | Public | Enable secret scanning, push protection and private vulnerability reporting; all free on a public repository |
| `amw-demo`, `amw-paypal-agent-demo` | Public | Same as the spec repository |

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
