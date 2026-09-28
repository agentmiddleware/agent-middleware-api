# Agent Middleware API: per-unit economics and commercial viability

**Comprehensive working draft · September 5, 2026 · USD**

**Evidence basis:** source inspection plus public vendor pricing. **Financial actuals: unknown.**
**Source snapshot:** `ebe36d7baaf0978b2c8160bd46d5b3ff8556f91f`; working tree was clean before this report was added.

This report evaluates the economics of selling the existing governed MCP gateway as a managed, dedicated customer deployment. It covers cost per logical action, customer contribution, pricing, onboarding, acquisition, retention, cash needs, failure exposure, and measurement. All account sizes, purchase prices, labor assumptions, failure frequencies, and conversion rates are scenarios. The user confirmed that actual hosting bills, customer counts, prices, and usage volumes were unavailable for this draft. Unknown values are not reported as zero.

## 1. Decision brief

**This product could support attractive unit economics as a narrowly scoped managed service, but there is no verified basis yet for claiming profitable customers, a 90% business gross margin, or a scalable self-serve SaaS model.** Its most plausible economic value is preventing duplicate gateway dispatch/debit and making uncertain consequential actions accountable. Its largest early costs are likely to be acquiring a qualified buyer, integrating a partner-owned tool, operating a dedicated deployment, and handling exceptions.

The central scenario tests **$1,500 per customer per month, including 100,000 unique governed attempts, plus $1 per additional 1,000 attempts**. At one million attempts, revenue would be **$2,400/month**. This is an analytical pricing hypothesis, not the product's current price or a validated offer.

Under explicit operating assumptions, that account produces **$1,737.35 monthly delivery contribution and a 72.4% contribution margin before an unresolved Railway Enterprise allocation**. If incremental Enterprise costs allocated to the account are $1,000/month, contribution falls to **$737.35 and 30.7%**. If they are $2,000/month, the account loses money before sales, engineering, and company overhead. The actual Enterprise amount, credit structure, and allocation basis are **not verified**.

Five conclusions should guide decisions:

1. **Price the managed customer relationship before optimizing the individual signature.** Dedicated deployment and operator work exist even at zero traffic. A low per-call fee alone cannot recover them at pilot volume.
2. **The repository's margin calculation is an estimate embedded in code.** It is not an invoice-based profitability statement. The configured MCP category mechanically reports a 90% modeled margin because its assigned cost scales with its price.
3. **There is a plausible healthy case and a plausible loss-making case at the same revenue.** One million attempts can produce $1,737 of contribution or a $4,844 monthly loss, depending on support and exception burden, even before Enterprise allocation.
4. **Generic gateway functionality faces very low price anchors.** Buyers must value the complete economic-control and reconciliation workflow enough to pay for dedicated operations. A signed receipt by itself is weak pricing justification.
5. **The next economic milestone is one paid, instrumented partner pilot.** It must establish an actual buyer, a consequential tool, integration effort, measured infrastructure usage, exception workload, and a decision about renewal. Another local demonstration cannot establish those values.

**Recommended commercial experiment:** a bounded one-tool pilot with an illustrative **$2,500 setup fee**, a separately stated recurring managed-service quote, and an explicit Enterprise-cost line or allocation. Test the $1,500 base plus usage hypothesis in discovery; do not lock a customer quote until the required infrastructure price and support scope are known. Keep the experiment within the current low-sensitivity staging boundary.

## 2. What is known, inferred, and missing

| Question | Evidence level | Finding and economic consequence |
| --- | --- | --- |
| What product is supported? | Verified from current repository | One configured upstream MCP tool governed through permit, budget, dispatch, ledger, receipt, and audit mechanisms. Broader proof surfaces are outside the main product. |
| Is shared customer hosting the supported model? | Contradicted by current pilot docs | The README requires customer-specific API, PostgreSQL, Redis, domain, keys, and admins. Model infrastructure per dedicated customer environment. |
| Is Enterprise optional? | Not established | The deployment SOP explicitly specifies a Railway Enterprise project. Public resource prices alone do not establish the full cost of satisfying that SOP. |
| Is a public subscription price offered? | Not verified; site says no pricing page | The site's FAQ says fit is qualified before deployment. This report proposes test prices only. |
| Do credits have a default dollar conversion? | Verified from code | `EXCHANGE_RATE` defaults to 1,000 credits per dollar. An accounting denomination is not proof that those credits were sold or collected. |
| Is `compute_cost` metered provider cost? | Contradicted by inspected calculation | It comes from constants multiplied by billed units. No invoice reconciliation feeds this path. |
| Are there paying customers? | Not verified | No billing/customer actuals were supplied; no private CRM, bank, or payment account was queried for this report. Do not infer zero customers from that scope. |
| Are latency, throughput, storage growth, support, and exception rates measured? | Not verified for this report | All workload and cost quantities below are assumptions. Tests listed in repository docs are correctness evidence, not unit-cost benchmarks. |
| Are the gateway guarantees sufficient to prove a downstream action happened exactly once? | Contradicted as a general claim | Remote effects require upstream idempotency and authoritative downstream evidence; the gateway observes its own dispatch boundary. |
| Has the validation sprint ended? | Current repository milestone verified | The recorded sprint runs August 12–September 11, 2026. No decision outcome is assumed here. |

Sources: [README: product boundary](../../../README.md), [deployment SOP](../../../docs/deploy-railway.md), [pricing FAQ](../../../site/compare/index.html), [configuration](../../../app/core/config.py), [validation sprint](../../../docs/30-day-customer-validation.md).

Historical project memory helped locate the validation and failure-semantics documents. Current repository files were re-read. Historical customer or test counts were not imported as current actuals. An old program-control path referenced by memory is absent from this checkout and is not used as evidence.

## 3. Choose the economic unit carefully

“Per API call” is too ambiguous for this product. At least eight units need separate treatment:

| Unit | Meaning | Use |
| --- | --- | --- |
| Raw inbound request | Every HTTP or JSON-RPC arrival, including retries, reads, denials, and malformed traffic | Capacity, egress, abuse, and machine cost |
| Unique logical governed attempt | First attempt under the persisted wallet/endpoint/idempotency identity | Proposed commercial usage meter |
| Gateway dispatch | A permitted attempt crossing the durable upstream dispatch boundary | At-most-one-dispatch accounting and tool-provider exposure |
| Successful terminal outcome | A valid response finalized at the gateway | Operational completion rate; not independently verified remote success |
| Receipt | Signed accounting evidence for an eligible terminal/reconciled outcome | Evidence volume and retention; not equal to every inbound request |
| Permit or quote | Authorization or price commitment that may cover or precede activity | Control-plane load and workflow friction |
| Customer-environment-month | One dedicated API/database/cache/key/admin deployment over a month | Core fixed delivery unit |
| Customer relationship | Acquisition, onboarding, recurring use, support, renewal, and eventual exit | Contribution lifetime value and payback |

Use **customer-environment-month plus unique logical attempts** for the first commercial model. A customer with two separately operated environments can cost more than a customer with twice the traffic in one environment. Extra environments must be scoped explicitly rather than silently included in “one account.”

For this draft, `N` means first-time logical governed attempts. Repeated requests with the same valid identity do not create a new billable unit. Denials still consume resources; this model conservatively counts first-time governed denials toward the proposed allowance. That is a **commercial hypothesis requiring agreement**, not a change to the existing rule that denied invocations have no tool-credit debit. Discovery, receipt retrieval, permit issuance, polling, and malformed requests need a bounded included allowance or rate limit.

A retry ratio of 20% means 1,000,000 logical attempts can create 1,200,000 invoke requests before discovery and evidence reads. It does not justify invoicing for 1,200,000 completed actions. Similarly, a single upstream tool invocation can involve MCP initialization and transport cleanup. The adapter opens a session and initializes it inside `_call_tool_once`; the economic cost is more than a single signature or SQL insert. [Upstream session lifecycle](../../../app/services/upstream_mcp.py), [one-call implementation](../../../app/services/upstream_mcp.py).

