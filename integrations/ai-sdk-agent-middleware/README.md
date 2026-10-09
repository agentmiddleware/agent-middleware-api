# ai-sdk-agent-middleware

Govern Vercel AI SDK tools with the Agent Middleware API. One rule: permit
before action, receipt after.

`governedTool` wraps an AI SDK `tool()` so every execution mints a permit
(`POST /v1/permits`), checks admission (`POST /v1/permits/verify`), then
dispatches through the governed invoke path (`POST /mcp/messages`
`tools/call`), which runs the tool and returns a signed receipt. A denied
permit throws `PermitDeniedError` before anything is dispatched, so the tool
never runs.

This package is not on npm. Install it from a checkout of this repository
(see below). There is no local receipt endpoint in the API: receipts are
minted server side by the invoke call and handed back to the wrapper, which
exposes the latest one as `wrapped.lastReceipt`.

## Requirements

- Node 18 or later (uses the global `fetch`)
- `ai` v6 and `zod` v4 (peer dependencies)

## Install from checkout

This package is not published to npm. From a checkout of this repository:

```bash
cd integrations/ai-sdk-agent-middleware
npm install
npm run build
```

To use it in another project from the same checkout:

```bash
cd /path/to/your-app
npm install /path/to/agent-middleware-api/integrations/ai-sdk-agent-middleware ai zod
```

Set your API key (never commit it):

```bash
export AMW_API_KEY="${AMW_API_KEY}"
```

## Working example

The tool must also be registered server side under the same `toolName`; the
wrapper keeps the AI SDK description and schema but execution goes through
the governed path.

```ts
import { generateText, tool } from "ai";
import { z } from "zod";
import { openai } from "@ai-sdk/openai";
import { governedTool, PermitDeniedError } from "ai-sdk-agent-middleware";

const saveNote = tool({
  description: "Save a short note for the user.",
  inputSchema: z.object({ text: z.string() }),
  execute: async () => ({ saved: false }), // never called directly; governed execute replaces it
});

const governedSaveNote = governedTool(saveNote, {
  toolName: "partner.notes.write",
  issuerWalletId: "wallet-issuer",
  subjectWalletId: "wallet-agent",
  // baseUrl defaults to https://api.thisisatest.tech
  // apiKey defaults to process.env.AMW_API_KEY
});

try {
  const result = await generateText({
    model: openai("gpt-4o-mini"),
    prompt: "Save a note saying hello.",
    tools: { saveNote: governedSaveNote },
    maxSteps: 3,
  });
  console.log(result.text);
  console.log("receipt:", governedSaveNote.lastReceipt?.receipt_id);
} catch (err) {
  if (err instanceof PermitDeniedError) {
    console.log("permit denied, tool did not run:", err.message);
  } else {
    throw err;
  }
}
```

Notes on the example:

- `generateText` needs a model and its provider package (here `@ai-sdk/openai`
  with `OPENAI_API_KEY` set). The governed flow itself only needs `AMW_API_KEY`
  plus funded issuer and subject wallets.
- The idempotency key for each call derives from the AI SDK `toolCallId`
  (`amw-<toolCallId>`), so a retry of the same model-issued tool call reuses
  the key. Pass `idempotencyKeyFor` to override.
- When the tool call fails server side, the wrapper throws
  `GovernedInvokeError` but still records the returned failure receipt on
  `lastReceipt`, when the API returned one.

## API

- `governedTool(baseTool, options)`: wrap an AI SDK tool. Options:
  `toolName` (required), `issuerWalletId` (required), `subjectWalletId`,
  `maxCredits`, `expiresInSeconds`, `scopes`, `baseUrl`, `apiKey`,
  `idempotencyKeyFor`, `fetchFn`.
- `AmwClient`: lower level client with `createPermit`, `verifyPermit`, and
  `invokeTool` against the real endpoints listed above.
- `PermitDeniedError`: thrown when the permit is denied; the tool is not run.
- `GovernedInvokeError`: thrown when the invoke fails; carries `receipt` when
  the server returned one.

## Release checklist (not yet run)

npm release is pending; none of these steps have been run.

1. Decide the public scope and name (currently unscoped `ai-sdk-agent-middleware`).
2. Add provenance and access config for the npm org.
3. Run `npm run build` and `npm test` on a clean checkout.
4. Run `npm pack --dry-run` and review the file list.
5. Run `npm publish` (requires maintainer approval; do not publish from fleet runs).
