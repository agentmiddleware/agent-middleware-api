# Environment API Key Rotation

Runbook for rotating the bootstrap-admin keys in `VALID_API_KEYS`. This is
the companion to `docs/key-management.md`, which covers the Ed25519
trust-plane signing key; this document covers the env-based API keys that
`app/core/auth.py` treats as bootstrap admins.

**Out of scope:** the static `amw_dev_` development/training keys in
`STATIC_DEV_API_KEYS` are deliberately never rotated. They authenticate
only in local-compatible environments and a production-like deployment
refuses to boot with them set, so the leak-means-compromise threat model
below does not apply to them. See `docs/static-dev-api-keys.md`.

## Why these keys matter

Any key listed in `VALID_API_KEYS` authenticates as a **bootstrap admin**:
it passes `require_bootstrap_admin()`, can read the full audit plane, mint
wallets, and create DB-backed wallet keys. A leak of one env key is
therefore a full-control compromise of the API surface, and the only
remediation is rotation at the host — deleting the key from the repo
removes it from neither git history nor existing clones.

## Incident record

| Date | Key | Exposure | Action |
| --- | --- | --- | --- |
| 2026-08-06 (Pacific; committed 2026-08-04, discovered and removed 2026-08-07 05:45 to 06:04 UTC) | `***REMOVED***` | Hardcoded in `scripts/stress_test_live.py`, reachable on `main`, which was public at the time. Removed from HEAD in #201; still reachable from `main`'s history until the 2026-10-20 rewrite (see the two notes below). The Key column shows `***REMOVED***` because the rewrite replaced the value everywhere in the repository, this table included | 2026-08-07: `VALID_API_KEYS` fully replaced on Railway and cutover completed via dashboard Redeploy of the last good deployment (variable-triggered rebuilds were crash-looping on the stale `master` trigger; the note under step 2 of the rotation procedure records that workaround as historical). Verified with `rotate_api_keys.py verify`: retired key rejected (403), replacement accepted (200) |

### Correction (2026-09-19): the key is still reachable from `main`

> Historical. The claims in this section were true on 2026-09-19 and stopped
> being true with the 2026-10-20 rewrite described in the next section. The
> section is kept unchanged as the record, except that the rewrite replaced
> the key's value inside it with `***REMOVED***`.

An earlier version of this record, and the scope note in `.gitleaks.toml`,
said `main`'s flattened history no longer contained the retired key and that
pruning stale unmerged branches would remove the reachable copies. **Both
claims were wrong**, and the second one would have made a repository-visibility
change look safer than it was. Verified on 2026-09-19 against `origin/main`:

```console
$ git merge-base --is-ancestor 9e45009 origin/main && echo reachable
reachable
$ git log origin/main --oneline -S'***REMOVED***' | wc -l
3
```

The flattening did not remove the blob from `main`'s ancestry: commit
`9e45009` is an ancestor of `origin/main`, and the value is recoverable from a
plain clone with one `git log -S`. It is additionally reachable from 155 refs
in total, so branch pruning alone was never sufficient.

What this does and does not mean:

- **It does not change the remediation.** Rotation was and is the only real
  fix, and it completed on 2026-08-07 — the retired key is dead at the
  provider and `rotate_api_keys.py verify` confirms it is refused (403).
  A dead credential becoming publicly readable costs nothing.
- **It does change what to claim.** Do not tell a reviewer, a design partner,
  or a security questionnaire that the leak is gone from history. It is not.
  The honest statement is: leaked, rotated within a day, verified dead, and
  still present in history because rewriting 1,280 commits across 155 refs to
  hide a dead key is not worth breaking every clone and fork.
- **History rewriting would not even be sufficient.** This table names the
  retired key in plaintext on purpose, so the value stays published in `main`'s
  tree regardless of what its history contains. That is a deliberate choice —
  an incident record that redacts the incident is not evidence — but it means
  purging the blob would buy nothing.

Pruning the stale branches is still worth doing before the repository is made
public, for signal rather than secrecy: 200 branches, most of them abandoned
agent sessions, is not what a reader should find in a project whose
credibility is the product.

### Update (2026-10-20): the history was rewritten after all

On 2026-10-20 (22:19 UTC) the maintainer force-pushed a rewrite of the whole
repository, every branch included, in which every commit SHA changed except
the first three commits of 2026-02-23, which were already identical. It
replaces the retired key's value with the literal `***REMOVED***` wherever it
appeared, including in this table and in the console transcript above. Verified on 2026-10-22 on
a fresh clone:

- `git cat-file -t 9e45009` reports "Not a valid object name": the commit the
  correction cites is no longer reachable from any branch or tag. GitHub
  still serves it by its full SHA (the commits API returned
  `9e45009ce010f6d9d4449bc94445a6bfdd5ec06b`, original value included, on
  2026-10-22) until it is garbage-collected or GitHub Support purges it; ask
  Support for the purge if that matters.
- A full-history gitleaks scan (`gitleaks detect --log-opts=--all` under
  `.gitleaks.toml`, every branch, 1,410 commits) reports nothing outside the
  allowlist. Under the previous allowlist it reported three findings of two
  kinds: the `***REMOVED***` marker itself, in the 2026-08-04 commit of
  `scripts/stress_test_live.py`, and (twice) a synthetic
  `amw_demo_secret_value` in `site/test_demo_key.mjs` on the unmerged
  `devops/demo-key-utm` branch; both kinds are allowlisted as non-secrets.
- `scripts/secret_scan_range.sh` now pins the `main` tip that scan covered
  (`9289867`) as its verified-clean base; the previous pin (`dd16051`) is no
  longer in the repository's history.

