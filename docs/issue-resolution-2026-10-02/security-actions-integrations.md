# Security, actions and integrations independent gate

Reviewed candidate: `f82700f750862b6e51566a46dfc559e5b81e0a95` (2026-10-02 local review).
Assigned checkout: `/Users/sellers/.openclaw/worktrees/amw-issues-20261002-gate`, branch `openclaw/amw-issues-20261002-gate`; origin `https://github.com/PetrefiedThunder/agent-middleware-api.git`.

**No blocking defect identified in this focused review.** Fresh current-candidate verification passed **576 tests in 31.09 seconds**, in one pytest process across 29 files. This is the independent security/action/integration subset, not whole-candidate acceptance, remote CI, deployment or customer proof.

## Scope and evidence identity

- All 28 scoped issue IDs and URLs match the saved issue inventory. All cited fix/follow-up commits resolve and are ancestors of the reviewed candidate. All original negative and green evidence files exist; original failure assertions and green result summaries were inspected without modifying those artifacts.
- Read repository and relevant service/test instructions, verified the worktree and clean status before execution, and reviewed the listed repair diffs plus current authorization/ownership boundaries. This is not a new full-repository audit.
- The historical disposition file freezes `24b7ae4` and explicitly does not accept its then-failing aggregate test run. Current `git diff 24b7ae4..f82700f` changes only 13 fixture lines in `tests/test_permit_issuance_retry.py`. Product code is unchanged. The later historical `final-review-f827.md` independently explains that isolation repair; current testing here includes issuance followed by AWI and other shared-service consumers.
- No product code changed in this review. Raw fresh logs and command metadata: `/tmp/amw-all-issues-20261002/gate/focused.log` and `focused-result.json`. Historical artifact extraction: `original-evidence-verified.json` in the same directory.

## Cross-subsystem guarantees checked

- Scoped JWT refresh preserves attenuation; JWT callers cannot create unrestricted keys; concurrent derived authentication consumes origin-key authority atomically and cannot choose rate buckets through ignored headers.
- Permit numeric rejection uses `PermitCreationRejectedError` before signing/persistence, preserving AE-001 cleanup. Generic mint, commit acknowledgment and completion failures hold issuance ownership. Abandonment checks the exact unfinished owner.
- Action signature verification uses the preparation session. Local counter contention retries before debit/effect; genuine budget/cap/status denials remain denials.
- AWI binds full request semantics, reserves permit authority, obtains the operation-key debit, and persists the charged marker before any of six callbacks. Uncertain admission, callback, refund or receipt outcomes cannot reopen the identity for redispatch. Only trusted non-dispatch evidence refunds. Unsupported per-tool call limits remain refused.
- IGA compensation removes its exact reservation; audit head and bounded event stream share one statement snapshot. Retired standalone generation refuses before registry traversal/output writes while standard no-argument discovery remains functional.

## Per-issue disposition

Each current test path below was included in the fresh 576-test run unless explicitly labeled static. Original log paths are relative to the immutable local evidence root `/Users/sellers/Documents/Codex/2026-10-01/task-4/`. Historical test totals overlap and must not be summed with each other or with the current run.

### [AE-001 · #512](https://github.com/PetrefiedThunder/agent-middleware-api/issues/512) — Release exact issuance ownership after a proven pre-persistence rejection

- Correction: Release only the exact issuance owner after an explicit proven pre-signing/pre-persistence rejection; retain ambiguous post-mint ownership. Fix commits: `0e4b141`.
- Current code: `app/routers/permits.py; app/services/idempotency.py; app/services/permits.py`. Current regression: `tests/test_permit_issuance_retry.py`.
- Original evidence: `evidence/qa-20261002/reviews/action_execution/issuance-retry-red-run.log`. Green evidence: `evidence/qa-20261002/reviews/action_execution/ae001-focused-green.log`.
- Coverage/limit: Exact pre-write rejection versus ambiguous signing/commit/completion; replacement owner protection.

