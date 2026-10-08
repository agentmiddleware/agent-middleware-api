# Break report: b2a_sdk and framework_integrations

Summary: 6 breaks found. 4 fixed and tested. 0 fixed but failing. 2 blocked (outside this target).

All tests used httpx mocks. No live HTTP, no production URL, no database.

## High: a wallet 402 could crash instead of telling the caller the wallet is short

What broke: `AgentMiddlewareClient.charge()` treated every HTTP 402 as a dict inside `detail`. A string or list detail raised `AttributeError`. A non-JSON body raised `JSONDecodeError`. A shortfall of `"nope"` raised `ValueError` from `float()`. The same float crash happened on any route that shares `_raise_http_error` (confirmed with `discover_tools()`). A null shortfall did raise `InsufficientFundsError`, but the server body was dropped (`payload` stayed `{}`) and `True` was reported as a 1.0 shortfall. The server `top_up_url` (often `/v1/billing/top-up/prepare`) was replaced with a guessed `/dashboard/top-up` link.

How to reproduce: mock `POST /v1/billing/charge` as HTTP 402 with `{"detail": "insufficient_funds"}`, or `{"detail": {"shortfall": "nope"}}`, or a non-JSON body. Call `charge()`. The exception is not `InsufficientFundsError`.

Root cause: `b2a_sdk/src/b2a_sdk/client.py` charge 402 branch (now line 561) and `_raise_http_error` (now line 226). `InsufficientFundsError` in `b2a_sdk/src/b2a_sdk/errors.py` (float at the constructor, now line 118) turns a bad shortfall into `ValueError`.

Fix: parse JSON safely, coerce a bad or boolean shortfall to None, keep the server body on the error, and use the server `top_up_url` when it is a non-empty string. A path that starts with `/` is joined to the client base URL. The dashboard link remains only when the server omits one. HTTP 403 is still `httpx.HTTPStatusError`.

Test results: failed before the fix (`AttributeError`, `ValueError: could not convert string to float: 'nope'`, `JSONDecodeError`, wrong URL, empty payload). Passes in the suite below.

## High: x402 labeled a retryable permit failure as a permanent 403 denial

What broke: `X402Client.settle_402()` turned every `permit_*` detail into `PermitDeniedError` with status 403. The server returns `permit_write_contended` as HTTP 503 and abandons that record so the caller can retry the same idempotency key (`app/routers/x402.py` line 224). Callers that treat 403 as "do not retry" stop. Real denials (HTTP 400, and 404 for `permit_not_found`) also reported status 403. A body whose error was `insufficient_funds` became a plain `APIError`, so a caller waiting for the wallet error would miss it.

How to reproduce: mock `POST /v1/x402/settle` as HTTP 503 with `{"detail": "permit_write_contended"}`. `settle_402()` raises `PermitDeniedError` and `status_code` is 403.

Root cause: `b2a_sdk/src/b2a_sdk/x402.py` settle error branch (now line 263) and `PermitDeniedError` hardcoding 403 (`b2a_sdk/src/b2a_sdk/errors.py` line 55).

Fix: `permit_write_contended` or HTTP 503 raises `APIError` with the real status. Other `permit_*` denials stay `PermitDeniedError` and keep the real status. A body that says `insufficient_funds` raises `InsufficientFundsError`. Any other HTTP 402, including `x402_invalid_requirement`, stays `APIError`. `PermitDeniedError.status_code` defaults to 403 when the caller does not pass one.

Test results: failed before the fix (type was `PermitDeniedError`, status 403 instead of 400 or 404, and `insufficient_funds` was `APIError`). Passes in the suite below.

## High: the framework client sent a different charge key than the SDK

What broke: `framework_integrations.client.B2AClient.charge()` sent the idempotency key raw, with no length check. `execute_awi_action()` counted length before stripping and sent the raw key and the raw permit id. The SDK strips first. A charge with `"  job-1  "` through the framework client, then a retry through the SDK, is two different ledger keys, so the wallet can be debited twice. `" " + ("k" * 128)` was rejected by framework `execute_awi_action` (length 129) and would be sent by the SDK as 128 k's.

How to reproduce: `B2AClient.charge(..., idempotency_key="  job-1  ")` against a mock transport. The `Idempotency-Key` header is `  job-1  `, not `job-1`.

Root cause: `framework_integrations/client.py` charge (previously the raw header at the old line 240, now line 263) and `execute_awi_action` (previously the length check at the old line 170, now lines 193 to 194).

Fix: the legacy client strips, rejects a blank key, rejects more than 128 characters after stripping, and rejects C0 and DEL. It does not import `b2a_sdk`. Permit ids are stripped the same way as the edge client. `X-API-Key` is still sent.

Test results: failed before the fix (header was `  job-1  `, a 129-character key was sent by `charge`, and execute rejected a 128-character key that only had a leading space). Passes in the suite below.

Behavior change: a key already stored with its surrounding spaces will not match a later call that now sends the stripped key.

## High, blocked: CrewAI wrapper turns a 402 or 403 into a normal tool string

What broke: `CrewAIB2ATool._run` catches `Exception` and returns `f"Error: {e}"`. A payment failure or a denial becomes a successful tool result. The agent can treat that as an answer and call again.

How to reproduce: read `wrappers/crewai-agent-middleware/src/crewai_b2a/tool.py` lines 180 and 245. Not executed here. This tree is outside `b2a_sdk/` and `framework_integrations/`.

