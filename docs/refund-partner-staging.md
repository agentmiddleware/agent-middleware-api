# Refund Partner Fixture On Staging

A non-idempotent, refund-style MCP upstream for exactly-once reviews. The echo
tool is idempotent by construction, so it cannot show whether gateway
exactly-once behavior reaches a real remote side effect. This fixture commits a
countable refund per dispatch. Synthetic fixture only; not for production.

It is test support (`tests/support/mcp_refund_partner_app.py`) and must never be
added to the production image. The steps below deploy it as its own Railway
service in the **staging** environment only.

## Behavior

- Tool `partner.refund(refund_ref, amount_cents, after_effect="none", hang_seconds=30)`.
- Reads the forwarded `_meta["io.agentmiddleware/idempotency_key"]` and
  `_meta["io.agentmiddleware/invocation_id"]`; both are required.
- `POST /__stress/mode {"honor_idempotency": true|false}` switches at runtime.
  Off: each dispatch commits a new effect. On: a repeated key returns the first
  effect, and the same key with different arguments is rejected.
- `after_effect`: `none` returns, `error` raises after the effect is committed,
  `hang` holds the response after the effect is committed.
- `GET /__stress/health` and `GET /__stress/effects[?refund_ref=...]` report
  counts, total cents refunded, and the effect rows. All `/__stress/*` routes
  require the `X-MCP-Refund-Control` header.

## Deploy (staging only)

Run from a machine with the Railway CLI logged in to the project.

```sh
scripts/build_refund_partner_bundle.sh /tmp/refund-partner-bundle
cd /tmp/refund-partner-bundle

railway link            # project agent-middleware-api, environment staging
railway add --service partner-refund-staging
railway domain --service partner-refund-staging   # note the hostname

BEARER="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
CONTROL="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
railway variables --service partner-refund-staging --environment staging \
  --set "MCP_REFUND_PARTNER_ALLOWED_HOST=<hostname from the domain step>" \
  --set "MCP_REFUND_PARTNER_BEARER_TOKEN=$BEARER" \
  --set "MCP_REFUND_PARTNER_CONTROL_TOKEN=$CONTROL" \
  --set "MCP_REFUND_PARTNER_DB_PATH=/tmp/refund-partner.sqlite3"

railway up --service partner-refund-staging --environment staging
```

Notes:

- `MCP_REFUND_PARTNER_DB_PATH` is on ephemeral disk, so effect counts reset on
  every redeploy or restart. Attach a volume and point the path at it if counts
  must survive restarts.
- Keep `$BEARER` and `$CONTROL` out of commits and chat. Give the control token
  to the reviewer by a private channel.

## Point the staging gateway at it

The gateway supports exactly one upstream. This replaces the echo upstream on
`api-service-staging`; record the current values first so they can be restored.

| Variable | Value |
| --- | --- |
| `MCP_UPSTREAM_URL` | `https://<refund partner hostname>/mcp` (match the form the echo value uses) |
| `MCP_UPSTREAM_BEARER_TOKEN` | the `$BEARER` value above |
| `MCP_UPSTREAM_TOOL_NAME` | `partner.refund` |
| `MCP_UPSTREAM_PUBLIC_TOOL_ID` | a new public tool id for the refund tool |
| `MCP_UPSTREAM_CREDITS_PER_CALL` | unchanged unless the reviewer asks |

Permits issued for the echo tool do not authorize the refund tool; the reviewer
needs new permits for the new public tool id.

## Verify

```sh
curl -s -H "X-MCP-Refund-Control: $CONTROL" https://<hostname>/__stress/health
```

Expect `status: ok`, `honor_idempotency: false`, and `effect_count: 0`. Then run
the reviewer scenarios and read `/__stress/effects` to count real side effects.

## Roll back

Restore the recorded echo values for the five variables above on
`api-service-staging`. The refund service can stay or be removed.
