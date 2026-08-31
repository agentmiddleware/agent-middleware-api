# Deep Market Lab: substitutes and market boundary

Research date: **2026-08-31**. Scope: seven alternatives to the supported
consequential-agent-action gateway boundary. This is a current primary-source
review, not a vendor benchmark, market-size estimate, or customer validation.
No accounts were accessed and no outreach was sent.

## Decision

**Inference:** Keep the one-tool customer experiment; do not expand the core.
The plausible product is a maintained integration of action-bound authority,
configured consumption, conservative dispatch semantics, and linked evidence.
Neither idempotency, durable execution, non-retry configuration, nor explicit
ambiguity is an uncontested primitive. Whether this combination earns another
inline dependency is **unknown**.

**Verified repo positioning:** [WEDGE.md](../../../WEDGE.md) limits the claim to
the gateway boundary, configured credits/call allowance, and gateway-signed
evidence. It excludes arbitrary upstream exactly-once effects and effect
attestation. [The active validation sprint](../../30-day-customer-validation.md)
requires a partner-owned agent, mutation, engineer, and commercial evidence.
Those are the correct constraints for this investigation. This report does not
independently re-certify the source code or the concurrent technical program.

Evidence labels used below:

- **Fact — documentation verified:** a named primary source actually documents
  the capability or limitation. This does not establish successful execution in
  our environment, adoption, security, or customer satisfaction.
- **Inference:** a conclusion drawn from those facts, with its reasoning stated.
- **Hypothesis:** a proposition requiring customer or experimental evidence.
- **Unknown / not verified:** the reviewed material does not establish the
  answer. Silence in documentation is not proof that a capability is absent.

## Seven meaningful alternatives

### 1. Native upstream idempotency and authoritative reconciliation

