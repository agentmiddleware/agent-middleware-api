/**
 * Tests for the minimal TypeScript gateway client. Every test runs against
 * a stubbed fetch, so no server and no network are needed. The stubs assert
 * the exact path, method and auth headers the gateway expects.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { GatewayClient } from "../src/index.js";
import {
  APIError,
  AuthenticationError,
  AuthorizationError,
  DeliveryUncertainError,
  IdempotencyConflictError,
  InsufficientFundsError,
  JsonObject,
  PermitDeniedError,
  TransportError,
} from "../src/index.js";

interface SeenRequest {
  url: string;
  init: RequestInit;
  body: JsonObject | null;
}

function permitPayload(): JsonObject {
  const now = new Date().toISOString();
  return {
    permit_id: "permit-1",
    issuer_wallet_id: "wallet-1",
    subject_wallet_id: "wallet-1",
    subject_key_id: "key-1",
    scopes: ["tool:partner.search:invoke"],
    allowed_tools: ["partner.search"],
    max_credits: "25",
    spent_credits: "0",
    expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
    nonce: "nonce-1",
    status: "active",
    signature: "permit-signature",
    key_id: "signing-key-1",
    issued_at: now,
    revoked_at: null,
  };
}

function receiptPayload(outcome = "success"): JsonObject {
  return {
    receipt_id: `receipt-${outcome}`,
    idempotency_record_id: "idem-1",
    permit_id: "permit-1",
    wallet_id: "wallet-1",
    key_id: "key-1",
    tool: "partner.search",
    request_hash: "request-hash",
    response_hash: "response-hash",
    ledger_entry_id: "ledger-1",
    dispatch_attempt_id: "dispatch-1",
    credits_authorized: "2",
    credits_charged: "2",
    outcome,
    audit_event_id: "audit-1",
    created_at: new Date().toISOString(),
    signature: "receipt-signature",
    signature_key_id: "signing-key-1",
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Stub fetch that records requests and replays one canned response. */
function stubFetch(handler: (seen: SeenRequest) => Response) {
  const seen: SeenRequest[] = [];
  const fetchImpl = async (url: string, init: RequestInit): Promise<Response> => {
    let body: JsonObject | null = null;
    if (typeof init.body === "string" && init.body.length > 0) {
      body = JSON.parse(init.body) as JsonObject;
    }
    const request: SeenRequest = { url, init, body };
    seen.push(request);
    return handler(request);
  };
  return { fetchImpl, seen };
}

function headersOf(seen: SeenRequest): Record<string, string> {
  const headers = new Headers(seen.init.headers as HeadersInit);
  const out: Record<string, string> = {};
  headers.forEach((value, key) => {
    out[key] = value;
  });
  return out;
}

describe("GatewayClient construction", () => {
  it("rejects a missing api key without sending anything", () => {
    assert.throws(() => new GatewayClient({ apiKey: "" }), TypeError);
  });

  it("rejects a blank bearer token without sending anything", () => {
    assert.throws(() => new GatewayClient({ apiKey: "k", bearerToken: "  " }), TypeError);
  });

  it("defaults to the local quickstart origin and trims trailing slashes", async () => {
    const { fetchImpl, seen } = stubFetch(() => jsonResponse({ tools: [] }));
    const client = new GatewayClient({ apiKey: "k", baseUrl: "http://127.0.0.1:8000///", fetchImpl });
    assert.equal(client.baseUrl, "http://127.0.0.1:8000");
    await client.discoverTools();
    assert.equal(seen[0].url, "http://127.0.0.1:8000/mcp/tools.json");
  });
});

describe("discoverTools", () => {
  it("sends the key header and parses the tool list", async () => {
    const { fetchImpl, seen } = stubFetch(() =>
      jsonResponse({ tools: [{ name: "partner.search", description: "search", inputSchema: {}, annotations: {} }] }),
    );
    const client = new GatewayClient({ apiKey: "secret", fetchImpl });
    const tools = await client.discoverTools();
    assert.equal(tools.length, 1);
    assert.equal(tools[0].name, "partner.search");
    assert.equal(seen[0].init.method, "GET");
    assert.equal(headersOf(seen[0])["x-api-key"], "secret");
  });

  it("rejects a malformed tools payload", async () => {
    const { fetchImpl } = stubFetch(() => jsonResponse({ tools: "nope" }));
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(() => client.discoverTools(), APIError);
  });
});

