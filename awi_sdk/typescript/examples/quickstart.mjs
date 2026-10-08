// Minimal AWI SDK example: start a session and run one action.
//
// Needs a local server with proof surfaces enabled plus a real API key,
// wallet, and permit. Fill in the placeholders, then run:
//
//   npm run build
//   node examples/quickstart.mjs

import { AWIClient } from "../dist/index.js";

const client = new AWIClient({
  baseUrl: "http://localhost:8000",
  apiKey: "your-key",
  walletId: "wallet-123",
});

const session = await client.createSession("https://shop.example.com");
console.log("session:", session.session_id);

const result = await client.execute(
  session.session_id,
  "search_and_sort",
  { query: "laptops", sort_by: "price" },
  {
    permitId: "permit-from-POST-/v1/permits",
    idempotencyKey: "quickstart-search-1",
  }
);
console.log("status:", result.status);
