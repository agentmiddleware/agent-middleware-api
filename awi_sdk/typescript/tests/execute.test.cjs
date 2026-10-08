const assert = require("node:assert/strict");
const { afterEach, test } = require("node:test");
const axios = require("axios");
const {
  AWIClient,
  AWIAuthenticationError,
  AWIIdempotencyConflictError,
  AWIPermitDeniedError,
  AWIApiError,
  MAX_IDEMPOTENCY_KEY_LENGTH,
} = require("../dist/index.js");

const originalAdapter = axios.defaults.adapter;
afterEach(() => { axios.defaults.adapter = originalAdapter; });

function clientWithTransport(adapter, config) {
  axios.defaults.adapter = adapter;
  return new AWIClient({
    baseUrl: "http://127.0.0.1",
    apiKey: "synthetic-test-key",
    ...config,
  });
}

function ok(body) {
  return async (config) => ({ status: 200, data: body, headers: {}, config });
}

function fail(status, data) {
  return async (config) => {
    throw new axios.AxiosError(
      `Synthetic ${status}`, "ERR_BAD_REQUEST", config, null,
      { status, data, headers: {}, config }
    );
  };
}

test("execute sends permit and idempotency headers with the payload", async () => {
  let seen;
  let headers;
  const client = clientWithTransport(async (config) => {
    seen = JSON.parse(config.data);
    headers = config.headers;
    return { status: 200, data: { status: "success" }, headers: {}, config };
  });
  await client.execute(
    "sess-1",
    "add_to_cart",
    { sku: "laptop-1" },
    { permitId: "permit-123", idempotencyKey: "idem-123" }
  );
  assert.equal(seen.session_id, "sess-1");
  assert.equal(seen.action, "add_to_cart");
  assert.deepEqual(seen.parameters, { sku: "laptop-1" });
  assert.equal(headers["X-Permit-Id"], "permit-123");
  assert.equal(headers["Idempotency-Key"], "idem-123");
});

test("execute rejects blank permit, blank key, and oversize key locally", async () => {
  let calls = 0;
  const client = clientWithTransport(async (config) => {
    calls += 1;
    return { status: 200, data: {}, headers: {}, config };
  });
  const cases = [
    [{ permitId: "", idempotencyKey: "k" }, "permitId must not be blank"],
    [{ permitId: "  ", idempotencyKey: "k" }, "permitId must not be blank"],
    [{ permitId: "p", idempotencyKey: "" }, "idempotencyKey must not be blank"],
    [{ permitId: "p", idempotencyKey: "   " }, "idempotencyKey must not be blank"],
    [
      { permitId: "p", idempotencyKey: "k".repeat(MAX_IDEMPOTENCY_KEY_LENGTH + 1) },
      "at most 128 characters",
    ],
    // 129 emoji are 129 code points but 258 UTF-16 units: still rejected.
    [{ permitId: "p", idempotencyKey: "😀".repeat(129) }, "at most 128 characters"],
  ];
  for (const [options, message] of cases) {
    await assert.rejects(
      client.execute("sess-1", "add_to_cart", {}, options),
      (error) => error.message.includes(message)
    );
  }
  // Boundary lengths pass validation and reach the transport.
  await client.execute(
    "sess-1", "add_to_cart", {},
    { permitId: "p", idempotencyKey: "😀".repeat(128) }
  );
  assert.equal(calls, 1);
});

test("execute maps 409 conflict, 403 permit denial, and 401 to typed errors", async () => {
  const conflict = clientWithTransport(
    fail(409, { error: "idempotency_conflict", message: "key reused" })
  );
  await assert.rejects(
    conflict.execute("s", "add_to_cart", {}, { permitId: "p", idempotencyKey: "k" }),
    (error) => error instanceof AWIIdempotencyConflictError
      && error.response.status === 409
  );

  const denied = clientWithTransport(
    fail(403, { error: "permit_denied", message: "permit refused" })
  );
  await assert.rejects(
    denied.execute("s", "add_to_cart", {}, { permitId: "p", idempotencyKey: "k" }),
    (error) => error instanceof AWIPermitDeniedError
      && error.response.status === 403
  );

  const auth = clientWithTransport(fail(401, { error: "unauthorized" }));
  await assert.rejects(
    auth.execute("s", "add_to_cart", {}, { permitId: "p", idempotencyKey: "k" }),
    (error) => error instanceof AWIAuthenticationError
      && error.response.status === 401
  );

  const other = clientWithTransport(fail(422, { detail: "bad input" }));
  await assert.rejects(
    other.execute("s", "add_to_cart", {}, { permitId: "p", idempotencyKey: "k" }),
    (error) => error instanceof AWIApiError && error.response.status === 422
  );
});

test("client works without apiKey and defaults baseUrl to localhost", async () => {
  let headers;
  let baseURL;
  const client = clientWithTransport(async (config) => {
    headers = config.headers;
    baseURL = config.baseURL;
    return { status: 200, data: { actions: [], categories: [] }, headers: {}, config };
  }, { apiKey: undefined, baseUrl: undefined });
  await client.discover();
  assert.equal(headers["X-API-Key"], undefined);
  assert.equal(baseURL, "http://localhost:8000");
});
