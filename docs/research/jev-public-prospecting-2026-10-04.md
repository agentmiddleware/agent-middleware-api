# Jev for real AMW prospecting and email review

Date: 2026-10-04. Real public-company evidence; unsent discovery drafts.

## Practical result

Start with Composio for discovery: its [production guide](https://docs.composio.dev/docs/production-readiness) documents non-deduplicated executions and warns about retrying unsafe side effects after a read timeout. Browserbase is a second technical discovery candidate. Lindy supports a question about approved writes and retries, while its current uncertain-dispatch handling remains unverified. These are research candidates; no buyer, current blocker, committed engineer or pilot has been validated.

The assistant wrote three drafts from official sources. Jev judged them with nine separate three-option Choice questions. Every primary label matched the 27 independently reviewed references. Current unmet need and execution-path ownership remained insufficient for all three companies. This is a hand-selected, three-company spot check without negative controls or full class coverage; it establishes no accuracy rate, production calibration, conversion or deliverability result.

| Judgment | Composio | Browserbase | Lindy |
| --- | --- | --- | --- |
| Technical discovery fit | relevant | relevant | insufficient |
| Current unmet need | insufficient | insufficient | insufficient |
| Current execution-path owner | insufficient | insufficient | insufficient |
| Factual draft claims | supports | supports | supports |
| Personalization | supported | supported | supported |
| Ask | clear | clear | clear |
| Discovery topic | relevant | relevant | relevant |
| Tone under the rubric | professional | professional | professional |
| Missing factual evidence within the draft | not_needed | not_needed | not_needed |

Technical fit means a documented consequential-action and execution boundary worth exploring. Topic relevance permits a bounded neutral question about documented actions or approval/retry features, even when retry safety or commercial need is unknown. The final evidence-coverage label concerns assertions in the draft; it does not establish a verified recipient, approve sending or qualify a sale.

## Actual drafts and evidence

### Composio

**Subject:** Tool execution after a read timeout

```text
Hi Composio team,

Your production guide says executions are not automatically retried because the backend does not deduplicate them; it recommends checking logs or the provider before retrying an unsafe call. I'm working on Agent Middleware. Would you be open to a fifteen-minute conversation about how your team handles uncertain execution outcomes today?

Christopher
```

Sources: [Official source 1](https://docs.composio.dev/docs/toolkits), [Official source 2](https://docs.composio.dev/docs/production-readiness).

### Browserbase

**Subject:** Reconciling consequential browser actions

```text
Hi Browserbase team,

Your ecommerce page describes agents submitting payments, and your Functions guide separates an accepted invocation from a completed handler. I'm working on Agent Middleware. Could we spend fifteen minutes reviewing how a consequential browser action is reconciled when its acknowledgement is uncertain?

Christopher
```

Sources: [Official source 1](https://www.browserbase.com/use-case/ai-agents-for-ecommerce), [Official source 2](https://docs.browserbase.com/platform/functions/invoke), [Official source 3](https://github.com/browserbase/sdk-node#retries).

### Lindy

**Subject:** Approval and retry evidence for write actions

```text
Hi Lindy team,

Your docs describe approval before write actions such as sending email or updating tickets. Your October 2025 changelog also introduced action retries. I'm working on Agent Middleware. Would you be open to a fifteen-minute conversation about how approved writes are reconciled after an uncertain response?

Christopher
```

Sources: [Official source 1](https://docs.lindy.ai/pricing), [Official source 2](https://www.lindy.ai/changelog).

Composio already documents connected-account permissions, confirmation guidance and deliberate execution retries. Browserbase REST SDK retries do not establish retrying a payment click; accepted Function invocation and completed handler are distinct states. Lindy already requires approval for outside-impact writes, and its retry announcement is dated October 21,2025. No absent safeguard, active incident, purchasing authority, product benefit or integration compatibility is invented.

Before outreach, identify the current owner of the execution path and establish whether the documented boundary creates a present workflow blocker. No individual recipient or address was established, and no message was sent.

## Sequential versus parallel execution

The same Composio and Browserbase request bytes ran first sequentially, then with two workers. Lindy ran once afterward. Primary results are the first response per company; the two parallel responses are exact execution repetitions.

| Two-request mode | Client group wall time | Input / output tokens | Estimated input cost | Errors / retries |
| --- | ---: | ---: | ---: | ---: |
| Sequential |0.504445s|11,078 /867|$0.000465276|0 /0|
| Parallel |0.238658s|11,078 /867|$0.000465276|0 /0|

The observed sequential/parallel wall ratio is 2.1137, about 53% shorter parallel wall time in this one pair. Parallel HTTP intervals overlap for 0.183900 s with maximum 2 active; sequential maximum is 1. Cooldown is outside the timer and was 0 for these groups. These intervals include client/network/provider time. One ordered pair does not isolate warmup, run-order effects, network variability or model compute and does not establish sustained speedup or provider capacity.

All 18 repeated labels stayed unchanged. Five Composio and four Browserbase parsed answer objects changed in their probabilities/confidences. No new errors, rate limits or retries occurred. Five requests across three groups used 0.952480 s of summed measured group wall time; local evidence preparation and independent review spanned roughly 17 minutes before the first dispatch. Artifact timestamps measure elapsed preparation, not separately instrumented active work. For this small run, research, ownership/need verification and review coordination dominated elapsed work; inference cost and measured HTTP time were small.

## Concentration and accounting

Six of 27 primary reported confidences were below 0.8; seven labels explicitly returned insufficient. Those signals are distinct. All per-dimension three-class macro recalls are undefined because each dimension lacks at least one gold class. Multiclass Brier sums and complete distributions were retained, without calibration claims.

One primary Browserbase personalization answer reports confidence 0.73 with displayed maximum probability approximately 0.81. The [documented three-option formula](https://docs.typesafe.ai/confidence), `(3*max_probability-1)/2`, gives approximately 0.715: about+0.015 discrepancy, above the prospectively declared heuristic 0.0125 tolerance for jointly rounding probability and confidence to the nearest two decimals. This does not change its label or prove a service defect. Decimal arithmetic prevents a false discrepancy at the exact tolerance boundary. No concentration score is a probability of factual truth, compatibility or purchase.

Five valid calls evaluated 27 primary and 18 repeated typed judgments. New usage is 27,407 input and 2,155 output tokens, estimated$0.001151094. Across this and earlier recorded work:85 dispatches,84 schema-valid responses,543,844 known input and 83,976 known output tokens. Known cumulative estimate is$0.022841448; conservative charge$0.025841448 includes one unchanged earlier$0.003 failure reserve with unknown usage. The earlier failed request was not retried here.

The [model price](https://docs.typesafe.ai/models), checked 2026-10-04, is$0.042 per million input tokens with free output. These are input-price estimates, not billing receipts. The user reports$100 credits; balance was not independently verified and no purchase occurred. The cap is a ceiling, not a spending target.

## Reproducible method and limits

Pinned `jev-1.13.0` at the official HTTPS `/v1/systemone` endpoint, with exact model/answer/type/probability/distribution/usage validation against the [API contract](https://docs.typesafe.ai/api). Reference labels, rationale and author notes stayed offline. No private AMW source or backlog entered the requests; sender context contained only the business intent to explore Agent Middleware. Official company facts retained source URLs, dates and explicit unknown fields.

The client reserves every initial group slot and$0.003 cost atomically before credentials/network. File and thread locks prevent competing groups; at most two workers and two starts in any rolling second, including retries. Requests are at most 35,000 wire bytes and 24 questions, task limits rather than proven tokenizer bounds. A single initial HTTP 429 may retry once with a new reserved slot and bounded advertised delay; every other error halts. Unknown dispatched costs retain their full reserve. No retries were exercised. Credentials stayed process memory and the official endpoint; redirects/proxies were disabled.

All reference labels, sources, drafts, criteria, exact request bytes, client, scorer, carry-in and usage limits received independent predispatch review. A prospective clarification separated Lindy discovery relevance from technical qualification before any outputs; prior unused payloads remain preserved. Fourteen offline safety/arithmetic/reference-isolation tests and Ruff passed. Raw responses, exact request/reference/meta seals, per-judgment scores, timing intervals, ledgers and independent reviews are retained in the task evidence workspace.

Request SHA-256 fingerprints (the first two repeat byte-identically across modes):

| Company | Request SHA-256 |
| --- | --- |
| Composio |`9699e0e97197a0f541459b1db2de5ee6696ea1e316cd8a67f015d72d8c0cb447`|
| Browserbase |`35d058c7ea5970f48b95d2cc86f42dcb9edfd5cca331b33ee3089828ed429f30`|
| Lindy |`03a62f346169c1f3d7476c90b6cf1f129d3652ba4ec3a1129a0e41ff2a1fdf45`|

This research changes no runtime integration, deployed configuration or shipped Jev guard. Keep the existing customer-validation invariant and deterministic authorization/accounting/execution gates. The practical workflow is official public evidence → assistant draft → atomic Jev judgments → human verification and correction. No further calls are planned under this protocol.