Root cause: `wrappers/crewai-agent-middleware/src/crewai_b2a/tool.py` lines 180 and 245.

Fix: none. Another worker owns `wrappers/`.

Test results: not run. No production code in that package was changed.

## Medium: a newline inside an idempotency key was sent as a header

What broke: the SDK validator stripped and capped length, then sent the key. Installed httpx accepted `job\n1`, `job\r1`, a NUL, and DEL, and the mock transport recorded the request. The edge client did the same for AWI execute. The trust plane rejects C0 and DEL. A retry is not a stable key if one client rejects the character and another sends it.

How to reproduce: `AgentMiddlewareClient.charge(..., idempotency_key="job\n1")` on the old code. No `ValueError`. The request is sent.

Root cause: `b2a_sdk/src/b2a_sdk/client.py` `_validate_idempotency_key` (now line 186) and the edge copy in `execute_awi_action` (now line 186). The framework client had the same hole (fixed with the finding above).

Fix: after stripping, reject any character below ASCII 32 or equal to DEL, before the request is sent. The edge client uses the SDK validator. Permit ids on the edge and framework clients get the same control-character check.

Test results: failed before the fix (`Failed: DID NOT RAISE ValueError` for newline, CR, NUL, and DEL). Passes in the suite below.

## Medium, blocked: wrapper permit caches ignore expiry

What broke: LangChain, CrewAI, and AutoGen caches store a permit id and reuse it with no `expires_at` check (`wrappers/langchain-agent-middleware/src/langchain_b2a/_tools.py` line 79, `wrappers/crewai-agent-middleware/src/crewai_b2a/tool.py` line 139, `wrappers/autogen-agent-middleware/src/autogen_b2a/tool.py` line 96). The OpenAI runner returns `record.permit_id` without comparing `expires_at` to now (`wrappers/openai-agent-middleware/src/openai_b2a/runner.py` line 485). After the permit expires, the wrapper keeps sending that id. The server still denies an expired permit, so this is not a silent charge. Calls fail until something mints a new permit.

Inside the named target, `LocalPermitValidator.check` re-reads `expires_at` on every call (`b2a_sdk/src/b2a_sdk/edge_client.py` line 465) and denies when it is due. That path was not a break.

How to reproduce: read those cache lookups. Not changed here.

Root cause: the wrapper files cited above. Out of this target.

Fix: none.

Test results: not run against the wrappers.

## Checked, not a break

- There is no retry loop in `b2a_sdk/` or `framework_integrations/` that drops an idempotency key. `governed_tool` sends a caller-supplied key through. If the caller omits the key, it derives a new uuid. That is documented, and changing it to a content hash would merge two intentional calls. Left as-is.
- `charge()` HTTP 403 (`wallet_access_denied`, `wallet_frozen`) still raises `httpx.HTTPStatusError`. An existing test locks that. The status is not swallowed.
- `parse_402` / a generic x402 HTTP 402 such as `x402_invalid_requirement` stays `APIError`, not `InsufficientFundsError`.

## Tests

Command before the fix (new tests only):

`PYTHONPATH="/Users/sellers/metacode/fleet/wt/brk-api-sdk/b2a_sdk/src:/Users/sellers/metacode/fleet/wt/brk-api-sdk" ~/metacode/fleet/heavy .venv/bin/pytest -q --tb=line b2a_sdk/tests/test_break_error_and_keys.py b2a_sdk/tests/test_break_framework_idempotency.py`

Result: 23 failed, 6 passed in 0.43s. Failures were the crashes, wrong status codes, unstripped keys, and control characters being sent. The 6 passes were locks that were already true: HTTP 403 stays an HTTP error, the dashboard URL is used when the server omits `top_up_url`, a generic x402 402 stays `APIError`, a non-permit 403 stays `AuthorizationError`, 409 stays a conflict, and the SDK already strips a 128-character key.

One test was added after that run, for the shared 402 mapper. Before it was wired in:

`... pytest -q --tb=line b2a_sdk/tests/test_break_error_and_keys.py::TestCharge402Mapping::test_shared_http_402_bad_shortfall_stays_typed`

Result: 1 failed. `ValueError: could not convert string to float: 'nope'` at `errors.py`.

Command after the fix:

`PYTHONPATH="/Users/sellers/metacode/fleet/wt/brk-api-sdk/b2a_sdk/src:/Users/sellers/metacode/fleet/wt/brk-api-sdk" ~/metacode/fleet/heavy .venv/bin/pytest -q --tb=short -x b2a_sdk/tests`

Result: 178 passed in 1.20s.

Ruff, after import-order fix, on the touched Python files: all checks passed. `ruff format` reformatted 1 file.

Commit then failed ruff UP038 at `b2a_sdk/src/b2a_sdk/errors.py:70` in `_coerce_shortfall`. Changed `isinstance(value, (int, float))` to `isinstance(value, int | float)`. The previous line still rejects `bool`, `None`, and `"unknown"`. String parsing and the non-finite check are unchanged.

## Open questions

- In-flight framework charges that were stored with surrounding spaces will not match a retry after this strip. If any caller depends on the padded key, they need to keep sending that exact padded value until those records expire. I did not find a server-side strip, and I did not add one.
- The billing charge route does not appear to call the trust-plane idempotency validator. The SDK now refuses control characters locally. A non-SDK client can still send them to that route. Not changed.
- Wrapper permit caches and the CrewAI string swallow belong to the wrapper worker. This change does not touch `wrappers/`.