### [AE-002 · #519](https://github.com/PetrefiedThunder/agent-middleware-api/issues/519) — Reuse the preparation transaction for action signature verification

- Correction: Reuse the action preparation transaction for signature verification rather than acquiring a second pooled connection. Fix commits: `59d24e2`.
- Current code: `app/services/action_permits.py; app/services/mcp_dispatch_attempts.py`. Current regression: `tests/test_action_verification_sessions.py`.
- Original evidence: `evidence/qa-20261002/reviews/action_execution/action-pool-red.log`. Green evidence: `evidence/qa-20261002/reviews/action_execution/ae002-focused.log`; `evidence/qa-20261002/reviews/action_execution/ae002-postgres-test.log`.
- Coverage/limit: Current run used SQLite. The original six-test PostgreSQL pool proof was inspected, not repeated.

### [AE-003 · #540](https://github.com/PetrefiedThunder/agent-middleware-api/issues/540) — Retry local call-counter contention instead of caching false budget denial

- Correction: Distinguish optimistic local permit counter contention from genuine authority/budget denial and retry before debit/effect. Fix commits: `61cb0ca`.
- Current code: `app/services/permits.py`. Current regression: `tests/test_local_permit_counter_contention.py`.
- Original evidence: `evidence/qa-20261002/reviews/action_execution/local-counter-race.log`; `evidence/qa-20261002/reviews/action_execution/local-counter-http-race.log`. Green evidence: `evidence/qa-20261002/reviews/action_execution/ae003-focused-green.log`.
- Coverage/limit: CAS contention, retry exhaustion, real caps, same-key replay and no duplicate debit/effect.

### [IP-001 · #513](https://github.com/PetrefiedThunder/agent-middleware-api/issues/513) — Rehydrate durable AI decisions and heals before exposing them through typed routes

- Correction: Rehydrate durable decision/heal records and timestamps and initialize read routes after restart. Fix commits: `88828e8`.
- Current code: `app/services/agent_intelligence.py; app/routers/ai.py`. Current regression: `tests/test_ai_durable_state.py`.
- Original evidence: `evidence/qa-20261002/reviews/integrations_product/ai-probe-red.log`. Green evidence: `evidence/qa-20261002/reviews/integrations_product/ai-fix-green.log`.
- Coverage/limit: Synthetic durable restart and ownership; no provider request.

### [IP-002 · #514](https://github.com/PetrefiedThunder/agent-middleware-api/issues/514) — Use the configured API root once when building OpenAI chat URLs

- Correction: Treat the configured OpenAI URL as the API root and append the chat path only once. Fix commits: `f20abec`.
- Current code: `app/services/llm.py`. Current regression: `tests/test_llm_endpoint.py`.
- Original evidence: `evidence/qa-20261002/reviews/integrations_product/ai-probe-red.log`. Green evidence: `evidence/qa-20261002/reviews/integrations_product/llm-fix-green.log`.
- Coverage/limit: Mock HTTP transport; configured root includes its version prefix; no provider request.

### [IP-003 · #515](https://github.com/PetrefiedThunder/agent-middleware-api/issues/515) — Propagate structured DOM execution failure to AWI top-level status before accounting

- Correction: Propagate structured browser failure as uncertain effect status and truthful governed accounting; preserve precharge/owner semantics from SEC-008. Fix commits: `19fe8c2`, `cb8d2f8`.
- Current code: `app/services/awi_session.py; app/services/awi_http_governance.py`. Current regression: `tests/test_awi_execution_boundaries.py; tests/test_awi_admission_ordering.py`.
- Original evidence: `evidence/qa-20261002/reviews/integrations_product/awi-boundary-red.log`. Green evidence: `evidence/qa-20261002/reviews/integrations_product/awi-stable-green.log`; `evidence/qa-20261002/reviews/awi_ordering/final-sqlite.log`; `evidence/qa-20261002/reviews/awi_ordering/pg-final.log`.
- Coverage/limit: SEC-008 supersedes historical zero-charge wording: uncertain dispatch keeps its debit.

