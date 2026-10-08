# AWI TypeScript SDK

TypeScript client for the Agentic Web Interface (AWI) routes.

> **Proof surface.** The `/v1/awi/*` routes are frozen proof surfaces,
> unmounted in production-like deployments (`ENABLE_PROOF_SURFACES=false`).
> This client only works against a server started with proof surfaces
> enabled. See `docs/PROOF_SURFACES.md`. The product-vs-demo decision is
> still open; do not sell this as a production integration.

## Install

Not published to npm. Install from this checkout:

```bash
cd awi_sdk/typescript
npm install
npm run build
```

Or reference the folder from your app:

```bash
npm install ../path/to/agent-middleware-api/awi_sdk/typescript
```

## Quick start

```typescript
import { AWIClient } from "@agent-middleware/awi-sdk";

const client = new AWIClient({
  baseUrl: "http://localhost:8000",
  apiKey: "your-key",
  walletId: "wallet-123",
});

const session = await client.createSession("https://shop.example.com");
const result = await client.execute(
  session.session_id,
  "search_and_sort",
  { query: "laptops", sort_by: "price" },
  { permitId: "permit-from-POST-/v1/permits", idempotencyKey: "search-1" }
);
console.log(result.status);
```

A runnable version lives in `examples/quickstart.mjs` (run `npm run build` first).

## Behavior notes

- `baseUrl` defaults to `http://localhost:8000` and `apiKey` is
  optional, matching the Python SDK. Calls without a key reach the
  server unauthenticated and get a 401.
- `execute` requires `permitId` and `idempotencyKey`. Blank or
  oversize keys throw before any network call. Key length counts
  code points, as the server does.
- API failures throw typed errors (`AWIAuthenticationError`,
  `AWIPermitDeniedError`, `AWIIdempotencyConflictError`, ...), each
  carrying the axios `response`, so `error.response.status` keeps
  working.
- Redirects are never followed, so `X-API-Key` cannot leak to
  another host.
