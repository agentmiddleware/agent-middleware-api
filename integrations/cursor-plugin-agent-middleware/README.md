# Cursor plugin scaffold for Agent Middleware

Public-ready scaffold, not yet submitted to any marketplace. Layout mirrors the public template at `https://github.com/cursor/plugin-template/` (multi-plugin layout with a single plugin): `.cursor-plugin/marketplace.json` at this directory root, one plugin under `plugins/agent-middleware/` with its own `.cursor-plugin/plugin.json`, plus the template's `scripts/validate-template.mjs` copied verbatim.

## What the plugin does

The `agent-middleware` plugin connects Cursor to the Agent Middleware API so that side-effecting tool calls follow one guardrail: permit before action, receipt after.

- `plugins/agent-middleware/mcp.json` points at the AMW API base `https://api.thisisatest.tech`, standard MCP endpoint `POST /mcp` (Streamable HTTP, the preferred endpoint in this repo; legacy JSON-RPC `POST /mcp/messages` also exists). The API key is the `${AMW_API_KEY}` environment placeholder. No real key is stored anywhere in this tree.
- `plugins/agent-middleware/skills/amw-permit-receipt/SKILL.md` tells the agent to request a permit (`POST /v1/permits`) before any side-effecting tool call and to record the signed receipt (`GET /v1/receipts/{receipt_id}`) after the action.

Note on transport: the endpoint path (`/mcp`) and the `X-API-Key` header shape were checked against this repo (standard MCP router, repo `.mcp.json`, quickstart docs). Cursor's exact remote-server key names may vary by version, so confirm the `mcp.json` fields against your Cursor version when installing.

## Install from a local checkout

This package is not on PyPI, npm, or any plugin marketplace. Install it from a local checkout only:

1. Clone this repo (or use your existing checkout) and note the plugin folder: `integrations/cursor-plugin-agent-middleware/plugins/agent-middleware`.
2. Export your API key in the shell that launches Cursor (never put it in a file): `export AMW_API_KEY=<your key>`.
3. In Cursor, install a plugin from disk and select that folder.
4. Confirm the `agent-middleware` MCP server connects, then try the skill: ask the agent to request a permit before a side-effecting tool call and to record the receipt after.

## Marketplace submission checklist (not yet run)

For C.Lee. None of these steps have been run; this scaffold is submission-ready but unsubmitted.

- [ ] Run `node scripts/validate-template.mjs` from `integrations/cursor-plugin-agent-middleware/` and fix any errors.
- [ ] Confirm plugin `name` is unique, lowercase, kebab-case (`agent-middleware`).
- [ ] Confirm `.cursor-plugin/marketplace.json` entry maps to the real plugin folder.
- [ ] Confirm frontmatter (`name`, `description`) is present in the skill file.
- [ ] Confirm the logo is committed and referenced with a relative path.
- [ ] Confirm no secrets, keys, or tokens appear anywhere in the tree.
- [ ] Prepare the repository link for submission to the Cursor team.
