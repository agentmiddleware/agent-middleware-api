# Prepared operator release decision

September 8, 2026. This is a review artifact, not authorization to deploy.

## Source candidate

`ff8182bcc9011c052b412e23eff20875d6f650b8`, [draft PR #417](https://github.com/PetrefiedThunder/agent-middleware-api/pull/417). Hosted checks: 23 success. No failed or pending checks. The candidate changes CI, the PostgreSQL proof alias, scanner fixture compatibility, and documentation.

## Immediate security release

The Redis process reports 8.2.1 through read-only SSH. The most recent successful deployment also uses `redis:8.2.1`. Railway's configured source is already `redis:8.2.9`; that configuration has not produced the running patched binary.

The Redis advisory identifies the 8.2 branch fix for CVE-2025-49844 in 8.2.2. The configured 8.2.9 release contains additional later security fixes. Sources: [advisory](https://github.com/redis/redis/security/advisories/GHSA-4789-qfc9-5f9q), [8.2.9 release](https://github.com/redis/redis/releases/tag/8.2.9).

Before activation, identify the Redis-only release operation and validate its recovery path and expected reconnect behavior. Do not accept the entire existing environment patch to deploy Redis: it has 69 staged changes covering other services. Closure requires the active deployment's image identity and `redis-server --version` to confirm the patched release, plus persistence and API health checks. A configured image string or automatic-update notice is insufficient.

## Read-only API IaC plan

The isolated checkout was linked locally to the explicitly selected existing project, production environment, and API service. Linking changed local CLI context only. The following command was then run without value-decryption, value-display, apply, or deployment flags:

```sh
railway config plan --file .railway/railway.ts --detailed-exit-code
```

CLI: 5.43.3. SDK: 3.11.0. Node: 24. The plan returned three proposed changes:

| Resource/field | Current graph | Desired graph |
|---|---|---|
| API source.repo | PetrefiedThunder/agent-middleware-api | null |
| API source.type | github | null |
| API build.builder | null | DOCKERFILE |
| API deploy.healthcheckPath | null | /health |
| API deploy.healthcheckTimeout | null | 300 |

Zero additions and zero resource destructions were reported. The source disconnect is still a consequential change. The deployment SOP calls for explicit review of that disconnect, a maintenance window, preservation of the previous config-file setting and release SHA, disposable convergence proof, and exact post-deployment identity checks. This plan is evidence to review; it does not establish convergence or authorize activation. The provider config reader also reports current runtime/build metadata differently from the IaC graph, so the legacy config-file transition must be resolved in that review.

The existing staged environment patch was a different object with 69 changes.
It was not accepted, cancelled, or edited. The API plan's three changes do not
explain or approve those 69 changes. Its provider object identifier is omitted
from this curated record.

## Required before a hosted tester

1. Resolve ownership and exact contents of the staged patch; keep unrelated PostgreSQL, Redis, variable, volume, and PITR changes isolated.
2. Activate the reviewed patched Redis release and verify the running binary and application reconnect.
3. Complete the candidate PR release decision and deploy the exact intended API SHA through the documented application path. Both `/health` and `/health/dependencies` must report it. Current public SHA is `2880ca706d2f4779876097e9414b6f1fab691a3e`.
4. Qualify the actual customer environment, schema, private data-service networking, signing identity and recovery material, and provider backup/restore procedure. A local logical dump/restore is already rehearsed; provider PITR and customer secret recovery are still unverified.
5. Bind the one synthetic or redacted action to a named partner engineer and define authoritative upstream effect lookup, stable operation identity, and who resolves uncertainty. Leave customer acceptance and economics Pending until their evidence exists.

No hosted writes, exploit, API tool invocation, restore, provider configuration mutation, or deployment was performed during this preparation. Read-only SSH commands were limited to binary version identification. No production credentials or customer rows were copied into this package.