### [IP-004 · #516](https://github.com/PetrefiedThunder/agent-middleware-api/issues/516) — Prevent browser dispatch when AWI callers explicitly request a dry run

- Correction: Reject unsupported dry run without browser commands or step mutation; final AWI precharge is refunded only on trusted not-dispatched evidence. Fix commits: `19fe8c2`, `cb8d2f8`.
- Current code: `app/services/awi_session.py; app/services/awi_http_governance.py`. Current regression: `tests/test_awi_execution_boundaries.py; tests/test_awi_admission_ordering.py`.
- Original evidence: `evidence/qa-20261002/reviews/integrations_product/awi-boundary-red.log`. Green evidence: `evidence/qa-20261002/reviews/integrations_product/awi-stable-green.log`; `evidence/qa-20261002/reviews/awi_ordering/final-sqlite.log`; `evidence/qa-20261002/reviews/awi_ordering/pg-final.log`.
- Coverage/limit: Dry run is explicitly refused and proven non-dispatch refunds once; no browser run.

### [IP-005 · #517](https://github.com/PetrefiedThunder/agent-middleware-api/issues/517) — Bind all effect-bearing AWI arguments into the idempotency identity

- Correction: Bind all normalized effect-bearing arguments plus wallet/tool/permit to AWI request identity; changed same-key semantics conflict. Fix commits: `19fe8c2`, `cb8d2f8`.
- Current code: `app/services/awi_http_governance.py; app/routers/awi.py; app/routers/awi_enhanced.py`. Current regression: `tests/test_awi_request_authority.py; tests/test_awi_http_governance.py`.
- Original evidence: `evidence/qa-20261002/reviews/integrations_product/awi-governance-red.log`. Green evidence: `evidence/qa-20261002/reviews/integrations_product/awi-stable-green.log`; `evidence/qa-20261002/reviews/awi_ordering/final-sqlite.log`; `evidence/qa-20261002/reviews/awi_ordering/pg-final.log`.
- Coverage/limit: Full normalized arguments, permit, tool and wallet bind identity; legacy partial-hash records are not migrated.

### [IP-006 · #518](https://github.com/PetrefiedThunder/agent-middleware-api/issues/518) — Enforce signed AWI argument prohibitions and atomic per-tool call limits before execution

- Correction: Enforce signed forbidden-field constraints and refuse unsupported per-tool call-limit authority before callbacks. Fix commits: `19fe8c2`, `cb8d2f8`.
- Current code: `app/services/awi_http_governance.py`. Current regression: `tests/test_awi_request_authority.py; tests/test_awi_admission_ordering.py`.
- Original evidence: `evidence/qa-20261002/reviews/integrations_product/awi-governance-red.log`. Green evidence: `evidence/qa-20261002/reviews/integrations_product/awi-stable-green.log`; `evidence/qa-20261002/reviews/awi_ordering/final-sqlite.log`; `evidence/qa-20261002/reviews/awi_ordering/pg-final.log`.
- Coverage/limit: Per-tool call-limited AWI permits fail closed with awi_call_limit_unsupported; support was not added.

### [IP-007 · #527](https://github.com/PetrefiedThunder/agent-middleware-api/issues/527) — Honor write-only and explicit-deny IoT topic ACLs

- Correction: Enforce READ/WRITE direction and precedence of every matching IoT DENY rule. Fix commits: `9b26b35`.
- Current code: `app/services/iot_bridge.py`. Current regression: `tests/test_iot_acl.py`.
- Original evidence: `evidence/qa-20261002/reviews/integrations_product/iot-acl-red.log`. Green evidence: `evidence/qa-20261002/reviews/integrations_product/iot-fix-green.log`.
- Coverage/limit: READ/WRITE direction and matching DENY precedence; no MQTT broker.

