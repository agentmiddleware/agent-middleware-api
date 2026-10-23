# MCP security posture

**Audience:** security reviewers and procurement teams evaluating this gateway
in the vocabulary of the MCP threat catalog (NSA CSI on MCP, CSA research
notes, OWASP Agentic Top 10). For the product boundary itself read
[`SECURITY_LIMITATIONS.md`](../SECURITY_LIMITATIONS.md) first; for the OWASP
mapping read [`owasp-agentic-top10-mapping.md`](owasp-agentic-top10-mapping.md).

Last updated: 2026-10-22. Claims name their evidence where it exists. Labels:
**verified** means read in code or in a test body for this revision;
**verified by name** means the test exists but its body was not read;
**documented** means stated elsewhere in the repo and not re-read here;
**external** means taken from a source outside the repo (§2), not re-verified.

**Deployment boundary.** The supported deployment is one vendor-managed
project per customer, restricted to synthetic or redacted, low-sensitivity
data. Wallet checks are application-layer isolation: there is no row-level
security and no tenant-isolation guarantee (`SECURITY_LIMITATIONS.md`).

## What this gateway is, in MCP terms

One MCP **client** (`app/services/upstream_mcp.py`) that talks to exactly one
operator-configured upstream server over Streamable HTTP, and three MCP
**server** transports mounted in the app:

| Endpoint | Code | Carries governed `tools/call`? |
|---|---|---|
| `POST /mcp/messages` | `app/routers/mcp.py`, legacy JSON-RPC, own parser | Yes. Deprecated in the OpenAPI contract. |
| `POST /mcp` | `app/routers/mcp_standard.py`, official SDK, stateless | Yes. Opt-in via `ENABLE_STANDARD_MCP_ENDPOINT`, default off. |
| `POST /mcp/public` | `app/routers/mcp_public.py`, official SDK, unauthenticated | No. Read-only verification and discovery tools; 404 unless enabled; refused in production-like environments. |

The REST route `POST /mcp/tools/{id}/invoke` is a deprecated entry into the
same governed pipeline.

**Which endpoints the supported pilot exposes is currently contradictory in the
repo.** `docs/deploy-railway.md` (the `ENABLE_STANDARD_MCP_ENDPOINT` row and
the post-deploy check) says that flag must be false or unset on a production
deployment ("Auto-minted permits on `POST /mcp`. Do not turn this on."), while
`README.md` and `SECURITY_LIMITATIONS.md` call `POST /mcp` the supported path
for new integrations. Until that is resolved, read every `POST /mcp` statement
below as applying only when that flag is on.

The agent never connects to the upstream. Every governed `tools/call` passes
the pipeline in [`POLICY_ENFORCEMENT.md`](POLICY_ENFORCEMENT.md) before the
gateway's client sends anything. One difference matters for the rows below: on
`POST /mcp` the gateway **mints a single-tool, single-call permit itself** for
whoever holds a wallet key (`_mint_auto_permit`, `mcp_standard.py`), so
operator-set permit constraints (scopes, `forbidden_fields`, use counts) apply
only on `/mcp/messages` and REST invoke. On `/mcp` the limits are the wallet
balance and wallet policy bundles.

That shape removes several MCP attack classes structurally rather than
defending against them, and it leaves gaps that §3 states plainly.

## 1. Attack classes and where each one is handled

