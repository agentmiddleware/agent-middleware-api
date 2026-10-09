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
| 2026-08-06 | `agent-middleware-secret-99` | Hardcoded in `scripts/stress_test_live.py`, reachable on public `main`. Removed from HEAD in #201. **Still reachable from `main`'s own history** — see the correction below | 2026-08-07: `VALID_API_KEYS` fully replaced on Railway and cutover completed via dashboard Redeploy of the last good deployment (variable-triggered rebuilds were crash-looping on the stale `master` trigger — see warning below). Verified with `rotate_api_keys.py verify`: retired key rejected (403), replacement accepted (200) |

### Correction (2026-09-19): the key is still reachable from `main`

An earlier version of this record, and the scope note in `.gitleaks.toml`,
said `main`'s flattened history no longer contained the retired key and that
pruning stale unmerged branches would remove the reachable copies. **Both
claims were wrong**, and the second one would have made a repository-visibility
change look safer than it was. Verified on 2026-09-19 against `origin/main`:

```console
$ git merge-base --is-ancestor 9e45009 origin/main && echo reachable
reachable
$ git log origin/main --oneline -S'agent-middleware-secret-99' | wc -l
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
