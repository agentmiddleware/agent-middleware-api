# @agent-middleware/gateway-client (TypeScript)

Minimal typed client for the Agent Middleware gateway permit, call and
receipt endpoints. Status: source only, not published to npm.

```ts
import { GatewayClient } from "./src/index.ts";

const client = new GatewayClient({ apiKey: process.env.AMW_API_KEY ?? "", baseUrl: "http://127.0.0.1:8000" });

const tools = await client.discoverTools();
const permit = await client.createPermit(
  { issuerWalletId: "wallet-1", subjectWalletId: "wallet-1", maxCredits: "25", expiresAt: "2026-10-09T00:00:00Z" },
  { idempotencyKey: "permit-key-1" },
);
const result = await client.invokeTool(
  "partner.search",
  { q: "bread" },
  { walletId: "wallet-1", permitId: permit.permitId, idempotencyKey: "call-key-1" },
);
const receipt = await client.getReceipt(result.receipt.receiptId);
const verification = await client.verifyReceipt(receipt.receiptId);
console.log(verification.valid, receipt.creditsCharged);
```

```bash
npm test            # builds with tsc and runs node:test against stubbed fetch
npm run typecheck   # strict typecheck with no emit
```

Notes for integrators:

- Every permit and call needs a caller-owned idempotency key. Blank or
  overlong keys are rejected locally before any request is sent.
- Redirects are never followed, so the API key cannot leak to a redirect
  target. A redirect answer raises TransportError.
- Errors are typed: AuthenticationError, PermitDeniedError,
  InsufficientFundsError, IdempotencyConflictError,
  DeliveryUncertainError, AuthorizationError, TransportError, APIError.
- Credit amounts stay strings so no precision is lost in transit.
- Revocation is live-checked server side. Re-verify a receipt here before
  relying on an exported copy, since offline checks alone cannot see a
  revocation.