When reporting customer value, keep a second denominator: **completed intended business actions**. If many logical attempts are denied or uncertain, a low cost per attempt can coexist with an expensive or unreliable customer workflow. A reduction in duplicates is valuable only relative to the buyer's actual previous workflow and residual risk.

## 4. Four different money measures must not be merged

**Gateway credits** record authorized and debited amounts within the wallet ledger. **Tool spend governed** is the economic exposure represented by actions. **Company revenue** is the consideration earned under a commercial agreement. **Cash collected** is the money that actually arrives after payment processing and settlement.

These can be numerically unrelated. A customer could use a permit budget equivalent to $100,000 while paying $2,400 for the managed gateway and paying the upstream provider directly. Reporting $100,000 as gateway revenue would overstate the business dramatically. Conversely, an operator can use credits as a synthetic budget in a staging pilot while collecting a real fixed pilot fee outside the product.

The recommended first model has the customer pay its upstream provider directly. Gateway delivery cost then excludes the customer's model tokens and tool-provider invoices. The inspected governed path performs authorization, metering, HTTP MCP transport, persistence, and signing; it does not require an LLM inference for each invocation. Optional external approval integrations and any future model-based controls would need separate cost allocation. This is a conclusion about the inspected path, not every module in the repository. [MCP router](../../../app/routers/mcp.py), [upstream adapter](../../../app/services/upstream_mcp.py).

If the company later resells model/tool usage, model provider spend, refunds, bad debt, payment fees on the full collection, and working capital separately. Principal-versus-agent revenue presentation depends on the actual contract and control of the service; this draft does not make an accounting determination. For management purposes, show both collected volume and the gateway's retained fee so the economics remain visible.