### [IP-008 · #528](https://github.com/PetrefiedThunder/agent-middleware-api/issues/528) — Persist completed content campaigns and their pipeline links

- Correction: Persist campaign pipeline links and terminal status, including failed render state, across restart. Fix commits: `527f3b7`.
- Current code: `app/services/content_factory.py`. Current regression: `tests/test_factory_campaign_persistence.py`.
- Original evidence: `evidence/qa-20261002/reviews/integrations_product/factory-durable-red.log`; `evidence/qa-20261002/reviews/integrations_product/factory-durable-initial-fixture-error.log`; `evidence/qa-20261002/reviews/integrations_product/factory-durable-async-fixture-error.log`. Green evidence: `evidence/qa-20261002/reviews/integrations_product/factory-fix-green.log`.
- Coverage/limit: Synthetic campaign restart, completed links and failed render; no external publishing.

### [IP-009 · #544](https://github.com/PetrefiedThunder/agent-middleware-api/issues/544) — Generate valid Python literals in the behavioral sandbox wrapper

- Correction: Generate valid Python values in behavioral runner wrappers while preserving captured output. Fix commits: `8d3ed08`.
- Current code: `app/services/behavioral_sandbox.py`. Current regression: `tests/test_behavioral_runner_results.py`.
- Original evidence: `evidence/qa-20261002/reviews/integrations_product/sandbox-validation-red.log`. Green evidence: `evidence/qa-20261002/reviews/integrations_product/behavioral-runner-green.log`.
- Coverage/limit: Local harmless wrapper probes and parsed results; no Docker isolation certification.

### [IP-010 · #545](https://github.com/PetrefiedThunder/agent-middleware-api/issues/545) — Validate RTaaS attack categories at the request boundary

- Correction: Validate RTaaS attack category values at the request boundary and return 422 before engine execution. Fix commits: `f6e9f51`.
- Current code: `app/routers/rtaas.py`. Current regression: `tests/test_rtaas_input_validation.py`.
- Original evidence: `evidence/qa-20261002/reviews/integrations_product/sandbox-validation-red.log`. Green evidence: `evidence/qa-20261002/reviews/integrations_product/rtaas-fix-green.log`.
- Coverage/limit: Unknown category rejected with 422 before mocked engine; frozen simulated surface.

### [IP-011 · #546](https://github.com/PetrefiedThunder/agent-middleware-api/issues/546) — Remove live security-testing and CI-gate claims from simulated scan route metadata

- Correction: Describe simulated security-scan behavior accurately in route metadata while keeping execution gates. Fix commits: `636f8cf`.
- Current code: `app/routers/red_team.py; app/routers/rtaas.py`. Current regression: `Static current route metadata read; historical simulation-metadata-check.log`.
- Original evidence: `evidence/qa-20261002/reviews/integrations_product/findings.json`. Green evidence: `evidence/qa-20261002/reviews/integrations_product/simulation-metadata-check.log`.
- Coverage/limit: Documentation-only correction; no new current runtime test was invented for text changes.

### [IP-012 · #581](https://github.com/PetrefiedThunder/agent-middleware-api/issues/581) — Delete every memory before removing the AWI session index

- Correction: Iterate a snapshot of session memory IDs so deletion removes every owned record without skipping mutated-index entries. Fix commits: `c3385e9`.
- Current code: `app/services/awi_rag_engine.py`. Current regression: `tests/test_awi_rag_lifecycle.py`.
- Original evidence: `evidence/qa-20261002/reviews/integrations_product/rag-parser-red.log`. Green evidence: `evidence/qa-20261002/reviews/integrations_product/rag-stable-c3385e9.log`.
- Coverage/limit: Deletes all owned synthetic records and preserves other sessions/owners; no vector store.

### [IP-013 · #582](https://github.com/PetrefiedThunder/agent-middleware-api/issues/582) — Reject or safely handle empty AWI RAG queries

