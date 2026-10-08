# Enterprise login runbook (Okta, Entra ID)

One-page operator guide for the enterprise IGA bridge in
`app/core/oidc_iga.py`. Read this before pitching SSO to a buyer.

## What it does

Verifies an enterprise OIDC access token (Okta `groups` claim, Entra
`roles` falling back to `groups`) against operator-pinned keys, maps the
token's groups to wallet PolicyBundles, and enforces per-group runtime
caps. There is no network key fetch: keys are pinned in config, so a
compromised IdP hostname cannot rotate keys under us. Rotation is an
explicit config change.

## Configuration

Two JSON-in-env variables. Both default to empty (layer disabled or
granting nothing). Malformed JSON fails the whole layer closed at use
time, never at import.

`IGA_TRUSTED_ISSUERS`: issuer URL to pinned verification material.

```json
{"https://example.okta.com/oauth2/default": {
  "audience": "api://agent-middleware",
  "algorithms": ["RS256"],
  "provider": "okta",
  "jwks": {"keys": []}}}
```

Rules, enforced by `app/core/oidc_iga.py`:

- `audience` is required and must match the token's audience.
- `algorithms` must be a non-empty list of names. `"none"` is never
  allowed, even if configured explicitly.
- Exactly one of `jwks` (object) or `public_key_pem` (non-empty
  string) is required. Both or neither fails closed.
- `provider` is `"okta"` or `"entra"` and optional when the issuer
  host makes it obvious (`*.okta.com`, `login.microsoftonline.com`,
  `sts.windows.net`). Custom vanity domains cannot be inferred: set
  `provider` explicitly or parsing fails closed.

`IGA_GROUP_POLICY_MAP`: group or role name to a PolicyBundle grant
with optional runtime caps.

```json
{"payments-ops": {"policy_id": "polb-...",
  "max_uses": 100,
  "velocity_window_seconds": 60, "velocity_max_calls": 10}}
```

Rules: `policy_id` is required. Caps are positive integers or null
(null means uncapped). A velocity cap needs both the window and the
limit; setting only one fails closed. Empty map grants nothing: every
enterprise principal is blocked with `iga_no_matching_role`.

## How calls authenticate (dual credential)

An enterprise Bearer token alone is not an API credential. Every
enterprise call sends both headers:

- `X-API-Key`: a normal wallet-scoped (or bootstrap) API key. This is
  what authenticates the call through the unchanged `get_auth_context`
  path.
- `Authorization: Bearer <enterprise token>`: carried as human-identity
  attribution on `AuthContext.enterprise_bearer_token` and fully
  verified (pinned key, algorithm allowlist, audience, issuer, expiry)
  at the enforcement points before any trust decision. Sent without an
  API key, it is refused with 401 exactly like any other bad Bearer token.

## Honest limits to state on a sales call

- Caps are per-instance, in process memory. They reset on restart and
  are not shared across replicas, so a fleet can exceed a stated limit
  by spreading calls. Give single-instance sizing guidance now; a
  shared counter store is future work.
- The per-tool gate (`require_enterprise_tool_access` in
  `app/core/auth.py`) is implemented and unit-tested
  (`tests/test_iga_policy.py`) but no route wires it yet, so group
  grants do not by themselves open or close any endpoint today.
  Integration work remains before SSO shortens a pilot.