For example, $10,000 collected for upstream usage with a $500 retained fee is not a $10,000 high-margin software sale. A 2.9% + $0.30 card collection would cost $290.30 on that $10,000 transaction, consuming 58.1% of the $500 fee before infrastructure or labor. This example assumes those exact gross and retained amounts; no reseller arrangement is verified. [Stripe domestic card pricing](https://stripe.com/pricing).

## 5. What the current billing code actually tells us

`DEFAULT_PRICING` sets `PLATFORM_FEE` to 0.1 credits per unit. At the default 1,000 credits/USD, that is **$0.0001 per unit**, or **$0.10 per 1,000 units and $100 per million**. The configured upstream tool registers under this category but supplies its own positive credit price. A setting default of zero does not mean a working free upstream: enabled upstream configuration rejects a zero or negative call price. [Pricing table](../../../app/services/pricing.py), [upstream price validation](../../../app/services/upstream_mcp.py), [upstream registration](../../../app/services/upstream_mcp.py).

`COMPUTE_COSTS` assigns `PLATFORM_FEE` a cost of 0.01 credits per unit. `BillingEngine.charge()` computes:

```text
charge_amount = units × configured category price
compute_cost  = units × assigned category cost
margin        = charge_amount − compute_cost
```

For an upstream price of `C` credits, `charge_units_for(C, PLATFORM_FEE)` produces `C / 0.1` units. The assigned cost becomes `(C / 0.1) × 0.01 = 0.1C`. The reported modeled margin is therefore **90% regardless of observed CPU, database, support, or Enterprise spend**. Raising the registered price also raises the assigned “compute cost,” even when the workload is unchanged. This is useful as a configurable estimate but cannot validate actual cost of service. [Cost constants](../../../app/services/agent_money.py), [charge calculation](../../../app/services/billing_engine.py), [unit conversion](../../../app/services/pricing.py).

The inspected `get_arbitrage_report()` has additional limitations for company reporting:

- It selects debit ledger entries, so the displayed total does not net compensating refund entries.
- It does not filter that query to the “yesterday to today” period used in the returned label.
- It aggregates stored assigned costs and margins, not infrastructure bills or time records.
- The query does not provide customer-specific subscription revenue or acquisition cost.
- The arbitrage HTTP surface belongs to the dormant proof expansion, not the supported subscription product.

These are source-level observations, not a claim that a live customer dashboard currently displays these values. No application behavior was changed. The correct report treatment is **“assigned credit economics; unsuitable as evidence of realized business gross margin.”** [Arbitrage function](../../../app/services/billing_engine.py), [router mounting and advertised paths](../../../app/main.py).

The proof categories for media, content generation, scanning, sandboxing, and other expansion services do not establish separate revenue lines for the current product. Do not build a blended revenue forecast by multiplying every category's default price by imagined demand. The repository explicitly keeps those broader capabilities outside the active wedge. [Proof category filtering](../../../app/services/pricing.py), [product priorities](../../../AGENTS.md).

## 6. Cost architecture of the supported deployment

The managed pilot needs its own API service, PostgreSQL service, Redis service, origin, signing material, and operator credentials. PostgreSQL holds durable control and economic evidence; Redis is a separate runtime dependency in the supported deployment. The runbook also requires enabled backups and a successful restore drill before onboarding. Public-site hosting is a separate company/shared expense unless a customer's contract requires a dedicated presentation surface. [Deployment boundary and backup requirement](../../../docs/deploy-railway.md).

| Cost class | Examples | Treatment in the model |
| --- | --- | --- |
| Customer baseline infrastructure | Resident API/database/cache memory, idle CPU, initial volume, monitoring, backup baseline | Fixed per customer-environment-month |
| Incremental machine usage | Active CPU, growing DB footprint, egress, additional logs, incremental backup data | Per logical attempt allowance, valid only at the assumed mix and retention age |
| Enterprise requirements | Contract minimum, premium support, extra control features beyond metered usage | Separate unknown allocation `E` |
| Routine delivery labor | Upgrades, customer support, evidence help, scheduled operational work | Hours × loaded/replacement hourly cost |
| Exception labor | Ambiguous outcomes, disputed debits, rejected responses, reconciliation cases | Event frequency × escalation share × time × hourly cost |
| One-time onboarding | Qualification engineering after sale, install, configuration, restore drill, partner session | Separate setup economics; never disappear inside “free founder time” |
| Customer acquisition | Discovery, sales calls, unsuccessful trials, presales review, sales travel | CAC; excluded from recurring delivery cost |
| Company overhead | Core maintenance, shared tooling, accounting/admin, general legal, founder non-delivery work | Shared operating cost; funded by contribution |

There must be no double counting. If a monthly provider invoice already includes CPU, memory, storage, and logs, do not add a second estimated all-in compute line to it. This model splits a baseline allowance from incremental usage only to make sensitivities understandable. When actual invoices arrive, replace that split with actual tagged costs, then allocate shared items explicitly.

The model's reserve is a 1% planning allowance for service concessions or losses; it is not an actuarial estimate or an accounting conclusion. Large incident liabilities, legal claims, taxes, and negotiated service credits are not proven covered by that allowance. Routine delivery labor and exception labor are deliberately separate, so a 15-minute reconciliation case cannot also be logged as ordinary support in the same model.

## 7. Public vendor prices and the Enterprise gap

The current Railway documentation lists **$20/vCPU-month, $10/GB-month of memory, $0.15/GB-month of volume storage, and $0.05/GB of egress**. These are published monthly equivalents; actual billing uses measured consumption and billing periods. The public pricing page's rounded per-second figures yield slightly different monthly equivalents, especially for storage, so this model uses the documentation's monthly rates for capacity illustrations. [Railway resource pricing](https://docs.railway.com/pricing/plans).

A sample resource-only floor, with **assumed consumption**, is:

| Component | Assumed average resources | Monthly calculation | Cost |
| --- | --- | --- | --- |
| API | 0.5 GB memory; 0.05 vCPU average | 0.5 × $10 + 0.05 × $20 | $6.00 |
| PostgreSQL | 1 GB memory; 0.05 vCPU average | 1 × $10 + 0.05 × $20 | $11.00 |
| Redis | 0.25 GB memory; 0.01 vCPU average | 0.25 × $10 + 0.01 × $20 | $2.70 |
| Persistent volumes | 20 GB | 20 × $0.15 | $3.00 |
| Public egress | 10 GB | 10 × $0.05 | $0.50 |
| **Resource-only illustration** | No performance guarantee | Sum | **$23.20** |

This is neither a measured bill nor a complete qualified pilot budget. It excludes Enterprise terms, meaningful backup history, monitoring services, growing retained evidence, load spikes, restore environments, operations, and customer support. For that reason the account scenarios use broader baseline infrastructure allowances of $75, $150, $500, and $450 rather than presenting $23.20 as an all-in customer cost.

Railway Pro has a $20 monthly subscription/usage minimum, while Enterprise is custom priced. Included usage must not be counted twice as “subscription plus the same usage.” Separate projects also do not automatically mean separate paid workspaces; the actual account and contract structure determines allocation. [Railway plan and subscription terms](https://docs.railway.com/pricing/plans).

The repository SOP's explicit Enterprise requirement creates an unresolved commercial dependency. Public Railway pricing lists committed-spend thresholds for some enterprise features, but none is treated here as a universal Enterprise quote. The correct input is the **incremental cost attributable to the required contract after included resource credits**, allocated across customers on an honest basis. [Railway published pricing and enterprise options](https://railway.com/pricing).

Use `E = $0` only to ask, “What would the account produce before this unresolved requirement?” It is not permission to deploy on Pro, share customer infrastructure, or assume free Enterprise. If a $5,000 workspace minimum includes $1,000 of resource consumption, the extra minimum is $4,000, not another $5,000 added to usage. Dividing that unused minimum across ten hypothetical future customers does not make it disappear from today's cash bill.

## 8. The recurring account model

```text
Revenue R = base fee + max(0, N − included attempts) × overage price
Exception labor X = N × exception rate × human escalation fraction
                    × hours per case × loaded hourly cost
Payment cost P = 2.9% × R + $0.30    [one domestic-card collection/month]
Delivery cost C = baseline infrastructure + N × incremental machine cost
                 + routine delivery labor + X + Enterprise allocation
                 + P + service concession/loss allowance
Delivery contribution = R − C
Contribution margin = (R − C) / R
```

This is an economic management view that includes direct labor at replacement cost. It is not audited financial-statement gross profit. The model includes the illustrative service loss allowance in delivery cost for prudence; accounting presentation may put some items elsewhere without changing the economic burden.

Scenario assumptions:

| Input | Lean pilot | Base account | Volume account | Troubled account |
| --- | --- | --- | --- | --- |
| Monthly unique attempts | 100,000 | 1,000,000 | 10,000,000 | 1,000,000 |
| Baseline infrastructure | $75 | $150 | $500 | $450 |
| Incremental machine cost / attempt | $0.00003 | $0.00010 | $0.00020 | $0.00050 |
| Routine delivery hours | 1 | 3 | 8 | 12 |
| Loaded labor / hour | $75 | $75 | $75 | $100 |
| Exception events / attempt | 0.001% | 0.005% | 0.005% | 0.050% |
| Exceptions requiring human work | 10% | 10% | 10% | 20% |
| Time per escalated case | 15 minutes | 15 minutes | 15 minutes | 30 minutes |
| Loss/concession allowance | 1% revenue | 1% revenue | 1% revenue | 1% revenue |

The machine allowances include an assumed 20% retry mix and ordinary control/evidence traffic. They are planning envelopes, not benchmark results. They include incremental storage costs at a representative operating age; indefinite retention can push an older account outside the envelope. The higher volume cost rate deliberately challenges the assumption that scale automatically improves margin.

<!-- BEGIN SCENARIOS -->
| Monthly scenario | Lean pilot | Base account | Volume account | Troubled account |
| --- | --- | --- | --- | --- |
| Unique governed attempts | 100,000 | 1,000,000 | 10,000,000 | 1,000,000 |
| Revenue (hypothesis) | $1,500.00 | $2,400.00 | $11,400.00 | $2,400.00 |
| Baseline infrastructure | $75.00 | $150.00 | $500.00 | $450.00 |
| Incremental machine cost | $3.00 | $100.00 | $2,000.00 | $500.00 |
| Routine delivery/support labor | $75.00 | $225.00 | $600.00 | $1,200.00 |
| Exception-handling labor | $1.88 | $93.75 | $937.50 | $5,000.00 |
| Payment fees | $43.80 | $69.90 | $330.90 | $69.90 |
| Service concession/loss allowance | $15.00 | $24.00 | $114.00 | $24.00 |
| Enterprise allocation: EXCLUDED | $0.00 | $0.00 | $0.00 | $0.00 |
| Delivery cost incl. labor | $213.68 | $662.65 | $4,482.40 | $7,243.90 |
| Monthly delivery contribution | $1,286.33 | $1,737.35 | $6,917.60 | -$4,843.90 |
| Contribution margin | 85.8% | 72.4% | 60.7% | -201.8% |
| Revenue per 1,000 attempts | $15.00 | $2.40 | $1.14 | $2.40 |
| Delivery cost per 1,000 attempts | $2.14 | $0.66 | $0.45 | $7.24 |
<!-- END SCENARIOS -->

At 100,000 attempts, the recurring fee carries the business and effective price is $15 per 1,000 attempts. At ten million, effective price falls to $1.14 per 1,000, while the example margin falls to 60.7%. That reduction arises because the assumed high-volume machine burden increases and the base fee contributes less per action. These are economic scenarios, not evidence the current deployment can process those loads.

The troubled account is the most important counterexample. Its 0.05% exception rate means 500 events per million attempts. If 20% require half an hour of work, they consume 50 operator hours and $5,000 of labor per month. Together with routine support, the account requires 62 delivery hours. A seemingly small reliability percentage can overwhelm a small contract.

## 9. Enterprise sensitivity and minimum viable revenue

For a target margin `g`, a percentage payment cost `f`, and a percentage reserve `l`, the required monthly revenue is:

```text
Required revenue = (all non-revenue-linked delivery costs + fixed payment fee)
                   / (1 − g − f − l)
```

With a 70% target, 2.9% card processing, and 1% loss allowance, the denominator is 0.261. Consequently, each additional $100 of recurring delivery cost requires approximately **$383.14 of extra monthly revenue** to preserve that target. A dollar-for-dollar pass-through recovers cash cost but does not preserve a 70% blended margin.

<!-- BEGIN ENTERPRISE -->
| Incremental Enterprise allocation / customer-month | Contribution at $2,400 revenue | Margin | Revenue needed for 70% margin |
| --- | --- | --- | --- |
| $0 | $1,737.35 | 72.4% | $2,180.27 |
| $200 | $1,537.35 | 64.1% | $2,946.55 |
| $500 | $1,237.35 | 51.6% | $4,095.98 |
| $1,000 | $737.35 | 30.7% | $6,011.69 |
| $2,000 | -$262.65 | -10.9% | $9,843.10 |
| $5,000 | -$3,262.65 | -135.9% | $21,337.36 |
<!-- END ENTERPRISE -->

The base account can absorb only **$57.35 of additional monthly cost** while keeping 70% margin at its $2,400 price. It can absorb $1,737.35 before reaching zero delivery contribution. Those are very different limits: a positive account can still be an unattractive way to fund acquisition, product maintenance, and business risk.

The 70% target is an explicit management objective for this model, not a market benchmark or an investor requirement. A paid pilot can rationally run below it to buy decision-quality evidence, provided the subsidy is capped, recorded, and does not become an indefinite support obligation.

If Enterprise is a pooled fixed minimum rather than a true per-customer incremental fee, use a company-level minimum-spend model. At low customer count, charge the unabsorbed portion to company overhead or allocate it to the existing accounts; do not hide it. At higher count, resource usage may absorb the minimum and change marginal economics. Obtain the actual contract before extrapolating either result.

## 10. Why pure usage pricing is fragile at the current stage

The following controlled sensitivity holds the base account's cost assumptions constant while varying volume. It isolates arithmetic; it is not the high-volume capacity forecast in Section 8. Enterprise remains excluded.

<!-- BEGIN VOLUME -->
| Monthly attempts | Default-equivalent $0.0001/action | Hybrid revenue | Delivery cost | Hybrid margin |
| --- | --- | --- | --- | --- |
| 10,000 | $1.00 | $1,500.00 | $435.74 | 71.0% |
| 100,000 | $10.00 | $1,500.00 | $453.18 | 69.8% |
| 1,000,000 | $100.00 | $2,400.00 | $662.65 | 72.4% |
| 10,000,000 | $1,000.00 | $11,400.00 | $2,757.40 | 75.8% |
<!-- END VOLUME -->

At the default-equivalent $0.0001/unit, one million units generate only $100. In the base cost scenario, the incremental machine allowance alone is $100; support, exceptions, infrastructure, payment costs, and acquisition remain unfunded. Increasing volume does not repair a fee whose incremental economics are negative.

This does **not** mean the live configured upstream is priced at the default category rate. The real upstream credit price is a required positive configuration value and was not read from deployment secrets. It means the source default should not be promoted into a managed-service pricing recommendation.

A low entry plan can be valid if it has a genuinely different delivery model, sharply bounded support, and low acquisition cost. The supported pilot does not currently establish those conditions. Do not introduce shared SaaS or a new billing system merely to make a spreadsheet's $49 plan look attractive. First verify that buyers want the current managed boundary at a price capable of funding it.

## 11. Compute is a small line item until measurement proves otherwise

It is tempting to define the cost of a governed invocation as the cost of creating an Ed25519 signature. That excludes identity lookup, policy evaluation, budget reservation, wallet locking, debit persistence, dispatch claiming, network transport, result serialization, receipt writing, audit-chain work, and idempotency completion. Those operations create different bottlenecks and cost drivers.

The following is only an **active-CPU conversion**, using Railway's published $0.00000772/vCPU-second. The CPU time quantities are assumptions; they are not measurements of this repository. [Railway public resource rates](https://railway.com/pricing).

<!-- BEGIN CPU -->
| Aggregate CPU seconds / new action | CPU dollars / million | CPU dollars / 1,000 |
| --- | --- | --- |
| 5 ms | $0.04 | $0.000039 |
| 20 ms | $0.15 | $0.000154 |
| 100 ms | $0.77 | $0.000772 |
| 500 ms | $3.86 | $0.003860 |
<!-- END CPU -->

These small numbers explain why optimizing cryptography before measuring the dedicated database and support load is unlikely to move early account economics. They do not imply that a million governed actions cost fifteen cents all-in. CPU time excludes resident memory, storage, managed-service baseline, network, I/O waiting costs, logs, backups, and labor. CPU across all relevant services must be accounted for once, not just inside the Python process.

There is no exact SQL-write count claimed in this report. The path's transaction and state transitions are visible in source, but request-level DB query/commit traces were not collected. The practical benchmark should count statements, commits, lock wait, connection occupancy, and bytes written for success, denial, replay, conflict, refund, and uncertain outcomes separately.

One million attempts in a 30-day month average about **0.386 attempts/second**; ten million average **3.86/second**. A 100-times burst factor turns the latter into roughly 386 attempts/second. Long upstream calls increase concurrent connections even when CPU remains low. Shared-wallet budget and ledger locks can create contention that a smooth average hides. Do not infer capacity from monthly volume alone.

The adapter initializes an MCP session per new tool call. That is a meaningful latency and connection-cost hypothesis to measure. A pooling or session-reuse rewrite is not authorized by the spreadsheet: correctness and claim fencing take precedence, and the current company milestone requires named customer evidence before new capability work.

## 12. Evidence retention can dominate the marginal cost

The durable schema contains more than one receipt. It includes ledger entries, indexed receipt metadata, signed audit records, idempotency envelopes, dispatch attempts, and bounded result JSON. Both `IdempotencyRecordModel.response_json` and `McpDispatchAttemptModel.result_json` can carry response-related data. The upstream response cap defaults to 1 MiB, but a cap is not an average record size. [Ledger model](../../../app/db/models.py), [receipt model](../../../app/db/models.py), [replay and dispatch models](../../../app/db/models.py), [response limit](../../../app/core/config.py).

Model storage as a stock that accumulates over time:

```text
Stored footprint at month t = retained monthly cohorts × new attempts/month
                             × logical bytes across relevant records/action
                             × physical-overhead multiplier
```

Here the logical-byte assumption must already include duplicate payload storage across tables. The illustrative 3x multiplier then represents indexes, row overhead, and working-space allowance; it does not automatically include every backup, WAL archive, or temporary restore copy. All GB and KB in these tables are decimal units.

<!-- BEGIN RETENTION -->
| Logical bytes per new action | 12-month data at 1M/month, 3x footprint (GB) | Monthly volume cost at month 12 | At 10M/month |
| --- | --- | --- | --- |
| 4 KB | 144 | $21.60 | $216.00 |
| 12 KB | 432 | $64.80 | $648.00 |
| 100 KB | 3,600 | $540.00 | $5,400.00 |
| 1,000 KB | 36,000 | $5,400.00 | $54,000.00 |
<!-- END RETENTION -->

The table shows the **monthly volume-storage cost at month 12**, not total first-year spend. With no deletion and approximately linear growth, the cumulative first-year stock-months equal 78 monthly cohorts if each new cohort is charged as present for a full month. An average-arrival convention gives lower first-year storage spend. Document the timing convention before reconciling invoices.

A 12 KB/action, one-million-per-month example adds 36 GB of physical footprint each month with the 3x multiplier. At $0.15/GB-month, that adds $5.40 to the monthly bill for each retained cohort and reaches $64.80/month at month 12. At 100 KB/action and ten million actions/month, month-12 primary-volume storage alone reaches $5,400/month. Large rows also increase backup, restore, index, and query costs not captured by the byte-price calculation.

These diagnostics are **not additional line items to add on top of the aggregate machine allowance in Section 8**. They test whether that allowance is credible for a given workload and account age. If measured retention exceeds the allowance, replace the allowance and recalculate. Quoting an indefinite fixed usage rate without a payload/retention envelope transfers an unbounded storage obligation to the vendor.

No automated evidence-retention/deletion policy was verified here. An `expires_at` column is not proof that terminal financial and replay evidence may safely be removed. The inspected idempotency abandonment method intentionally protects charged or completed records. Treat long retention as a scenario and retention behavior as a contract/design question requiring separate verification. [Protected idempotency records](../../../app/services/idempotency.py).

Cheap object storage is not a free substitute for database evidence. As a price reference only, Cloudflare R2 Standard lists $0.015/GB-month and separate write/read operation charges; the active pilot runbook keeps durable customer evidence in that customer's PostgreSQL service. Moving it changes retrieval, integrity, isolation, and restore assumptions. This report recommends no such migration. [R2 pricing](https://developers.cloudflare.com/r2/pricing/), [current storage boundary](../../../docs/deploy-railway.md).

## 13. Failure paths have different economics

| Path | Current economic state in gateway credits | Cost consequence | Commercial interpretation to agree |
| --- | --- | --- | --- |
| Successful finalization | Charged once | Full control, transport, storage, and evidence path | Count one unique attempt; do not promise independently proven remote effect |
| Finalized replay | Original envelope; no second dispatch/debit | Read, validation, serialization, egress | No second action fee; bound abusive polling separately |
| Scope/budget/policy denial | No tool-credit debit | Validation and eligible denial evidence still cost resources | Disclose whether it consumes a platform allowance |
| Confirmed refunded failure | Debit compensated or never taken | Work can be incurred with no retained tool debit | Avoid using gross debits as net revenue |
| `delivery_uncertain` | Charge retained; no automatic redispatch | Evidence plus possible investigation | Describe the charge and resolution process clearly |
| `response_rejected` | Charge retained after unusable response | Transport and persistence work plus support risk | Do not call it a successful business action |
| Refund failure | Durable operator work remains | Compensation and reconciliation labor | Track unresolved obligations separately |
| Local post-effect crash | Manual review; no automatic redispatch, potentially no receipt | Open-ended investigation burden | Outside the fully reconciled upstream guarantee |

Source: [failure semantics and terminal outcomes](../../../docs/failure-semantics.md).

The retained debit on an uncertain outcome prevents a simplistic “induce timeout, get refund, keep effect” incentive. It is not evidence the customer accepts the contract, and it is not permission to treat every ambiguous gateway credit as collected company revenue. A buyer will ask who investigates, what evidence resolves the case, and who bears the loss if the provider cannot answer.

The stale-claim recovery window is also commercially material. The documented eligibility threshold is 11,430 seconds, followed by a five-minute sweep and possible backlog—nominally about 3.26 hours to pickup at the stated maximum. An immediately detected timeout can already return an uncertain outcome; the long window concerns stale worker/claim recovery. Do not price or sell this as instant reconciliation. [Reconciliation timing](../../../docs/failure-semantics.md).

The model's exception rate is the frequency of economically relevant unresolved or support-generating events, not the overall API error rate. Known denials that need no human work should not be counted as support incidents. Conversely, one correlated upstream outage can generate hundreds of events and a single investigation; multiplying every event by a full case duration would overstate labor. Measure both events and distinct operator cases.

## 14. Support and reconciliation are the strongest operating sensitivities

For the base one-million-attempt account at $2,400 revenue, keeping all other assumptions fixed and excluding Enterprise:

<!-- BEGIN SUPPORT -->
| Routine support hours / month | At $75 / hour | Contribution | Margin |
| --- | --- | --- | --- |
| 1 | $75.00 | $1,887.35 | 78.6% |
| 3 | $225.00 | $1,737.35 | 72.4% |
| 5 | $375.00 | $1,587.35 | 66.1% |
| 10 | $750.00 | $1,212.35 | 50.5% |
| 20 | $1,500.00 | $462.35 | 19.3% |
<!-- END SUPPORT -->

The account can support approximately **3.76 routine labor hours/month at $75/hour** while preserving the illustrative 70% margin, assuming its exception labor stays at $93.75. The base assumption is three hours. One extra hour consumes $75 and reduces contribution margin by 3.125 percentage points.

Exception sensitivity is steeper because it scales with traffic:

<!-- BEGIN EXCEPTIONS -->
| Exception rate | Exceptions per million | Human hours (10% escalated, 15 min each) | Labor cost | Margin |
| --- | --- | --- | --- | --- |
| 0.001% | 10 | 0.25 | $18.75 | 75.5% |
| 0.005% | 50 | 1.25 | $93.75 | 72.4% |
| 0.010% | 100 | 2.50 | $187.50 | 68.5% |
| 0.100% | 1,000 | 25.00 | $1,875.00 | -1.8% |
| 1.000% | 10,000 | 250.00 | $18,750.00 | -705.0% |
<!-- END EXCEPTIONS -->

At the other base inputs, a roughly **0.00806% exception rate—about 81 events per million—uses the available 70% margin budget** under the assumed 10% escalation share and 15-minute handling time. This is a financial threshold, not an SLO or measured reliability target. A change in case duration, batching, escalation, or Enterprise allocation changes it immediately.

Manual human approval is another separate cost. If 1% of one million attempts needs two minutes of approval work, that is about **333 hours/month**. If the customer's own employees approve, it belongs in the buyer's ROI calculation. If the vendor staffs approval, it belongs in delivery cost and requires a different price. The existence of an approval integration does not establish which party bears the labor.

Record support by activity: install help, routine operations, defect investigation, evidence export, security questionnaires, partner workflow debugging, and commercial questions. The classification matters. Presales questionnaires belong in CAC; a recurring evidence-export obligation belongs in delivery; a general product bug fix often belongs in shared engineering. A single hour cannot sit in all three categories.

## 15. Acquisition economics: the expensive unit may be a qualified customer

The active wedge has a demanding adoption path. A buyer must accept another inline dependency, provide one consequential staging tool, assign an engineer, verify evidence independently, and decide who pays. That is a more involved sale than a simple API key signup. The exact sales cycle and conversion rates are not verified.

Calculate acquisition cost over a cohort:

```text
CAC = (sales cash + presales labor + marketing + failed qualification/pilot costs)
      / new paying customers in that cohort
```

When no paying customer has closed, CAC is **undefined**, not zero. Report cohort spend and pipeline status. A prospect's praise is not a denominator. Keep post-sale setup work separate if it is recovered by a setup fee; otherwise track unrecovered onboarding as an additional acquisition-recovery requirement without counting it twice.

An illustrative founder-led funnel might involve 50 targeted prospects, 10 discovery calls, four qualified opportunities, two technical pilots, and one paying customer. Those are assumptions: 20% contact-to-meeting, 40% meeting-to-qualified, 50% qualified-to-pilot, and 50% pilot-to-paid. If the cohort consumes 80 presales hours at $75 plus $2,000 in other acquisition spend, CAC is $8,000. If the same effort wins no customer, the business has spent $8,000 without a validated acquisition unit.

Do not optimize an outreach conversion percentage independently of customer quality. A higher close rate among buyers with tiny exposure and large support needs can worsen total economics. Qualify willingness to operate within the supported deployment boundary before investing in a bespoke integration.

<!-- BEGIN CAC -->
| Acquisition cost / customer | Payback with E=$0 | Payback with E=$1,000 |
| --- | --- | --- |
| $2,000 | 1.15 months | 2.71 months |
| $8,000 | 4.60 months | 10.85 months |
| $20,000 | 11.51 months | 27.12 months |
<!-- END CAC -->

Payback uses recurring delivery contribution, not revenue, and excludes setup contribution in this table. With $8,000 CAC, moving from E=$0 to E=$1,000 extends simple payback from 4.60 to 10.85 months. A six-month payback objective would permit approximately $10,424 of CAC in the first case and $4,424 in the second. These are decision thresholds, not measured efficiency.

Simple payback assumes revenue and contribution persist each month. It ignores churn during recovery, collection delays, ramp-up, expansion, and the time value of money. A first contract with a three-month pilot term cannot be treated as guaranteeing eleven months of contribution. Track committed term and renewal separately.

## 16. Onboarding, paid pilots, and setup pricing

The proposed $2,500 setup fee is intended to expose implementation effort as a real cost. It is not justified by the number of features in the repository. A bounded scope could include one dedicated staging environment, one configured public-HTTPS MCP tool, one restore qualification, one partner session, a replay/conflict/denial walkthrough, and one independent receipt verification.

At 20 delivery hours × $75 plus $100 of one-time machine/other costs, setup consumes $1,600 before collection fees and the planning reserve. A single $2,500 domestic-card collection and a 1% reserve leave **$802.20 of setup contribution**, about **32.1%**. At 40 hours, the same setup loses **$697.80**. The cash-neutral labor ceiling under these assumptions is about **30.70 hours**. Enterprise fees and recurring service costs are additional.

This example deliberately distinguishes setup contribution from recurring margin. The one-time fee should not be added to MRR or ARR, and a high setup collection should not make a loss-making recurring service appear healthy. If the setup involves extensive bespoke engineering, the company is buying research or delivering a services project; record that honestly.

Run the first pilot with a written effort cap and a short decision window. An illustrative internal cap is 20 onboarding hours and a defined number of partner working sessions. If a prospect requires a second tool, private VPC access, regulated production data, high availability, or an uptime commitment, that is outside the current pilot boundary; qualify the request before accepting its cost or changing the product.

The pilot succeeds economically only if it produces useful operating measurements and a real commercial decision. A prepaid pilot is stronger evidence than an unpaid demonstration, but it still does not prove repeatable retention. A written commitment naming a buyer, budget path, and date is commercial evidence; it is not collected revenue.

## 17. Retention, expansion, and contribution lifetime value

A gateway can be deeply integrated yet still be easy to remove commercially if the customer decides the protected workflow has little consequence. Integration friction is not customer value. Retention should be evaluated through continued use of the consequential action, renewal of the paid agreement, and demonstrated reliance on the boundary.

For a flat-contribution account with monthly churn probability `c`, a simple capped 36-month contribution value is:

```text
36-month contribution value = monthly contribution × Σ[(1 − c)^m], m = 0…35
```

This assumes the customer is active for month one, churn happens between monthly periods, and contribution stays constant. It excludes discounting, expansion, contraction, unpaid invoices, exit costs, and changes in retained data cost. It is a sensitivity, not an observed LTV. The cap avoids treating a small assumed churn rate as an unlimited forecast.

<!-- BEGIN LTV -->
| Monthly logo churn assumption | 12-month logo survival | 36-month capped contribution value | Value / $8K CAC |
| --- | --- | --- | --- |
| 1% | 88.6% | $52,743.65 | 6.59x |
| 3% | 69.4% | $38,567.57 | 4.82x |
| 5% | 54.0% | $29,264.65 | 3.66x |
| 10% | 28.2% | $16,982.10 | 2.12x |
<!-- END LTV -->

These values use the base account **before Enterprise allocation**. At E=$1,000, multiply them by approximately 0.4244 because recurring contribution falls from $1,737.35 to $737.35. A superficially strong LTV/CAC ratio can collapse when a previously omitted delivery cost is included.

Track logo retention and revenue retention separately. Net revenue retention includes expansion and contraction in the starting customer cohort; it must exclude new customers. Expansion can come from more governed attempts in the same supported tool. Additional environments increase both revenue and fixed delivery cost. Additional tool breadth is not an assumed growth engine while the one-tool scope remains the supported boundary.

Usage retention alone can mislead. A customer may double attempts through retries, denials, or a broken loop while completing no more useful business actions. Conversely, a customer may reduce raw traffic because duplicate attempts are eliminated while becoming more satisfied. Pair paid renewal with completed workflow counts, supported exposure, and exception burden.

## 18. Company break-even and founder capacity

Recurring contribution pays for acquisition, shared engineering, administration, and profit. A 72% account margin does not mean a 72% company margin. Use:

```text
Company operating result = sum(customer delivery contributions)
                           − shared operating overhead − acquisition expense
                           + setup contribution
```

The following simplified break-even table excludes new acquisition and setup activity. It assumes all accounts look like the base one-million-attempt account and the stated Enterprise allocation is truly incremental per customer.

<!-- BEGIN BREAK_EVEN -->
| Incremental Enterprise allocation / customer | Customers for $3K overhead | For $10K | For $30K |
| --- | --- | --- | --- |
| $0 | 2 | 6 | 18 |
| $500 | 3 | 9 | 25 |
| $1,000 | 5 | 14 | 41 |
| $2,000 | No finite break-even | No finite break-even | No finite break-even |
<!-- END BREAK_EVEN -->

At six base accounts and E=$0, monthly revenue would be $14,400, delivery contribution $10,424.10, and surplus after $10,000 shared overhead only **$424.10**, before new acquisition costs. At ten accounts, $24,000 MRR can produce $7,373.50 after that overhead with E=$0, but a **$2,626.50 loss** with E=$1,000/customer. Revenue milestones alone hide this difference.

The $3,000, $10,000, and $30,000 overhead values are illustrative cost envelopes. Direct delivery labor is already in account cost. If founder compensation is included in overhead, allocate the founder's delivery hours out of that overhead or remove the duplicate labor charge. The model is useful only if it counts each hour once.

Time capacity can fail before cash economics. Twenty base accounts require 20 × 4.25 = **85 delivery hours/month** for routine and exception work. Two new onboardings at 20 hours each bring that to 125 hours before sales, product maintenance, security work, or administration. Adding 40 hours of sales and 40 of shared product work produces 205 hours/month. Under a 160-hour planning capacity, this is not a one-person operating plan.

Do not assume high-volume customers solve the capacity constraint. The volume example requires 20.5 delivery hours per account per month before onboarding; the troubled example requires 62. Customer selection and exception handling may improve capacity more than acquiring additional logos.

## 19. Cash flow, collection timing, and runway

Economic labor cost and immediate cash outflow are different. In the base example, total delivery cost is $662.65, of which $318.75 is routine/exception labor. If the founder performs all that work unpaid, the remaining **$343.90 is a cash-like operating allowance**, not a verified cash bill. It still includes the $24 planning reserve, which may not be spent that month. The unpaid labor remains a real constraint and replacement cost.

For a bank-runway view, exclude noncash imputed labor and unspent reserves, then include actual payroll, contractor payments, provider bills, taxes, acquisition spend, and collection timing. For a sustainable-unit-economics view, include the labor. Reporting only one view either hides the near-term cash requirement or hides the founder's subsidy.

At a hypothetical $10,000/month cash burn, a three-month sales cycle consumes $30,000 before the first collection, unless another revenue stream offsets it. The number is an illustration of timing, not the company's actual burn. A profitable signed contract still cannot pay today's invoice until cash is collected.

Annual prepayment can improve cash timing but creates a year of service obligations. A 15% discount on $28,800 annual recurring revenue removes $4,320 of revenue before considering payment savings or any variable-cost response. Assess the discount against expected avoided churn and working-capital value, not solely the attractive upfront collection.

If customers pay upstream directly, the gateway avoids financing their tool usage. If it resells $50,000/month of provider usage, pays the provider immediately, and collects customers 30 days later, roughly $50,000 of working capital can be tied up before taxes, disputes, or growth. Do not add a prepaid wallet/reseller business merely to monetize an existing credit ledger.

Payment economics also favor aggregation over microtransactions:

<!-- BEGIN PAYMENTS -->
| Single customer payment | Domestic card fee | Effective card rate | ACH processing illustration |
| --- | --- | --- | --- |
| $5 | $0.45 | 8.90% | $0.04 |
| $20 | $0.88 | 4.40% | $0.16 |
| $100 | $3.20 | 3.20% | $0.80 |
| $500 | $14.80 | 2.96% | $4.00 |
| $2,400 | $69.90 | 2.91% | $5.00 |
<!-- END PAYMENTS -->

The table uses Stripe's published US domestic card rate and ACH Direct Debit processing rate of 0.8%, capped at $5. It excludes optional invoicing/subscription software, returns, disputes, international/FX charges, and other product fees. It is not a total-fee quote or evidence those collection methods are implemented here. [Stripe payment pricing](https://stripe.com/pricing).

## 20. Buyer ROI and willingness to pay

The buyer's avoided loss is the best candidate for value-based pricing, but it must be measured. Use:

```text
Expected avoided duplicate loss = consequential actions × baseline duplicate rate
                                 × economic loss per duplicate × effective reduction
Total buyer benefit = avoided loss + independently evidenced operating savings
Total buyer cost = vendor fee + buyer integration amortization
                  + buyer operating labor + residual/introduced operating cost
```

Do not equate the tool's full transaction value with its duplicate loss. A duplicated $10,000 transfer that is reversed in five minutes has a different economic cost from an irreversible $10,000 purchase. The buyer's loss may be unrecoverable spend, recovery labor, delay, lost contribution, contractual cost, or customer damage. Ask for the real mechanism and avoid adding overlapping estimates.

An illustrative buyer has 100,000 consequential actions/month, a baseline duplicate rate of 0.1%, a $50 economic loss per duplicate, and 90% effective reduction from the full adopted workflow. Expected avoided loss is $4,500/month. If separately evidenced operational savings add ten hours at $100, benefit is $5,500. With a $2,400 fee, $200/month amortized buyer integration cost, and $200/month buyer operations, total cost is $2,800; the benefit/cost ratio is about **1.96x**, and net benefit is $2,700/month.

The 90% effectiveness value is not a product guarantee. It must incorporate upstream support for idempotency, correct logical-key reuse, deployment coverage, bypass paths, and residual incidents. The gateway cannot prevent a client from deliberately representing the same business action under unrelated valid identities without additional business identity constraints. [Gateway guarantee boundary](../../../docs/30-day-customer-validation.md), [logical identity and failure limitations](../../../docs/failure-semantics.md).

If the same buyer's actual duplicate rate is only 0.01%, avoided loss falls to $450. Keeping the $1,000 labor savings produces $1,450 of benefit against $2,800 of cost. That buyer should reasonably decline the offer. Increasing the number of product features would not repair this particular economic mismatch.

A useful qualifying threshold, ignoring separate labor savings, is:

```text
Required loss per duplicate = total monthly buyer cost
                             / (actions × duplicate probability × effective reduction)
```

With 100,000 actions, 0.1% baseline duplication, 80% effective reduction, and $2,800 total monthly buyer cost, the threshold is **$35 per duplicate**. At 0.01% duplication it becomes **$350**. This explains why consequential paid or operational side effects are a more plausible first segment than cheap, harmless read-only calls.

Evidence and authorization can have value beyond duplicate prevention, but quantify that separately. Do not price against hypothetical regulatory fines or claim a compliance certification the current release does not have. For an audit-evidence use case, measure analyst hours saved, reconstruction effort, and the buyer's actual acceptance criteria.

## 21. Competitive price anchors and the build-versus-buy objection

Current published prices establish an uncomfortable comparison for a product pitched merely as a gateway:

| Alternative | Published commercial reference | Interpretation for this product |
| --- | --- | --- |
| AWS Bedrock AgentCore Gateway | $0.005 per 1,000 ordinary gateway API invocations; separate charges for other capabilities | Approximately $5 per million gateway invocations is a component-price anchor. It is not an equivalent fully managed transaction-integrity contract. |
| Portkey Production | $49/month; 100,000 recorded logs; $9 per additional 100,000 requests; Enterprise custom | Generic gateway/observability has a low entry price. Deployment and capability scope differ. |
| Stripe idempotent requests | Documented API behavior returns stored outcomes for the same key | Buyers with one provider may prefer native idempotency plus their own controls. No separate unit fee is inferred here. |

Sources: [AWS AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/), [Portkey pricing](https://portkey.ai/pricing), [Stripe idempotency semantics](https://docs.stripe.com/api/idempotent_requests). Prices were checked for this report; no full competitive equivalence audit was performed.

AWS's gateway price is per API invocation, not per the logical economic unit defined here. Initialization, discovery, and other capabilities can add usage. Portkey's inclusion and retention definitions also differ. The table should create a buyer question, not an unsupported claim that any vendor fully reproduces—or fails to reproduce—the repository's economic state machine.

At $2,400/month, a buyer comparing only “one million gateway calls” will see a large premium. The sale must establish why a linked authorization, debit, dispatch, uncertain-outcome, and evidence workflow plus dedicated operation is worth that premium. The repository's own strategy demotes signatures as a standalone differentiator. [Wedge positioning](../../../WEDGE.md).

Build-versus-buy needs the same discipline. If a buyer spends 100 engineering hours at $150/hour to build and validate a sufficiently narrow internal control, initial cost is $15,000. Five hours/month maintaining it adds $750/month. The $15,000 divided by a $2,400 monthly vendor fee is only 6.25 months before maintenance, differences in capability, and vendor integration cost. Do not assume enterprise engineering is infinitely expensive or that the buyer needs every mechanism this repository contains.

Ask what the buyer would actually build, what failure semantics it would accept, and who would operate it. A customer with strong internal platform capabilities may rationally build; a small team with an expensive near-term consequential workflow may value managed delivery. Customer segment selection matters more than asserting generic technical superiority.

## 22. A pricing structure worth testing

The first pricing proposal should be understandable without exposing the repository's service-category taxonomy:

| Commercial element | Illustrative hypothesis | Why it exists |
| --- | --- | --- |
| Initial one-tool setup | $2,500, bounded scope and effort | Recovers onboarding and reveals bespoke work |
| Managed customer environment | $1,500/month starting hypothesis | Funds dedicated operation at low traffic |
| Included volume | 100,000 first-time governed attempts/month | Simplifies pilot purchasing and small usage changes |
| Overage | $1 per 1,000 new governed attempts | Tests a sustainable usage charge without charging identical replays twice |
| Enterprise requirement | Separately resolved quote/allocation | Prevents an omitted contract minimum from destroying margin |
| Additional environment or unusual payload/retention | Explicit review and quote | Avoids silently multiplying infrastructure and evidence obligations |
| Buyer-paid upstream usage | Customer contracts/pays upstream directly | Keeps gateway economics separate from provider resale |

These are test hypotheses, not an instruction to publish a pricing page or implement subscriptions. Start with manual contracting, a monthly usage export, and a simple invoice. The built-in credit ledger can remain the operational budget mechanism. Changing API debit semantics or adding subscription billing is separate work and is unnecessary to learn whether a buyer will pay.

At the base assumptions, variable machine plus exception labor is $0.00019375 per new attempt. To preserve 70% incremental margin after percentage payment/reserve costs, incremental price needs to exceed approximately **$0.00074234/action**, before additional routine labor, infrastructure steps, and Enterprise cost. At the volume-account assumptions, that threshold is approximately **$0.00112548/action**. The proposed $0.001 overage therefore fails a 70% incremental target in that high-volume scenario.

This does not automatically justify a higher quote: willingness to pay still constrains price. It means volume discounts must follow measured declining marginal cost, not an assumption that every additional call becomes cheaper. A customer that insists on very low usage pricing may need a narrower, lower-touch engagement that the present product does not support.

Avoid unlimited support, unlimited retained payloads, unlimited additional environments, guaranteed downstream exactly-once effects, and unmeasured uptime/recovery commitments. These are economic scope controls grounded in current documented limitations, not extra capabilities to build.

## 23. The highest-value measurement plan

The immediate task is to turn a scenario into an account P&L. Use existing evidence exports, provider metrics, and a manual time log first. Instrument new runtime behavior only when needed for the active pilot and reviewed for security and correctness.

| Measure | Definition | Source or collection method | Decision enabled |
| --- | --- | --- | --- |
| Unique attempt volume | Count persisted logical invocation identities over a defined period | Customer-specific idempotency/dispatch records | Usage denominator and adoption |
| Outcome distribution | Success, denial, refund, uncertain, rejected, unresolved | Receipt/dispatch/ledger reconciliation | Failure economics and buyer experience |
| Raw requests and replay ratio | Arrival counts relative to unique attempts | Redacted ingress/runtime metrics | Unbilled capacity and abuse exposure |
| Net credit movement | Debits less correlated refunds by customer and period | Ledger export with exact decimals | Operational accounting, separate from company cash |
| Actual commercial revenue | Earned recurring/setup/usage amounts under each agreement | Invoice and contract records | Revenue; credits do not substitute |
| Cash collected | Settled net receipts and dates | Payment/bank statement reconciliation | Runway and working capital |
| CPU/memory/network | Actual tagged consumption per service | Railway project usage export | Infrastructure cost allocation |
| Database growth | Table+index footprint and response-size distribution | Customer-scoped PostgreSQL measurement | Retention envelope and capacity |
| Backup/restore cost | Billed data plus elapsed operator time | Backup invoices and restore record | Complete recovery cost |
| Added latency | Gateway overhead with and without upstream time | Matched end-to-end timing samples | Inline-dependency adoption cost |
| Routine support hours | Customer, activity, duration | Manual timer/log | Margin and capacity |
| Exception handling | Distinct cases, event fan-out, human time, resolution | Operator case log | True per-incident economics |
| CAC and sales time | All presales spend including failed opportunities | Prospect cohort ledger | Acquisition payback |
| Buyer value | Prior loss, integration hours, recurring work saved, residual incidents | Partner-owned records and interview | Price ceiling and renewal |

Prefer separate per-customer exports over a new shared telemetry data store; the pilot runbook forbids shared customer evidence storage. Capture counts, durations, sizes, and opaque stable identifiers. Raw tool arguments, secrets, customer payloads, or personal data are unnecessary for most economic measurements.

Measure matched periods with timezone and account boundaries. Count a logical action once even when a receipt joins multiple ledger/audit rows. Join refunds through the documented correlation rather than subtracting every credit in a wallet; funding and transfers are not sales refunds. Reconcile the sum of outcome-specific records to the total, and keep unresolved records visible instead of dropping them as “incomplete.”

A week of smooth synthetic traffic can establish a baseline resource shape, but it cannot establish rare-event rates, production reliability, retention, or willingness to pay. For a simple zero-event observation, the approximate 95% upper bound is 3/n under an independent-event assumption. Zero relevant exceptions in 10,000 attempts still permits roughly 0.03%—300 per million—under that approximation. Correlated outages make independent-event assumptions optimistic. Use controlled negative paths and record the remaining uncertainty.

## 24. Recommended experiments and economic stop conditions

Order experiments by how much uncertainty they remove per unit of founder effort:

1. **Resolve the mandatory hosting price.** Obtain or inspect a redacted Enterprise quote/invoice and its credit/minimum structure. Record account/workspace/customer allocation. This removes the largest identified unpriced delivery dependency.
2. **Qualify one buyer's consequential action.** Record current loss mechanism, alternatives, engineer, staging tool, budget owner, and decision date. Reject hypothetical exposure as a substitute for a real problem.
3. **Run the bounded paid pilot.** Track every onboarding hour; execute the existing partner-owned acceptance flow; collect workload/cost/outcome data and independent verification evidence.
4. **Offer a concrete renewal price.** State recurring service, volume, payload/retention scope, support, and hosting terms. A renewal decision is stronger evidence than agreement with a hypothetical survey price.
5. **Replicate with a second independent customer.** Determine whether installation time and support decline without weakening the required controls. One exceptional buyer does not establish repeatability.

The validation sprint's recorded decision date is September 11, 2026. Use that existing gate rather than opening another unconstrained research or feature program. If a complete pilot cannot fit before it, record the exact missing commercial or technical evidence and a bounded next action; do not relabel local proof as completion. [Existing milestone and day-30 decision](../../../docs/30-day-customer-validation.md).

Suggested **analytical** stop/reprice thresholds:

- The buyer's quantified benefit does not exceed total buyer cost with credible assumptions.
- Required Enterprise allocation makes recurring contribution negative at the acceptable price.
- Routine support repeatedly exceeds the price's supported labor budget.
- Exception frequency, handling time, or large retained payloads invalidate the quoted envelope.
- Onboarding exceeds the agreed effort cap without a documented, paid reason to continue.
- The buyer requires unsupported deployment/data/SLA conditions to make the purchase.
- No budget owner, partner engineer, staging action, or purchase decision emerges from qualification.

These are decision rules proposed by this report, not automated production controls. “Reprice” may mean reducing scope, declining a customer, or ending a subsidized pilot. It does not automatically mean building a new feature or reducing integrity guarantees.

## 25. What to freeze and what to improve first

Keep broad proof-surface monetization, a marketplace, provider resale, shared SaaS, new infrastructure orchestration, and speculative additional-tool support frozen unless named customer evidence clears the repository's gate. They introduce acquisition, capital, compliance, and operational burdens that this product has not yet earned the right to assume.

The most useful near-term improvements are analytical and operational: honest cost reporting, separate actual revenue from credits, track labor, obtain the infrastructure quote, cap pilot scope, and measure the existing one-tool path. The debit-only/arbitrage-report limitations should be recorded as reporting limitations; correcting that dormant surface is not a prerequisite to using a manual account P&L for a pilot.

Do not weaken idempotency, dispatch fencing, receipts, tenant boundaries, or evidence durability to achieve a target margin. Those controls are part of what a customer would be paying for. If the smallest trustworthy deployment cannot be sold above its cost, the issue is fit, price, or deployment scope—not a mandate to remove the product's integrity properties.

## 26. Model files, reproducibility, and interpretation

The companion model uses the Python standard library and no application imports. It never reads credentials, customer records, or live services. Every scenario input is editable in [assumptions.json](../../../docs/research/unit-economics-2026-09-05/assumptions.json). The calculations are in [model.py](../../../docs/research/unit-economics-2026-09-05/model.py), with [scenario CSV](../../../docs/research/unit-economics-2026-09-05/scenarios.csv), [JSON results](../../../docs/research/unit-economics-2026-09-05/model-results.json), and [generated tables](../../../docs/research/unit-economics-2026-09-05/calculated-tables.md).

From the repository root:

```bash
.venv/bin/python docs/research/unit-economics-2026-09-05/model.py
```

The generated scenario tables reconcile revenue, delivery cost, contribution, per-unit measures, and sensitivity formulas. The report prose is a dated draft: changing inputs requires reviewing the surrounding narrative and any manually worked examples before sharing it. The CSV contains calculated values rather than spreadsheet formulas; `assumptions.json` and the Python model are the editable source of truth.

The standalone HTML includes a small account calculator for exploring the base relationship. Its results are scenarios and do not establish actual hosting eligibility, operating performance, or buyer demand. It does not modify the report inputs or application configuration.

## 27. Evidence limits and remaining risk

This draft did not access Railway billing, customer contracts, bank statements, production metrics, private CRM records, or a deployed database. It did not benchmark the gateway, run the application's test suite, verify hosted CI, or reproduce crash-recovery proofs. The repository provides specific correctness tests and evidence references, but those results were not freshly executed for this economics report.

Public vendor prices were read from official pages. Provider credits, taxes, regional rates, negotiated terms, minimum commitments, and future changes can alter the actual bill. The Enterprise requirement remains the most significant unresolved contractual input. The report's assumptions are deliberately transparent so that a quote and one measured pilot can replace them.

The main business risks are insufficient buyer value, high acquisition effort, low renewal, persistent support load, correlated failures, growing retained evidence, and an expensive dedicated deployment. Product correctness reduces some risks but does not establish a viable price or a repeatable sales motion.

The defensible claim today is narrower: **the current product has a specific economic-control mechanism whose commercial unit economics can be modeled, but actual customer profitability and scalable demand remain not verified.** The appropriate next investment is a bounded paid partner experiment with measured delivery cost and a real renewal decision.

## 28. Work record

- **Files changed:** this report and its companion analytical files under `docs/research/unit-economics-2026-09-05/` only.
- **What changed:** added a detailed economic assessment, explicit scenarios, reproducible calculations, and a local HTML reading/calculator view. No application billing, API, schema, auth, or deployment configuration changed.
- **Tests run:** model arithmetic and reconciliation checks, targeted lint of the model, report/link checks, and local HTML/calculator inspection; final verification details are recorded in the companion validation file.
- **What passed:** see [VALIDATION.md](../../../docs/research/unit-economics-2026-09-05/VALIDATION.md) for the exact completed checks.
- **What was not tested:** product runtime, production performance, real invoices, actual customer economics, and hosted deployment/CI.
- **Remaining risks:** unknown Enterprise cost, unmeasured workload and labor, no supplied commercial actuals, and no validated willingness to pay for the proposed prices.
- **Recommended next step:** resolve the Enterprise quote and use one paid, instrumented partner pilot to replace the highest-impact assumptions.