- Correction: Reject blank RAG queries at the HTTP schema boundary and safely return no results for direct empty search without embedding/access mutations. Fix commits: `c3385e9`.
- Current code: `app/schemas/awi_enhanced.py; app/services/awi_rag_engine.py`. Current regression: `tests/test_awi_rag_lifecycle.py`.
- Original evidence: `evidence/qa-20261002/reviews/integrations_product/rag-parser-red.log`. Green evidence: `evidence/qa-20261002/reviews/integrations_product/rag-stable-c3385e9.log`.
- Coverage/limit: Blank HTTP requests fail before governance; direct empty search has no embedding/access effects.

### [IP-014 · #583](https://github.com/PetrefiedThunder/agent-middleware-api/issues/583) — Do not report malformed or failed Python runner output as success

- Correction: Reject malformed, nonobject or failed Python runner output and process errors instead of reporting success. Fix commits: `8d3ed08`.
- Current code: `app/services/behavioral_sandbox.py`. Current regression: `tests/test_behavioral_runner_results.py`.
- Original evidence: `evidence/qa-20261002/reviews/integrations_product/rag-parser-red.log`. Green evidence: `evidence/qa-20261002/reviews/integrations_product/behavioral-runner-green.log`.
- Coverage/limit: Malformed/nonobject/missing-bool results and nonzero process exit fail closed.

### [QA-ACTION-TRANSPORT-001 · #529](https://github.com/PetrefiedThunder/agent-middleware-api/issues/529) — Standalone MCP generator emits Python that cannot start

- Correction: Retire the server standalone generator with explicit refusal before registry traversal or output writes; retain callable argument compatibility and active metadata generation. Fix commits: `e4a046b`.
- Current code: `app/services/mcp_generator.py`. Current regression: `tests/test_mcp_generator.py`.
- Original evidence: `evidence/qa-20261002/reviews/action_execution/transports-generator-probe.log`. Green evidence: `evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log`.
- Coverage/limit: Explicit retirement before registry access/file output, not repair or support of standalone generated servers. SDK retirement is independently owned by the clients/docs lane.

### [QA-ACTION-TRANSPORT-002 · #524](https://github.com/PetrefiedThunder/agent-middleware-api/issues/524) — A valid no-argument local tool breaks standard MCP discovery

- Correction: Normalize absent/null no-argument tool schemas to an object schema for standard MCP discovery, preserving explicit schemas. Fix commits: `1f47952`.
- Current code: `app/services/mcp_generator.py`. Current regression: `tests/test_mcp_generator.py; tests/test_standard_mcp_endpoint.py`.
- Original evidence: `evidence/qa-20261002/reviews/action_execution/transports-discovery-probe.log`; `evidence/qa-20261002/reviews/action_execution/transports-discovery-repair-control.log`. Green evidence: `evidence/qa-20261002/reviews/action_execution/transport002-focused.log`.
- Coverage/limit: Only absent/null schema normalized; explicit schema and siblings preserved; discovery does not invoke handlers.

### [SEC-001 · #503](https://github.com/PetrefiedThunder/agent-middleware-api/issues/503) — Refresh widens an attenuated JWT scope set

- Correction: Preserve attenuated or empty JWT scopes across refresh and reject unbound/malformed refresh authority. Fix commits: `cd9440c`.
- Current code: `app/core/jwt.py; app/routers/auth.py`. Current regression: `tests/test_jwt_authority.py; tests/test_jwt_auth.py`.
- Original evidence: `evidence/qa-20261002/reviews/security_runtime/jwt-authority.log`. Green evidence: `evidence/qa-20261002/reviews/security_runtime/fix-regression-stable.log`.
- Coverage/limit: Attenuated/empty scopes persist; missing scope binding and refresh replay fail closed.

### [SEC-002 · #504](https://github.com/PetrefiedThunder/agent-middleware-api/issues/504) — Scoped access tokens can mint unrestricted wallet API keys

