# Aggregate acceptance report

## Latest full-suite acceptance

Status: PASSED, exit `0`, finished `2026-10-03T03:53:28.982293+00:00` at exact source SHA `4ac5a56880a493ed3e275eef9a305423d31e8a2b`.

**`4866 passed, 85 skipped, 6 warnings in 309.54s (0:05:09)`**

- Source SHA before and after identical; worktree clean after completion.
- Machine-readable source/result snapshot: `/tmp/amw-all-issues-20261002/aggregate/full-4ac5a56/snapshot.json`
- Exact skip records: `/tmp/amw-all-issues-20261002/aggregate/full-4ac5a56/skips.txt`
- Skip categories: 69 PostgreSQL or explicit disposable-database harness; 14 Optional framework or browser dependency missing; 1 Linux-only CI test; 1 Opt-in constant-loop integration.

- Root supplied the reviewed test-contract fix preserving existing no-secret/no-fabricated-data assertions and requiring relative runtime links. Aggregate applied `git cherry-pick --ff d42bbcf..4ac5a56`; source clean, exact root integration SHA.
- All `tests/` are selected, including proof tests; no `-m` selection filter.
- Command: `/Users/sellers/Projects/agent-middleware-api/.venv/bin/python -m pytest tests/ -x -q -ra --basetemp=/var/folders/jq/nbt0s6qs6njf4yfc0w30wmxh0000gn/T/amw-aggregate-full-4ac5a56-8749qv9m/pytest`
- Fresh database: `/tmp/amw-all-issues-20261002/aggregate/full-4ac5a56/full.db`
- Full raw log: `/tmp/amw-all-issues-20261002/aggregate/full-4ac5a56/full.log`
- Start metadata: `/tmp/amw-all-issues-20261002/aggregate/full-4ac5a56/start.json`
- Completed result is saved at `/tmp/amw-all-issues-20261002/aggregate/full-4ac5a56/result.json`.
- Prior stale assertion also reproduced independently at d42bbcf: `2 failed, 6 passed in 0.94s` in `tests/test_human_accessibility.py`; evidence `/tmp/amw-all-issues-20261002/aggregate/human-contract-d42bbcf`. Both route variants failed on the same old hosted URL assertion.

## Source identity and scope

- Worktree: `/Users/sellers/.openclaw/worktrees/amw-issues-20261002-aggregate`
- Branch: `openclaw/amw-issues-20261002-aggregate`
- Remote: `https://github.com/PetrefiedThunder/agent-middleware-api.git`
- Required repair SHA: `f82700f750862b6e51566a46dfc559e5b81e0a95`
- Source clean before execution; no product files edited by aggregate validator.
- Root and tests `AGENTS.md` read. One pytest process per worktree.
- Only local test calls authorized. No `.env` content or credentials read, no provider/production requests, and no remote mutations performed.

## Full fast suite at repair SHA

Status: FAILED due to harness temp-path mismatch, started `2026-10-03T03:37:24.174721+00:00`.

Command (cwd is the worktree above):

```text
/Users/sellers/Projects/agent-middleware-api/.venv/bin/python -m pytest tests/ -x -q -m not proof -ra --basetemp=/tmp/amw-all-issues-20261002/aggregate/fast-f82700f/pytest-artifacts
```

