# Agent Middleware API: unit economics reconsidered

**Finalized September 8, 2026 • Evidence collected September 5 Pacific time / September 6 UTC • USD**

This report replaces the recommendation in the earlier September 5 draft. It combines a fresh review of primary sources, read-only Railway usage retrieval, the public deployment's health data, current repository inspection, and explicitly hypothetical commercial models.

**Decision:** continue a tightly bounded customer-validation experiment. The evidence is more encouraging about small-scale machine cost than the first report suggested, but less persuasive about differentiated demand and the proposed subscription price. The central risk is whether a buyer will pay for the specific gateway guarantee after accounting for integration and support.

**Evidence boundary:** actual project resource usage is now available. Actual product revenue, paying-customer count, collection history, commercial workload, support time, conversion, retention, and the applicable Enterprise contract remain unknown. Unknown does not mean zero.

**Source snapshot:** repository commit 795cd9b3c691a2c697bfef364546940dd5780e93. The observed deployment reports commit 2880ca706d2f4779876097e9414b6f1fab691a3e. These are different versions; local source inspection is not deployed-release verification.

## 1. What changed my recommendation

The first report correctly separated internal credits from company revenue and recognized the importance of support labor. Its center of gravity was wrong. A speculative Enterprise allocation received more emphasis than measured resource usage, source independence, and the conditions under which the product can prevent a buyer's actual failure.

The fresh research changes five judgments.

First, the project's previous billing period incurred **$3.68 of provider-reported metered resource usage**. This is a real observation, not a modeled server bill. It is small enough that routine support can readily exceed machine spending by an order of magnitude. It does not establish a $3.68 commercial customer cost: the current stack is a demonstration environment with very little observed dispatch history.

Second, the deployment SOP's Enterprise requirement is a **product and operating policy to justify**, not proof that the code intrinsically needs an expensive contract. A customer-specific project is not automatically a customer-specific paid workspace or a new Enterprise minimum. Contract terms still matter, but the right question is which required control creates an incremental cost.

