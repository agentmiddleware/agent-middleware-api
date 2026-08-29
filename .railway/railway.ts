import { defineRailway, preserve, project, service } from "railway/iac";

export const partial = "api-service";

export default defineRailway(() =>
  project("agent-middleware-api", {
    resources: [
      service("api-service", {
        build: {
          builder: "DOCKERFILE",
          dockerfilePath: "Dockerfile",
        },
        deploy: {
          healthcheckPath: "/health",
          healthcheckTimeout: 300,
        },
        replicas: {
          "us-west2": 1,
        },
        domains: ["api.thisisatest.tech"],
        variables: {
          ALLOW_LEGACY_UNPERMITTED_MCP: preserve(),
          CORS_ORIGINS: preserve(),
          DATABASE_URL: preserve(),
          DEBUG: preserve(),
          ENABLE_DOGFOOD_TOOL: preserve(),
          ENABLE_PROOF_SURFACES: preserve(),
          ENABLE_PUBLIC_MCP_ENDPOINT: preserve(),
          ENVIRONMENT: preserve(),
          MCP_UPSTREAM_BEARER_TOKEN: preserve(),
          MCP_UPSTREAM_CREDITS_PER_CALL: preserve(),
          MCP_UPSTREAM_ENABLED: preserve(),
          MCP_UPSTREAM_PUBLIC_TOOL_ID: preserve(),
          MCP_UPSTREAM_TOOL_NAME: preserve(),
          MCP_UPSTREAM_URL: preserve(),
          PORT: preserve(),
          PRODUCTION_URL: preserve(),
          PUBLIC_CONTACT_EMAIL: preserve(),
          PUBLIC_CONTACT_NAME: preserve(),
          PUBLIC_CONTACT_URL: preserve(),
          PUBLIC_URL: preserve(),
          REDIS_URL: preserve(),
          RUN_MIGRATIONS_ON_START: preserve(),
          SENTINEL_API_KEY: preserve(),
          SENTINEL_API_URL: preserve(),
          SIMULATION_MODE_HUMAN_APPROVAL: preserve(),
          STATE_BACKEND: preserve(),
          TRUST_MODE_ENABLED: preserve(),
          TRUST_SIGNING_KEY_ID: preserve(),
          TRUST_SIGNING_PRIVATE_KEY_B64: preserve(),
          VALID_API_KEYS: preserve(),
          WEBAUTHN_ALLOW_MOCK: preserve(),
        },
      }),
    ],
  }),
);
