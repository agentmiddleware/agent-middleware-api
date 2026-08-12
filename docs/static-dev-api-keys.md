# Static Development / Training API Keys

Stable, non-rotating API keys for local testing, development, and training
material. This is the companion to `docs/api-key-rotation.md`, which covers
the rotated `amw_live_` bootstrap keys in `VALID_API_KEYS`; this document
covers the `amw_dev_` keys in `STATIC_DEV_API_KEYS`, which are deliberately
**exempt from rotation**.

## Why a separate key class

Rotation is the right posture for anything that can touch production, but it
is actively hostile to development and training workflows: every rotation
breaks recorded demos, notebooks, onboarding docs, local `.env` files, and
test fixtures that embedded the old key. The fix is not to stop rotating the
live keys — it is a key class whose *only* power is local, so it never needs
rotating in the first place:

- **Static by design.** Nothing rotates, expires, or revokes an `amw_dev_`
  key. Once generated, it keeps working for the lifetime of your local
  setup, so training material stays reproducible.
- **Worthless outside local.** Two independent layers enforce this:
  1. `app.core.trust_mode.validate_trust_mode_guardrails` refuses to boot a
     production-like deployment (`production`, `staging`, `preview`, …) when
     `STATIC_DEV_API_KEYS` is set at all.
  2. The auth path (`app.core.auth.get_auth_context`) ignores static dev
     keys whenever `ENVIRONMENT` is production-like, even if the guardrail
     were somehow bypassed.
  A leaked dev key therefore compromises nothing that matters — which is
  exactly why it is allowed to be static.
- **Never confusable with a live key.** Static dev keys must carry the
  `amw_dev_` prefix; entries without it are ignored by the auth path. A
  rotated `amw_live_` bootstrap key pasted into `STATIC_DEV_API_KEYS` never
  authenticates, and the prefix keeps dev keys greppable for secret
  scanners.

## Setup

1. **Generate** (never hand-write key material):

   ```bash
   python scripts/generate_static_dev_keys.py --count 2
   ```

2. **Configure** your local `.env` (see `.env.example`):

   ```bash
   ENVIRONMENT=local
   STATIC_DEV_API_KEYS=amw_dev_...,amw_dev_...
   ```

3. **Use** the key exactly like any other API key (shown via an env var —
   keeping the literal out of shell history and scanner reports):

   ```bash
   export STATIC_DEV_KEY=amw_dev_...   # one of the generated values
   curl -H "X-API-Key: $STATIC_DEV_KEY" http://localhost:8000/v1/audit/summary
   ```

## What a static dev key can do

In a local-compatible environment (`local`, `dev`, `development`, `test`,
`testing`, `ci`, `localhost`, or unset), a static dev key authenticates as a
**bootstrap admin** — the same power as a `VALID_API_KEYS` entry: it passes
`require_bootstrap_admin()`, can read the audit plane, mint wallets, and
create DB-backed wallet keys. Audit records distinguish it with
`auth_source="static-dev"` so local traces show which key class acted.

In a production-like environment it does nothing: the server refuses to
boot with the variable set, and the auth path would not honor the key even
if it did.

## Rules

- **Never** put an `amw_dev_` key in `VALID_API_KEYS`, and never "promote" a
  dev key to production use. Production keys come from
  `scripts/rotate_api_keys.py generate` and live in the host secret manager.
- **Never** set `STATIC_DEV_API_KEYS` on a shared or hosted deployment.
  Production-like environments fail startup on it by design; local-shaped
  shared instances (e.g. a team demo box) should use `VALID_API_KEYS` with
  rotation instead, because anything shared is leakable and anything
  leakable must be rotatable.
- Committing a dev key to a **private** training doc or local fixture is the
  intended use. Still keep them out of the public repo — greppable
  `amw_dev_` strings in public history invite copy-paste confusion even
  though the keys hold no production power.

## Relationship to the rotation runbook

`docs/api-key-rotation.md` and its incident table apply **only** to
`VALID_API_KEYS` / `amw_live_` keys and DB-backed wallet keys. Static dev
keys are out of scope there on purpose: the runbook's threat model (a leaked
key is a full-control compromise) does not apply to a key class that no
production deployment will ever accept.
