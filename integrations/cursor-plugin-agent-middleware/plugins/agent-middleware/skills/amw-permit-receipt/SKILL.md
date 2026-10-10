---
name: amw-permit-receipt
description: Request an Agent Middleware permit before any side-effecting tool call, and record the signed receipt after the action. Use when the agent is about to invoke a tool that changes state, spends budget, or calls an external service.
---

# AMW permit and receipt

Govern side-effecting tool calls through the Agent Middleware API: permit before action, receipt after.

## When to use

- Before invoking any tool that changes state, spends budget, or calls an external service.
- After such an action completes (or fails), to capture the receipt.
- When auditing a past action, to fetch and verify its receipt.

## Instructions

1. Before the side-effecting call, request a permit from the Agent Middleware API (`POST /v1/permits`). The permit names the wallet, the allowed tool, and the spend cap. Do not proceed without one.
2. Pass the issued `permit_id` with the governed invocation (standard MCP endpoint `POST /mcp`, legacy JSON-RPC `POST /mcp/messages`).
3. After the action, record the receipt: keep the returned receipt id and payload with the permit id that authorized it, so the action can be audited later (`GET /v1/receipts/{receipt_id}`, or `GET /v1/permits/{permit_id}/receipts`).
4. If the call is denied (for example the spend cap is reached), keep the denial response with the same permit reference instead of retrying with a different permit.
5. Never store API keys in files, prompts, or receipts. The key always comes from the `AMW_API_KEY` environment placeholder.
