# Deployment verification checklist

**Audience:** whoever is about to say "that fix is live".
**Rule:** source tests prove the repository. Only the steps below prove the
deployment. A green suite on `main` is not a statement about what
`https://api.thisisatest.tech` is running.

## Why this exists — the 2026-09-05 observation

Read-only public `GET`s, no credentials, no mutation:

| Surface | Observed |
|---|---|
| `GET /health` → `commit_sha` | `2880ca706d2f4779876097e9414b6f1fab691a3e` |
| `GET /health/dependencies` → `build_provenance` | `stamped` |
| `GET /health/dependencies` → `version` / `environment` / `production_like` | `1.3.0` / `production` / `true` |
| Repository `main` reviewed | `c6b05343c164f9e5a49ee4a54f7888df76a46e04` |
| `git log --oneline 2880ca7..c6b0534` | 11 commits |

How to read it. `build_provenance: "stamped"` means the SHA was read from the
`.build_commit_sha` file baked into the image by the documented `railway up`
release path ([`app/core/build_metadata.py`](../app/core/build_metadata.py)),
and that path refuses to read the mutable `BUILD_COMMIT_SHA` service variable
at all. The reported SHA is therefore trustworthy. The deployment is not
misreporting itself; it is **behind `main`**. As of that reading, the eleven
later commits — among them the dispatch-integrity hardening in #391 and #392 —
were not running in production, and nothing in this repository can make that
claim true except a release performed under
[`deploy-railway.md`](deploy-railway.md). This checklist does not deploy.

The liveness probe now carries the same `build_provenance` field as
`/health/dependencies`, so the cheapest public probe answers "is this SHA
trustworthy?" on its own. Before that change a bare SHA on `/health` could not
be told apart from a stale stamp without the second request.

## Before the release

1. **Pin the intended commit** on a clean, detached checkout:

   ```bash
   git status --porcelain            # must print nothing
   DEPLOY_SHA="$(git rev-parse HEAD)"
   git merge-base --is-ancestor "$DEPLOY_SHA" origin/main && echo on-main
   ```

2. **Stamp the release context** and prove the stamp is the intended commit
   ([`scripts/prepare_railway_release.py`](../scripts/prepare_railway_release.py)):

   ```bash
   test "$(cat "$RELEASE_CONTEXT/.build_commit_sha")" = "$DEPLOY_SHA"
   ```

3. **Validate the customer manifest** against that tree without touching the
   live service:

   ```bash
   python3 scripts/railway_preflight.py --manifest-only --manifest "$MANIFEST"
   ```

## After the release

4. **Read the live provenance** and compare every field, not just the SHA:

   ```bash
   curl -sS "$API_URL/health/dependencies" \
     | python3 -c 'import json,sys; b=json.load(sys.stdin); print({k: b.get(k) for k in ("status","version","environment","production_like","commit_sha","build_provenance")})'
   ```

   | Field | Required value |
   |---|---|
   | `commit_sha` | exactly `$DEPLOY_SHA`, all 40 characters |
   | `build_provenance` | `stamped` |
   | `version` | the `APP_VERSION` the release notes name |
   | `environment` / `production_like` | `production` / `true` |
   | `status` | `healthy` |

5. **Run the strict live preflight** so the comparison is mechanical and
   fails closed on a mismatch or on any provenance other than `stamped`:

   ```bash
   python3 scripts/railway_preflight.py --live --strict --url "$API_URL" \
     --manifest "$MANIFEST"          # or: --expected-commit-sha "$DEPLOY_SHA"
   ```

6. **List what is still not live.** Any output means those commits are not in
   production, whatever the test suite says about them:

   ```bash
   LIVE_SHA="$(curl -sS "$API_URL/health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["commit_sha"])')"
   git fetch origin main
   git log --oneline "$LIVE_SHA..origin/main"
   ```

7. **Before claiming a specific fix is live**, prove the fix commit is an
   ancestor of the live SHA:

   ```bash
   git merge-base --is-ancestor "$FIX_SHA" "$LIVE_SHA" && echo live || echo NOT-live
   ```

   Cite both SHAs in the claim. "Merged to `main`" and "live" are different
   statements.

## Reading `build_provenance`

| Value | Meaning | Action |
|---|---|---|
| `stamped` | Baked stamp present; agrees with Railway's SHA when Railway supplies one. The only value the documented release path can produce. | Trust `commit_sha`; compare it with `main` (step 6). |
| `mismatch` | Baked stamp and Railway's SHA are both valid and disagree. The image was built from one commit and deployed as another. | Stop promotion. Rebuild through the documented path. |
| `control_plane_only` | No valid baked stamp; the SHA comes only from Railway's deployment metadata (a GitHub-triggered rebuild, not an operator release). | Stop promotion. The image did not come through the release path. |
| `unstamped` | Neither source yields a valid SHA. | Stop promotion. Provenance unknown. |

## Do not

- Do not redeploy to make the hashes match. A deployment is a release
  decision with its own gate; a hash comparison is only evidence that the
  decision is pending.
- Do not describe a passing local, SQLite, or CI run as a production
  guarantee. The reviewed commit can be fully green and still not be the
  commit that is serving traffic.
- Do not read `BUILD_COMMIT_SHA` or `COMMIT_SHA` service variables as
  provenance. The application deliberately ignores them
  ([`tests/test_stale_commit_sha_prevention.py`](../tests/test_stale_commit_sha_prevention.py)).