- Harness: `/tmp/amw-all-issues-20261002/aggregate/run_fast.py`
- Start metadata (including exact scrubbed environment): `/tmp/amw-all-issues-20261002/aggregate/fast-f82700f/start.json`
- Fresh database: `/tmp/amw-all-issues-20261002/aggregate/fast-f82700f/fast.db`
- Fresh test artifacts: `/tmp/amw-all-issues-20261002/aggregate/fast-f82700f/pytest-artifacts`
- Raw output: `/tmp/amw-all-issues-20261002/aggregate/fast-f82700f/fast.log`
- Completed result metadata is recorded at `/tmp/amw-all-issues-20261002/aggregate/fast-f82700f/result.json`.
- Equivalent prerequisites and environment to original accepted-validation harness; same verified Python runtime. Fresh DB/output paths and explicit fresh pytest basetemp isolate this retry.
- Summary: `1 failed, 3375 passed, 84 skipped, 746 deselected, 6 warnings in 295.94s (0:04:55)`. Exit `1`; source stayed clean at the required SHA.
- `tests/test_site_agent_interface.py::test_site_build_blocks_missing_and_provisional_contacts` failed because explicit `--basetemp=/tmp/...` was outside macOS `TMPDIR`, so the output safety guard correctly rejected the output path.
- The same test passed unchanged at the same SHA with a fresh basetemp below the system temp directory: `1 passed in 0.67s`; exit `0`. Evidence: `/tmp/amw-all-issues-20261002/aggregate/baseline-site-env-check/result.json` and `/tmp/amw-all-issues-20261002/aggregate/baseline-site-env-check/targeted.log`. No product change or test weakening.
- Proof tests were excluded by requested `-m 'not proof'`. This partial run is not full acceptance.

## Reused previous successful evidence

These completed result records have before/after SHA exactly equal to this repair SHA, exit 0, and clean recorded worktrees. Raw records/logs remain untouched.

| Check | Exit | Raw summary | Result record |
| --- | --- | --- | --- |
| accounting | `0` | 12 passed, 2 warnings in 2.23s | `/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/integration/accepted-validation/accounting-result.json` |
| process | `0` | 10 passed, 1 warning in 23.00s | `/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/integration/accepted-validation/process-result.json` |
| migration | `0` | 1 passed, 1 warning in 6.98s | `/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/integration/accepted-validation/migration-result.json` |
| sdk-config | `0` | 148 passed in 0.49s | `/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/integration/accepted-validation/sdk-config-result.json` |

## Final integrated complete suite

Status: FAILED at `2026-10-03T03:46:46.130440+00:00`; exit `1`.

Summary: `1 failed, 1816 passed, 43 skipped, 3 warnings in 191.33s (0:03:11)`. Source remained clean at `d42bbcf78031cd4b8c6d28312bd26f02ced625e7`.

Failure: `tests/test_human_accessibility.py:97` requires the old hosted `https://api.thisisatest.tech/health/dependencies` link. Integrated UX003 intentionally changed `static/dashboard.html` to same-origin `/health/dependencies`. Existing fabricated-data, browser-secret, no-script, and provider-domain exclusion checks ran before this assertion and passed. Root owns a contract-test repair retaining all security checks and verifying same-origin runtime URLs. No source edits made by aggregate validator.

- Root requested complete `tests/` including proof tests at integrated SHA `d42bbcf78031cd4b8c6d28312bd26f02ced625e7`.
- Applied requested six commits via `git cherry-pick --ff f82700f..d42bbcf`, preserving the exact integration SHA. Clean worktree and empty tree diff against integration before validation.
- Command:

```text
/Users/sellers/Projects/agent-middleware-api/.venv/bin/python -m pytest tests/ -x -q -ra --basetemp=/var/folders/jq/nbt0s6qs6njf4yfc0w30wmxh0000gn/T/amw-aggregate-full-d42bbcf-1j1ycb8y/pytest
```

- Fresh SQLite database: `/tmp/amw-all-issues-20261002/aggregate/full-d42bbcf/full.db`
- Raw output: `/tmp/amw-all-issues-20261002/aggregate/full-d42bbcf/full.log`
- Exact command and scrubbed environment: `/tmp/amw-all-issues-20261002/aggregate/full-d42bbcf/start.json`
- Completed result record: `/tmp/amw-all-issues-20261002/aggregate/full-d42bbcf/result.json`
- Actual system temp directory is used for fresh test artifact output, matching the build safety contract.

## Integrated run observed skip reasons

