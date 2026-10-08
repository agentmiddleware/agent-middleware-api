# Backend correctness resolution — 2026-10-02

## Scope and disposition

Implemented the two remaining backend findings from [draft QA PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586), under [backend charter #556](https://github.com/PetrefiedThunder/agent-middleware-api/issues/556) and [parent work item #499](https://github.com/PetrefiedThunder/agent-middleware-api/issues/499).

- **BE-002 — resolved locally:** supported JWT Bearer authentication now appears beside API-key authentication as an OpenAPI OR alternative.
- **BE-003 — resolved locally:** both outbound URL guards reject IPv4 and IPv6 multicast literals and DNS answers before dispatch.
- This patch does not represent all work in #556 or #499. It adds only these corrections to base `f82700f`, which already contains the preceding QA repairs. No remote issue or PR state was changed.

Verified repository `https://github.com/PetrefiedThunder/agent-middleware-api.git`, branch `openclaw/amw-issues-20261002-backend`, and worktree `/Users/sellers/.openclaw/worktrees/amw-issues-20261002-backend` before editing. The checkout was clean at entry.

## Root cause and implementation

### BE-002: supported Bearer authentication was missing from OpenAPI

`app/core/auth.py:get_auth_context` already accepted the raw `Authorization` header and delegated JWT validation to `_resolve_auth_context`, but only `APIKeyHeader` was declared as a FastAPI security dependency. Consequently, generated clients discovered only API-key authentication.

Added an optional `HTTPBearer(auto_error=False)` security dependency. FastAPI now emits two separate security requirement objects, `[{"APIKeyHeader": []}, {"HTTPBearer": []}]`, which means OR. The raw header remains authoritative in `_resolve_auth_context`; the newly parsed credential is deliberately not used to authenticate, because FastAPI's parser accepts casing and spacing rejected by the existing parser. Malformed or invalid Authorization still cannot fall back to a valid API key. No runtime credential acceptance rule changed.

Regenerated `docs/openapi.json` from the application. Its diff contains the Bearer security scheme and alternatives on 53 operations, with no unrelated schema changes.

### BE-003: `is_global` does not exclude multicast

`app/core/url_guard.py:_address_blocked` and `app/services/upstream_mcp.py:validate_upstream_url` treated `ipaddress.is_global` as sufficient to accept an address. IPv4 and IPv6 multicast can return true for that property.

Both checks now reject `is_multicast` explicitly. The checks apply to literal destinations and every address in a DNS response, including mixed public/multicast responses. Existing public-target acceptance, local upstream loopback handling, private-target rejection, and general-guard development override remain unchanged. The upstream configuration error now names multicast among rejected address classes.

## Files changed

- `app/core/auth.py`: optional Bearer scheme and dependency; raw-header validation remains in place.
- `app/core/url_guard.py`: explicit multicast block and corrected explanatory comment.
- `app/services/upstream_mcp.py`: explicit multicast block and matching configuration error.
- `tests/test_backend_contract_regressions.py`: 40 focused checks for schema OR semantics, route auth rejection, and literal/resolved/mixed multicast addresses.
- `docs/openapi.json`: generated schema snapshot.
- `docs/issue-resolution-2026-10-02/backend.md`: this evidence record.

## Verification evidence

Raw logs are outside the repository at `/tmp/amw-all-issues-20261002/backend/`. One pytest process ran at a time in this worktree. All new network boundary tests use synthetic addresses and mocked DNS; no multicast connection was attempted.

### Red control, before production changes

```text
uv run --with-requirements requirements.txt pytest tests/test_backend_contract_regressions.py -q
28 failed, 12 passed in 4.11s
```

Log: `red.log`. Four schema cases fail with missing `HTTPBearer`; twelve general URL-guard cases accept multicast unexpectedly; twelve upstream cases fail to raise `UpstreamMcpConfigurationError`. The twelve unauthenticated/malformed-header route controls already pass before the fix.

### Green regression suite, after production changes

```text
uv run --with-requirements requirements.txt pytest tests/test_backend_contract_regressions.py tests/test_jwt_auth.py tests/test_jwt_authority.py tests/test_agent_url_and_input_hardening.py tests/test_upstream_mcp.py tests/test_route_auth_inventory.py tests/test_revocation_containment.py tests/test_tenant_isolation_hardening.py -q
235 passed in 3.48s
```

Log: `green.log`. Coverage includes successful JWT/API-key authentication, invalid/malformed/refresh-token rejection, Authorization precedence, revoked credentials, scope attenuation, cross-wallet access denial, private/public URL boundaries, local loopback behavior, and upstream transport handling.

### Static checks and generated contract

```text
ruff check app/core/auth.py app/core/url_guard.py app/services/upstream_mcp.py tests/test_backend_contract_regressions.py
All checks passed!

uv run --with-requirements requirements.txt --with mypy mypy --config-file=mypy.ini app/
Success: no issues found in 187 source files

pre-commit run --files app/core/auth.py app/core/url_guard.py app/services/upstream_mcp.py tests/test_backend_contract_regressions.py docs/openapi.json
ruff: Passed
ruff-format: Passed
mypy (project env): Passed
```

Logs: `ruff.log`, `mypy.log`, and `pre-commit.log`. These are the hooks configured in this checkout's `.pre-commit-config.yaml`; the shared instruction's description of a detect-secrets hook does not match that file.

`gitleaks protect --staged --redact` also passed with `no leaks found`; its redacted output is in `gitleaks.log`.

The exporter and its readback check used the same synthetic local settings, with no local `.env` present:

```text
DATABASE_URL=sqlite+aiosqlite:///./test.db STATE_BACKEND=memory ENVIRONMENT=local VALID_API_KEYS=test-key TRUST_MODE_ENABLED=false ALLOW_LEGACY_UNPERMITTED_MCP=true ENABLE_PROOF_SURFACES=false uv run --with-requirements requirements.txt python scripts/export_openapi.py
Wrote docs/openapi.json (268776 bytes)

DATABASE_URL=sqlite+aiosqlite:///./test.db STATE_BACKEND=memory ENVIRONMENT=local VALID_API_KEYS=test-key TRUST_MODE_ENABLED=false ALLOW_LEGACY_UNPERMITTED_MCP=true ENABLE_PROOF_SURFACES=false uv run --with-requirements requirements.txt python scripts/export_openapi.py --check
docs/openapi.json matches app.openapi()
```

Logs: `openapi-export.log` and `openapi-check.log`.

An independent backend reviewer inspected the current production and test diff and reported no blocking finding. The reviewer did not modify files or run a competing pytest process.

## Limits, remaining risk, and next step

This is local code/test evidence. Hosted CI, live deployment, provider readback, PostgreSQL integration, and customer execution were not run. The general URL guard remains a pre-flight check with its documented DNS-rebinding limitation and `ALLOW_PRIVATE_NETWORK_TARGETS` development override; this patch does not strengthen those separate controls. No dependencies, credentials, database schemas, or deployment settings changed.

Next step: integrate this local commit with the other issue-resolution lanes, run the combined release checks, and have the aggregate gate review the final diff before any authorized remote action.