| Class | Posture | Mechanism | Evidence |
|---|---|---|---|
| **Tool poisoning, tool description** | Structurally absent | The upstream's top-level `description` is discarded at discovery and replaced with a gateway constant (`_GATEWAY_TOOL_DESCRIPTION`); `title` and `annotations` are never copied. | `test_catalog_carries_gateway_description_and_the_tool_is_present` (verified) |
| **Tool poisoning, input schema** | **Residual channel** | `inputSchema` is published verbatim, so any string inside it (property descriptions, titles, defaults, enum values, property names) is upstream-authored text that reaches the agent. It is bounded by `MCP_UPSTREAM_MAX_RESPONSE_BYTES` (default 1 MiB, summed over the whole `tools/list`), which limits memory, not influence, and rejected if it echoes the bearer token. Not rewritten. `outputSchema` is kept in the registry record only; the catalog advertises a `hasOutputSchema` flag. | `test_hostile_text_inside_input_schema_reaches_the_catalog_verbatim` (verified) |
| **Tool shadowing / name collision** | Refused at startup | The configured tool name must appear exactly once in `tools/list`; two entries, or zero, abort registration. The startup call is unguarded in the lifespan, so the deployment does not boot. | `test_duplicated_tool_name_aborts_registration_before_any_dispatch`; `test_discovery_fails_closed_when_exact_tool_is_absent` (verified) |
| **Rug pull** (definition changes after startup) | Pinned for the agent, not detected | Discovery runs once at startup (`register_configured_upstream_mcp`, called from the `app/main.py` lifespan; that call-site fact is by code reading, not asserted). The agent-facing definition is the startup registry record and is never refreshed. The gateway does not notice a change, and it checks a result against no output schema, pinned or live. **The call session no longer consults the live upstream.** The SDK used to list tools after each call and validate the result against the live `outputSchema`, so a drifting or hostile schema could turn a completed call into a signed `delivery_uncertain`; the adapter now switches that validation off, so the live schema cannot change a call's outcome (§3.2). | `test_definition_rewritten_after_startup_does_not_reach_the_agent` (verified, agent-facing only); `test_live_output_schema_drift_must_not_turn_a_completed_call_uncertain`, `test_completed_call_with_drifted_live_schema_is_a_charged_success_end_to_end` (verified, §3.2) |
| **Confused deputy** | Enforced at the agent boundary; textbook gap at the upstream boundary (§3.1) | Application-layer wallet checks run before the idempotency store is touched; a key cannot use another wallet's permit; a key-bound permit refuses another key. No row-level security. | `scripts/invariant_attacks/attack6_key_misuse.py` (HELD, run against the quickstart's local tool); `tests/test_trust_negative_security.py` (verified by name) |
| **Token passthrough** | Structurally absent | The upstream credential is operator configuration (`MCP_UPSTREAM_BEARER_TOKEN`), loaded at startup and never read from a request. The agent's `X-API-Key` is never forwarded. A discovery page or tool result that contains the bearer string **verbatim** is rejected; encoded or partial reflections are not detected, and a rejected result is a charged call (`response_rejected` keeps the debit). | `_contains_exact_secret`, `upstream_mcp.py`; `test_discovery_rejects_bearer_token_echo_without_exposing_it`; `test_call_rejects_bearer_token_echo_without_returning_or_logging_it` (verified by name) |
| **Session hijack / event injection** | Structurally absent | `POST /mcp` is stateless: `mcp_session_id=None` (`mcp_standard.py:752`), `stateless=True` (`:768`), authenticated per request by `Depends(get_auth_context)` (`:788`); GET and DELETE return 405. `/mcp/messages` has no SSE transport (module docstring, `mcp.py:15`). The upstream client opens a fresh session per call. | `mcp_standard.py` (verified); `tests/test_standard_mcp_endpoint.py` (documented) |
| **Replay / duplicate side effect** | Enforced for keyed calls; **not** for un-keyed calls on `POST /mcp` | On `/mcp/messages` and REST invoke, a permit-bound call without an idempotency key is refused (`idempotency_key_required`, `mcp.py:1265-1278`). On `POST /mcp` an absent key is replaced by a server-generated `mcp-auto-<uuid>` (`mcp_standard.py:400`) and the call runs, so an un-keyed retry is a new charged operation; the key is mandatory there only when wallet policy requires human approval. With a client key: same key replays the stored receipt, a changed payload fails closed, at most one **gateway** dispatch and debit. The upstream's effect is once only if it honors the forwarded `io.agentmiddleware/idempotency_key`. A timeout after the dispatch claim is signed `delivery_uncertain`, keeps the debit, and is never redispatched. | [`failure-semantics.md`](failure-semantics.md); `tests/test_adversarial_five_claims.py` (documented) |
| **Excessive scope / permission creep** | Enforced on `/mcp/messages` and REST; wallet-level only on `/mcp` | Permits are Ed25519-signed capabilities naming the tool, scopes, spend cap, use count, expiry, optional key binding. Wallet policy bundles add standing caps on every path. | `app/services/permits.py`, `app/services/policies.py`; `make red-team-trust-plane` (documented) |
| **Prompt injection, direct or indirect** | Contained, not prevented | The gateway does not see prompts. A hijacked agent holding a permit cannot act outside it, and an out-of-permit call against an existing permit produces a signed `denied` receipt. Refusals that happen before permit lookup (bad key, no permit, no idempotency key, wallet access) are audit events or HTTP errors, not receipts. Tool results are bounded and canonicalized but their content is passed through unlabeled (§3.3). | ASI01 row in the OWASP mapping (documented); `mcp.py:1355` (verified) |
| **Local MCP server compromise** (client launches a process from configuration) | Not applicable | The gateway launches no process from configuration (§2). | search, §2 (verified) |
| **SSRF via upstream URL** | Enforced | The URL is shape-validated, resolved, checked against private and reserved ranges, and pinned for the connection while preserving Host and SNI; redirects are refused. Validation runs on every connection (`_http_client` calls `validate_upstream_url` for each session), not once. Production requires public HTTPS. The upstream certificate is verified, not pinned. | `validate_upstream_url`, `_PinnedAsyncTransport`; `test_url_guard_*`, `test_http_transport_pins_validated_address_and_blocks_endpoint_drift` (verified by name) |
| **Argument injection into the tool call** | Enforced for named keys only | A permit's `forbidden_fields` match dict keys anywhere in the argument tree, exactly and case-sensitively (`_find_forbidden_field`, `permits.py:180`, enforced at `:892`); values are not scanned. The gateway does **not** validate call arguments against the published `inputSchema`; the discovery-time check only requires that schema to have type `object` or no type. Conformance is the upstream's job. | `permits.py` (verified); `test_discovery_requires_object_input_schema_or_absent_type` (verified) |
| **Upstream abusing client capabilities** (sampling, elicitation, roots, server `instructions`, prompts, resources) | Refused or ignored by SDK defaults; not tested here | The adapter builds `ClientSession(read_stream, write_stream)` with no callbacks, so the SDK answers server-initiated requests with its defaults, and the gateway never relays server `instructions`, prompts, or resources to the agent. | `upstream_mcp.py` `_session` (verified); behavior of the SDK defaults not tested |
| **Oversized or malformed payloads** | Enforced | Inbound bodies are capped on every route by the app-wide `RequestBodyLimitMiddleware` (`app/middleware/request_body_limit.py`, registered at `app/main.py:560`, `MAX_REQUEST_BODY_BYTES`, 1 MiB default) before the rate limiter; upstream responses are capped on the identity-encoded stream before buffering; discovery metadata is capped, paged, and tool-count-limited. | `SECURITY_LIMITATIONS.md`; `test_discovery_bounds_*`, `test_transport_*` (documented) |