- Correction: Reject JWT callers that attempt to mint or replace unrestricted persistent API credentials. Fix commits: `cd9440c`.
- Current code: `app/routers/api_keys.py`. Current regression: `tests/test_jwt_authority.py; tests/test_api_keys.py`.
- Original evidence: `evidence/qa-20261002/reviews/security_runtime/jwt-authority.log`. Green evidence: `evidence/qa-20261002/reviews/security_runtime/fix-regression-stable.log`.
- Coverage/limit: JWT creation, rotation and replacement routes refuse persistent broader credentials; cross-wallet controls.

### [SEC-003 · #505](https://github.com/PetrefiedThunder/agent-middleware-api/issues/505) — Derived JWT authentication bypasses the originating key use budget

- Correction: Atomically consume the originating live key use budget when authenticating derived JWTs. Fix commits: `cd9440c`.
- Current code: `app/core/auth.py; app/services/api_key_service.py`. Current regression: `tests/test_jwt_authority.py`.
- Original evidence: `evidence/qa-20261002/reviews/security_runtime/jwt-authority.log`. Green evidence: `evidence/qa-20261002/reviews/security_runtime/fix-regression-stable.log`.
- Coverage/limit: Concurrent JWTs share the final origin-key use; revoked, expired and wrong-wallet origin rejected.

### [SEC-004 · #506](https://github.com/PetrefiedThunder/agent-middleware-api/issues/506) — Bearer callers choose fresh rate buckets with ignored API-key headers

- Correction: Select rate buckets from the accepted authentication path, ignoring spoofed unused key headers and stabilizing JWT rotation identity. Fix commits: `cd9440c`.
- Current code: `app/core/rate_limiter.py`. Current regression: `tests/test_jwt_authority.py`.
- Original evidence: `evidence/qa-20261002/reviews/security_runtime/authority-runtime-expanded2.log`. Green evidence: `evidence/qa-20261002/reviews/security_runtime/fix-regression-stable.log`.
- Coverage/limit: Unused spoofed key headers and rotated JWTs retain the accepted credential bucket; no live Redis.

### [SEC-005 · #507](https://github.com/PetrefiedThunder/agent-middleware-api/issues/507) — Readiness probe returns healthy HTTP status during dependency failure

- Correction: Probe required ORM and durable-state dependencies with bounded waits; return HTTP 503 when unavailable. Fix commits: `4a4fc75`.
- Current code: `app/core/health.py; app/main.py`. Current regression: `tests/test_readiness_fail_closed.py`.
- Original evidence: `evidence/qa-20261002/reviews/security_runtime/authority-runtime-expanded2.log`. Green evidence: `evidence/qa-20261002/reviews/security_runtime/fix-regression-stable.log`.
- Coverage/limit: Required DB/state exceptions and bounded timeouts return 503; synthetic fault injection.

### [SEC-006 · #508](https://github.com/PetrefiedThunder/agent-middleware-api/issues/508) — Late IGA compensation erases a different invocation velocity reservation

- Correction: Compensate the exact identity-bearing IGA velocity reservation once; never remove a newer invocation reservation. Fix commits: `13c7097`.
- Current code: `app/core/oidc_iga.py; app/routers/mcp.py`. Current regression: `tests/test_iga_compensation_identity.py; tests/test_iga_policy.py; tests/test_action_preacceptance.py`.
- Original evidence: `evidence/qa-20261002/reviews/security_runtime/authority-runtime-expanded2.log`. Green evidence: `evidence/qa-20261002/reviews/security_runtime/fix-regression-stable.log`.
- Coverage/limit: Exact reservation identity, stale compensation and double/mismatched release; process-local counters remain process-local.

### [SEC-007 · #525](https://github.com/PetrefiedThunder/agent-middleware-api/issues/525) — Concurrent valid append makes audit verification falsely report truncation