```text
SKIPPED [1] tests/test_action_migrations.py:167: requires fresh disposable local action migration DB
SKIPPED [1] tests/test_action_multiprocess.py:213: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [6] tests/test_action_multiprocess.py:254: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_action_multiprocess.py:362: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_action_multiprocess.py:386: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_action_multiprocess.py:406: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [2] tests/test_action_postgres.py:58: requires explicitly opted-in disposable local amw_action PostgreSQL database
SKIPPED [1] tests/test_action_postgres.py:65: requires explicitly opted-in disposable local amw_action PostgreSQL database
SKIPPED [1] tests/test_action_postgres.py:69: requires explicitly opted-in disposable local amw_action PostgreSQL database
SKIPPED [2] tests/test_action_postgres.py:96: requires explicitly opted-in disposable local amw_action PostgreSQL database
SKIPPED [1] tests/test_action_postgres.py:181: requires explicitly opted-in disposable local amw_action PostgreSQL database
SKIPPED [5] tests/test_action_postgres.py:185: requires explicitly opted-in disposable local amw_action PostgreSQL database
SKIPPED [1] tests/test_awi_phase9.py:708: Playwright not installed
SKIPPED [1] tests/test_ci_second_tool_denial.py:165: CI workflow test only runs on Linux (GitHub Actions environment)
SKIPPED [1] tests/test_constant_test_loop.py:345: Set RUN_CONSTANT_TEST_LOOP_INTEGRATION=1 to run full integration test
SKIPPED [1] tests/test_dispatch_call_slot_migration.py:28: requires fresh disposable migration PostgreSQL
SKIPPED [3] tests/test_duplicate_guard_postgres_concurrency.py:37: requires a PostgreSQL DATABASE_URL for real row-lock semantics
SKIPPED [6] tests/test_framework_legacy_tools.py:260: could not import 'langchain_core.tools': No module named 'langchain_core'
SKIPPED [1] tests/test_framework_legacy_tools.py:273: could not import 'langchain_core.tools': No module named 'langchain_core'
SKIPPED [6] tests/test_framework_legacy_tools.py:285: could not import 'llama_index.core.tools': No module named 'llama_index'
```

## Baseline observed skip reasons

