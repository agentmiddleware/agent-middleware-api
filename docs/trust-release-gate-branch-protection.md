# Trust release gate as branch protection

The trust plane's differentiator is that its claims are executable. That is only
worth something if a claim cannot regress into `main` unproven. This document
specifies how to make the repository **gate-first, execute-second**: no change
reaches `main` until the release gate has run and passed against it.

The gate itself is `scripts/trust_release_gate.sh` (`make trust-release-gate`).
It runs, in order:

1. the focused trust-plane pytest suite, including
   `tests/test_adversarial_five_claims.py` — the in-process adversarial pass
   over the five claims;
2. the trust-core coverage gate (`scripts/trust_coverage_gate.sh`, an 80% floor
   across the named trust-plane control modules);
3. the trust-plane demo proof (`scripts/demo_trust_plane.py --assert`);
4. discovery-drift tests;
5. committed-OpenAPI parity (`scripts/export_openapi.py --check`);
6. simulation-inventory parity (`scripts/generate_sim_inventory.py --check`).

CI runs the same script as a dedicated job named **`trust_release_gate`**
(`.github/workflows/ci.yml`), so branch protection can require one check that
maps exactly to the operator gate.

## Required status checks

Mark every one of these as **required** on `main`. Matrix jobs expose one check
per matrix value; the name in parentheses is the exact check name GitHub
reports.

| Check | Job | What a failure means |
|---|---|---|
| `trust_release_gate` | `trust_release_gate` | A trust claim, coverage floor, demo proof, discovery contract, OpenAPI parity, or sim-inventory parity regressed |
| `test (3.11)`, `test (3.12)` | `test` | Unit/integration suite or trust-primitive invariants failed |
| `python_sdk (3.10)`, `python_sdk (3.11)`, `python_sdk (3.12)` | `python_sdk` | The offline receipt verifier / SDK broke against a clean wheel |
| `postgres_trust` | `postgres_trust` | Trust loop failed against real PostgreSQL/asyncpg |
| `production_trust` | `production_trust` | Production-like trust flags failed to boot fail-closed |
| `postgres_permit_concurrency` | `postgres_permit_concurrency` | Two-process exactly-once / permit row-lock concurrency regressed |
| `secret_scan` | `secret_scan` | A credential-shaped literal reached the working tree |
| `lint` | `lint` | `ruff` or `mypy app/` failed |

`trust_release_gate` overlaps some of what `test` already runs. That redundancy
is deliberate: the single named gate is the one a reviewer looks for, and it is
the one that fails loudly and specifically when a claim regresses.

## Exact settings for `main`

Branch protection rule, `main`:

- **Require a pull request before merging** — on.
  - Require approvals: 1 (raise as the team grows).
  - Dismiss stale approvals when new commits are pushed — on.
  - Require review from Code Owners — on (`CODEOWNERS` is present).
- **Require status checks to pass before merging** — on.
  - Require branches to be up to date before merging — on. (Forces the gate to
    run against the actual merge result, not a stale base.)
  - Required checks: every row in the table above.
- **Require conversation resolution before merging** — on.
- **Do not allow bypassing the above settings** — on (applies the rule to
  admins too; this is the whole point of gate-first).
- **Restrict force pushes** — on. **Restrict deletions** — on.
- Linear history — optional; enable if the team prefers rebase-merge.

### Via the REST API

Set once, from an account with admin on the repo (requires a token with
`repo` / branch-protection admin scope):

```bash
# OWNER/REPO and the required check contexts are the only things to edit.
curl -sS -X PUT \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer <ADMIN_TOKEN>" \
  https://api.github.com/repos/OWNER/REPO/branches/main/protection \
  -d '{
    "required_status_checks": {
      "strict": true,
      "contexts": [
        "trust_release_gate",
        "test (3.11)", "test (3.12)",
        "python_sdk (3.10)", "python_sdk (3.11)", "python_sdk (3.12)",
        "postgres_trust", "production_trust", "postgres_permit_concurrency",
        "secret_scan", "lint"
      ]
    },
    "enforce_admins": true,
    "required_pull_request_reviews": {
      "dismiss_stale_reviews": true,
      "require_code_owner_reviews": true,
      "required_approving_review_count": 1
    },
    "required_conversation_resolution": true,
    "restrictions": null,
    "allow_force_pushes": false,
    "allow_deletions": false
  }'
```

Check names must match GitHub's reported contexts exactly, including the matrix
suffixes. If a job is renamed or a matrix value changes, update the required
contexts in the same PR, or protection silently stops requiring the renamed
check.

## Local equivalent, before you push

```bash
make trust-release-gate
```

Green locally is the same gate CI enforces. Run it before opening a PR so the
required check is a confirmation, not a surprise.
