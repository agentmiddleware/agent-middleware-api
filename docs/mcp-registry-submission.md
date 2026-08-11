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

The registry entry declares a `streamable-http` remote. The production
gateway does **not** serve that transport yet: `/mcp/messages` implements the
HTTP/JSON-RPC tools subset only (`tools/list`, `tools/call`), returns
`-32601` for `initialize`, and requires out-of-band permit context that no
standard MCP client can supply. Publishing before a spec-compliant Streamable
HTTP endpoint ships would advertise a transport and lifecycle the server does
not serve — the same class of overclaim
[`discovery-standards-proposal.md`](discovery-standards-proposal.md) exists to
prevent.

The publish workflow enforces this gate: it sends a real MCP `initialize`
request to the remote URL in `server.json`, then exercises `tools/list` on
the negotiated session, and refuses to publish unless both succeed. That
probe is a necessary condition for spec compliance, not proof of it — a
server could pass it and still fail standard clients elsewhere (e.g. a
`tools/call` path that demands out-of-band context). Do not bypass the
preflight, and do not treat a passing preflight as a substitute for testing
with a real MCP client.

`app/partner_mcp.py` is the in-tree reference for a compliant Streamable HTTP
server (official SDK, stateless HTTP, bearer auth middleware); the registrable
endpoint should generalize that pattern over the governed adapter.

## The artifact: `server.json`

The repo-root [`server.json`](../server.json) is the complete submission.
Field notes:

- `name` — reverse-DNS namespace plus server name. GitHub authentication
  grants `io.github.PetrefiedThunder/*`. Publishing under a custom domain
  namespace (e.g. `dev.agent-middleware/*`) requires DNS or HTTP domain
  verification with an Ed25519 key instead.
- `remotes[0].url` — must be HTTPS; localhost URLs are rejected at publish
  time, and the registry requires (but does not itself verify) that remotes
  are publicly accessible. `streamable-http` is the recommended type (`sse`
  is legacy-only).
- `remotes[0].headers` — declares the `X-API-Key` credential clients must
  send. Keys are operator-provisioned
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

Once the compliant endpoint is live, users connect per client:

**Claude Code**

```bash
claude mcp add --transport http agent-middleware \
  https://api-service-production-433c.up.railway.app/mcp \
  --header "X-API-Key: <operator-provisioned key>"
```

**Project-scoped `.mcp.json`** — the repo-root [`.mcp.json`](../.mcp.json) is
the Claude Code project-scoped format (top-level `mcpServers`). It is
deliberately inert by default: the entry has no baked-in URL, because there
is currently no spec-compliant endpoint to point it at, and a checked-in
default would advertise a transport the server does not serve. Once the
compliant endpoint ships, opt in by setting `AGENT_MIDDLEWARE_MCP_URL` (the
endpoint URL) and `AGENT_MIDDLEWARE_API_KEY` in the environment.

**claude.ai / Claude Desktop custom connectors** require OAuth (dynamic
client registration or a Client ID Metadata Document) or an authless server;
static API-key headers are an org-admin beta only. With `X-API-Key`-only
auth, this server is not registrable on those hosted surfaces yet.

**VS Code** (`.vscode/mcp.json`, top-level key `servers`) and **Cursor**
(`.cursor/mcp.json`, top-level key `mcpServers`) both accept static headers
on remote entries.