Two anti-patterns the MCP authorization guidance names deserve their own
sentence each, because evaluators ask for them by name:

- **Confused deputy.** At the agent boundary the gateway acts only with the
  caller's own wallet authority. At the upstream boundary it acts with **one
  operator service identity** for every caller. That second half is the
  anti-pattern in its textbook form, and it is a known gap (§3.1).
- **Token passthrough.** No caller token is ever forwarded. The upstream never
  learns which key or wallet initiated a call except through the forwarded
  metadata fields `io.agentmiddleware/invocation_id` and
  `io.agentmiddleware/idempotency_key`, which carry no credential.

## 2. The April 2026 MCP SDK disclosure

### What it was

All of this section is **external**, read on 2026-10-20 and not re-verified:

- CSA research note, 2026-05-04:
  <https://labs.cloudsecurityalliance.org/research/csa-research-note-mcp-security-crisis-20260504-csa-styled/>
- CSA research note, 2026-04-20:
  <https://labs.cloudsecurityalliance.org/research/csa-research-note-mcp-by-design-rce-ox-security-20260420-csa/>
- The Python SDK's GitHub advisory list:
  <https://github.com/modelcontextprotocol/python-sdk/security/advisories>
  (twelve advisories; the ten that matter here were opened individually).
  The TypeScript, Java, and Rust SDK advisory lists were not checked.
- OX Security's original research, "The Mother of All AI Supply Chains", is
  cited by both notes and was **not** read. Anything load-bearing should be
  checked there and against the individual NVD entries.

The two notes describe a **design default in the STDIO transport** of the
official MCP SDKs (Python, TypeScript, Java, Rust): when a server is
configured with a `command`, the SDK launches it unconditionally, before
checking whether the child is an MCP server, with no restriction on command
syntax. Any party that can influence a STDIO server's `command` (prompt
injection into an IDE, a writable config file, an unauthenticated management
UI, a malicious marketplace package) gets code execution. The notes quote an
estimated 200,000 vulnerable instances across more than 150 million package
downloads and attribute seven to ten downstream CVEs to the class (LiteLLM,
Cursor, Windsurf, Flowise, LibreChat, MCP Inspector, among others). As the
notes report it, Anthropic confirmed the behavior as intentional, declined to
change the SDK or protocol, and updated the SDK `SECURITY.md` to say STDIO
adapters should be used with care. In the Python SDK advisory list read on
2026-10-20 **no advisory concerns STDIO or command execution**, and the notes
name no fixed SDK version for the class.

