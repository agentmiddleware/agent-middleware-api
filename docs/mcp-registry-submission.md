# MCP Registry Submission

Publishing this server to the official MCP Registry
(`registry.modelcontextprotocol.io`) is done with the checked-in
[`server.json`](../server.json) and the `mcp-publisher` CLI. There is no
form-based submission: an earlier version of this document described a
copy-paste payload and an "Add Server" form that the registry does not have.
The registry stores metadata only and is consumed by downstream aggregators
(PulseMCP, the GitHub MCP registry, client marketplaces), which sync roughly
hourly.

## Publish gate (read first)

**Preflight status (all must be YES before publishing):**

- [ ] Public contact monitored: `CONTACT_EMAIL` (or equivalent) set to a
  monitored inbox, no placeholder values.
- [ ] Endpoint enabled: a deployment approved to serve `POST /mcp`
  (`ENABLE_STANDARD_MCP_ENDPOINT=true`) is live at the remote URL.
- [ ] Preflight passed: the publish workflow's live `initialize` plus
  `tools/list` probe succeeds against that deployment.

**The entry is intentionally unpublished, and `server.json` declares no
remote.** A registry entry would declare a `streamable-http` remote at
`POST /mcp`. That endpoint is implemented (`app/routers/mcp_standard.py`:
stateless JSON-mode lifecycle with `initialize`, notifications, `ping`,
`tools/list`, and `tools/call` backed by server-minted single-tool permits)
but ships **disabled**: `ENABLE_STANDARD_MCP_ENDPOINT` defaults to false and
returns 404 until an operator enables it on the deployment. The production
SOP keeps it that way — [`deploy-railway.md`](deploy-railway.md#required-production-variables)
lists `ENABLE_STANDARD_MCP_ENDPOINT` as `false` or unset with "Do not turn
this on" — so the first-party origin (`api.thisisatest.tech`) will not serve
`/mcp`, and a remote pointing at it would advertise a transport the server
does not serve: the class of overclaim
[`discovery-standards-proposal.md`](discovery-standards-proposal.md) exists
to prevent.

Adding a remote is therefore a product decision that changes that SOP first,
not a manifest edit. Only after a deployment is approved to serve `/mcp`
should `remotes` (see the field notes below) be added to `server.json`.

The publish workflow enforces this gate: it refuses a `server.json` with no
remote, sends a real MCP `initialize` request to the remote URL otherwise,
then exercises `tools/list` on the negotiated session, and refuses to publish
unless both succeed — which requires the deployed endpoint to be enabled.
That probe is a necessary condition for spec compliance, not proof of it. Do
not bypass the preflight, and do not treat a passing preflight as a
substitute for testing with a real MCP client (e.g.
`claude mcp add --transport http`).

## The artifact: `server.json`

The repo-root [`server.json`](../server.json) is the submission, minus the
`remotes` block it deliberately omits until the gate above is lifted. Field
notes:

- `name` — reverse-DNS namespace plus server name. GitHub authentication
  grants `io.github.PetrefiedThunder/*`. Publishing under a custom domain
  namespace (e.g. `dev.agent-middleware/*`) requires DNS or HTTP domain
  verification with an Ed25519 key instead.
- `remotes[0].url` (not present today) — must be HTTPS; localhost URLs are
  rejected at publish time, and the registry requires (but does not itself
  verify) that remotes are publicly accessible. `streamable-http` is the
  recommended type (`sse` is legacy-only).
- `remotes[0].headers` (not present today) — would declare the `X-API-Key`
  credential clients must send. Keys are operator-provisioned
  ([`partner-api-key-bootstrap.md`](partner-api-key-bootstrap.md)); there is
  no public self-serve issuance, and a registry listing does not change that.
- `version` — unique and immutable per publish. Registry entries cannot be
  edited or deleted after publish; metadata fixes require publishing a new,
  *higher* version (e.g. `1.2.1` after `1.2.0`). A prerelease like `1.2.0-1`
  published after `1.2.0` sorts below it and is never marked "latest", so
  aggregators will not surface it — prereleases only help when published
  *before* the release version. Version strings must not look like ranges
  (`^1.2.0`, `1.x` are rejected). This field currently mirrors the project
  version (`pyproject.toml`, `APP_VERSION`); nothing checks the three stay
  in sync, so bump it manually for `workflow_dispatch` publishes (tag-driven
  publishes overwrite it from the tag).

Once a deployment is approved to serve `/mcp`, the block to add is:

```json
"remotes": [
  {
    "type": "streamable-http",
    "url": "https://<approved-origin>/mcp",
    "headers": [
      {
        "name": "X-API-Key",
        "description": "Operator-provisioned wallet API key; there is no public self-serve issuance",
        "isRequired": true,
        "isSecret": true
      }
    ]
  }
]
```

## Publishing from CI (preferred)

[`.github/workflows/publish-mcp.yml`](../.github/workflows/publish-mcp.yml)
publishes on either:

- a tag matching `mcp-registry-v*` (e.g. `mcp-registry-v1.2.0`; the tag
  version is written into `server.json` before publish), or
- a manual `workflow_dispatch` run.

It is deliberately **not** wired to release tags (`v*`), so a routine release
cannot publish a registry entry as a side effect.

Authentication is GitHub OIDC (`id-token: write`) — no long-lived secret. The
optional `MCP_PREFLIGHT_API_KEY` repository secret lets the preflight
authenticate its `initialize` probe if the compliant endpoint requires a key.

## Publishing manually

```bash
brew install mcp-publisher   # or the release tarball from the registry repo
mcp-publisher login github   # device flow; grants io.github.PetrefiedThunder/*
mcp-publisher publish        # reads ./server.json
```

Run the same `initialize` probe as the workflow before publishing manually;
the honesty gate applies regardless of which path publishes.

## Verification after publish

```bash
curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.PetrefiedThunder/agent-middleware-api"
```

The registry lists the entry immediately; downstream aggregators pick it up
on their next sync (expect hours, not minutes). The registry is in preview —
breaking changes or data resets may occur before GA.

## Client registration

No first-party deployment serves `/mcp` (see the publish gate). On a
deployment that does — for example a local instance started with
`ENABLE_STANDARD_MCP_ENDPOINT=true` — users connect per client:

**Claude Code**

```bash
claude mcp add --transport http agent-middleware \
  <deployment origin>/mcp \
  --header "X-API-Key: <operator-provisioned key>"
```

**Project-scoped `.mcp.json`** — the repo-root [`.mcp.json`](../.mcp.json) is
the Claude Code project-scoped format (top-level `mcpServers`). It is
deliberately inert by default: the entry has no baked-in URL, because the
production deployment ships with the standard endpoint disabled, and a
checked-in default would advertise a transport the server does not serve.
Opt in by setting `AGENT_MIDDLEWARE_MCP_URL` (the deployment's `/mcp` URL,
once enabled there) and `AGENT_MIDDLEWARE_API_KEY` in the environment.

**claude.ai / Claude Desktop custom connectors** require OAuth (dynamic
client registration or a Client ID Metadata Document) or an authless server;
static API-key headers are an org-admin beta only. With `X-API-Key`-only
auth, this server is not registrable on those hosted surfaces yet.

**VS Code** (`.vscode/mcp.json`, top-level key `servers`) and **Cursor**
(`.cursor/mcp.json`, top-level key `mcpServers`) both accept static headers
on remote entries.
