# Clients and documentation issue resolution — 2026-10-02

## Scope and evidence boundary

Verified base: `f82700f750862b6e51566a46dfc559e5b81e0a95`. Worktree: `/Users/sellers/.openclaw/worktrees/amw-issues-20261002-docs`; branch: `openclaw/amw-issues-20261002-docs`; origin: `https://github.com/PetrefiedThunder/agent-middleware-api.git`. The checkout was clean before edits. All 20 saved QA-CLIENT findings are accounted for: 18 existing local repairs and two explicit retirements. They were not reimplemented. All 12 distinct original fix/follow-up commits resolve locally and are ancestors of this base; the machine-readable check is saved in `/tmp/amw-all-issues-20261002/docs/original-fix-ancestry.json`.

The only product-documentation changes in this lane repair BE-100 in the self-credentialing guide, tool-interface guide and elevator pitch. No runtime code, API, schema, authentication policy, provider setting or dependency was changed. Issue closure and deployment acceptance are separate from the local findings below.

[PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is the existing QA evidence PR. The coordinator read it as draft/open at head `359d56393ee950dc4d826164e223f17b28ec8587` during this task. Its `docs/qa/2026-10-02/FINDINGS.md` records BE-100 and explicitly says its product findings were unfixed. It is **audit evidence, not a fix PR**, and this report does not invent remote links for the local original fix commits. The common issue is [#499](https://github.com/PetrefiedThunder/agent-middleware-api/issues/499).

The saved issue snapshot is `/tmp/amw-all-issues-20261002/issues.json`. Historical disposition source: [`finding-dispositions.json`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/integration/finding-dispositions.json>). That source freezes candidate `24b7ae4`, which is an ancestor of `f82700f`; its aggregate status was explicitly not accepted. Historical test totals below are retained subset evidence, not a claim that the historical final full suite completed. The fresh validation in this report is limited to this lane and must not be counted as deployment or customer proof.

## Fresh validation

All commands ran from the assigned worktree. Python uses the already installed AMW main-checkout interpreter at `/Users/sellers/Projects/agent-middleware-api/.venv/bin/python`; no RegEngine interpreter was used. Pytest processes ran serially because these tests use a worktree-local SQLite fixture.

| Check | Result | Log under `/tmp/amw-all-issues-20261002/docs/` |
|---|---|---|
| Focused client, docs, receipt-failure and site contracts | 69 passed in 16.10s | `focused-python.log` |
| SDK permit verifier and standalone retirement | 33 passed in 0.06s | `sdk-regressions-rerun.log` |
| Actual arcade gameplay factories with local recording/stub helpers | 6 passed | `arcade-regressions.log` |
| Code comment/docstring symbol references | 678 references across 274 files resolve | `docrefs.log` |
| Self-credentialing shell/dotenv recipe, without executing generation | Passed | `credentialing-doc-static.log` |
| Twelve unique original fix commits are ancestors of `f82700f` | Passed | `original-fix-ancestry.json` |
| Catalog source and retained-evidence links | 161 links resolve, 91 unique local paths | `catalog-links.log` |
| Configured pre-commit run for the four Markdown files | Exit 0; Ruff, Ruff formatting and mypy correctly skip non-Python files | `pre-commit.log` |
| Staged Gitleaks scan | No leaks found | `gitleaks-staged.log` |

The first SDK command collected zero tests and returned two import errors because its own `b2a_sdk/pyproject.toml` selected a root without the source path. The unchanged test run passed after setting `PYTHONPATH=b2a_sdk/src`; the initial failure remains in `sdk-regressions.log`. This was a test invocation correction, not a code repair. The doc-reference script checks Python prose symbols; it does not itself validate the semantic truth of these Markdown claims.

```text
/Users/sellers/Projects/agent-middleware-api/.venv/bin/python -m pytest tests/test_sdk_action_permit_contract.py tests/test_wrapper_permit_retry_contract.py tests/test_framework_legacy_client.py tests/test_discovery_honesty.py tests/test_onboarding_doc_contracts.py tests/test_operator_doc_contracts.py tests/test_historical_probe_retirement.py tests/test_receipt_write_contention_surface.py tests/test_site_agent_interface.py::test_public_surfaces_separate_public_proof_from_private_source_access tests/test_site_agent_interface.py::test_arcade_ships_as_progressive_enhancement -ra
PYTHONPATH=b2a_sdk/src /Users/sellers/Projects/agent-middleware-api/.venv/bin/python -m pytest b2a_sdk/tests/test_local_permit_validator.py b2a_sdk/tests/test_mcp_retirement.py -ra
node --test tests/test_arcade_regressions.mjs
/Users/sellers/Projects/agent-middleware-api/.venv/bin/python scripts/check_doc_references.py
```

## BE-100 — receipt completion and local/upstream distinctions

**New scoped repair in this lane.** The original QA source names `docs/agent-self-credentialing.md`, `docs/tool-interface-authority.md` and `ELEVATOR_PITCH.md`. They retained unconditional one-debit/one-finalized-receipt wording, an exactly-once dispatch pipeline without the upstream qualifier, and an identical local/upstream governance claim.

**Implementation evidence.** [`app/routers/mcp.py`](../../app/routers/mcp.py) defines `TerminalRecordContendedError` and `_terminal_record_contended_data`: committed effects can coexist with zero receipts, the response requires manual review, and a fresh-key retry can run and charge again. `_execute_registered_tool` creates a dispatch service only when `execution_backend == "upstream_mcp"`; local governed tools have no corresponding dispatch state machine. [`tests/test_receipt_write_contention_surface.py`](../../tests/test_receipt_write_contention_surface.py) covers both legacy and standard transports.

**Wording now used.** An accepted identity permits at most one debit and, for the configured upstream MCP tool, at most one gateway dispatch. Receipts describe outcomes that finalize or reconcile. Local crashes or exhausted receipt/audit writes after effects may require manual review without a receipt. Upstream `delivery_uncertain` is receipted when finalization/reconciliation succeeds. Gateway dispatch authority does not prove a downstream effect; controlled local dogfood replay does not prove upstream crash recovery. Unresolved effects must not be retried under a fresh key.

**Validation and limit.** Eleven existing receipt-contention regressions passed within the fresh 69-test run; the standard-transport negative path explicitly asserts one tool execution and zero receipts with `manual_review_required`. This is a documentation correction reflecting tested existing behavior, not a new receipt-completion guarantee. PostgreSQL crash proof and deployment/provider execution were not run in this lane.

## Per-issue disposition

### QA-CLIENT-001 — SDK local permit verification rejects valid action-bound permits

Issue: [#509](https://github.com/PetrefiedThunder/agent-middleware-api/issues/509). Disposition: **local fixed**; present before this task.

**Original defect.** The SDK previously omitted six action-binding fields when rebuilding a permit signature. Genuine server-issued action permits therefore failed local verification.

**Original fix commits.** `02622db97980975d26377235c1ce4d606a0c0774`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** `LocalPermitValidator.permit_signing_payload` adds all six fields before calculating the payload hash, rejects incomplete bindings and malformed hashes, and requires an integer contract version of 1. Null or absent binding fields preserve legacy signed bytes.

**Inspected source and retained tests.** [`b2a_sdk/src/b2a_sdk/edge_client.py`](../../b2a_sdk/src/b2a_sdk/edge_client.py), [`app/services/permits.py`](../../app/services/permits.py), [`tests/test_sdk_action_permit_contract.py`](../../tests/test_sdk_action_permit_contract.py), [`b2a_sdk/tests/test_local_permit_validator.py`](../../b2a_sdk/tests/test_local_permit_validator.py).

**Fresh acceptance.** The fresh 69-test run includes server-signature reconstruction and `GovernedEdgeSession.open` through a mock transport. The separate 33-test SDK run includes per-field tampering, genuinely signed malformed bindings, unknown keys, legacy compatibility and refusal before local execution.

**Retained original evidence.** [`test_sdk_action_signature.py`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_sdk_action_signature.py>), [`sdk-action-red.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/sdk-action-red.log>), [`sdk-action-red-result.json`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/sdk-action-red-result.json>). Passing historical subset: [`action-fix-stable.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/action-fix-stable.log>). Historical review artifact: [`independent-security-client-review.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** This verifies local cryptographic compatibility and the server/SDK contract. It does not make cached local authorization authoritative over current server budget or revocation state.

### QA-CLIENT-002 — Framework wrapper retry changes permit body after a lost creation response

Issue: [#510](https://github.com/PetrefiedThunder/agent-middleware-api/issues/510). Disposition: **local fixed**; present before this task.

**Original defect.** After an accepted permit-creation request lost its response, a wrapper regenerated its expiry on retry. The same idempotency key then carried a different request body.

**Original fix commits.** `0bf6151eb94bbb35562e3d2f856fa16bc259b153`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** Each wrapper stores the original `PermitRequest` before its first await. A response loss or concurrent caller reuses that body; a successful acknowledgement records the permit ID. Changed tool, wallet or budget terms are refused under the cached permit key.

**Inspected source and retained tests.** [`wrappers/autogen-agent-middleware/src/autogen_b2a/tool.py`](../../wrappers/autogen-agent-middleware/src/autogen_b2a/tool.py), [`wrappers/crewai-agent-middleware/src/crewai_b2a/tool.py`](../../wrappers/crewai-agent-middleware/src/crewai_b2a/tool.py), [`wrappers/langchain-agent-middleware/src/langchain_b2a/_tools.py`](../../wrappers/langchain-agent-middleware/src/langchain_b2a/_tools.py), [`tests/test_wrapper_permit_retry_contract.py`](../../tests/test_wrapper_permit_retry_contract.py).

**Fresh acceptance.** All 17 retained wrapper contract cases passed in the fresh 69-test run: lost acknowledgement, concurrent same-key creation, changed authority, mutated wallet/budget and CrewAI synchronous entry. The gateway is an HTTPX mock that compares complete request bytes and accepted invoke keys.

**Retained original evidence.** [`test_wrapper_retry_contract.py`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_wrapper_retry_contract.py>), [`wrapper-retry-red.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/wrapper-retry-red.log>), [`wrapper-retry-red-result.json`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/wrapper-retry-red-result.json>). Passing historical subset: [`wrapper-fix-tests.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/wrapper-fix-tests.log>). Historical review artifact: [`independent-security-client-review.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** The cache survives retries in that wrapper instance. No process-restart durability or real optional-framework runtime certification is claimed; missing framework imports use narrow test boundaries.

### QA-CLIENT-003 — Legacy SDK standalone MCP command and generated scripts are unusable

Issue: [#511](https://github.com/PetrefiedThunder/agent-middleware-api/issues/511). Disposition: **retired with explicit refusal**; present before this task.

**Original defect.** The legacy standalone generator exposed a command and emitted scripts that could not support the advertised invocation path.

**Original fix commits.** `e4a046bc65c833c9765315355be0c4c1fd99e08b`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** `generate_standalone_server` now raises a controlled retirement error directing callers to governed `POST /mcp/messages`. The CLI accepts existing arguments and exits 2 before discovery or output writes.

**Inspected source and retained tests.** [`b2a_sdk/src/b2a_sdk/mcp.py`](../../b2a_sdk/src/b2a_sdk/mcp.py), [`b2a_sdk/tests/test_mcp_retirement.py`](../../b2a_sdk/tests/test_mcp_retirement.py), [`docs/agent-recipes.md`](../../docs/agent-recipes.md).

**Fresh acceptance.** Seven retirement cases passed in the fresh 33-test SDK run. Tests forbid discovery and assert that absent files stay absent, existing output contents remain intact, and the CLI returns exit 2.

**Retained original evidence.** [`test_sdk_mcp_cli_contract.py`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_sdk_mcp_cli_contract.py>), [`sdk-mcp-red.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/sdk-mcp-red.log>), [`sdk-mcp-red-result.json`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/sdk-mcp-red-result.json>). Passing historical subset: [`resumed-stable-suite.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log>). Historical review artifact: [`clients-review-infra.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** Resolution is an explicit support-boundary refusal, not a functioning standalone generator. The remaining legacy discovery/serving helpers are outside this finding.

### QA-CLIENT-004 — Legacy framework client omits current discovery authentication and AWI governance inputs

Issue: [#530](https://github.com/PetrefiedThunder/agent-middleware-api/issues/530). Disposition: **local fixed**; present before this task.

**Original defect.** The legacy framework client omitted authentication on discovery and did not carry current AWI permit/idempotency inputs.

**Original fix commits.** `8e5e684d3d2fcae9a53330b45be4e467e80fba64`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** `B2AClient.discover` sends the configured authentication headers. `execute_awi_action` requires caller-provided permit and idempotency values, validates blank and excessive-length input, and forwards the original retry key without trimming it.

**Inspected source and retained tests.** [`framework_integrations/client.py`](../../framework_integrations/client.py), [`tests/test_framework_legacy_client.py`](../../tests/test_framework_legacy_client.py).

**Fresh acceptance.** All 17 legacy client cases passed in the fresh 69-test run. The transport records exact headers; invalid inputs cause no request. Route-level cases also verify replay accounting, changed-request conflict, cross-wallet refusal and invalid-key refusal.

**Retained original evidence.** [`test_framework_discovery_contract.py`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_framework_discovery_contract.py>), [`framework-discovery-red.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/framework-discovery-red.log>), [`framework-discovery-red-result.json`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/framework-discovery-red-result.json>). Passing historical subset: [`legacy-client-stable.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/legacy-client-stable.log>). Historical review artifact: [`independent-security-client-review.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** This repairs the client contract. It does not certify every dormant AWI workload or turn those workloads into a supported production product surface.

### QA-CLIENT-005 — AWI discovery still denies permit enforcement on governed HTTP routes

Issue: [#531](https://github.com/PetrefiedThunder/agent-middleware-api/issues/531). Disposition: **local fixed**; present before this task.

**Original defect.** AWI discovery described permit enforcement as absent even where HTTP routes already required governance headers.

**Original fix commits.** `740098d11c30e04f3f6fb534ed627e8865f6e44a`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** `AWI_HTTP_PERMIT_ENDPOINTS` lists the six governed HTTP endpoints with `X-Permit-Id` and `Idempotency-Key`; RAG query additionally needs `X-Wallet-Id`. Broad all-route governance metadata is replaced by this bounded route inventory.

**Inspected source and retained tests.** [`app/routers/well_known.py`](../../app/routers/well_known.py), [`app/routers/discover.py`](../../app/routers/discover.py), [`tests/test_discovery_honesty.py`](../../tests/test_discovery_honesty.py).

**Fresh acceptance.** Five discovery tests passed in the fresh 69-test run. The route-inventory test parses actual `begin_awi_http_governed` calls and compares their endpoint set with the manifest. It also preserves the proof-surface label and excludes session creation from the guarded list.

**Retained original evidence.** [`test_framework_discovery_contract.py`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_framework_discovery_contract.py>), [`framework-discovery-red.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/framework-discovery-red.log>), [`framework-discovery-red-result.json`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/framework-discovery-red-result.json>). Passing historical subset: [`discovery-claims-stable.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/discovery-claims-stable.log>). Historical review artifact: [`independent-security-client-review.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** The metadata correction is not acceptance of AWI execution, accounting or admission behavior. Those findings have separate backend ownership.

### QA-CLIENT-006 — Public site and bootstrap manifests claim private source repository is public

Issue: [#532](https://github.com/PetrefiedThunder/agent-middleware-api/issues/532). Disposition: **local fixed**; present before this task.

**Original defect.** Public site and bootstrap metadata advertised unauthenticated access to a repository whose saved audit metadata reported private visibility.

**Original fix commits.** `817ccd52e3efde57b8be3ebdbf171e674663ec30`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** Source-access copy now requires granted repository access while preserving public proof and public-key downloads. The original repair changed copy and manifests, not repository access settings.

**Inspected source and retained tests.** [`app/routers/well_known.py`](../../app/routers/well_known.py), [`site/.well-known/agent.json`](../../site/.well-known/agent.json), [`site/index.html`](../../site/index.html), [`site/proof/index.html`](../../site/proof/index.html), [`site/compare/index.html`](../../site/compare/index.html), [`site/llms.txt`](../../site/llms.txt), [`site/llms-full.txt`](../../site/llms-full.txt), [`static/llm.txt`](../../static/llm.txt), [`tests/test_site_agent_interface.py`](../../tests/test_site_agent_interface.py).

**Fresh acceptance.** `test_public_surfaces_separate_public_proof_from_private_source_access` passed in the fresh 69-test run after rendering the current site. It checks every named machine/human surface for the private-source distinction. The original finding records a coordinator metadata read at 2026-10-02 21:33 UTC.

**Retained original evidence.** [`findings.json`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/findings.json>). Passing historical subset: [`source-claims-stable.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/source-claims-stable.log>). Historical review artifact: [`independent-security-client-review.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** The current run checks copy consistency; it does not refresh live repository visibility or public artifact availability. The old catalog includes generated manifest paths as negative evidence; those are generated snapshots, not independent failed tests. The original `findings.json` record is the primary retained finding.

### QA-CLIENT-007 — Agent self-credentialing guide writes unevaluated shell substitution into dotenv signing key

Issue: [#538](https://github.com/PetrefiedThunder/agent-middleware-api/issues/538). Disposition: **local fixed**; present before this task.

**Original defect.** The self-credentialing guide placed a shell substitution inside dotenv, which stores the unevaluated text rather than generating a signing seed.

**Original fix commits.** `028e36e8cf66a0b80ce0d232b724e3df483db92e`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** The dotenv block contains literal non-secret settings. A separate shell block exports a fresh local seed and starts the loopback server in the same shell. The existing fix remains intact; this task only changes the later claim boundary for BE-100.

**Inspected source and retained tests.** [`docs/agent-self-credentialing.md`](../../docs/agent-self-credentialing.md).

**Fresh acceptance.** `credentialing-doc-static.log` confirms no substitution/signing seed appears in the literal dotenv block, the shell block exports the seed, startup binds `127.0.0.1`, and `bash -n` accepts the snippet. No seed generation or server launch was executed.

**Retained original evidence.** [`test_doc_credentialing_seed.py`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_doc_credentialing_seed.py>), [`credentialing-doc-red.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/credentialing-doc-red.log>), [`credentialing-doc-red-result.json`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/credentialing-doc-red-result.json>). Passing historical subset: [`credentialing-doc-stable.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/credentialing-doc-stable.log>). Historical review artifact: [`independent-security-client-review.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** Static recipe verification does not establish a booted local or production instance. The original failing probe targets the historical pre-fix wording and is retained as historical evidence, not rerun as a current regression.

### QA-CLIENT-008 — Key Rotation can consume multiple lives in one update despite granting invulnerability

Issue: [#560](https://github.com/PetrefiedThunder/agent-middleware-api/issues/560). Disposition: **local fixed**; present before this task.

**Original defect.** Key Rotation could charge multiple lives within one update because later sweepers ignored invulnerability granted by the first collision.

**Original fix commits.** `3e6d52e404f724d62a3b8d52e5a9ee3172afa2d0`, `dd834f0c80d8d77cf5ac62165801657fd3f1ae93`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** The sweeper loop checks invulnerability at each collision decision. The subsequent cache-busting commit changes delivered script references so a deployed page can receive the repaired code.

**Inspected source and retained tests.** [`site/arcade.js`](../../site/arcade.js), [`tests/test_arcade_regressions.mjs`](../../tests/test_arcade_regressions.mjs), [`site/build_site.py`](../../site/build_site.py), [`tests/test_site_agent_interface.py`](../../tests/test_site_agent_interface.py).

**Fresh acceptance.** The fresh six-case Node run tests three deterministic seeds for 6,000 frames or game end, exercises collisions, permits at most one life lost per update, enforces the invulnerability interval and prevents negative lives. The fresh site test checks shipped arcade references.

**Retained original evidence.** [`check_arcade_cabinets.cjs`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/check_arcade_cabinets.cjs>), [`arcade-cabinet-check.json`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/arcade-cabinet-check.json>). Passing historical subset: [`resumed-stable-suite.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log>), [`resumed-stable-arcade.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-arcade.log>), [`ux-cache-site-tests.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/ux-cache-site-tests.log>). Historical review artifact: [`clients-review-infra.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** The Node harness executes actual gameplay factories with local Canvas/animation stubs. No browser rendering, deployment propagation or real user play session is claimed.

### QA-CLIENT-009 — Happy Path draws the player twelve pixels above its collision position

Issue: [#561](https://github.com/PetrefiedThunder/agent-middleware-api/issues/561). Disposition: **local fixed**; present before this task.

**Original defect.** Happy Path rendered the player body twelve pixels above the position used for collisions.

**Original fix commits.** `3e6d52e404f724d62a3b8d52e5a9ee3172afa2d0`, `dd834f0c80d8d77cf5ac62165801657fd3f1ae93`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** Rendering now uses the same player origin as ground and platform collision checks. The cache-busting follow-up updates shipped script references.

**Inspected source and retained tests.** [`site/arcade.js`](../../site/arcade.js), [`tests/test_arcade_regressions.mjs`](../../tests/test_arcade_regressions.mjs), [`site/build_site.py`](../../site/build_site.py), [`tests/test_site_agent_interface.py`](../../tests/test_site_agent_interface.py).

**Fresh acceptance.** The fresh Node run records Canvas rectangle calls and verifies visible feet on the ground before and after jumping, and on a known platform landing. Both cases retain all three lives. The current site shipping contract also passed.

**Retained original evidence.** [`check_arcade_cabinets.cjs`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/check_arcade_cabinets.cjs>), [`arcade-cabinet-check.json`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/arcade-cabinet-check.json>). Passing historical subset: [`resumed-stable-suite.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log>), [`resumed-stable-arcade.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-arcade.log>), [`ux-cache-site-tests.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/ux-cache-site-tests.log>). Historical review artifact: [`clients-review-infra.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** This verifies geometry and simulation state, not physical browser pixels or assistive-technology behavior.

### QA-CLIENT-010 — Tap Forge discards passive quota earnings on every animation frame

Issue: [#562](https://github.com/PetrefiedThunder/agent-middleware-api/issues/562). Disposition: **local fixed**; present before this task.

**Original defect.** Tap Forge rounded passive quota earnings on every animation frame, discarding fractional progress at normal frame rates.

**Original fix commits.** `3e6d52e404f724d62a3b8d52e5a9ee3172afa2d0`, `dd834f0c80d8d77cf5ac62165801657fd3f1ae93`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** Fractional passive quota carries across frames; reset clears the carry. The later script-reference change makes the repaired asset eligible for cache replacement.

**Inspected source and retained tests.** [`site/arcade.js`](../../site/arcade.js), [`tests/test_arcade_regressions.mjs`](../../tests/test_arcade_regressions.mjs), [`site/build_site.py`](../../site/build_site.py), [`tests/test_site_agent_interface.py`](../../tests/test_site_agent_interface.py).

**Fresh acceptance.** The fresh Node run buys a signer and compares passive progress at 1, 30 and 60 Hz, then checks manual minting and reset. Each rate preserves the same ten whole quota units from 10.8 earned units.

**Retained original evidence.** [`check_arcade_progress.cjs`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/check_arcade_progress.cjs>), [`arcade-progress-check.json`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/arcade-progress-check.json>). Passing historical subset: [`resumed-stable-suite.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log>), [`resumed-stable-arcade.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-arcade.log>), [`ux-cache-site-tests.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/ux-cache-site-tests.log>). Historical review artifact: [`clients-review-infra.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** Only deterministic local gameplay logic and current shipped references were verified; hosted cache state is unverified.

### QA-CLIENT-011 — Security reviewer claim omits local invocations that cannot produce a receipt

Issue: [#563](https://github.com/PetrefiedThunder/agent-middleware-api/issues/563). Disposition: **local fixed**; present before this task.

**Original defect.** The security-review claim implied every invocation produces terminal receipt evidence despite local post-effect crash paths.

**Original fix commits.** `ed6b396d0290de8904b9ac6db6e90626ad0ad1aa`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** The original repair restricts the claim to terminalized/reconciled invocations and explicitly describes local manual review without a receipt. BE-100 extends that same correction to three other integration/pitch pages in this task.

**Inspected source and retained tests.** [`docs/security-review-kit.md`](../../docs/security-review-kit.md), [`docs/failure-semantics.md`](../../docs/failure-semantics.md), [`tests/test_onboarding_doc_contracts.py`](../../tests/test_onboarding_doc_contracts.py), [`tests/test_receipt_write_contention_surface.py`](../../tests/test_receipt_write_contention_surface.py), [`app/routers/mcp.py`](../../app/routers/mcp.py).

**Fresh acceptance.** The onboarding contract and all eleven receipt-contention cases passed in the fresh 69-test run. On standard `/mcp`, exhaustion after execution returns `manual_review_required` with `reconcile_out_of_band`; the tool ran once and the receipt count is zero.

**Retained original evidence.** [`test_docs_contracts.py`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_docs_contracts.py>), [`docs-contract-controls.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/docs-contract-controls.log>). Passing historical subset: [`resumed-stable-suite.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log>). Historical review artifact: [`clients-review-infra.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** A missing receipt is not evidence that no charge or effect occurred. Receipts and upstream crash recovery remain different from controlled local replay proof.

### QA-CLIENT-012 — Golden-path dogfood substitution leaves incompatible message arguments

Issue: [#564](https://github.com/PetrefiedThunder/agent-middleware-api/issues/564). Disposition: **local fixed**; present before this task.

**Original defect.** The golden-path dogfood substitution changed the tool name but retained incompatible `message` arguments.

**Original fix commits.** `ed6b396d0290de8904b9ac6db6e90626ad0ad1aa`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** The guide now replaces `message` with `text` for both the first invocation and its identical replay.

**Inspected source and retained tests.** [`docs/golden-path.md`](../../docs/golden-path.md), [`app/services/dogfood_tool.py`](../../app/services/dogfood_tool.py), [`tests/test_onboarding_doc_contracts.py`](../../tests/test_onboarding_doc_contracts.py).

**Fresh acceptance.** `test_golden_path_dogfood_arguments_bind_without_invoking_tool` passed. It parses the real `_write_note` function signature, replaces the body with `pass`, and binds the documented JSON without creating an on-disk note.

**Retained original evidence.** [`test_docs_contracts.py`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_docs_contracts.py>), [`docs-contract-controls.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/docs-contract-controls.log>). Passing historical subset: [`resumed-stable-suite.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log>). Historical review artifact: [`clients-review-infra.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** The check proves argument compatibility while deliberately performing no tool effect. It is not a live end-to-end onboarding run.

### QA-CLIENT-013 — Partner offline-verification install command omits required verify extra

Issue: [#565](https://github.com/PetrefiedThunder/agent-middleware-api/issues/565). Disposition: **local fixed**; present before this task.

**Original defect.** The partner offline-verifier install commands omitted the SDK extra that provides the cryptographic verification dependency.

**Original fix commits.** `ed6b396d0290de8904b9ac6db6e90626ad0ad1aa`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** Both source and wheel recipes include `[verify]`, matching the optional verifier dependency group.

**Inspected source and retained tests.** [`docs/partner-first-tool-runbook.md`](../../docs/partner-first-tool-runbook.md), [`b2a_sdk/pyproject.toml`](../../b2a_sdk/pyproject.toml), [`tests/test_onboarding_doc_contracts.py`](../../tests/test_onboarding_doc_contracts.py).

**Fresh acceptance.** The source/wheel recipe contract passed in the fresh 69-test run. SDK permit verification also passed with the existing environment; no dependency installation was needed for this task.

**Retained original evidence.** [`test_docs_contracts.py`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_docs_contracts.py>), [`docs-contract-controls.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/docs-contract-controls.log>). Passing historical subset: [`resumed-stable-suite.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log>). Historical review artifact: [`clients-review-infra.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** A fresh machine installation, wheel publication and fully offline receipt CLI exercise were not performed in this lane.

### QA-CLIENT-014 — CI bootstrap recipe combines credentials from three separate provisioning runs

Issue: [#566](https://github.com/PetrefiedThunder/agent-middleware-api/issues/566). Disposition: **local fixed**; present before this task.

**Original defect.** The CI bootstrap example separately provisioned the API key, wallet and key ID, mixing three identities.

**Original fix commits.** `ed6b396d0290de8904b9ac6db6e90626ad0ad1aa`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** The primary example provisions once, extracts every identity field from that one JSON response, disables shell tracing and unsets the response variable afterward.

**Inspected source and retained tests.** [`docs/constant-test-loop.md`](../../docs/constant-test-loop.md), [`tests/test_onboarding_doc_contracts.py`](../../tests/test_onboarding_doc_contracts.py).

**Fresh acceptance.** `test_ci_recipe_exports_one_provisioned_identity` passed in the fresh 69-test run. A local fake Python executable counts invocations and returns only synthetic identity data; the shell recipe must export key, wallet and key ID from invocation 1.

**Retained original evidence.** [`test_bootstrap_docs.py`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_bootstrap_docs.py>), [`bootstrap-doc-red.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/bootstrap-doc-red.log>). Passing historical subset: [`resumed-stable-suite.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log>). Historical review artifact: [`clients-review-infra.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** No production provisioning command was run and no credential store was read. The test proves shell data flow, not operator permission or production bootstrap success.

### QA-CLIENT-015 — Legacy database guidance recommends stamping current head without schema equivalence

Issue: [#567](https://github.com/PetrefiedThunder/agent-middleware-api/issues/567). Disposition: **local fixed**; present before this task.

**Original defect.** Legacy database guidance recommended stamping head when tables existed, without proving schema and migration-history equivalence.

**Original fix commits.** `7cb38a46581ae6f172f8e21e349c87b5afa83699`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** Existing unstamped tables require manual physical-schema and data-migration-history review. Only a proven matching historical revision may be stamped before the controlled rollout applies required migrations.

**Inspected source and retained tests.** [`docs/deploy-railway.md`](../../docs/deploy-railway.md), [`docs/human-onboarding.md`](../../docs/human-onboarding.md), [`scripts/railway_preflight.py`](../../scripts/railway_preflight.py), [`tests/test_operator_doc_contracts.py`](../../tests/test_operator_doc_contracts.py).

**Fresh acceptance.** Both legacy-database documentation contracts passed in the fresh 69-test run and explicitly reject the former stamp-head wording. Inspection confirms the guidance points to the controlled schema rollout.

**Retained original evidence.** [`test_operator_docs.py`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_operator_docs.py>), [`operator-doc-controls.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/operator-doc-controls.log>). Passing historical subset: [`resumed-stable-suite.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log>). Historical review artifact: [`clients-review-infra.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** No operational database was inspected or mutated. This is a safer documented recovery boundary, not evidence that any database is schema-equivalent or migration-ready. Infrastructure validation of the preflight change is tracked separately.

### QA-CLIENT-016 — Lockdown and key-rotation runbooks retain deployment paths contradicted by current immutable release SOP

Issue: [#568](https://github.com/PetrefiedThunder/agent-middleware-api/issues/568). Disposition: **local fixed**; present before this task.

**Original defect.** Lockdown and key-rotation recipes retained release paths that contradicted the immutable release procedure.

**Original fix commits.** `7cb38a46581ae6f172f8e21e349c87b5afa83699`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** Lockdown links to the canonical deployment procedure. Rotation requires a qualified exact-SHA release, schema-compatible recovery and the explicit schema-042 rollout before changing a key.

**Inspected source and retained tests.** [`docs/deploy-railway.md`](../../docs/deploy-railway.md), [`docs/api-key-rotation.md`](../../docs/api-key-rotation.md), [`tests/test_operator_doc_contracts.py`](../../tests/test_operator_doc_contracts.py).

**Fresh acceptance.** The lockdown and rotation document contracts passed in the fresh 69-test run. They reject stale GitHub-integration/redeploy-click instructions in the repaired sections.

**Retained original evidence.** [`findings.json`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/findings.json>). Passing historical subset: [`resumed-stable-suite.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log>). Historical review artifact: [`clients-review-infra.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** No release, rollback, signing-key rotation or provider change was executed. Actual target, schema and approval evidence are separate operational requirements.

### QA-CLIENT-017 — Local demo Compose recipe omits DATABASE_URL required for its key and trust workflow

Issue: [#569](https://github.com/PetrefiedThunder/agent-middleware-api/issues/569). Disposition: **local fixed**; present before this task.

**Original defect.** The local demo Compose recipe omitted the database URL needed by its key and trust workflow.

**Original fix commits.** `7cb38a46581ae6f172f8e21e349c87b5afa83699`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** The broken local Compose example was replaced with supported `make quickstart`, which persists the database and signing seed together under `data/quickstart/`.

**Inspected source and retained tests.** [`docs/demo-instance.md`](../../docs/demo-instance.md), [`scripts/quickstart.py`](../../scripts/quickstart.py), [`tests/test_operator_doc_contracts.py`](../../tests/test_operator_doc_contracts.py).

**Fresh acceptance.** The local-demo document contract passed in the fresh 69-test run and confirms the supported command, database/seed persistence and removal of the incomplete volume-only recipe.

**Retained original evidence.** [`test_operator_docs.py`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_operator_docs.py>), [`operator-doc-controls.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/operator-doc-controls.log>). Passing historical subset: [`resumed-stable-suite.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log>). Historical review artifact: [`clients-review-infra.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** This task did not launch quickstart or Docker. It validates the documented supported entry point; runtime boot acceptance is a separate check.

### QA-CLIENT-018 — Historical external diagnostic harness reports zero findings for unauthenticated200 responses

Issue: [#570](https://github.com/PetrefiedThunder/agent-middleware-api/issues/570). Disposition: **retired with explicit refusal**; present before this task.

**Original defect.** The historical external diagnostic harness could print zero findings for unauthenticated synthetic 200 responses and did not propagate an aggregate failure exit.

**Original fix commits.** `9edad00dfcde0a1daa79b2da47faadd9221f46f5`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** The historical harness is explicitly retired and non-gating. Both the CLI and raw transport refuse before probes run; archived diagnostic counts are labeled as observations rather than an authentication verdict.

**Inspected source and retained tests.** [`docs/research/external-adversarial-2026-09-11/gauntlet.py`](../../docs/research/external-adversarial-2026-09-11/gauntlet.py), [`docs/research/external-adversarial-2026-09-11/README.md`](../../docs/research/external-adversarial-2026-09-11/README.md), [`tests/test_historical_probe_retirement.py`](../../tests/test_historical_probe_retirement.py).

**Fresh acceptance.** All three retirement tests passed in the fresh 69-test run. They replace `urlopen` with a forbidden-call assertion and verify transport/CLI refusal, then render a synthetic protected-route 200 as diagnostic output without the old zero-findings claim.

**Retained original evidence.** [`test_historical_gauntlet.py`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_historical_gauntlet.py>), [`historical-gauntlet-red.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/historical-gauntlet-red.log>). Passing historical subset: [`resumed-stable-suite.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log>). Historical review artifact: [`clients-review-infra.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** This is retirement with controlled refusal, not a repaired production attack scanner. No external network battery was run or newly authorized.

### QA-CLIENT-019 — Partner checklist uses GET for the POST-only receipt verification operation

Issue: [#571](https://github.com/PetrefiedThunder/agent-middleware-api/issues/571). Disposition: **local fixed**; present before this task.

**Original defect.** The partner checklist used GET for the POST-only receipt-verification operation.

**Original fix commits.** `ed6b396d0290de8904b9ac6db6e90626ad0ad1aa`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** The checklist now uses authenticated `POST /v1/receipts/verify` with a JSON `receipt_id`, matching the router and `ReceiptVerifyRequest` body.

**Inspected source and retained tests.** [`docs/partner-first-tool-runbook.md`](../../docs/partner-first-tool-runbook.md), [`app/routers/receipts.py`](../../app/routers/receipts.py), [`tests/test_onboarding_doc_contracts.py`](../../tests/test_onboarding_doc_contracts.py).

**Fresh acceptance.** The method/body/authentication document contract passed in the fresh 69-test run. Source inspection confirms `@router.post("/verify")`; offline portable-bundle verification remains a separate checklist step.

**Retained original evidence.** [`findings.json`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/findings.json>). Passing historical subset: [`resumed-stable-suite.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log>). Historical review artifact: [`clients-review-infra.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** No receipt was fetched or posted to a deployed service. Server verification checks its stored receipt; independent verification of a downloaded artifact is a distinct proof.

### QA-CLIENT-020 — Failure-lab suite quick commands select the older lab instead of the advertised fast tier

Issue: [#572](https://github.com/PetrefiedThunder/agent-middleware-api/issues/572). Disposition: **local fixed**; present before this task.

**Original defect.** The fast-tier quick command selected the older comparative Failure Lab target instead of the documented scenario suite.

**Original fix commits.** `ed6b396d0290de8904b9ac6db6e90626ad0ad1aa`. Each is an ancestor of the verified base. No remote fix PR is claimed.

**Current implementation.** The quick command now selects `make failure-lab-suite`, whose recipe runs `python -m failure_lab run --tier fast --source ci_run`.

**Inspected source and retained tests.** [`docs/failure-lab-suite.md`](../../docs/failure-lab-suite.md), [`Makefile`](../../Makefile), [`tests/test_onboarding_doc_contracts.py`](../../tests/test_onboarding_doc_contracts.py).

**Fresh acceptance.** The retained test extracts the target from the actual quick-command block and verifies its Make recipe contains `--tier fast`; it passed in the fresh 69-test run.

**Retained original evidence.** [`findings.json`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/findings.json>). Passing historical subset: [`resumed-stable-suite.log`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log>). Historical review artifact: [`clients-review-infra.md`](</Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md>). Those review records cover only their stated code and time; they are not fresh approval of this follow-up.

**Remaining scope limit.** Neither lab was executed in this lane. The command mapping fix does not validate historical measurements or close separate lab-infrastructure findings.

## Release and acceptance limits

This lane did not push, open or mutate a PR/issue, merge into main, deploy, execute a provider operation, read a credential store or read an environment file. No current production behavior, published package installation, live GitHub visibility, Docker quickstart, PostgreSQL crash recovery or customer-owned staging acceptance is claimed. The historical local evidence links intentionally point to the retained coordinator workspace; they are not downloadable hosted CI artifacts.

The repo-specific `AGENTS.md` and real `Makefile` supersede the supplied generic statement that there is no Makefile. The actual `.pre-commit-config.yaml` configures Ruff, Ruff formatting and mypy only; it does not contain the generic instructions' described detect-secrets hook. This lane does not change hook configuration or add a bypass. Final local aggregate acceptance belongs to the coordinator after gate review and its requested checks.
