# agent-middleware

Permit before action, receipt after, for side-effecting tool calls made from Cursor through the Agent Middleware API.

## Included

- `mcp.json`: MCP server config pointing at the Agent Middleware API (`https://api.thisisatest.tech/mcp`), with the API key as the `${AMW_API_KEY}` environment placeholder.
- `skills/amw-permit-receipt/`: the governance skill. Request an AMW permit before any side-effecting tool call, record the receipt after the action.
