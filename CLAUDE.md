# CLAUDE.md

This repository's agent guidance lives in [`AGENTS.md`](AGENTS.md). Read it
first — it defines the project mission (a governed trust plane for
agent-to-tool actions, **not** a generic agent backend), the core
`discover → authenticate → authorize → invoke → meter → receipt → audit → govern`
loop every feature is judged against, the security-critical areas, and the
analysis/implementation rules. Everything there applies to work done from
Claude Code.

## Local credentials — provision your own, never hardcode

When you need an API key against a **local** instance, mint your own instead
of asking for production secrets (full detail:
[`docs/static-dev-api-keys.md`](docs/static-dev-api-keys.md), and the
"Local Credentials for Agents" section of `AGENTS.md`):

- **Static admin-shaped key**: run
  `python scripts/generate_static_dev_keys.py`, set the printed value as
  `STATIC_DEV_API_KEYS=...` in `.env`, and restart. Bootstrap-admin in
  local-compatible environments only; never rotated by design.
- **Wallet-scoped key, no restart** (server running with
  `ENABLE_DEV_KEY_SELF_PROVISION=true`): `POST /v1/dev-keys/self-provision`
  (empty body works) mints a sponsor wallet, agent wallet, and wallet-scoped
  key with no pre-shared secret — use this to exercise the real
  permit → invoke → receipt loop as a non-admin caller. Call it from a
  CLI/SDK, not a browser (cross-origin browser requests are refused).

Both surfaces are refused by production-like deployments at boot, so neither
weakens production auth.