**Fact:** Stripe documents replaying the first status/body for an idempotency
key, parameter mismatch rejection, and possible key pruning after at least
24 hours. A reused key after pruning can create a new request.
[Stripe idempotent requests — accessed 2026-08-31](https://docs.stripe.com/api/idempotent_requests).

**Fact:** Stripe explicitly treats some `500` outcomes as indeterminate, warns
against substituting a new key, and describes later reconciliation and webhooks
correlated through caller-supplied metadata. This is substantive ambiguity
handling, not merely response caching.
[Stripe advanced error handling — accessed 2026-08-31](https://docs.stripe.com/error-low-level).

**Inference:** This is the strongest substitute when the prospective customer's
actual upstream already prevents duplicate effects and provides usable effect
records. An additional gateway must justify its authority/accounting linkage
or lower operational burden. Multiple safe HTTP attempts are not inherently
inferior to one dispatch.

**Unknown:** The chosen partner tool's key scope, retention, concurrent-request
behavior, mutation coverage, lookup consistency, and delegated-authority needs.
Stripe's contract cannot be generalized to all APIs or MCP wrappers.

### 2. Temporal plus a deliberately designed action Activity

**Fact:** Temporal's retry-policy documentation says `Maximum Attempts = 1`
means one attempt without retries. Its official idempotency article explicitly
describes at-most-once execution using normal Activities, not Local Activities,
with this setting; zero execution remains possible. The same article covers
stable Activity idempotency keys and unique-operation database records.
[Temporal retry policies — accessed 2026-08-31](https://docs.temporal.io/encyclopedia/retry-policies),
[Temporal idempotency and durable execution — accessed 2026-08-31](https://temporal.io/blog/idempotency-and-durable-execution).

**Inference:** “Temporal retries; we do not” is an unfair comparison. A partner
already using Temporal can configure the mutation boundary conservatively and
persist its domain-specific uncertain state. The real comparison is the cost
of assembling authority, consumption, evidence, and recovery correctly.

**Unknown:** The customer's Activity implementation, SDK-level retries,
workflow identity/reuse/retention settings, reset procedures, and authority
store. The reviewed docs do not verify an off-the-shelf combination equivalent
to this repo, but they provide powerful ingredients.

### 3. LangGraph with durable checkpoints, approval interrupts, and tool wrappers

**Fact:** LangGraph documents persistence for recovery and human intervention.
Its Functional API guidance says an unfinished task can execute again when
resumed and recommends idempotency keys or checking existing results. Interrupts
persist state for external input.
[LangGraph persistence — accessed 2026-08-31](https://docs.langchain.com/oss/python/langgraph/persistence),
[Functional API, idempotency — accessed 2026-08-31](https://docs.langchain.com/oss/python/langgraph/functional-api),
[Interrupts — accessed 2026-08-31](https://docs.langchain.com/oss/python/langgraph/interrupts).

**Inference:** For teams owning the graph and tool implementation, a small
wrapper plus their existing database may be an adequate substitute. Checkpoints
alone do not eliminate the interval between a remote effect and recording a
task result; the native API or wrapper must handle that interval.

**Unknown:** Whether a particular deployment already includes a durable action
ledger, safe retry wrapper, scoped approval enforcement, and acceptable audit
records. No competing LangGraph implementation was run here.

### 4. Amazon Bedrock AgentCore Gateway and stateful Policy

**Fact:** Current AWS docs include Dogwood temporal policies with historical
approval conditions, call counts, and accumulated input amounts. This is broader
than stateless Cedar authorization. AWS documents one-time-use approval and
cumulative-budget examples. Its approval example consumes a completed-response
event and warns to sequence calls after the relevant response is recorded.
[AWS temporal policy authoring — accessed 2026-08-31](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal-authoring.html).

**Fact:** Temporal history is session-scoped; callers supply the session ID.
AWS explicitly warns that a new session resets count-based limits. The maximum
temporal condition window is 24 hours. Request interceptors also permit custom
validation before target invocation.
[AWS temporal policies — accessed 2026-08-31](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html),
[AWS interceptor contracts — accessed 2026-08-31](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors-types.html).

**Inference:** This is the closest documented managed-platform bundling threat.
Generic approval, historical policy, and aggregate-budget messaging are weak
claims of differentiation. A server-owned action identity across retries and
sessions is a more specific comparison, subject to testing.

**Unknown:** Concurrency behavior of the selected policy, outcome classification
after effect-then-response-loss, dispatch replay guarantees, and whether custom
interceptors plus existing storage already satisfy the customer's requirements.
Do not turn the documented example's response dependency into an untested
claim that AgentCore is exploitable or cannot implement safe consumption.

### 5. Portkey / Prisma AIRS AI Gateway

**Fact:** Portkey's current MCP docs list credential injection, user/tool access
controls, request/response logging, rate limits by key/server/tool, and content
filters and approval workflows. Its separate automatic-retries page is
explicitly about LLM requests; that page does not establish MCP mutation retry
behavior.
[Portkey MCP Gateway — accessed 2026-08-31](https://portkey.ai/docs/product/mcp-gateway),
[Portkey LLM retries — accessed 2026-08-31](https://portkey.ai/docs/product/ai-gateway/automatic-retries).

**Fact:** Palo Alto Networks announced that the Portkey acquisition closed on
May 29, 2026, and announced Prisma AIRS AI Gateway general availability on
July 16, 2026. The latter describes unified LLM, MCP, and A2A enforcement.
[Acquisition completion — published 2026-05-29; accessed 2026-08-31](https://www.paloaltonetworks.com/company/press/2026/palo-alto-networks-completes-acquisition-of-portkey-to-secure-ai-agents),
[GA announcement — published 2026-07-16; accessed 2026-08-31](https://www.paloaltonetworks.com/blog/2026/07/announcing-general-availability-of-prisma-airs-ai-gateway/).

**Inference:** Bundling into an existing security purchase can outweigh a narrow
technical advantage. Portkey should no longer be evaluated solely as a small
independent LLM router.

**Unknown:** Exact consequential-tool replay, idempotency, consumption, and
reconciliation contracts for the customer's edition and deployment. Marketing
language about governing transactions is not proof of this repo's state machine.

### 6. agentgateway plus external policy/processing

**Fact:** agentgateway documents MCP authorization using CEL, OAuth/JWT support,
and MCP-aware external authorization/processing. Its retry policy is
configurable, and `attempts: 1` means no retry. The retry page says a different
backend is preferred when retrying, where possible.
[MCP authorization — accessed 2026-08-31](https://agentgateway.dev/docs/standalone/latest/configuration/security/mcp-authz/),
[ExtMCP guardrails — accessed 2026-08-31](https://agentgateway.dev/docs/standalone/latest/mcp/guardrails/about/),
[Retry policy — accessed 2026-08-31](https://agentgateway.dev/docs/standalone/latest/configuration/resiliency/retries/).

**Inference:** A team can keep its preferred gateway and put specialized state
in a service it controls. This creates both a substitution route and a possible
future integration boundary. Merely offering MCP proxying or disabling retries
does not establish a separate product.

**Unknown:** End-to-end mutation semantics of any chosen configuration,
including external processor failures and replays from the client. No conclusion
about missing durable state follows from the reviewed retry page.

### 7. Developer-owned database action ledger / transactional outbox

**Fact:** AWS's transactional-outbox guidance describes committing a database
change and outbox record together, and warns that delivery can duplicate
messages, requiring idempotent consumers.
[AWS transactional outbox — accessed 2026-08-31](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html).

**Inference:** A team controlling the authoritative mutation database can place
logical identity, payload hash, authorization state, and consumption in its
existing transaction. For a remote mutation, its ledger can instead permanently
claim dispatch and leave ambiguity for reconciliation. The former can control
the actual effect; the latter has the same remote-boundary limitation as this
repo. An outbox alone does not make arbitrary external effects exactly once.

**Unknown:** The partner's engineering/support cost, isolation guarantees,
recovery procedures, and willingness to own this code. “They can build it” is
not proof that maintaining it is economical; “it is difficult” is not proof of
willingness to buy.

## Viable niche versus incumbent response

All entries in this table are **hypotheses**, not observed buyer behavior.

| Candidate situation | Why a separate boundary might earn its place | Strong incumbent response / disconfirmation |
| --- | --- | --- |
| A real staging write is blocked because retries and delegated consumption are owned by different teams | One narrowly installed, maintained action record reduces integration and incident work | Existing gateway plus native idempotency and a ledger clears the block faster |
| Different agent runtimes call the same consequential tool | A tool-boundary contract applies without migrating every runtime | The existing gateway's extension point or server wrapper can host that contract |
| Operators need to connect authorization, configured debit, and ambiguous dispatch during incidents | Linked exportable evidence saves reconciliation time | Existing workflow history and authoritative records are already sufficient; offline signatures add no buying value |

**Inference:** The likely initial economic buyer is the owner of the blocked
workflow or platform deployment, with security reviewing the boundary. This is
not established by the vendor landscape. The viable niche is narrower than
“agents need governance,” and there is no demonstrated moat from this review.
An incumbent response need not copy every primitive; it only needs to satisfy
the customer's safety and operating requirements at lower total cost.

**Unknown:** Qualified buyer count, incident frequency, acceptable added latency,
budget owner, purchase size, and willingness to retain this service. This review
does not supply TAM, revenue forecasts, customer logos, or fabricated demand.

## The killer comparison experiment

**Proposed; not executed.** Add a fair removal comparison to the existing
[partner acceptance test](../../30-day-customer-validation.md#pilot-acceptance-test).
Use one actual partner staging tool and one partner engineer. The baseline must
be the partner's best acceptable existing stack, including native idempotency,
effect lookup, correctly configured workflow retries, approvals, and available
ledger controls. Do not remove protections to manufacture a product win.

| Arm | Configuration |
| --- | --- |
| A: best existing stack | Partner-selected native API/workflow/gateway/ledger configuration, with its documented safety limits |
| B: current repo | Same tool and native protections, plus the supported governed MCP path; no speculative new capability |

Apply the same synthetic logical actions and fault placement to both arms:

1. Successful mutation, exact replay, and concurrent duplicate submission.
2. Same logical identity with changed payload, and out-of-scope or exhausted
   configured allowance requests.
3. Tool commits an effect, then the response is lost. Restart the caller or
   gateway and replay the same logical action.
4. Dispatch is claimed but no upstream effect occurs. Record how the operator
   recovers the work without assuming that absence of a response proves failure.
5. Where applicable, repeat across a new client session and documented identity
   retention boundaries. Do not simulate expiry by silently weakening one arm.

Record network dispatches, authoritative effect count, configured debit/count,
payload-conflict outcome, remaining uncertainty, and evidence available after a
restart. Measure integration hours, added latency, operator minutes to establish
effect truth, and time until the business action can safely proceed. Ask the
engineer to perform reconciliation and verify the repo receipt offline without
founder assistance.

**Fairness rule:** More than one network request with one safe native-idempotent
effect can pass the business test. The repo must separately satisfy its own
at-most-one-gateway-dispatch/debit claim. A vendor need not emit this repo's
receipt format to be an adequate substitute. Conversely, a signed record must
not be counted as proof of the remote effect.

**Continue signal:** Both technical invariants and a partner-valued difference
are observed, the partner keeps the boundary, and an owner commits to payment
or a written commercial decision. Set acceptable burden and latency before the
test; there is no evidence here for inventing universal numeric thresholds.

**Disconfirming signal:** Arm A is sufficient, the difference is only a preferred
evidence format, or Arm B's reconciliation/availability burden is unacceptable.
In that case the repo can be technically correct without supporting a company.

## At most three actions

1. Use the existing sprint to secure one qualified, partner-owned comparison.
   Record the actual baseline, unacceptable failure, owner, tool, and decision
   date before expanding product work.
2. Correct comparison language when next editing positioning: AgentCore now has
   stateful policies; Temporal can disable Activity retries; Stripe already
   treats uncertain mutations explicitly; Portkey is part of Prisma AIRS. Keep
   the superseded competitive matrix out of current claims.
3. Keep generic gateway, IAM, approval platform, generalized spend accounting,
   and new adapter work frozen. Only a documented blocker in that pilot can
   justify a new vertical slice; otherwise use the sprint's narrow/reframe/stop
   decision.

## Delivery record

- **Files changed:** this report only.
- **What changed:** fresh primary-source comparison, explicit unknowns,
  incumbent response analysis, and a partner-operated comparison protocol.
- **Tests run:** documentation review, whitespace/local-link checks, and
  `git diff --check`; no application or database tests because this work changes
  no runtime behavior.
- **What passed:** source links were opened or returned by current web research;
  local links resolve, whitespace checks pass, and the report separates
  documented facts from inference and unexecuted tests.
- **What was not tested:** vendors, integrations, latency, customer acceptance,
  commercial demand, and the concurrent implementation program.
- **Remaining risks:** vendor documentation can change or omit capabilities;
  configuration and account entitlements can change the comparison. This is
  not evidence of market absence, superiority, or willingness to pay.
- **Recommended next step:** perform action 1 using the active partner sprint.
