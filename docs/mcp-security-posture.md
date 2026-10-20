# MCP security posture

**Audience:** security reviewers and procurement teams evaluating this gateway
in the vocabulary of the MCP threat catalog (NSA CSI on MCP, CSA research
notes, OWASP Agentic Top 10). For the product boundary itself read
[`SECURITY_LIMITATIONS.md`](../SECURITY_LIMITATIONS.md) first; for the OWASP
mapping read [`owasp-agentic-top10-mapping.md`](owasp-agentic-top10-mapping.md).

Last updated: 2026-10-20. Every claim below names the file that enforces it or
the test that attacks it. "Verified" means read in code or test for this
revision; "documented" means stated elsewhere in the repo and not re-read here.

## What this gateway is, in MCP terms

One MCP **client** (`app/services/upstream_mcp.py`) that talks to exactly one
operator-configured upstream server over Streamable HTTP, and two MCP **server**
transports that agents talk to (`app/routers/mcp_standard.py`, the opt-in
standards endpoint on the official SDK; `app/routers/mcp.py`, the legacy
JSON-RPC endpoint with its own parser). The agent never connects to the
upstream. Every `tools/call` passes the governed pipeline in
[`POLICY_ENFORCEMENT.md`](POLICY_ENFORCEMENT.md) before the gateway's client
sends anything.

That shape removes several MCP attack classes structurally rather than
defending against them, and it leaves two gaps that this page states plainly
(§3).

## 1. Attack classes and where each one is handled

