const EXPECTED_VARIABLES = [
  "ALLOW_LEGACY_UNPERMITTED_MCP",
  "CORS_ORIGINS",
  "DATABASE_URL",
  "DEBUG",
  "ENABLE_DOGFOOD_TOOL",
  "ENABLE_PROOF_SURFACES",
  "ENABLE_PUBLIC_MCP_ENDPOINT",
  "ENVIRONMENT",
  "MCP_UPSTREAM_BEARER_TOKEN",
  "MCP_UPSTREAM_CREDITS_PER_CALL",
  "MCP_UPSTREAM_ENABLED",
  "MCP_UPSTREAM_PUBLIC_TOOL_ID",
  "MCP_UPSTREAM_TOOL_NAME",
  "MCP_UPSTREAM_URL",
  "PORT",
  "PRODUCTION_URL",
  "PUBLIC_CONTACT_EMAIL",
  "PUBLIC_CONTACT_NAME",
  "PUBLIC_CONTACT_URL",
  "PUBLIC_URL",
  "REDIS_URL",
  "RUN_MIGRATIONS_ON_START",
  "SENTINEL_API_KEY",
  "SENTINEL_API_URL",
  "SIMULATION_MODE_HUMAN_APPROVAL",
  "STATE_BACKEND",
  "TRUST_MODE_ENABLED",
  "TRUST_SIGNING_KEY_ID",
  "TRUST_SIGNING_PRIVATE_KEY_B64",
  "VALID_API_KEYS",
  "WEBAUTHN_ALLOW_MOCK",
];

const MINIMUM_NODE_MAJOR = 24;

class CheckFailure extends Error {}

function fail(message) {
  throw new CheckFailure(message);
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function requireRecord(value, label) {
  if (!isRecord(value)) {
    fail(`${label} must be an object`);
  }
  return value;
}

function requireExactKeys(value, expectedKeys, label) {
  const record = requireRecord(value, label);
  const actualKeys = Object.keys(record).sort();
  const expected = [...expectedKeys].sort();
  if (
    actualKeys.length !== expected.length ||
    actualKeys.some((key, index) => key !== expected[index])
  ) {
    fail(`${label} keys do not match the pinned contract`);
  }
  return record;
}

function requireEqual(actual, expected, label) {
  if (actual !== expected) {
    fail(`${label} does not match the pinned contract`);
  }
}

function requireSupportedNodeRuntime(version) {
  const major = Number.parseInt(version.split(".", 1)[0], 10);
  if (!Number.isInteger(major) || major < MINIMUM_NODE_MAJOR) {
    fail(`Node.js 24 or newer is required; found ${version}`);
  }
}

function requireNoSource(value, path = "project") {
  if (Array.isArray(value)) {
    value.forEach((child, index) => requireNoSource(child, `${path}[${index}]`));
    return;
  }
  if (!isRecord(value)) {
    return;
  }
  for (const [key, child] of Object.entries(value)) {
    if (key === "source") {
      fail(`${path} must not declare a source`);
    }
    requireNoSource(child, `${path}.${key}`);
  }
}

async function main() {
  requireSupportedNodeRuntime(process.versions.node);
  const [{ createRailwayContext, project }, config] = await Promise.all([
    import("railway/iac"),
    import("./railway.ts"),
  ]);
  requireEqual(config.partial, "api-service", "partial name");
  if (typeof config.default !== "function") {
    fail("default export must be a Railway program");
  }

  const definition = await config.default(
    createRailwayContext({ environment: "production" }),
    project,
  );
  const desiredProject = requireExactKeys(
    definition,
    ["name", "resources"],
    "project",
  );
  requireEqual(desiredProject.name, "agent-middleware-api", "project name");
  if (!Array.isArray(desiredProject.resources)) {
    fail("project resources must be an array");
  }
  if (desiredProject.resources.length !== 1) {
    fail("project must contain exactly one resource");
  }

  const api = requireExactKeys(
    desiredProject.resources[0],
    [
      "address",
      "build",
      "deploy",
      "kind",
      "name",
      "networking",
      "type",
      "variables",
    ],
    "API resource",
  );
  requireEqual(api.address, "service.api-service", "API resource address");
  requireEqual(api.type, "service", "API resource type");
  requireEqual(api.kind, "empty", "API source posture");
  requireEqual(api.name, "api-service", "API service name");
  requireNoSource(desiredProject);

  const build = requireExactKeys(
    api.build,
    ["builder", "dockerfilePath"],
    "API build",
  );
  requireEqual(build.builder, "DOCKERFILE", "API builder");
  requireEqual(build.dockerfilePath, "Dockerfile", "API Dockerfile path");

  const deploy = requireExactKeys(
    api.deploy,
    [
      "healthcheckPath",
      "healthcheckTimeout",
      "multiRegionConfig",
    ],
    "API deploy config",
  );
  requireEqual(deploy.healthcheckPath, "/health", "API health path");
  requireEqual(deploy.healthcheckTimeout, 300, "API health timeout");
  const regions = requireExactKeys(
    deploy.multiRegionConfig,
    ["us-west2"],
    "API replica regions",
  );
  const west = requireExactKeys(
    regions["us-west2"],
    ["numReplicas"],
    "us-west2 replica config",
  );
  requireEqual(west.numReplicas, 1, "us-west2 replica count");

  const networking = requireExactKeys(
    api.networking,
    ["customDomains"],
    "API networking",
  );
  const domains = requireExactKeys(
    networking.customDomains,
    ["api.thisisatest.tech"],
    "API custom domains",
  );
  const domain = requireExactKeys(
    domains["api.thisisatest.tech"],
    ["port"],
    "API custom domain config",
  );
  requireEqual(domain.port, 8080, "API custom domain port");

  const variables = requireExactKeys(
    api.variables,
    EXPECTED_VARIABLES,
    "API variables",
  );
  for (const name of EXPECTED_VARIABLES) {
    const value = requireExactKeys(variables[name], ["type"], `variable ${name}`);
    requireEqual(value.type, "preserve", `variable ${name} preservation`);
  }

  process.stdout.write(
    `Railway IaC check passed: one API service and ${EXPECTED_VARIABLES.length} preserved variables verified.\n`,
  );
}

main().catch((error) => {
  const message =
    error instanceof CheckFailure
      ? error.message
      : "configuration could not be evaluated safely";
  process.stderr.write(`Railway IaC check failed: ${message}.\n`);
  process.exitCode = 1;
});