The two notes disagree with each other on the CVE count, on the severity of
CVE-2025-49596, on the wording of the `SECURITY.md` change, and on how the
exploitation families are grouped.

### Whether this deployment was exposed

**No, for the disclosed class.** The precondition is an MCP client that
launches a configured command over STDIO. This repository has none
(verified by search on 2026-10-22):

- Within `app/`, `b2a_sdk/`, `framework_integrations/`, and `wrappers/`, the
  only MCP client is `app/services/upstream_mcp.py`, which uses
  `mcp.client.streamable_http.streamable_http_client` against a URL. The
  tree's other MCP clients (`failure_lab/gateway.py`,
  `failure_lab/scenarios/t14_standard_mcp_client.py`, `scripts/failure_lab.py`,
  and two tests) are also Streamable HTTP clients. There is no `stdio_client`
  and no `StdioServerParameters` anywhere.
- The code that does spawn subprocesses is not an MCP transport and launches
  a fixed executable, never a configured command. The behavioral sandbox runs
  **caller-supplied code by design**: `docker run <image> python -I -S -c <code>`
  (`app/services/behavioral_sandbox.py:411`, image from operator settings) or,
  behind `ALLOW_UNSAFE_HOST_PYTHON_SANDBOX`, `sys.executable -I -S -c <code>`
  (`:471`). It is a proof surface, unmounted in production, and not a
  production isolation boundary (`SECURITY_LIMITATIONS.md`); production
  refuses the host backend and the flag at boot.
- The three code files that mention `stdio` are all server-side:
  `b2a_sdk/src/b2a_sdk/mcp.py` serves itself over its own stdin/stdout
  (`mcp.run(transport=transport, ...)`, default `"stdio"`), spawning nothing;
  `examples/mcp_tool_example.py` calls that server; and
  `app/services/mcp_generator.py` emits a standalone server template with that
  default (its manifest path is used by the product routers; only the template
  method is unreachable from any route). **A customer who registers the MIT
  `b2a_sdk` STDIO server as a `command` in their own IDE or agent config is in
  the population the disclosure describes, on their client side.** That is the
  client's exposure, not the gateway's.
- The upstream is chosen by operator environment variables at startup
  (`MCP_UPSTREAM_*`). No request, agent, or API route can register or change
  an upstream server. The persistent service registry
  (`POST /v1/billing/services`) records metadata-only entries with no
  executor (`BillingEngine.register_service`; the registry labels such rows
  `metadata_only`). That route is on the expansion router, mounted only when
  `ENABLE_PROOF_SURFACES=true`, which production refuses. The registry-level
  behavior is covered by
  `tests/test_upstream_mcp.py::test_persistent_services_are_metadata_only_and_not_executable`;
  `tests/test_secret_persistence.py` drives the route for ownership and auth,
  but no test asserts through the route that a registered service cannot be
  executed.

The broader lesson of the disclosure does apply and is already the design:
the model never holds the configuration that decides what gets executed. Keep
it that way. Any future adapter that lets a tenant point the gateway at a
server of their choosing must be reviewed against this section first.

### SDK advisories that touch the transports in use

Affected ranges and patched versions are quoted from the advisory pages
(external, read 2026-10-20). The "excluded by floor" notes use the repo's
version floor before this change, `mcp>=1.29.0`.