Third, the apparent independence of some problem evidence was overstated. The Stripe and CrewAI issues were opened by the same author, who promotes a related guard implementation. The LangGraph issue is a distinct firsthand production report, not an independently reproduced incident. These distinctions lower confidence in demand while preserving useful information about failure mechanisms. [Stripe issue](https://github.com/stripe/ai/issues/402), [CrewAI issue](https://github.com/crewAIInc/crewAI/issues/5802), [LangGraph issue](https://github.com/langchain-ai/langgraph/issues/7417).

Fourth, the most consequential technical qualification belongs in the business case: **different accepted idempotency keys represent different operations**. The gateway does not infer that two differently keyed requests are the same business intent. A prospect whose agent invents a fresh key after every retry needs an integration that preserves operation identity before this guarantee addresses their problem. [Failure semantics and key contract](../../../docs/failure-semantics.md).

Fifth, fresh alternatives show that policy, budgets, receipts, and routing are increasingly available at a range of prices. Low published prices constrain generic positioning; high published pilot prices demonstrate seller ambition, not willingness to pay. Neither justifies mechanically choosing a cheaper or more expensive subscription.

My revised recommendation is therefore to **sell and measure one protected workflow, with a bounded setup deliverable and a separately scoped recurring service**. Keep $499, $999, and $1,500 as testable offer hypotheses matched to delivery scope. Do not publish these as validated tiers. A $1,500 offer may be economically sensible, but this research has not established that a buyer values the current pilot enough to accept it.

## 2. Corrections to the earlier analysis

| Earlier emphasis | Revised treatment | Effect on the decision |
| --- | --- | --- |
| All financial inputs unknown | Resource usage has been retrieved directly; most commercial actuals remain unknown | Use the measured bill in its proper scope |
| Enterprise cost dominates uncertainty | Separate contractual policy, workspace commitment, and incremental customer usage | Resolve the requirement without letting an invented fee drive the thesis |
| $1,500 base plus $0.001 overage is the lead commercial hypothesis | Flat, scoped workflow service is the first test; usage is an operating boundary until metering and buyer value are established | Reduces premature packaging precision |
| One million attempts is the central account | Use 10K and 100K operating illustrations; keep 1M as an unbenchmarked stress case | Fits the evidence maturity more honestly |
| Several issues support external demand | Deduplicate authors and distinguish implementation advocacy from firsthand operating pain | Lower confidence in demand and acquisition efficiency |
| Idempotency solves the cited retry problem | Only if identity survives retry, restart, and framework reconstruction within the supported scope | Integration becomes a commercial acceptance criterion |
| A favorable modeled margin suggests an attractive business | Margin must survive onboarding, acquisition, retention, and founder capacity | Separates a useful technical product from a repeatable company |

The previous draft remains available as a historical document. Its calculations were scenarios, and their arithmetic is not invalidated by new evidence. Its weighting and recommendation are superseded by this report. [Earlier report](../../../docs/research/unit-economics-2026-09-05/REPORT.md).

This revision does not conclude that Enterprise costs are zero, that the product is commercially validated, or that low-cost alternatives reproduce the entire transaction state machine. Those questions remain open at different evidence levels.

## 3. The evidence ladder

A unit-economics report needs to separate observations that are often collapsed into one attractive story.

| Evidence | What it establishes | What it does not establish |
| --- | --- | --- |
| Provider usage report | Metered resource charges attributed to the project and period | Account invoice, payment, full contractual cost, customer unit cost |
| Public health response | Reported deployed commit, dependency status, and scoped counters at that moment | Qualified deployment, load capacity, customer identity, complete sales activity |
| Current source | Implemented pricing calculations and documented contract boundaries | Behavior of a different deployed commit or a real partner integration |
| A firsthand public issue | The author's report of a problem in their environment | Independent reproduction, buyer budget, intention to purchase this product |
| Competitor pricing page | The seller's published offer and stated commercial status | Completed sales, retention, true service delivery cost |
| Scenario calculation | Consequences if the inputs hold | Probability that those inputs will hold |
| Paid partner acceptance and renewal | Direct evidence of value and commercial behavior for that partner | Broad market demand or a stable cohort |

The strongest new evidence in this revision is the provider usage retrieval. The most important negative correction is the weaker independence of market evidence. The most important unresolved experiment is a partner-owned staging workflow with stable operation identity and an engineer who verifies the resulting receipt independently.

The repository already sets that partner milestone and requires a commercial commitment. Technical demonstrations should support that milestone rather than substitute for it. [Customer-validation sprint](../../../docs/30-day-customer-validation.md).

## 4. Actual resource usage: what the current project costs

The read-only provider usage query returned the following values. The curated
model input keeps only coarse period labels, generic service categories, and
amounts rounded to four decimals; it omits account, project, service, and exact
billing-window identifiers.

<!-- BEGIN OBSERVED -->
| Service | Previous period usage | Current partial period usage |
| --- | --- | --- |
| database | $1.68 | $0.42 |
| API | $1.38 | $0.24 |
| cache | $0.13 | $0.02 |
| pilot tool | $0.43 | $0.08 |
| retired service | $0.06 | $0.00 |
| Project total | $3.68 | $0.76 |
<!-- END OBSERVED -->

The curated previous total is **$3.6773**; the current partial total is
**$0.7593**. Rounding displayed service totals can cause a one-cent difference
from the displayed project sum. The model reconciles every retained service
subtotal.

The core active API, PostgreSQL, and Redis services account for approximately **$3.19** of the previous period. The separate demonstration upstream contributes approximately **$0.43**; deleted services contribute approximately **$0.06**. That upstream is part of demonstrating the product, whereas a commercial buyer may pay for its own actual tool. Keeping those categories separate prevents accidental tool-cost resale assumptions.

Memory dominates the active API and database resource charges in this observation. This supports a narrow inference: the lightly used deployment is inexpensive in metered-resource terms. It says little about sustained utilization, high availability, larger retention, restore exercises, customer operations, or time spent investigating failures.

**This is not the full account bill.** The query does not establish plan fees, unused commitment, credits, tax, discounts, payment settlement, or allocation of shared account costs. An account-level total also includes unrelated projects and is not an appropriate substitute for this project's costs.

The observation also contains varying service lifetimes and activity within the month. It should not be advertised as a normalized monthly quote for a fresh always-on customer stack. The next commercial pilot should reconcile its actual invoice and resource period, including backups and any restored sibling service used during qualification.

[Curated resource-cost input](../../../docs/research/unit-economics-reconsidered-2026-09-05/resource-cost-input.json).

## 5. Why there is still no measured cost per action

The public health endpoint reports **31 succeeded and one returned-error durable dispatch records**, with zero uncertainty and reconciliation backlog in the observed state. It also reports zero calls in its process-local counters. Those are different scopes: one survives in the durable backend; the other resets with the process. The public upstream tool is partner.echo.

The correct conclusion is that the observed deployment has a small durable dispatch history and no reported backlog at that moment. It is not that no calls ever happened, nor that the product has a zero production failure rate. The single returned error does not establish a platform defect rate either.

Dividing $3.68 by 32 would be invalid. The numerator covers a billing period and several services; the denominator is a point-in-time durable history with no matched billing-period boundary, customer attribution, retained-history guarantee, or separation of test activity. Most idle infrastructure cost would also be incorrectly characterized as marginal request cost.

Likewise, the process-local latency total cannot be divided by an independently retrieved durable count. A correct measurement needs matching time windows, deployment versions, tenants, workload classes, retention policies, and billing resources.

A seven-day resource query returned current CPU and memory summaries. A seven-day HTTP query failed because of the provider's data-point limit; the shorter one-day HTTP query returned service identities without request measures. Neither produced a usable historical throughput denominator. This report does not fill that gap with an invented count.

The live deployment reports commit **2880ca706d2f4779876097e9414b6f1fab691a3e**; the reviewed local source is **795cd9b3c691a2c697bfef364546940dd5780e93**. This is why the report treats current source behavior and current live observations as separate evidence.

The raw runtime response is intentionally not retained. Historical observation:
[public health endpoint](https://api.thisisatest.tech/health/dependencies).

## 6. Enterprise hosting: a decision to justify

The deployment SOP explicitly calls for a separate Railway Enterprise project per customer, with its own API, PostgreSQL, Redis, domain, administrators, signing material, and upstream credentials. It also limits the supported pilot to synthetic or redacted low-sensitivity workloads and requires a backup and restore drill. These are the current operating instructions, not speculative architecture. [Deployment SOP](../../../docs/deploy-railway.md).

The research did not find evidence that every customer therefore creates a separate Enterprise contract. Project isolation, workspace billing, contractual support, and infrastructure consumption are distinct dimensions. An Enterprise-only control could create a genuine cost step, but its amount and billing scope require the actual agreement.

Railway publicly lists Pro at a $20 usage minimum with $20 of included usage and Enterprise as custom. That is a relevant alternative to evaluate for an appropriately scoped pilot; it is not authorization to override the current SOP. Public plan positioning also distinguishes ordinary production teams from Enterprise needs. [Railway pricing](https://railway.com/pricing).

My recommendation is to document **which specific pilot requirement needs Enterprise**, who owns that requirement, and what lower-cost configuration would fail to provide it. If the justification is only the word “enterprise” in the customer description, reconsider the policy. If the buyer needs a contracted control or support commitment unavailable elsewhere, price that requirement explicitly.

Keep customer isolation, private data services, secret handling, restore qualification, and honest workload restrictions as requirements. A cheaper plan name does not eliminate them. Conversely, an expensive plan name does not qualify a deployment or make sensitive workloads acceptable.

A change to this deployment policy should be a deliberate, separately reviewed operating decision. This report changes no configuration and makes no commercial commitment to a provider. It recommends resolving the policy alongside qualification, rather than waiting for a large generic quote before establishing whether a buyer wants the product.

## 7. Model the provider commitment once

A creditable workspace commitment should not be added to usage a second time. For a simple contract where the minimum is fully usable against eligible usage:

**Workspace bill = max(commitment, eligible resource usage) + noncredited fees.**

**Incremental resource bill for a new customer = bill after adding that customer − bill before adding that customer.**

These equations are generic accounting models. Actual Enterprise terms may contain separate fees, limited credits, multiple pools, expiration, or noncreditable items. Those terms must replace the simplified formula.

<!-- BEGIN COMMITMENT -->
| Illustrative workspace commitment | Customers | Usage total ($20 each) | Workspace bill | Unabsorbed minimum | Allocated / customer | Next resource increment |
| --- | --- | --- | --- | --- | --- | --- |
| $20.00 | 1 | $20.00 | $20.00 | $0.00 | $20.00 | $20.00 |
| $20.00 | 5 | $100.00 | $100.00 | $0.00 | $20.00 | $20.00 |
| $20.00 | 20 | $400.00 | $400.00 | $0.00 | $20.00 | $20.00 |
| $20.00 | 50 | $1,000.00 | $1,000.00 | $0.00 | $20.00 | $20.00 |
| $1,000.00 | 1 | $20.00 | $1,000.00 | $980.00 | $1,000.00 | $0.00 |
| $1,000.00 | 5 | $100.00 | $1,000.00 | $900.00 | $200.00 | $0.00 |
| $1,000.00 | 20 | $400.00 | $1,000.00 | $600.00 | $50.00 | $0.00 |
| $1,000.00 | 50 | $1,000.00 | $1,000.00 | $0.00 | $20.00 | $20.00 |
<!-- END COMMITMENT -->

The $1,000 rows are **hypothetical commitment stress cases**, not a Railway quote. The $20 per customer's resource usage is also an assumption. The table demonstrates allocation behavior without presenting an estimate as a contract.

If the workspace commitment is underused, the next small customer may add no immediate resource bill. It still adds support, risk, and opportunity cost; zero incremental provider billing does not mean zero delivery cost. Conversely, dividing an unused commitment among many imagined future customers does not fund today's shortfall.

For management reporting, keep two views. The customer contribution view assigns directly attributable delivery expenses and a transparent resource allocation. The company view includes the entire actual provider bill and all unabsorbed commitments. Reconcile the views monthly so no expense disappears between them.

The recurring scenarios below include a resource allowance but no additional Enterprise contract increment. If a contract creates cost beyond that allowance, incorporate it once under the actual pool structure. The omission is an explicit unresolved input, not a statement that the company can serve qualified customers without it.

## 8. What unit should be sold?

The most useful initial commercial unit is **one supported consequential workflow per customer-month**, with one configured upstream MCP tool and a named operational owner. An operation count remains valuable for usage boundaries and cost measurement, but it need not be the buyer's primary purchasing unit.

The buyer is purchasing controlled execution and the ability to explain an ambiguous outcome. A thousand harmless lookups and a thousand consequential actions may consume similar gateway resources while creating very different buyer value. Pricing solely by calls can therefore detach price from the reason a buyer cares.

For measurement, retain at least six distinct units: received requests; unique accepted logical operation identities; dispatch claims; finalized outcomes; durable evidence footprint; and human delivery hours. Replays and denials consume resources even where no new economic debit occurs. Failed and uncertain outcomes can consume more labor than successful calls.

A commercial bill is a separate contract from the internal ledger. For the first scoped offer, use a fixed fee with written usage, retention, and support boundaries. Define whether exceeding those boundaries pauses enrollment, triggers a reviewed quote, or invokes an agreed overage. Do not introduce surprising fees for denied attempts or charge a second commercial operation fee for an exact replay.

At higher volume, a base fee plus usage can make sense after the cost slope and billing identity are measured. The earlier $0.001 overage was an unvalidated design choice. It should not become an application billing rule merely because it appeared in a financial report.

Keep upstream tool spending outside platform revenue when the buyer contracts and pays for that tool directly. A $100 payment or a $10 paid API call passing through the gateway is not automatically $100 or $10 of company sales.

## 9. The guarantee has a commercial boundary

The strongest product claim remains scoped economic authorization: one accepted idempotency key permits at most one gateway dispatch to the configured upstream MCP tool and at most one linked ledger debit, with the documented finalization and reconciliation behavior.

This is a valuable control, but its qualifications determine the addressable problem.

| Prospect's problem | Fit of the current guarantee |
| --- | --- |
| Network or framework retry preserves the operation key in the supported scope | Strong candidate for a partner acceptance test |
| Framework reconstructs the same intent with a fresh key | Requires stable identity integration; distinct keys are distinct operations |
| One upstream request internally creates two effects | Outside proof of one gateway dispatch; upstream behavior must be assessed |
| Remote effect occurs but response is lost | Relevant: explicit uncertainty and no automatic redispatch; does not prove the remote result |
| Local tool crashes after an effect | Different path with manual review; do not sell the remote dispatch state machine as local behavior |
| Customer wants a global monthly cash settlement or regulatory guarantee | Outside the current internal-ledger and low-sensitivity pilot scope |

The fresh-key qualification directly affects the use of the Stripe issue as sales evidence. If the customer's existing SDK can preserve a business operation ID and the upstream already offers adequate idempotency, the incremental value of another gateway may be limited. If the customer needs policy, debit integrity, and durable ambiguity handling across their chosen tool boundary, there may be a stronger reason to buy.

The product does not perform semantic deduplication of arbitrary intentions. Adding that as a response would introduce difficult questions about repeated legitimate actions and false suppression. The first task is to integrate the existing contract with a stable, caller-owned identity, not to invent a broader guarantee.

Receipt verification proves properties of the gateway record and signature. It does not independently prove a downstream bank transfer, customer email, or database mutation occurred exactly once. A buyer's acceptance test should include the upstream's own evidence where effects matter.

[Failure semantics](../../../docs/failure-semantics.md), [wedge and boundaries](../../../WEDGE.md), [security limitations](../../../SECURITY_LIMITATIONS.md).

## 10. Reassessing the public problem evidence

The repository's earlier market research describes several public issues as strong external validation. A source-quality audit supports a more cautious interpretation.

| Source | Fresh observation | Revised evidence treatment |
| --- | --- | --- |
| Stripe AI issue 402 | Opened by azender1; describes retries with new keys and points to the author's SafeAgent guard | Mechanism report and related-tool advocacy; not a verified loss or buying signal |
| CrewAI issue 5802 | Also opened by azender1; describes repeat side effects and links a guard implementation | Same-author corroboration of a mechanism across frameworks; not an independent second buyer |
| LangGraph issue 7417 | Different author reports production re-execution of long calls and redundant cost | Firsthand reported operating pain; not independently reproduced here |
| OpenBB issue 7455 | Feature request for signed receipts; promotes a reference implementation | An attributable request, not evidence that an OpenBB buyer has budget or operates the claimed workflow |

Sources: [Stripe](https://github.com/stripe/ai/issues/402), [CrewAI](https://github.com/crewAIInc/crewAI/issues/5802), [LangGraph](https://github.com/langchain-ai/langgraph/issues/7417), [OpenBB](https://github.com/OpenBB-finance/OpenBB/issues/7455).

The OpenBB issue's author identity and product role do not establish that the author is a production OpenBB operator. Its claims about legal requirements are not treated as legal findings. This report does not repeat the earlier characterization of a verified production operator asking for the feature.

Similarly, a report labeled “confirmed production incident” in an internal document should be attributed to the person who reported it unless additional confirming evidence exists. “Verified that the issue says this” is different from “verified that the incident occurred exactly as described.”

None of these observations implies bad faith by an issue author. Tool builders often understand a real problem well. The analytical correction is to avoid counting their related posts as independent purchasing demand.

This revision therefore preserves the technical problem hypothesis while reducing confidence in broad demand, easy acquisition, and a large prevention-value pool. The appropriate response is narrower customer work, not another generalized feature expansion.

[Existing market research for comparison](../../../docs/market-research-2026-08.md).

## 11. A fresh comparison of published offers

The comparison below describes public offers as observed, not tested substitutes or verified customer transactions.

| Alternative | Published price or status | Economic relevance and limits |
| --- | --- | --- |
| AWS AgentCore Gateway plus Policy | Gateway $0.005/1,000 invocations; Policy $0.000025/authorization request | About $30 for 1M gateway invocations plus 1M ordinary authorizations, before other services and operations |
| Portkey Production | $49/month with 100K recorded logs; $9 per additional 100K requests | Low anchor for gateway and observability buying; custom security and residency needs belong to a different offer |
| Bindfort Team / Business | $249 / $999 per month; paid activation is guided; a small design-partner offer includes a free period | More direct policy/evidence positioning; published prices are not proven paid adoption |
| Permission Protocol | Free developer entry; design-partner pilot from $50K over eight weeks for one gate | Shows a high-value workflow sales thesis; no transaction evidence was established |
| AgentOracle | $99/month subscription; $0.09 per verification described as a future general-availability rate | Do not treat a future usage rate or open beta endpoint as current paid usage |
| ABOM | Free Apache-2.0 self-hosted edition; hosted per-call offer without a public numeric rate | Free enforcement/provenance alternatives challenge a receipt-only license pitch |

Sources: [AWS](https://aws.amazon.com/bedrock/agentcore/pricing/), [Portkey](https://portkey.ai/pricing), [Bindfort](https://bindfort.com/pricing), [Permission Protocol](https://www.permissionprotocol.com/), [AgentOracle](https://agentoracle.co/pricing), [ABOM](https://abom.ai/pricing.html).

The $30 AWS calculation assumes one ordinary gateway invocation and one authorization per modeled action. Extra discovery, ping, search, policy creation or generation, guardrail use, runtime, storage, observability, tool spending, and operational labor can change the bill. It is a component comparison, not a complete replacement quote.

AWS also documents session-based temporal policy for budgets, rate limits, prerequisites, and action ordering. Session scope matters: caller-provided session identity and expiration define the history boundary. These capabilities make a generic budget or policy claim less distinctive; the inspected documentation does not by itself establish equivalence to this repository's linked debit, dispatch claim, and uncertain-outcome reconciliation. [Temporal policy documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-session-based-temporal.html).

The implication is not that this product must charge $30, $249, or $50,000. Managed integration, specialized operational responsibility, and buyer value can justify a premium. But a premium must pay for something the buyer actually needs beyond cheaply available components.

There is no evidence here of a durable monopoly on signatures or policy. The defensible commercial candidate is the narrowly implemented workflow plus the reliability of operating it and reducing the customer's own engineering burden. That candidate remains unvalidated.

## 12. Build versus buy is the real comparison

A capable buyer may already have a durable job queue, operation IDs, upstream idempotency, an internal ledger, and an incident process. For that buyer, buying another gateway adds deployment, dependency, and review work. The relevant competitor may be a small integration in the existing system rather than a named vendor.

A useful comparison separates three situations.

A buyer with a supported framework, one consequential tool, and no durable identity discipline may need a small correction to its current integration. If that correction solves the entire problem, this product's managed subscription is hard to justify.

A buyer with several disconnected controls may value a coherent debit-to-dispatch record and explicit ambiguity handling. The product could save engineering and investigation time, provided integrating it is simpler than maintaining the existing controls.

A buyer with extensive private-network, procurement, regulated-data, or service-level requirements may have substantial willingness to pay but fall outside the current pilot. That buyer is not evidence to add a large platform before securing a concrete commitment.

The repository is MIT licensed. A buyer can evaluate and self-host the software within that license, so a commercial fee must be understood as payment for hosted operation, setup, support, or a contracted outcome rather than access to scarce source code. Self-hosting still has operating costs, but the source license weakens a license-only pricing story. [License](../../../LICENSE).

Use discovery to estimate the buyer's remaining implementation work, not the total effort that went into this repository. Sunk engineering effort does not determine buyer value. A correct feature that a customer can obtain more simply elsewhere may have little incremental commercial value even if it took substantial effort to build.

## 13. What the billing code can and cannot measure

The source still uses a default PLATFORM_FEE price of 0.1 credits and an assigned compute cost of 0.01 credits. At the default exchange rate of 1,000 credits per dollar, the default fee is $0.0001 per unit. Those constants are not a signed customer contract or a cloud-cost measurement. [Pricing definitions](../../../app/services/pricing.py), [assigned cost table](../../../app/services/agent_money.py).

The upstream registration supplies its own positive credit price. The unit conversion divides that price by the category's default. Consequently, the assigned cost scales with the charged price, and the default category produces a modeled 90% spread mechanically. Raising the configured price can raise the assigned “cost” with no change in actual resource consumption.

The arbitrage report aggregates debit entries and uses assigned costs. In the inspected implementation, its displayed yesterday-to-today label does not correspond to a matching timestamp filter, and refunds are not netted into that debit aggregation. It is not a usable company gross-margin statement. [BillingEngine.get_arbitrage_report](../../../app/services/billing_engine.py).

Four quantities must remain separate: internal ledger debits; customer money collected; recognized platform revenue; and cash or economic delivery cost. A refunded internal debit need not produce a card refund of a monthly service fee. A prepaid credit purchase is not automatically the same-period revenue from completed service. This report uses simple operating contribution, not an accounting-policy opinion.

No per-action model inference was found in the inspected governed upstream path. The customer's agent model and its upstream tool may have substantial costs, but those costs belong in the buyer's economics unless the company explicitly resells them. Optional or frozen product surfaces should not be used to inflate the cost of the supported one-tool loop.

A first useful management report can be manual: reconcile the platform invoice, provider bill, delivery time, and period-matched operation counts for one pilot. Building a new analytics subsystem before that reconciliation would add work without resolving the main uncertainty.

## 14. The revised recurring model

The working illustration is a **$999 monthly workflow fee**, **100,000 unique accepted attempts**, **$50 resource allowance**, **$20 other directly attributable delivery allowance**, and **three routine delivery hours at $75 per hour**. These are operating assumptions, not a production entitlement or benchmark.

The resource allowance includes the scenario's API, database, cache, and provider storage/backup budget. It is not added to the observed demonstration bill. Other delivery covers a modest allocation for customer-specific monitoring or operational services; it excludes shared company overhead. Both must be replaced by measured attributable costs.

Exception labor is modeled separately:

**Exception hours = attempts × exception frequency × share needing a human × hours per human case.**

At 100K attempts, 50 exceptions per million, 10% requiring a human, and 15 minutes per human case, this is 0.125 hours per month. This is an expectation across repeated periods. A single complicated case can consume the budget for many otherwise quiet months.

Collection uses the illustrative standard US domestic-card rate of 2.9% plus $0.30 for one monthly payment. The model includes a separate 1% service-concession/loss planning reserve. The reserve is a management assumption, not measured loss history or a statement that processor fees cover service risk. Different payment methods, international cards, billing products, taxes, and negotiated terms require different inputs. [Stripe pricing](https://stripe.com/pricing).

<!-- BEGIN WATERFALL -->
| Working illustration, 100K attempts | USD per customer-month |
| --- | --- |
| Revenue | $999.00 |
| Resource allowance | $50.00 |
| Other delivery allowance | $20.00 |
| Routine support: 3h x $75 | $225.00 |
| Exceptions: 0.125h x $75 | $9.38 |
| Collection fees | $29.27 |
| Planning reserve | $9.99 |
| Delivery cost | $343.64 |
| Contribution | $655.36 |
<!-- END WATERFALL -->

The result is **$655.36 monthly delivery contribution, or 65.6%**. This leaves money for acquisition, engineering, shared operations, and profit; it does not prove those expenses are covered.

The same delivery pattern at $1,500 yields **$1,136.83 contribution and a 75.8% margin**. That is a reason to test the higher price if the buyer values the outcome. It is not evidence that the buyer will accept it.

The model's 70% target is an internal planning threshold, not an asserted industry benchmark or a requirement for a useful pilot. At the working costs, the price needed to reach it is **$1,167.34 per month**. A learning pilot below that threshold can be rational if its effort is bounded and it produces credible evidence.

## 15. Five possible customer-months

<!-- BEGIN SCENARIOS -->
| Scenario | Fee / month | Actions / month | Delivery hours | Delivery cost | Contribution | Margin |
| --- | --- | --- | --- | --- | --- | --- |
| Bounded, low-touch | $499.00 | 10,000 | 1.012 | $125.70 | $373.30 | 74.8% |
| Working illustration | $999.00 | 100,000 | 3.125 | $343.64 | $655.36 | 65.6% |
| Same workload, higher price | $1,500.00 | 100,000 | 3.125 | $363.18 | $1,136.83 | 75.8% |
| Support-heavy | $999.00 | 100,000 | 13.000 | $1,084.26 | -$85.26 | -8.5% |
| Volume stress, unbenchmarked | $999.00 | 1,000,000 | 6.250 | $778.01 | $220.99 | 22.1% |
<!-- END SCENARIOS -->

Every number in this table is hypothetical. Figures are rounded independently, so displayed costs and contribution can differ from the fee by one cent.

The bounded $499 case assumes a smaller 10K workload, only one routine hour, and lower resource and other delivery allowances. It is not the $999 case sold at half price. Its 74.8% margin depends on containing the service obligation.

The working illustration has no measured probability and should not be called an expected forecast. The higher-price row changes only the commercial fee, making the price-versus-delivery relationship explicit.

The support-heavy case combines eight routine hours with 100 exceptions per 100K attempts, 20% escalated, and 15 minutes each. That produces five exception hours and 13 total delivery hours. At $999, the account loses **$85.26** before acquisition and overhead. A small provider bill cannot rescue uncontrolled human obligations.

The volume stress case retains the $999 flat price at one million attempts, increases the resource allowance to $250 and routine support to five hours, and leaves the lower exception assumptions in place. Contribution falls to **$220.99**, or 22.1%. This does not claim that the deployment supports one million attempts or that $250 buys sufficient capacity. It shows why a fixed-fee offer needs a measured usage boundary.

No scenario includes an additional unresolved Enterprise contract increment. Apply the actual commitment model before quoting qualified hosted service. Likewise, do not use a resource allowance as proof of backup adequacy or an availability promise.

## 16. Support capacity determines which price is viable

This sensitivity holds the 100K working workload, $70 combined resource/other allowance, and base exception assumptions constant. Only price and routine support hours change.

<!-- BEGIN PRICE_HOURS -->
| Monthly price | 1 routine hour | 3 routine hours | 8 routine hours | 70% margin: max routine hours |
| --- | --- | --- | --- | --- |
| $249.00 | 34.0% | -26.3% | -176.9% | -0.20h |
| $499.00 | 65.1% | 35.0% | -40.1% | 0.67h |
| $999.00 | 80.6% | 65.6% | 28.1% | 2.41h |
| $1,500.00 | 85.8% | 75.8% | 50.8% | 4.16h |
| $2,500.00 | 89.9% | 83.9% | 68.9% | 7.64h |
<!-- END PRICE_HOURS -->

At $999, a 70% contribution target supports about **2.41 routine hours** per month under these assumptions, plus the separately modeled exception allowance. At $1,500 it supports about **4.16 routine hours**. At $249, the nonroutine costs already exceed that target's available delivery budget; the negative hour figure denotes an infeasible target, not negative work.

These are planning boundaries, not a reason to withhold essential incident handling. The commercial scope should specify what routine assistance is included, how additional project work is approved, and who owns upstream investigation. If urgent responsibility is uncapped, price and staffing must reflect it.

Track implementation help, credential setup, policy edits, incident triage, evidence export, restore qualification, and reconciliation separately. “Support” is too broad to identify which work can become repeatable. A difficult one-off setup should not silently become a permanent monthly obligation.

At the working wage, one additional delivery hour consumes **$75 of contribution**. A $45 resource optimization, moving the allowance from $50 to $5, saves less than one hour of work. This is the practical reason to prioritize an understandable integration and clear handoff over premature infrastructure optimization.

Reducing service effort through documentation or an existing wrapper can be valuable. However, the current OpenAI wrapper describes a source-only integration and recorded-shape tests. That is not proof of published distribution, a live model integration, or low customer onboarding effort. Its persisted tool-call identity helps with retries of the same tool call; a newly generated tool-call ID remains a new identity. [Wrapper README](../../../wrappers/openai-agent-middleware/README.md).

## 17. Hosting sensitivity after the new evidence

<!-- BEGIN RESOURCE -->
| Resource allowance / month | Contribution at $999 | Margin | Revenue for 70% margin |
| --- | --- | --- | --- |
| $5.00 | $700.36 | 70.1% | $994.92 |
| $20.00 | $685.36 | 68.6% | $1,052.39 |
| $50.00 | $655.36 | 65.6% | $1,167.34 |
| $150.00 | $555.36 | 55.6% | $1,550.48 |
| $500.00 | $205.36 | 20.6% | $2,891.48 |
| $1,000.00 | -$294.64 | -29.5% | $4,807.18 |
<!-- END RESOURCE -->

These rows replace the resource allowance in the working illustration; they are not incremental fees added on top of the $50 base. All other assumptions stay fixed.

Moving from $50 to $5 improves contribution by $45. Moving from $50 to $150 reduces it by $100. A genuine $1,000 attributable resource or contract burden would still make the $999 offer unattractive. The revised conclusion is about evidence and emphasis: that burden has not been established, while low current metered usage has.

Do not interpret the $5 row as a qualified deployment budget merely because it resembles the demonstration's observed spend. It assumes a completed customer setup, a full period, a particular workload, and an allocation that have not been measured.

A provider commitment can also be an operating constraint even when a marginal customer is profitable. If a large minimum exists, the company must fund it at today's customer count. Reconcile the company cash requirement with customer allocations rather than hiding it in an arbitrary per-action rate.

The useful infrastructure task is modest: obtain the applicable plan/contract terms, map the required controls, and collect a pilot's full-period resource bill. A migration, shared-database redesign, or orchestration project would not answer the current value question.

## 18. Storage and failure outcomes need separate budgets

Small current storage does not imply a permanently flat resource bill. Retention depends on evidence per operation, result size, indexes, copies, backup policy, and expiration. A receipt alone is not the entire durable footprint.

The table uses decimal KB/GB, twelve months of uniform new activity, no expiry within that period, and a hypothetical threefold total footprint. Replace that multiplier with measurement; do not add the same copy or index factor twice.

<!-- BEGIN RETENTION -->
| Net logical bytes / action | 100K/month, month 12 with 3x footprint | 1M/month, month 12 |
| --- | --- | --- |
| 4 KB | 14.4 GB | 144.0 GB |
| 12 KB | 43.2 GB | 432.0 GB |
| 100 KB | 360.0 GB | 3600.0 GB |
<!-- END RETENTION -->

At 100K operations per month, a 12KB net logical record and a threefold footprint accumulate 43.2GB after twelve months. At one million operations, the same assumptions produce 432GB. Large retained results change the economics faster than signature size.

The supported retention policy should identify which fields are essential for replay, financial linkage, receipt verification, and audit. Price longer retention or unusually large results only after the product can enforce and explain the agreed boundary. Do not remove needed records solely to improve the scenario margin.

Failure states also differ economically. A pre-dispatch rejection consumes control-plane work but no upstream invocation. A replay consumes lookup and response work. A returned error can consume an upstream attempt and investigation. An uncertain outcome can leave a debit in place while requiring human reconciliation. A failed refund can create a durable operator work item.

Explicit ambiguity handling is part of the value proposition, but it does not make uncertainty free. A customer who expects immediate certainty about every upstream effect may be buying an obligation the current product cannot fulfill.

Model correlated incidents separately from independent exception rates. An outage affecting all customers can create a burst of work and concessions at once. The 1% reserve and average-case exception formula are not a modeled tail-risk distribution. [Failure outcomes and reconciliation](../../../docs/failure-semantics.md).

## 19. Setup economics and the first offer

The initial deliverable should be concrete: one partner agent, one partner staging MCP tool, stable operation identity through a retry, one ordinary success, one relevant failure or uncertainty exercise, and a receipt verified independently by the partner engineer. Include an operational handoff and a record of delivery time.

A **$2,500 fixed-fee setup with a 20-hour delivery budget** remains a reasonable offer to test. This is an offer hypothesis, not a discovered market-clearing price. Scope it to the supported pilot and accompany it with a short acceptance checklist.

The setup sensitivity assumes $100 of one-time resource/other expenses, $75 per delivery hour, one card collection, and the same 1% reserve. It excludes sales work, which belongs in acquisition cost, and the recurring service period unless explicitly bundled.

<!-- BEGIN ONBOARD -->
| Setup fee | 10 delivery hours | 20 delivery hours | 40 delivery hours |
| --- | --- | --- | --- |
| $1,000.00 | $110.70 | -$639.30 | -$2,139.30 |
| $2,500.00 | $1,552.20 | $802.20 | -$697.80 |
| $5,000.00 | $3,954.70 | $3,204.70 | $1,704.70 |
<!-- END ONBOARD -->

At 20 delivery hours, the $2,500 fee leaves **$802.20 setup contribution**. At 40 hours, it loses **$697.80**. An undefined “pilot” can become subsidized consulting even when the server bill is tiny.

If a buyer will commit only to a small paid diagnostic, a $1,000, ten-hour scope has little contribution under these assumptions. It may still purchase useful evidence, but treat it as a bounded learning expense rather than a healthy recurring business.

After setup, quote the recurring fee from the measured service obligation. Test roughly **$1,000–$1,500 per month** for a managed workflow if the value warrants it. Reserve $499 for a demonstrably smaller, lower-touch scope. Do not lower price merely to compensate for an unconvincing value story; reduce scope or decline the account if necessary.

Keep setup and recurring revenue separate. A large first invoice can disguise weak recurring economics. If setup is credited against future subscriptions, model the credit as a reduction in subsequent collections rather than counting the same cash twice.

## 20. Buyer value must survive the identity qualification

Use the buyer's actual workflow and remaining alternatives.

**Monthly net benefit = attributable operating time saved + attributable net losses avoided − added integration, operating, delay, and review costs − platform fee.**

“Attributable” matters. A failure that existing idempotency already prevents is not incremental value. Nor is a new-key duplicate prevented by a system that still receives two distinct accepted identities.

This table shows gross-benefit thresholds. It assumes the buyer values an hour at $100 and an avoided incident at $500 of net loss. Neither is a measured severity or incident frequency.

<!-- BEGIN ROI -->
| Monthly platform fee | Buyer hours to break even ($100/h) | Hours for 3x gross benefit | $500 net incidents avoided to break even |
| --- | --- | --- | --- |
| $499.00 | 4.99h | 14.97h | 0.998 |
| $999.00 | 9.99h | 29.97h | 1.998 |
| $1,500.00 | 15.00h | 45.00h | 3.000 |
| $2,500.00 | 25.00h | 75.00h | 5.000 |
<!-- END ROI -->

At $999, ten saved hours approximately cover the subscription before buyer-side integration or operating costs. A threefold gross-benefit target requires about 30 hours. Threefold benefit is a suggested evaluation hurdle, not a proven purchasing rule.

Net incident loss should account for refunds, recoveries, replacement work, investigation, and business disruption without double-counting time. A duplicate $10,000 authorization is not automatically a permanent $10,000 loss. Conversely, an inexpensive action can create substantial investigation cost.

For rare incidents, document historical frequency, the fraction this exact integration could prevent, residual risk, and the cost of the new control. Do not multiply a dramatic maximum loss by an unsupported probability.

The strongest early buyer may pay for reduced engineering and reconciliation burden rather than catastrophe prevention. That benefit can be measured through setup time, failure diagnosis, handoff clarity, and a concrete adoption plan. The evidence needs to come from the buyer.

## 21. Acquisition may be the largest per-unit cost

The commercially scarce unit may be a qualified customer with a relevant tool, a stable identity path, an engineer, a budget owner, and a date. Public interest in agent safety does not automatically supply that unit.

Acquisition cost should include unsuccessful opportunities, technical discovery, demonstrations, security review before the sale, and direct acquisition expenses. Do not assign only the winning buyer's meeting time to the win.

These examples use $75 per acquisition hour plus $300 of expenses per acquired customer. They assume unchanged working recurring contribution and exclude setup contribution, churn, discounting, expansion, and additional fixed overhead.

<!-- BEGIN CAC -->
| Acquisition effort per win | Acquisition cost | Payback at working illustration | 12-month contribution after acquisition |
| --- | --- | --- | --- |
| 10h + $300 expenses | $1,050.00 | 1.6 months | $6,814.37 |
| 40h + $300 expenses | $3,300.00 | 5.0 months | $4,564.37 |
| 100h + $300 expenses | $7,800.00 | 11.9 months | $64.37 |
<!-- END CAC -->

At 100 hours per acquired customer, the model takes almost twelve months to recover acquisition cost. After twelve unchanged customer-months, only about $64 remains from recurring contribution after acquisition. A strong delivery margin can therefore coexist with a poor business.

No observed funnel or retention cohort was supplied or discovered. Calculating actual lifetime value by dividing contribution by invented churn would be misleading. The table is a conditional payback illustration.

Record each opportunity's stage and disqualification reason. A prospect without a consequential tool differs from one that lacks budget or already has sufficient controls. These distinctions reveal whether the problem is positioning, distribution, product fit, or price.

The corrected issue evidence makes this discipline more important. Related-tool authors and curious developers can be useful technical contacts; they become qualified leads when they demonstrate a buying role.

## 22. Retention, cash flow, and company capacity

A recurring fee is attractive only if the customer continues to receive value and the service obligation remains controlled. The first retention observation is continued use and an actual renewal or explicitly renewed commitment.

Separate activation, technical acceptance, commercial acceptance, recurring use, and renewal. A free pilot can reveal integration friction but cannot establish paid retention. A setup payment can establish willingness to fund a project without establishing a subscription market.

Collecting setup before delivery reduces cash exposure, but the team still owes the contracted work. Annual prepayment improves cash while creating a future service obligation and potentially a discount. It does not multiply monthly economic contribution by upfront collections.

The company illustration uses $655.36 contribution and 3.125 delivery hours per customer-month.

<!-- BEGIN COMPANY -->
| Shared monthly overhead | Customers to cover overhead | Monthly direct delivery hours |
| --- | --- | --- |
| $3,000.00 | 5 | 15.6h |
| $10,000.00 | 16 | 50.0h |
| $30,000.00 | 46 | 143.8h |
<!-- END COMPANY -->

At $10,000 monthly shared overhead, the calculation needs 16 comparable customers and 50 direct delivery hours. At $30,000, it needs 46 customers and about 144 hours. Acquisition, onboarding, shared engineering, management, incident peaks, and time off require additional capacity.

These are arithmetic thresholds, not staffing plans. Shared overhead must exclude labor already charged to direct delivery, or compensation will be counted twice. Treating founder time as free can make cash margins look high while hiding a capacity limit.

Maintain cash and economic views. Cash contribution may exclude unpaid founder labor if labeled; economic contribution should include its opportunity cost. Decisions about scale need both that cost and the actual bank balance.

A profitable services practice and a scalable software business can both be worthwhile. The evidence does not yet establish which form this product can support. The next customers should make that distinction clearer through repeatability and delivery time.

## 23. A practical measurement plan

This can be maintained manually for the first pilot. Provider usage, durable counters, ledger records, and a time log are enough to start; a new analytics platform is unnecessary.

| Measurement | Definition and source | Why it changes the decision |
| --- | --- | --- |
| Revenue and collections | Platform/setup fees, credits, refunds, dates; invoice record | Establishes willingness to pay and cash timing |
| Provider cost | Customer usage plus reconciled actual commitments and noncreditable fees | Replaces allowances without hiding fixed costs |
| Workload | Period-matched identities, dispatch states, replays, denials, record sizes | Produces a valid cost denominator |
| Delivery time | Setup, routine support, incidents, reconciliation, restore work | Reveals the likely primary cost driver |
| Buyer effort | Integration hours, identity persistence, diagnosis, handoff | Tests whether the control saves more work than it creates |
| Acquisition | All opportunity work, including losses, divided by wins | Tests whether contribution repays acquisition |
| Retention | Continued workflow use and renewed commitment | Separates project revenue from recurring demand |
| Evidence boundary | Commit, deployment, restrictions, partner verification | Prevents a demo from becoming a commercial claim |

Use the same period and scope on both sides of each unit-cost ratio. Exclude development and proof traffic from customer workload while assigning its spending to the company. Retain attribution sufficient to reconcile totals without copying customer payloads into this report.

Record how the partner creates and persists the operation identity before invoking the tool. Test a framework retry and process restart at that integration boundary. A gateway-only replay test is insufficient when the customer failure involves reconstructing an operation.

An early operating dashboard needs reconciled rows and an explanation of differences. It does not need an attractive gross-margin percentage until the inputs represent real money and delivery.

## 24. What to freeze and what to improve

Freeze expansion into a general middleware platform. Additional tool families, a marketplace, broad agent billing, semantic deduplication, regulated-data positioning, and new deployment modes should require the named customer evidence specified by the repository.

Do not build a pricing engine to implement these scenario fees. A manually agreed, invoiced pilot is enough to test the offer. Keep internal credit integrity focused on correctness rather than treating configured compute costs as financial truth.

Do not migrate hosting merely because the demo bill is small or another public minimum is cheaper. Identify the actual control requirement, contract, and customer. Simplification is useful when it removes a measured delivery burden within the supported boundary.

Prioritize integration and documentation fixes that help a real partner preserve identity, understand uncertainty, independently verify a receipt, and complete the handoff. Those changes can reduce labor and strengthen the exact value being sold.

Continue security, correctness, reliability, and release maintenance in the existing loop. The validation constraint does not justify ignoring defects. It does justify declining speculative capabilities without a prospect, owner, date, and blocker.

The older market document also needs qualified wording before its claims are reused in a pitch: independent demand, a confirmed incident, and the asserted role of the OpenBB requester. This report records the corrections with primary sources; it does not silently rewrite historical research.

## 25. Revised decision and near-term experiment

**Proceed with one bounded paid validation offer, without claiming the company's unit economics are established.**

The first gate is fit: one named prospect, one consequential staging tool, persistent business operation identity, an engineer, and a problem the existing contract addresses. If a simpler configuration of the buyer's current tools resolves the problem, acknowledge that and avoid unnecessary integration.

The next gate is scope: a proposed $2,500 setup, at most 20 delivery hours before a scope review, written success criteria, the supported low-sensitivity workload, and a separate recurring hypothesis. Resolve the hosting control and contract before promising the managed configuration.

Technical acceptance is partner-owned. The partner should demonstrate stable identity through its retry path, observe the relevant debit/dispatch outcome, and verify a receipt independently. A successful self-issued demo is preparation for this gate.

Commercial acceptance is payment or a written commitment naming buyer, scope, price, and next date, followed by a recurring decision. Test whether $1,000–$1,500 per month buys a benefit the buyer can explain. Use $499 only for a smaller service obligation.

Suggested internal continuation criteria are positive delivery contribution, a credible path to 70% at repeatable scope, manageable acquisition payback, and evidence that the buyer prefers this approach to its existing integration. These are planning choices, not industry facts.

Pause broader commercialization if qualified prospects consistently lack the identity discipline required by the contract and will not implement it, value only cheaply available features, require unbounded support, or reject the price needed for their deployment requirements. Those findings could favor a narrower integration product, a services-led model, or stopping the commercial experiment.

My changed judgment is specific: **the machine-cost obstacle is smaller in the observed environment; proof of buyer value is weaker than the earlier framing suggested.** The product is worth testing because its narrow transaction behavior may solve an expensive problem. It is not yet justified as a broad premium control platform.

## 26. Research register and reproducibility

Primary-source research and provider observations were collected September 5 Pacific time / September 6 UTC. This report was finalized September 8. The saved evidence remains a dated snapshot. Published offers and deployment state may change.

| Source group | Primary references | Status |
| --- | --- | --- |
| Provider usage | Coarse curated model input with identifiers removed and amounts rounded | Derived from provider-reported usage; full invoice not verified |
| Live demo | Public health response and metric scopes observed at the time | Historical observation; raw response omitted; no customer-load inference |
| Product contract | Pricing, billing engine, failure semantics, deployment SOP, license | Inspected local source at stated commit; different observed live commit |
| Problem evidence | Stripe 402, CrewAI 5802, LangGraph 7417, OpenBB 7455 | Attributed reports; independence and buying intent qualified |
| Alternatives | AWS, Portkey, Bindfort, Permission Protocol, AgentOracle, ABOM | Published prices/status; behavior and paid adoption not tested |
| Scenarios | Python model and curated JSON input | Reproducible arithmetic; generated outputs untracked; not financial actuals |

Reproduction uses the standalone model, report builder, and browser export script. These helpers import no application code and change no customer billing, infrastructure, or release settings. HTML includes an editable calculator; PDF preserves the report and tables for sharing.

[Model](../../../docs/research/unit-economics-reconsidered-2026-09-05/model.py), [curated resource-cost input](../../../docs/research/unit-economics-reconsidered-2026-09-05/resource-cost-input.json), [validation record](../../../docs/research/unit-economics-reconsidered-2026-09-05/VALIDATION.md). The model generates assumptions, scenario CSV, JSON results, and calculated tables on demand; those derived files are intentionally untracked.

**Files changed:** a new reconsidered research package; the earlier report is retained as historical context.

**What changed:** recommendation, evidence grading, actual resource-cost section, commercial unit, identity qualification, competitor comparison, and scenario model.

**Tests run:** arithmetic and evidence reconciliation, browser calculator, document structure and local links, PDF export, and lint/compile checks for the standalone model. Exact results are in VALIDATION.md.

**What passed:** checks recorded as completed in the validation record; financial scenarios remain conditional when their arithmetic passes.

**What was not tested:** application runtime suites, customer integrations, competitor implementations, load capacity, account settlement, actual Enterprise terms, willingness to pay, and retention.

**Remaining risks:** uncertain demand, lightly used demo evidence, required identity integration, human delivery burden, retention growth, unresolved provider commitments, and a different observed live version.

**Recommended next step:** qualify and price one partner-owned workflow, resolve its hosting requirement, and replace assumptions with measured cost, delivery time, and commercial response.