| Class | Posture | Mechanism | Evidence |
|---|---|---|---|
| **Tool poisoning** (hostile instructions in a tool description) | Structurally absent | The upstream's description is discarded at discovery and replaced with a gateway constant (`_GATEWAY_TOOL_DESCRIPTION`); the agent-facing catalog never carries upstream prose. Input schema is kept verbatim because the agent needs it, bounded by `MCP_UPSTREAM_MAX_RESPONSE_BYTES`. | `tests/test_mcp_upstream_tool_poisoning.py`; `tests/test_upstream_mcp.py::test_discovery_initializes_and_caches_exact_tool_schema` (verified) |
| **Tool shadowing / name collision** | Refused at boot | The configured tool name must appear exactly once in `tools/list`; two entries, or zero, fail discovery and the tool is never registered. | `test_duplicated_tool_name_is_refused_before_any_dispatch`; `test_discovery_fails_closed_when_exact_tool_is_absent` (verified) |
| **Rug pull** (definition changes after approval) | Pinned, not detected | Discovery runs once at boot (`register_configured_upstream_mcp`). The call path dispatches by the configured name with the cached schema and never re-lists tools, so a post-boot rewrite does not reach the agent until the next boot. The gateway does **not** notice the change. | `test_metadata_that_changes_after_discovery_never_reaches_the_agent` (verified) |
| **Confused deputy** (server acts with more authority than the caller) | Enforced at the agent boundary; see gap §3.1 for the upstream boundary | Wallet ownership is checked before the idempotency store is touched; a key cannot use another wallet's permit, and a permit bound to a key refuses another key. | `scripts/invariant_attacks/attack6_key_misuse.py` (HELD); `tests/test_trust_negative_security.py` (verified by name) |
| **Token passthrough** (forwarding the caller's token downstream) | Structurally absent | The upstream credential is operator configuration (`MCP_UPSTREAM_BEARER_TOKEN`), loaded once, never read from a request. The agent's `X-API-Key` is never forwarded. A discovery page or tool result that reflects the bearer token is rejected before it is stored or returned. | `_contains_exact_secret`, `upstream_mcp.py`; `test_discovery_rejects_bearer_token_echo_without_exposing_it`; `test_call_rejects_bearer_token_echo_without_returning_or_logging_it` (verified) |
| **Session hijack / event injection** | Structurally absent on the server side | The standard endpoint is stateless: no `Mcp-Session-Id`, a fresh SDK transport per POST, every request re-authenticated by key (`mcp_standard.py:49`). There is no server-initiated stream to inject into. The upstream client opens a fresh session per call. | `mcp_standard.py` (verified); `tests/test_standard_mcp_endpoint.py` (documented) |
| **Replay / duplicate side effect** | Enforced | A governed call requires an idempotency key; the same key replays the stored receipt, a changed payload under it fails closed, and at most one gateway dispatch is claimed per key. | [`failure-semantics.md`](failure-semantics.md); `tests/test_adversarial_five_claims.py` (documented) |
| **Excessive scope / permission creep** | Enforced | Permits are Ed25519-signed capabilities naming the tool, scopes, spend cap, use count, expiry, and optional key binding. Wallet policy bundles add standing caps. | `app/services/permits.py`, `app/services/policies.py`; `make red-team-trust-plane` (documented) |
| **Prompt injection, direct or indirect** | Contained, not prevented | The gateway does not see prompts. A hijacked agent still cannot act outside its permit, and the refusal is itself a signed receipt. Tool results are bounded and canonicalized but their content is passed through unlabeled. | ASI01 row in the OWASP mapping (documented) |
| **Local server compromise / SSRF via upstream URL** | Enforced | The upstream URL is shape-validated, resolved once, checked against private and reserved ranges, pinned for the connection while preserving Host and SNI, and redirects are refused. Production requires public HTTPS. | `validate_upstream_url`, `_PinnedAsyncTransport`; `test_url_guard_*`, `test_http_transport_pins_validated_address_and_blocks_endpoint_drift` (verified by name) |
| **Argument injection into the tool call** | Enforced for named fields | A permit's `forbidden_fields` are deep-scanned in the arguments; the input schema must describe an object. Semantic validation of arguments is the tool's job. | `permits.py:172`; `test_discovery_requires_object_input_schema_or_absent_type` (verified) |
| **Oversized or malformed payloads** | Enforced | Inbound bodies capped on every route before the limiter runs; upstream responses capped on the identity-encoded stream before buffering; discovery metadata capped and paged with a tool-count limit. | `SECURITY_LIMITATIONS.md`; `test_discovery_bounds_*`, `test_transport_*` (documented) |

Two anti-patterns the MCP authorization guidance names deserve their own
sentence each, because evaluators ask for them by name:

- **Confused deputy.** At the agent boundary the gateway acts only with the
  caller's own wallet authority, checked before any state is written. At the
  upstream boundary it acts with **one operator service identity** for every
  caller. That second half is the anti-pattern in its textbook form, and it is
  a known gap, not an oversight (§3.1).
- **Token passthrough.** No caller token is ever forwarded. The upstream never
  learns which key or wallet initiated a call except through the forwarded
  metadata fields `io.agentmiddleware/invocation_id` and
  `io.agentmiddleware/idempotency_key`, which carry no credential.

## 2. The April 2026 MCP SDK disclosure

### What it was

Two Cloud Security Alliance research notes (2026-04-20 and 2026-05-04, both
summarizing OX Security's "The Mother of All AI Supply Chains") describe a
**design default in the STDIO transport** of the official MCP SDKs (Python,
TypeScript, Java, Rust): when an MCP server is configured with a `command`,
the SDK launches that command unconditionally, before checking whether the
child is an MCP server, with no restriction on command syntax. Any party that
can influence the `command` field of a STDIO server configuration (prompt
injection into an IDE, a writable config file, an unauthenticated management
UI, a malicious marketplace package) gets code execution. The notes quote an
estimated 200,000 vulnerable instances across more than 150 million package
downloads, attribute seven to ten downstream CVEs to the class (LiteLLM,
Cursor, Windsurf, Flowise, LibreChat, MCP Inspector, among others), and report
that Anthropic confirmed the behavior as intentional, declined to change the
SDK or protocol, and updated the SDK `SECURITY.md` to say STDIO adapters should
be used with care. **No CVE or GitHub advisory was assigned to the SDKs
themselves**, and no fixed SDK version exists for the class, because the
maintainers categorize it as expected behavior.

Read before citing: the two CSA notes disagree with each other on the CVE
count, on the severity of CVE-2025-49596, on the wording of the `SECURITY.md`
change, and on how the exploitation families are grouped. Cite OX Security's
original posts and the individual NVD entries for anything load-bearing. This
page relied on the CSA notes and on the Python SDK's GitHub advisory list, read
on 2026-10-20.

### Whether this deployment was exposed

**No, for the disclosed class.** The precondition is a STDIO client that
spawns a configured command. This repository has none:

- The only MCP client is `app/services/upstream_mcp.py`, which uses
  `mcp.client.streamable_http.streamable_http_client` against a URL. There is
  no `stdio_client`, no `StdioServerParameters`, and no subprocess spawned from
  configuration anywhere in `app/`, `b2a_sdk/`, `framework_integrations/`, or
  `wrappers/` (verified by search on 2026-10-20).
- The two mentions of `stdio` in the tree are server-side: `b2a_sdk/mcp.py`
  can serve itself over its own stdin/stdout (`mcp.run(transport="stdio")`),
  and `app/services/mcp_generator.py`, a frozen proof surface, emits a server
  template with that default. Neither launches anything.
- The upstream is chosen by operator environment variables at boot
  (`MCP_UPSTREAM_*`). No request, agent, or API route can register or change
  an upstream server. The persistent service registry
  (`POST /v1/billing/services`) records metadata-only entries that are not
  executable (`tests/test_upstream_mcp.py::test_persistent_services_are_metadata_only_and_not_executable`).

The broader lesson of the disclosure does apply and is already the design:
the model never holds the configuration that decides what gets executed. Keep
it that way. Any future adapter that lets a tenant point the gateway at a
server of their choosing must be reviewed against this section first.

### SDK advisories that do touch our transports

The Python SDK's published advisories (read 2026-10-20) are unrelated to
STDIO. Those relevant to surfaces this repo uses, and the repo's posture:

| Advisory | Topic | Posture here |
|---|---|---|
| GHSA-5h93-6whr-6q8j | HTTP client transports followed cross-origin redirects with headers | Upstream client sets `follow_redirects=False` and a test asserts it; the pinned transport refuses endpoint drift. |
| GHSA-fmmv-w9g8-j3gc | HTTP server transports read bodies with no size limit | `RequestBodyLimitMiddleware` wraps the standard endpoint (`mcp_standard.py:662`); every route is additionally capped by `MAX_REQUEST_BODY_BYTES`. `requirements.txt` pins `>=1.29.0` because that release provides the pre-parse body guard. |
| GHSA-84m7-p3x7-pcfv, GHSA-jpw9-pfvf-9f58 | Sessions never reclaimed; session requests served without verifying the principal | Both endpoints are stateless with a fresh transport per POST and key authentication per request. No session table exists to leak or hijack. |
| GHSA-w4fh-qvv9-3v23, GHSA-qx49-fqc8-xw99 | SDK bearer-token audience check; OAuth client credential leakage | The SDK's auth components are not used. Authentication is `X-API-Key` on every request; the upstream bearer is static operator configuration. |
| GHSA-rwrf-2pqf-9j8j | Client fetched server-chosen `$ref` URLs while validating tool results | The upstream call session never calls `tools/list`, so the SDK holds no output schema to validate against in that session (`_call_tool_once`, verified). The gateway validates results by its own shape and size checks. Re-verify on any SDK upgrade; the premise is SDK-internal. |
| GHSA-vj7q-gjh5-988w, GHSA-hvrp-rf83-w775 | WebSocket transport host validation; experimental task handlers | Neither feature is used. |
| GHSA-9h52-p55h-vw2f | DNS-rebinding protection off by default for localhost servers | Not evaluated here. The production server is on a public origin behind Railway; the local quickstart binds loopback only. |

### Version pins

- `requirements.txt:32` pins `mcp>=1.29.0,<2`. The `<2` is for API stability
  (2.x renamed and moved the low-level server internals this repo overrides),
  not for security; Dependabot major bumps are ignored by decision (#460).
- `uv.lock` resolves `mcp==1.29.1` but its recorded specifier for the `mcp`
  extra is `>=1.29.0,<3`, which does not match `pyproject.toml:11` (`<2`).
  The lockfile is stale relative to the project metadata. Not a vulnerability;
  a drift finding to fix in a dependency PR.
- Fixed versions for the advisories above were not verified for this page.
  Before a security review, read each advisory's affected range against the
  version in the deployed image, not the version on a developer machine.

## 3. Gaps, stated plainly

### 3.1 One service identity to the upstream

Every caller reaches the upstream through the same operator bearer. The
upstream cannot distinguish callers, cannot apply per-user policy, and cannot
audit which human a call served, except through the forwarded metadata. The
remedy the MCP authorization guidance prescribes is per-user token exchange
(RFC 8693) or an on-behalf-of credential per call. Neither is implemented and
both are frozen under `WEDGE.md` until a named partner's upstream can consume
such a token. Until then the honest description is: **the gateway is the
upstream's single tenant; the gateway's own permits and receipts are where
per-caller authority and evidence live.**

### 3.2 Definition pinning without drift detection

The boot-time tool definition is pinned, not hashed. A changed upstream
definition is not noticed until the next boot, and at that boot it is accepted
if it still passes discovery validation. A hash pin with refusal or quarantine
on mismatch would close this; it is a small change and it is not built because
no partner has a tool whose definition changes under them. The test that would
need extending is `tests/test_mcp_upstream_tool_poisoning.py`.

### 3.3 Tool results are bounded, not labeled

The gateway caps, canonicalizes, and secret-scans every tool result but
returns its content to the agent unmarked. Labeling results as untrusted for
the agent's context assembly is a runtime concern above this boundary.

## 4. What to ask us live

Reviewers who want to go past this page should run the invariant attacks in
`scripts/invariant_attacks/` against a quickstart instance
([`security-review-kit.md`](security-review-kit.md)) and extend
`tests/test_mcp_upstream_tool_poisoning.py` with the upstream behavior they
are worried about. A finding is anything that produces a dispatch, a debit, or
agent-visible upstream prose that this page says cannot happen.