| Advisory | Topic | Affected `mcp` (1.x) | Fixed | Posture here |
|---|---|---|---|---|
| GHSA-5h93-6whr-6q8j | Streamable HTTP client followed cross-origin redirects, forwarding custom headers and 307/308 bodies | `>=1.8.0,<1.30.0` | 1.30.0 | Also mitigated structurally: the upstream client sets `follow_redirects=False` (asserted by test) and the pinned transport refuses endpoint drift. |
| GHSA-fmmv-w9g8-j3gc (CVE-2026-109527) | Server transports and OAuth routes read request bodies with no size limit | `<1.29.1` | 1.29.1 | The SDK's own guard (`RequestBodyLimitMiddleware` inside the SDK transport wrapper, `mcp_standard.py:662`) is wired only for `/mcp/public` (256 KiB); the standard endpoint passes no limit to it. `/mcp` and `/mcp/messages` are bounded by the app-wide middleware (1 MiB default, `app/main.py:560`) that runs before the rate limiter. Excluded by the floor in any case. |
| GHSA-84m7-p3x7-pcfv (CVE-2026-59951) | Stateful Streamable HTTP sessions never reclaimed | `>=1.8.0,<1.30.0` | 1.30.0 | Not reachable: `/mcp` and `/mcp/public` are stateless with a fresh transport per POST; `/mcp/messages` does not use the SDK. |
| GHSA-jpw9-pfvf-9f58 (CVE-2026-52869) | Session requests routed by session id without checking the principal | `<=1.27.1` | 1.27.2 | Not reachable (no sessions), and excluded by the floor. |
| GHSA-w4fh-qvv9-3v23 | Server bearer-token auth had no audience check | `>=1.10.0,<1.30.0` | 1.30.0, plus opt-in `validate_token_resource=True` | Not used. `/mcp` and `/mcp/messages` authenticate through the gateway's own `get_auth_context` (`X-API-Key`; on deployments that enable it, a gateway-issued JWT or an enterprise bearer alongside a key); `/mcp/public` is unauthenticated and read-only by design. None imports `mcp.server.auth`. The upstream bearer is static operator configuration. |
| GHSA-qx49-fqc8-xw99 | OAuth client could send credentials to a server-chosen token endpoint | `>=1.9.1,<1.30.0` | 1.30.0, plus `issuer=` on the provider | Not used: the upstream bearer is static operator configuration; there is no OAuth client. |
| GHSA-rwrf-2pqf-9j8j | Client fetched server-chosen `$ref` URLs while validating tool results | `>=1.10.0,<1.30.0` | 1.30.0 | **Closed on the call path by the adapter, in addition to the pin.** The SDK's `ClientSession.call_tool` used to fetch the live output schema after the call was dispatched and validate `structuredContent` against it (`mcp/client/session.py:412-447`, 1.30.0); that is where a hostile upstream's live `$ref` was reachable on any image below 1.30.0. The adapter now seeds the SDK's per-session schema cache before the dispatch checkpoint (`_bypass_sdk_result_validation`), so no `tools/list` follows the call and no result schema is compiled or resolved. `test_hostile_external_ref_in_live_output_schema_is_never_resolved` makes outbound connections fail and asserts none are attempted; `test_production_session_sends_no_tools_list_after_dispatch` observes the production session's HTTP traffic. The floor stays: the other advisories above still depend on it. The bypass uses a private SDK attribute; if a release drops it, calls fail closed before dispatch (§3.2). Result size is bounded by the response guard. |
| GHSA-vj7q-gjh5-988w (CVE-2026-59950) | Deprecated WebSocket server transport lacked Host/Origin validation | `<1.28.1` | 1.28.1 | Not used, and excluded by the floor. |
| GHSA-hvrp-rf83-w775 (CVE-2026-52870) | Experimental task handlers allowed cross-client task access | `>=1.23.0,<=1.27.1` | 1.27.2 | Not used, and excluded by the floor. |
| GHSA-9h52-p55h-vw2f (CVE-2025-66416) | DNS-rebinding protection off by default for localhost FastMCP servers | `<1.23.0` | 1.23.0 | Fixed in 1.23.0; excluded by the floor. |

### Version pins, and what is and is not known about the deployed image

Five of those advisories are fixed in **1.30.0** (5h93, 84m7, w4fh, qx49,
rwrf). The version sources:

| Source | `mcp` version | Used by |
|---|---|---|
| `requirements.txt` | was `>=1.29.0,<2`, now `>=1.30.0,<2` | `Dockerfile` (`pip install -r requirements.txt`), so the production image, CI, and the `Makefile`'s `uv run --with-requirements requirements.txt` targets |
| `pyproject.toml` `mcp` extra | `>=1.30.0,<2`, kept identical | editable installs of the project |
| `uv.lock` | gitignored; regenerated locally by the pre-commit `mypy` hook | nothing in CI or the image. Not a repo artifact; do not cite it. |