- Correction: Read audit head and bounded event stream from one SQL statement snapshot, retaining real truncation detection. Fix commits: `ee32061`.
- Current code: `app/services/audit_chain.py`. Current regression: `tests/test_audit_snapshot.py`.
- Original evidence: `evidence/qa-20261002/reviews/security_runtime/audit-snapshot.log`. Green evidence: `evidence/qa-20261002/reviews/security_runtime/fix-regression-stable.log`.
- Coverage/limit: Single-statement snapshot prevents false truncation under a concurrent valid append; actual truncation checks retained in source.

### [SEC-008 · #526](https://github.com/PetrefiedThunder/agent-middleware-api/issues/526) — AWI performs effects before budget/debit and repeats them after reservation contention

- Correction: Reserve permit authority and checkpoint an operation-key debit before any of six AWI callbacks. Preserve owners across ambiguous errors/process death; refund only proven non-dispatch, and replay receipts without redispatch. Fix commits: `cb8d2f8`, `2c6f429`.
- Current code: `app/services/awi_http_governance.py; app/services/idempotency.py; app/routers/awi.py; app/routers/awi_enhanced.py`. Current regression: `tests/test_awi_admission_ordering.py; tests/test_awi_admission_process.py; tests/test_awi_http_governance.py`.
- Original evidence: `evidence/qa-20261002/reviews/security_runtime/awi-ordering2.log`. Green evidence: `evidence/qa-20261002/reviews/awi_ordering/original-green.log`; `evidence/qa-20261002/reviews/awi_ordering/final-sqlite.log`; `evidence/qa-20261002/reviews/awi_ordering/pg-final.log`.
- Coverage/limit: Six callbacks, empty wallet, contention, charged checkpoint, receipt acknowledgment loss and fresh-process crash boundaries. Ambiguous owners need manual reconciliation.

### [SEC-009 · #584](https://github.com/PetrefiedThunder/agent-middleware-api/issues/584) — SQLite permit issuance signs values that change during persistence

- Correction: Reject permit max_credits/aggregate caps that cannot survive exact storage before signing; preserve the numeric bounds in generated schemas. Fix commits: `f27c213`, `34040b3`.
- Current code: `app/core/credits.py; app/schemas/trust.py; app/services/permits.py`. Current regression: `tests/test_permit_numeric_storage.py; tests/test_permit_request_flow.py; tests/test_permit_issuance_retry.py`.
- Original evidence: `evidence/qa-20261002/reviews/security_runtime/independent-permit-numeric-ef64d02.log`. Green evidence: `evidence/qa-20261002/reviews/accounting_data/resume-numeric-green.log`; `evidence/qa-20261002/reviews/accounting_data/resume-numeric-postgres-v2.log`; `evidence/qa-20261002/reviews/accounting_data/resume-schema-green.log`.
- Coverage/limit: Reject nonrepresentable signed values before write; numeric rejection retains AE-001 exact-owner cleanup. Existing persisted records are not rewritten.

## Fresh execution

Command prefix: `uv run --with-requirements requirements.txt pytest --tb=short`; exact 29-file argument list is recorded in `focused-result.json`. The environment retained only user/runtime path variables and set a task-owned synthetic SQLite database plus memory state. No inherited provider credentials were passed. No tests were deselected by marker.

```text
============================= 576 passed in 31.09s =============================
```

Besides the per-issue acceptance files, `tests/test_trust_negative_security.py` and `tests/test_tenant_isolation_hardening.py` passed in the same process. These cover unauthorized access, tenant boundaries, signed authority and replay behavior alongside the repairs.

## Limits and final gate

Current execution used SQLite and synthetic/mocked providers. Original PostgreSQL pool, AWI, and numeric evidence was inspected, but this reviewer did not rerun PostgreSQL or touch the root-owned databases. No live browser, WebAuthn provider, MQTT broker, vector store, external LLM, production credential, payment rail, deployment or customer workflow was exercised. Frozen/default-unmounted proof surfaces remain frozen.

