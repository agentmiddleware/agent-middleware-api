const assert = require("node:assert/strict");
const { afterEach, test } = require("node:test");
const axios = require("axios");
const { AWIClient } = require("../dist/index.js");

const originalAdapter = axios.defaults.adapter;
afterEach(() => { axios.defaults.adapter = originalAdapter; });

function clientWithTransport(adapter) {
  axios.defaults.adapter = adapter;
  return new AWIClient({ baseUrl: "http://127.0.0.1", apiKey: "synthetic-test-key" });
}

test("explicit zero reaches the API unchanged and its rejection propagates", async () => {
  let submitted;
  const client = clientWithTransport(async (config) => {
    submitted = JSON.parse(config.data);
    throw new axios.AxiosError("Synthetic API validation rejection", "ERR_BAD_REQUEST", config, null, {
      status: 422, data: { detail: "max_steps must be at least 1" },
    });
  });
  await assert.rejects(
    client.createSession("https://example.test", { maxSteps: 0 }),
    (error) => error.response.status === 422,
  );
  assert.equal(submitted.max_steps, 0);
});

test("only omitted maxSteps defaults to 100; explicit limits stay unchanged", async () => {
  const submitted = [];
  const client = clientWithTransport(async (config) => {
    const data = JSON.parse(config.data);
    submitted.push(data);
    return { status: 200, data, headers: {}, config };
  });
  await client.createSession("https://example.test");
  await client.createSession("https://example.test", {});
  for (const maxSteps of [1, 1000, -1, 1001]) {
    await client.createSession("https://example.test", { maxSteps, allowHumanPause: false });
  }
  assert.deepEqual(submitted.map((body) => body.max_steps), [100, 100, 1, 1000, -1, 1001]);
  assert.equal(submitted[0].allow_human_pause, true);
  assert.equal(submitted[2].allow_human_pause, false);
});