The floor change (2026-10-20) lands with this page; until it is merged and an
image is rebuilt from it, nothing about the deployed image changes. **The SDK
version running in production is not verified here.** With a floor and no
exact pin, `pip` installs whatever 1.x release is current when the image is
built, and nothing in the repo records which version a deployment runs. Check
it from inside the image (`python -c "import importlib.metadata as m;
print(m.version('mcp'))"`), not from a developer machine. An image built
before 1.30.0 shipped carried the five advisories above: one structurally
mitigated (redirects), three not reachable (sessions, server-side bearer
audience, OAuth client), and one reachable by a hostile or compromised
upstream (`$ref` fetch during result validation), where the version was the
only protection until the call-session fix in §3.2, which closes that one in the
adapter as well. An exact pin would make the image reproducible; that is a
dependency-policy decision, not made here.

The `<2` ceiling is for API stability (2.x renamed and moved the low-level
server internals this repo overrides), not for security. Major-version
Dependabot bumps are suppressed by a Dependabot command on GitHub (#460), which
is **not recorded in the repo**: `.github/dependabot.yml` has no `ignore` rule,
so a reviewer cannot confirm the suppression from the repository.

## 3. Gaps, stated plainly

### 3.1 One service identity to the upstream

Every caller reaches the upstream through the same operator bearer. The
upstream cannot distinguish callers, cannot apply per-user policy, and cannot
audit which human a call served, except through the forwarded metadata. The
remedy the MCP authorization guidance prescribes is per-user token exchange
(RFC 8693) or an on-behalf-of credential per call. Neither is implemented.
`WEDGE.md` does not list them among its frozen items; they are deferred under
the same named-partner rule it applies to those items, until a named partner's
upstream can consume such a token. Until then the honest description is:
**the gateway is the upstream's single tenant; the gateway's own permits and
receipts are where per-caller authority and evidence live.**

### 3.2 Definition pinning without drift detection; the billing defect it exposed is fixed

The startup tool definition is pinned for the agent, not hashed. A changed
upstream definition is not noticed until the next startup, and at that startup
it is accepted if it still passes discovery validation. A hash pin with
refusal or quarantine on mismatch would close that. It is not built (see
"Still open" below).

**The defect (found 2026-10-22, fixed in this change).** The real SDK lists
tools **after** the call is dispatched and validates the result against the
upstream's *live* `outputSchema`. A probe against the real adapter and an
in-memory SDK server showed: with no output schema, or a matching one, the call
succeeded; with a live output schema that the result did not satisfy, the
adapter signed `delivery_uncertain` for a call that **completed**. A failing
`tools/list` after the call, or a schema demanding structured content the
result lacked, had the same effect. The consequences were: the debit retained
and the call never redispatched (the designed handling of true ambiguity,
applied to a known success); a drifting or hostile upstream could force it
deliberately, and the optional circuit breaker counts `delivery_uncertain`
(`mcp.py`, `_observe_upstream_admission(..., failure=True)`), so it could also be
used to open the breaker; and the receipt misstated the outcome.

**The decision: stop the SDK validating, rather than reclassify its failures.**

| Option | What it does | Why / why not |
|---|---|---|
| (b) Keep SDK validation; map its failure to `response_rejected` | Charge kept, honest receipt | Rejected. The SDK raises a bare `RuntimeError`, or the transport error of its own `tools/list`, from inside `call_tool`, so the received `CallToolResult` is discarded: there is nothing to hash or return, and the caller is charged for a result it never sees. A failed post-call `tools/list` cannot be told from a failed `tools/call` by exception type, only by matching message text. |
| **(a) Seed the SDK's schema cache with `None` for the configured tool** (chosen) | The SDK treats the tool as schema-less: no second `tools/list`, no validation. The received result goes to the adapter's own checks (shape, size, bearer echo) | Smallest change that makes "a received result is never `delivery_uncertain`" structurally true, and it removes a post-dispatch network round trip. |

The trade-off of (a), stated plainly: the gateway now relays a result whose
`structuredContent` does not match the upstream's live schema, and no longer
notices the mismatch at all. That check was never a defence. The schema came
from the same upstream as the result, so a hostile upstream satisfies it by
construction, and the agent-facing catalog advertises only `hasOutputSchema`
(§1), so the gateway made no conformance promise to the agent. The cost of (a)
is a dependency on a private SDK attribute (`_tool_output_schemas`) in a package
held at `<2`, not at one release. If a release drops it, `_call_tool_once`
fails closed **before** the dispatch claim: nothing is sent or charged, the call
ends as the generic pre-dispatch failure, and the reason is logged as
`upstream_mcp_sdk_result_validation_not_disabled`. If a release keeps the
attribute but changes what it means, only the real-SDK tests below notice, so
they must stay in CI.

What did not change: a failure with no received result (the connection drops,
the request times out, a JSON-RPC error answers `tools/call`) is still
`delivery_uncertain`; a tool-level `isError` result is still `returned_error`
and refunded; an oversized or bearer-echoing result is still `response_rejected`
and charged ([`failure-semantics.md`](failure-semantics.md)).

Evidence, all using a real in-memory SDK server behind the real adapter unless
noted: `test_live_output_schema_drift_must_not_turn_a_completed_call_uncertain`
(was a strict expected failure); the failing-`tools/list` and
no-structured-content cases; `test_hostile_external_ref_in_live_output_schema_is_never_resolved`;
`test_normal_success_is_unchanged_with_or_without_an_output_schema`;
`test_call_that_yields_no_result_is_still_delivery_uncertain` and
`test_error_result_is_still_a_returned_error_under_a_drifted_schema` (the
boundary); `test_sdk_without_the_schema_cache_fails_closed_before_dispatch`;
`test_production_session_sends_no_tools_list_after_dispatch` (the production
`_session` over HTTP, observing the requests that reach the upstream); and
`test_completed_call_with_drifted_live_schema_is_a_charged_success_end_to_end`
(through the governed router: one debit, one dispatch, a `success` receipt, and
a replay that sends nothing). With the one call that applies the fix disabled,
every one of these fails except the two boundary tests, which hold either way,
and the end-to-end test returns `-32005 delivery_uncertain`.

**Still open, a neighbouring defect found while verifying this fix (not
changed).** A tool response whose *envelope* the SDK cannot parse (for example
`content` that is a string, or a non-boolean `isError`) is meant to end as
`response_rejected`: `_call_tool_once` has a `ValidationError` branch for it.
Through a real SDK session it ends as `delivery_uncertain` instead, because the
SDK's task group rewraps the `ValidationError` in an `ExceptionGroup` before
that branch can match. Probed 2026-10-22 against an in-memory SDK server, with
and without the fix above, with identical results. The charge stays either
way; what differs is the receipt outcome (504 / `-32005`, counted by the
circuit breaker, versus a terminal 502 / `-32006`). A fix has to unwrap the
group in `_call_tool_once`'s handlers and is its own change with its own tests.
A second, narrower gap in the same function: its `ValidationError` branch lacks
the "a result is already in hand" guard that the two sibling handlers have, so a
`ValidationError` raised only while the session closes would turn a received
result into `response_rejected`.

**Still open, drift detection.** The gateway checks results against no output schema. If a
customer needs drift detection, it belongs in the adapter, against the
**startup-pinned** schema, offline, on the received result, with the outcome
`response_rejected`; never in the SDK against the live schema. That is a new
capability and is held under the named-partner rule in `AGENTS.md`.

### 3.3 Tool results are bounded, not labeled

The gateway caps and canonicalizes every tool result and checks it for the
exact upstream bearer string, but returns its content to the agent unmarked.
Any other credential in a result passes; so does an encoded or split copy of
the bearer. Labeling results as untrusted for the agent's context assembly is
a runtime concern above this boundary.

### 3.4 Custody and network

`TRUST_SIGNING_PRIVATE_KEY_B64` is an environment variable and there is no
KMS (`SECURITY_LIMITATIONS.md`), so a host compromise can forge permits and
receipts. `MCP_UPSTREAM_BEARER_TOKEN` is a deployment variable read at
startup, so rotating it needs a restart. An egress allowlist for the single
upstream origin is the operator's job. The upstream certificate is verified
but not pinned.

## 4. What to ask us live

For upstream behavior, run and extend `tests/test_upstream_mcp.py`,
`tests/test_mcp_upstream_tool_poisoning.py`, and `make failure-lab`
(`failure_lab/gateway.py` drives the real `register_configured_upstream_mcp`
path). The scripts in `scripts/invariant_attacks/` run against the quickstart's
local governed tool and cannot exercise any upstream row above. Start from
[`security-review-kit.md`](security-review-kit.md) for rules of engagement. A
finding is a dispatch or debit that this page says cannot happen, or
upstream-authored text reaching the agent through a channel other than the
input schema.