What this changes in what to claim: the value is no longer reachable from
this repository's branches or tags. It is still served by GitHub by commit
SHA until garbage collection or a Support purge, it is quoted verbatim in the
description of pull request 448, it is still in every clone taken before
2026-10-20 (the repository has no forks as of 2026-10-22), and it was
published in plaintext in this file from 2026-08-07 (06:42 UTC, #202) until
the rewrite, so treat it as public knowledge. The remediation is unchanged:
the key was rotated on 2026-08-07, is dead at the provider, and
`rotate_api_keys.py verify` confirms it is refused. The honest statement is
now: leaked (on `main` from 2026-08-04), rotated within a day of discovery
(2026-08-07), verified dead, removed from the repository's reachable history
on 2026-10-20, and still present in pre-rewrite copies, in GitHub's dangling
pre-rewrite objects until those are purged, and in the text of pull request
448.

## Rotation procedure (Railway)

Before changing keys, qualify the exact-SHA release and a schema-compatible
recovery image under [the current rollout](schema-042-rollout.md) and the
[operator release procedure](deploy-railway.md#canonical-deploy-path).

1. **Generate replacements** (never reuse or hand-write keys):

   ```bash
   python scripts/rotate_api_keys.py generate --count 2
   ```

2. **Set the new list** on the `api-service` service in the Railway
   dashboard (project `agent-middleware-api` → `api-service` → Variables):
   replace `VALID_API_KEYS` with the comma-separated new keys. Do not
   append — the point of rotation is that the old list dies. Railway
   redeploys the service on variable change; `get_settings()` is cached
   per process, so the new list only takes effect with that restart.

   > A variable change is live only after a healthy deployment cuts over.
   > Follow the [canonical operator release](deploy-railway.md#canonical-deploy-path)
   > from a clean exact-SHA checkout and its stamped release context, resolving
   > the new variables into that deployment. Qualify a schema-compatible release
   > or recovery image under [the current rollback boundary](schema-042-rollout.md)
   > before changing the key list. A restart alone can reuse an old environment
   > snapshot. The 2026-08-07 stale-source/redeploy workaround in the incident
   > table is historical and superseded by this release procedure.

3. **Verify** once the deploy is live:

   ```bash
   export AGENT_MIDDLEWARE_API_URL=https://api.thisisatest.tech
   export OLD_API_KEY=<retired key>
   export NEW_API_KEY=<replacement key>
   python scripts/rotate_api_keys.py verify
   ```

   The verifier asserts the retired key gets 401/403 and the replacement
   gets 200 on `GET /v1/audit/summary` (read-only, admin-gated). Non-zero
   exit means the rotation is NOT complete — stop and investigate.

4. **Distribute** the new key to legitimate operators out of band. Update
   any local `.env` files and CI secret stores that carry a copy
   (currently none — CI holds only `RAILWAY_TOKEN`).

## Post-rotation audit

An env key is a bootstrap admin, so assume a leaked one was used until the
audit trail says otherwise:

- `GET /v1/audit/summary` and `GET /v1/audit/events` — look for wallet
  creation, permit issuance, or governed invokes you don't recognize in
  the exposure window.
- Review DB-backed keys (`APIKeyModel`) created during the window: a
  bootstrap admin can mint wallet keys that survive env-key rotation.
  Rotate or revoke any that cannot be attributed — `POST
  /v1/api-keys/rotate` per key, or `POST /v1/api-keys/emergency-revoke`
  to kill every key on a wallet at once.
- Replacement keys never widen authority: a rotated key inherits the old
  key's expiry and *remaining* `max_uses` budget (rotating a use-budgeted
  key requires `revoke_old: true`, otherwise the remaining budget would
  exist twice), and an emergency replacement takes both its bounds from
  one donor credential. For a wallet-scoped caller the donor is the
  caller's own key (exhausted included, so a key spending its final use on
  the emergency call cannot mint itself an unbounded replacement); if that
  key is no longer a non-expired active key, every key is still revoked but
  no replacement is minted. For a bootstrap admin the donor is the active,
  non-expired key with the largest remaining budget, tie-broken by latest
  expiry. A wallet key that is itself bounded
  (it has a `max_uses` budget or an expiry), or a JWT derived from one,
  cannot mint fresh keys at all: `POST /v1/api-keys`, and `POST
  /v1/api-keys/rotate` without `key_id` or with any `key_id` other than its
  own, answer 403 `bounded_key_cannot_mint`, because the new key would take
  only the bounds its request names, or those of a looser sibling key it
  never held. Such a key can still rotate itself (with its `key_id`,
  plus `revoke_old: true` when it has a `max_uses` budget), which carries
  its expiry and remaining budget over. To issue a
  key with fresh bounds, mint one explicitly with `POST /v1/api-keys` as a
  bootstrap admin or with an unbounded wallet key.
- The trust-plane signing key (`TRUST_SIGNING_PRIVATE_KEY_B64`) is a
  separate secret that has never been committed; it does not need rotation
  for an API-key leak. If you suspect it anyway, follow the compromise
  flow in `docs/key-management.md`.

## What prevents recurrence

- CI secret scanning (`.gitleaks.toml`) fails the build on any
  credential-named variable bound to a string literal, the exact shape of
  the 2026-08-06 leak.
- `scripts/stress_test_live.py` and `scripts/trust_plane_conformance.py`
  exit non-zero when `AGENT_MIDDLEWARE_API_KEY` is unset instead of
  falling back to a default.
- Keys generated by `scripts/rotate_api_keys.py` carry the `amw_live_`
  prefix so a future leak is greppable and matches vendor-style secret
  scanners, unlike the dictionary-word key that evaded entropy rules.
