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

function echoClient(submitted) {
  return clientWithTransport(async (config) => {
    const data = JSON.parse(config.data);
    submitted.push(data);
    return { status: 200, data, headers: {}, config };
  });
}

const TASK = ["manual", "https://example.test", [{ op: "noop" }]];

test("omitted priority defaults to 5", async () => {
  const submitted = [];
  const client = echoClient(submitted);
  await client.createTask(...TASK);
  assert.equal(submitted[0].priority, 5);
});

test("explicit zero priority reaches the API unchanged", async () => {
  const submitted = [];
  const client = echoClient(submitted);
  await client.createTask(...TASK, 0);
  assert.equal(submitted[0].priority, 0);
});

test("explicit nonzero priorities stay unchanged", async () => {
  const submitted = [];
  const client = echoClient(submitted);
  for (const priority of [1, 5, 10]) {
    await client.createTask(...TASK, priority);
  }
  assert.deepEqual(submitted.map((body) => body.priority), [1, 5, 10]);
});