Ambiguous admitted AWI operations may retain keys, debit and/or reserved authority until manual reconciliation. That conservative result is part of the reviewed contract. Historical records and legacy hash identities were not migrated.

The coordinator owns integration of later worker commits, focused review of their diffs, final combined validation, and remote release decisions. This report accepts only the stated 28-issue review scope at the stated candidate and does not approve a later candidate automatically.

## Follow-up backend commit review

Read-only independent review of `eefd1c1d7d57c59e53d12774298545e0dbabe799` found no blocking defect. Reviewed its complete runtime and regression diff, generated OpenAPI security delta, and saved red/green logs. This commit was not checked out or executed by this reviewer; the coordinator must run it on the final combined candidate.

- BE-002: `HTTPBearer(auto_error=False)` contributes an OpenAPI OR alternative. The parsed result is deliberately unused; raw Authorization still goes through the existing strict parser and cannot fall back to X-API-Key on malformed credentials. Direct-call compatibility remains intact.
- BE-003: both guards explicitly reject multicast as well as nonglobal addresses. The check evaluates every DNS answer, including mixed public/multicast answers. The upstream loopback exception still requires a local environment, an explicit loopback host, and every resolved address to be loopback. The general guard retains its separately documented local override and DNS-rebinding limitation.
- Confirmed owner evidence in `/tmp/amw-all-issues-20261002/backend/`: `red.log` records 28 failures and 12 passing controls before the change; `green.log` records 235 passes after it. These results are owner execution, separate from the 576 tests independently run above.

## Frozen documentation and frontend follow-ups

Read-only review found no blocking defect in documentation commit `7aa67f48e7c84cc5e996eddbdb94b833e460c0de` or frontend commit `45eccbcc4b797967ab9559af2c7073eaea610f6f`. Verified the reviewed source files match their committed blobs. These commits were not checked out or independently executed here.

- Documentation: read the complete three-file BE-100 wording diff. It limits dispatch guarantees to the configured upstream MCP tool, receipt claims to finalized/reconciled outcomes, and explicitly describes missing receipts, manual reconciliation, and the danger of fresh-key retries. All 20 QA-CLIENT catalog IDs, issue URLs and original fix commits match the saved disposition input. The catalog keeps original, owner, aggregate, deployment and customer evidence separate.
- Frontend/SDK: the nullish default preserves explicit zero and other limits for API validation; the Axios-adapter test observes serialized payloads and propagated rejection. The new TypeScript project emits CommonJS JavaScript and declarations at the package's declared entrypoints. The package remains private. No dependency was added. The CSS change targets only the paper comparison card. The operator command block is keyboard-focusable and named, runtime/discovery links resolve on the served origin, and hosted public proof remains explicitly separate.
- Inspected owner browser probe and `browser-results.json`: Chromium, Firefox and WebKit all record paper contrast 2.1308:1 before and 6.9376:1 after, clearing the two targeted axe checks. Fixed command regions receive keyboard focus and scroll; WebKit's original region cannot receive Tab focus, while the fixed region scrolls 164px. All fixed runtime URLs are loopback-origin URLs. The probe aborts non-preview-origin browser requests. These are owner browser results, not a new gate browser run.
- Inspected SDK package dry-run JSON: both `dist/index.js` and `dist/index.d.ts` are included. Saved SDK negative control observes `100 !== 0`; fixed log has two passing cases. Owner frontend Python log records 85 passes, and site design log records 78 scenarios. No published package, deployed API, native Safari/mobile device or screen reader was exercised by this reviewer.
- Backend generated contract cross-check: after removing only HTTPBearer scheme/alternative additions, parsed `docs/openapi.json` at `eefd1c1` is identical to the base. This confirms the declared schema scope without relying solely on the owner's report.

Final combined-candidate execution and release acceptance remain coordinator-owned. These focused reviews do not silently extend the independently executed 576-test result to new source revisions.