describe("createPermit", () => {
  const request = {
    issuerWalletId: "wallet-1",
    subjectWalletId: "wallet-1",
    maxCredits: "25",
    expiresAt: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
  };

  it("posts the permit payload with the idempotency key header", async () => {
    const { fetchImpl, seen } = stubFetch(() => jsonResponse(permitPayload()));
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    const permit = await client.createPermit(request, { idempotencyKey: "permit-key-1" });
    assert.equal(permit.permitId, "permit-1");
    assert.equal(permit.maxCredits, "25");
    assert.equal(seen[0].url, "http://127.0.0.1:8000/v1/permits");
    assert.equal(seen[0].init.method, "POST");
    const headers = headersOf(seen[0]);
    assert.equal(headers["idempotency-key"], "permit-key-1");
    assert.equal(headers["x-api-key"], "k");
    assert.equal(seen[0].body?.issuer_wallet_id, "wallet-1");
  });

  it("rejects a blank idempotency key before any request is sent", async () => {
    const { fetchImpl, seen } = stubFetch(() => jsonResponse(permitPayload()));
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(() => client.createPermit(request, { idempotencyKey: "  " }), TypeError);
    assert.equal(seen.length, 0);
  });

  it("rejects an overlong idempotency key before any request is sent", async () => {
    const { fetchImpl, seen } = stubFetch(() => jsonResponse(permitPayload()));
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(() => client.createPermit(request, { idempotencyKey: "x".repeat(129) }), TypeError);
    assert.equal(seen.length, 0);
  });

  it("rejects a malformed permit payload", async () => {
    const { fetchImpl } = stubFetch(() => jsonResponse({ permit_id: "permit-1" }));
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(() => client.createPermit(request, { idempotencyKey: "k1" }), APIError);
  });
});

describe("invokeTool", () => {
  function successEnvelope(): JsonObject {
    return {
      jsonrpc: "2.0",
      id: "call-key-1",
      result: {
        content: [{ type: "text", text: "ok" }],
        receipt: receiptPayload(),
      },
    };
  }

  it("posts a tools/call envelope and returns content plus receipt", async () => {
    const { fetchImpl, seen } = stubFetch(() => jsonResponse(successEnvelope()));
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    const result = await client.invokeTool(
      "partner.search",
      { q: "bread" },
      { walletId: "wallet-1", permitId: "permit-1", idempotencyKey: "call-key-1" },
    );
    assert.equal(result.receipt.receiptId, "receipt-success");
    assert.equal(result.content.length, 1);
    assert.equal(seen[0].url, "http://127.0.0.1:8000/mcp/messages");
    const params = (seen[0].body?.params ?? {}) as JsonObject;
    assert.equal(params.name, "partner.search");
    const context = (params.mcpContext ?? {}) as JsonObject;
    assert.equal(context.permit_id, "permit-1");
    assert.equal(headersOf(seen[0])["idempotency-key"], "call-key-1");
  });

  it("maps a permit denial to PermitDeniedError", async () => {
    const { fetchImpl } = stubFetch(() =>
      jsonResponse({ jsonrpc: "2.0", id: "k", error: { code: -32000, message: "permit_expired", data: {} } }),
    );
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(
      () => client.invokeTool("t", {}, { walletId: "w", permitId: "p", idempotencyKey: "k" }),
      (err: unknown) => err instanceof PermitDeniedError && err.reason === "permit_expired",
    );
  });

  it("maps an uncertain outcome to DeliveryUncertainError carrying the receipt id", async () => {
    const uncertain = receiptPayload("delivery_uncertain");
    const { fetchImpl } = stubFetch(() =>
      jsonResponse({
        jsonrpc: "2.0",
        id: "k",
        error: { code: -32000, message: "delivery_uncertain", data: { receipt: uncertain } },
      }),
    );
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(
      () => client.invokeTool("t", {}, { walletId: "w", permitId: "p", idempotencyKey: "k" }),
      (err: unknown) => err instanceof DeliveryUncertainError && err.receiptId === "receipt-delivery_uncertain",
    );
  });

  it("maps insufficient funds to InsufficientFundsError", async () => {
    const { fetchImpl } = stubFetch(() =>
      jsonResponse({ jsonrpc: "2.0", id: "k", error: { code: -32000, message: "insufficient_funds", data: {} } }),
    );
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(
      () => client.invokeTool("t", {}, { walletId: "wallet-9", permitId: "p", idempotencyKey: "k" }),
      (err: unknown) => err instanceof InsufficientFundsError && err.walletId === "wallet-9",
    );
  });

  it("maps a reused key to IdempotencyConflictError", async () => {
    const { fetchImpl } = stubFetch(() =>
      jsonResponse({ jsonrpc: "2.0", id: "k", error: { code: -32009, message: "idempotency_key_reused", data: {} } }),
    );
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(
      () => client.invokeTool("t", {}, { walletId: "w", permitId: "p", idempotencyKey: "k" }),
      IdempotencyConflictError,
    );
  });
});