```text
SKIPPED [1] tests/test_action_migrations.py:167: requires fresh disposable local action migration DB
SKIPPED [1] tests/test_action_multiprocess.py:213: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [6] tests/test_action_multiprocess.py:254: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_action_multiprocess.py:362: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_action_multiprocess.py:386: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_action_multiprocess.py:406: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [2] tests/test_action_postgres.py:58: requires explicitly opted-in disposable local amw_action PostgreSQL database
SKIPPED [1] tests/test_action_postgres.py:65: requires explicitly opted-in disposable local amw_action PostgreSQL database
SKIPPED [1] tests/test_action_postgres.py:69: requires explicitly opted-in disposable local amw_action PostgreSQL database
SKIPPED [2] tests/test_action_postgres.py:96: requires explicitly opted-in disposable local amw_action PostgreSQL database
SKIPPED [1] tests/test_action_postgres.py:181: requires explicitly opted-in disposable local amw_action PostgreSQL database
SKIPPED [5] tests/test_action_postgres.py:185: requires explicitly opted-in disposable local amw_action PostgreSQL database
SKIPPED [1] tests/test_ci_second_tool_denial.py:165: CI workflow test only runs on Linux (GitHub Actions environment)
SKIPPED [1] tests/test_constant_test_loop.py:345: Set RUN_CONSTANT_TEST_LOOP_INTEGRATION=1 to run full integration test
SKIPPED [1] tests/test_dispatch_call_slot_migration.py:28: requires fresh disposable migration PostgreSQL
SKIPPED [3] tests/test_duplicate_guard_postgres_concurrency.py:37: requires a PostgreSQL DATABASE_URL for real row-lock semantics
SKIPPED [6] tests/test_framework_legacy_tools.py:260: could not import 'langchain_core.tools': No module named 'langchain_core'
SKIPPED [1] tests/test_framework_legacy_tools.py:273: could not import 'langchain_core.tools': No module named 'langchain_core'
SKIPPED [6] tests/test_framework_legacy_tools.py:285: could not import 'llama_index.core.tools': No module named 'llama_index'
SKIPPED [1] tests/test_mcp_postgres_multiprocess.py:1065: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_mcp_postgres_multiprocess.py:1124: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_mcp_postgres_multiprocess.py:1174: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_mcp_postgres_multiprocess.py:1261: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_mcp_postgres_multiprocess.py:1350: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_mcp_postgres_multiprocess.py:1419: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_mcp_postgres_multiprocess.py:1534: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_mcp_postgres_multiprocess.py:1601: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_mcp_postgres_multiprocess.py:1662: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [7] tests/test_mcp_postgres_multiprocess.py:1933: set RUN_MCP_MULTIPROCESS_TESTS=1 only for the isolated PostgreSQL multiprocess harness
SKIPPED [1] tests/test_permit_postgres_concurrency.py:396: requires a PostgreSQL DATABASE_URL for real row-lock semantics
SKIPPED [1] tests/test_permit_postgres_concurrency.py:474: requires a PostgreSQL DATABASE_URL for real row-lock semantics
SKIPPED [1] tests/test_permit_postgres_concurrency.py:578: requires a PostgreSQL DATABASE_URL for real row-lock semantics
SKIPPED [1] tests/test_permit_postgres_concurrency.py:637: requires a PostgreSQL DATABASE_URL for real row-lock semantics
SKIPPED [1] tests/test_permit_postgres_concurrency.py:689: requires a PostgreSQL DATABASE_URL for real row-lock semantics
SKIPPED [1] tests/test_permit_postgres_concurrency.py:746: requires a PostgreSQL DATABASE_URL for real row-lock semantics
SKIPPED [1] tests/test_permit_postgres_concurrency.py:902: requires a PostgreSQL DATABASE_URL for real row-lock semantics
SKIPPED [1] tests/test_permit_postgres_concurrency.py:955: requires a PostgreSQL DATABASE_URL for real row-lock semantics
SKIPPED [12] tests/test_permit_postgres_concurrency.py:147: requires a PostgreSQL DATABASE_URL for real row-lock semantics
SKIPPED [1] tests/test_postgres_datetime_binding.py:203: TEST_POSTGRES_URL not set; Postgres-dialect coverage skipped
SKIPPED [1] tests/test_postgres_datetime_binding.py:225: TEST_POSTGRES_URL not set; Postgres-dialect coverage skipped
SKIPPED [1] tests/test_postgres_datetime_binding.py:263: TEST_POSTGRES_URL not set; Postgres-dialect coverage skipped
SKIPPED [1] tests/test_postgres_datetime_binding.py:323: TEST_POSTGRES_URL not set; Postgres-dialect coverage skipped
SKIPPED [1] tests/test_postgres_datetime_binding.py:346: TEST_POSTGRES_URL not set; Postgres-dialect coverage skipped
SKIPPED [1] tests/test_security_fuzz_battery.py:705: requires PostgreSQL for accurate concurrent budget accounting
```

## Limits and next action

The original `accepted-validation/fast.log` stopped at 38% and has no result record. It is not acceptance evidence. The newer repair-SHA fast run stopped at a harness-path failure and did not validate tests beyond that point. Its failure is diagnosed and the affected test passed without source changes. Complete-suite acceptance now targets the final combined code at the root's request. Remote CI, deployment, provider readback, and live/customer behavior were not tested by this task. The complete integrated run stopped on the stale hosted-URL assertion. Root supplied the reviewed contract-test repair at 4ac5a56 and the fresh complete suite passed with 4866 passed, 85 skipped, and 6 warnings. The 85 skips are explicit coverage limits; they are not passes. No further broad tests were run.

## Final files, risk, and next step

Aggregate validator edited no product or test source; only applied root-supplied commits by fast-forward. Wrote local harnesses, reports, raw logs, metadata, and fresh SQLite data under `/tmp/amw-all-issues-20261002/aggregate`. Earlier failed runs remain preserved. Residual coverage: PostgreSQL/opt-in harness checks, optional Python integrations/browser package, and Linux-only behavior are skipped here; root owns their separate evidence. Root should retain this result and snapshot with the final issue-resolution packet. This result does not establish remote CI, deployment, or live/customer behavior.