describe("receipts", () => {
  it("fetches a receipt by id", async () => {
    const { fetchImpl, seen } = stubFetch(() => jsonResponse(receiptPayload()));
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    const receipt = await client.getReceipt("receipt-success");
    assert.equal(receipt.receiptId, "receipt-success");
    assert.equal(seen[0].url, "http://127.0.0.1:8000/v1/receipts/receipt-success");
  });

  it("verifies a receipt and returns the parsed receipt", async () => {
    const { fetchImpl, seen } = stubFetch(() =>
      jsonResponse({ valid: true, reason: null, receipt: receiptPayload() }),
    );
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    const verification = await client.verifyReceipt("receipt-success");
    assert.equal(verification.valid, true);
    assert.equal(verification.receipt?.receiptId, "receipt-success");
    assert.equal(seen[0].url, "http://127.0.0.1:8000/v1/receipts/verify");
    assert.equal(seen[0].init.method, "POST");
    assert.equal(seen[0].body?.receipt_id, "receipt-success");
  });

  it("rejects a verification payload with a non-boolean valid flag", async () => {
    const { fetchImpl } = stubFetch(() => jsonResponse({ valid: "yes" }));
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(() => client.verifyReceipt("r"), APIError);
  });
});

describe("http error mapping", () => {
  it("maps 401 to AuthenticationError", async () => {
    const { fetchImpl } = stubFetch(() => jsonResponse({ detail: "bad key" }, 401));
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(() => client.getReceipt("r"), AuthenticationError);
  });

  it("maps 402 to InsufficientFundsError with the server shortfall", async () => {
    const { fetchImpl } = stubFetch(() =>
      jsonResponse({ detail: { shortfall: 3.5, top_up_url: "https://pay.example/topup" } }, 402),
    );
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(
      () => client.getReceipt("r"),
      (err: unknown) =>
        err instanceof InsufficientFundsError && err.shortfall === 3.5 && err.topUpUrl === "https://pay.example/topup",
    );
  });

  it("maps 403 without a permit prefix to AuthorizationError", async () => {
    const { fetchImpl } = stubFetch(() => jsonResponse({ detail: "forbidden" }, 403));
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(
      () => client.getReceipt("r"),
      (err: unknown) => err instanceof AuthorizationError && !(err instanceof PermitDeniedError),
    );
  });

  it("maps 409 to IdempotencyConflictError", async () => {
    const { fetchImpl } = stubFetch(() => jsonResponse({ detail: "idempotency_key_reused" }, 409));
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(() => client.getReceipt("r"), IdempotencyConflictError);
  });

  it("maps a transport failure to TransportError", async () => {
    const fetchImpl = async (): Promise<Response> => {
      throw new Error("socket hung up");
    };
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(() => client.getReceipt("r"), TransportError);
  });

  it("treats redirects as blocked instead of following them", async () => {
    const fetchImpl = async (): Promise<Response> => new Response(null, { status: 307 });
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(() => client.getReceipt("r"), TransportError);
  });

  it("rejects a non-JSON body", async () => {
    const fetchImpl = async (): Promise<Response> => new Response("not json", { status: 200 });
    const client = new GatewayClient({ apiKey: "k", fetchImpl });
    await assert.rejects(() => client.getReceipt("r"), APIError);
  });
});
