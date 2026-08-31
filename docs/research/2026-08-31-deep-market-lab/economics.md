# Economics: sell one bounded pilot before inventing a usage business

**Decision:** test a paid, one-tool service with explicit infrastructure reimbursement. Do not derive a business margin from the repo's credits or publish a per-action price yet. Demand, actual operating costs, Enterprise terms, and customer value are **not verified**. The model is a reproducible set of illustrative sensitivities, not a forecast.

At **one isolated customer tenant and 10,000 new logical actions/month**, the illustrative base case needs **$2,182.50/month** to cover modeled nonlabor vendor costs plus founder labor at a replacement rate, including onboarding amortized over six months. Its first-month equivalent is **$2,932.50**. Neither number is a quote: the assumed $1,000 cloud commitment and all Sentinel prices are unverified. The cost of a real supported pilot cannot be determined without those contracts.

## What the repository establishes

| Evidence | Reality level | Economic consequence |
|---|---|---|
| [Deployment SOP](../../deploy-railway.md), lines 8–15: separate Railway **Enterprise** project, API, PostgreSQL, Redis, credentials, administrators, signing material, and Sentinel tenant per customer | **Verified as documented deployment boundary**; live deployment not inspected | Each additional customer creates another operated stack. A pooled request-only SaaS cost curve is inappropriate. |
| Same SOP, lines 43–55: backups, a restore drill, and no unmeasured SLA/RTO/RPO claim | **Verified as required procedure**; completion not verified | Onboarding and continuing operations consume time even at ten actions. |
| [`tool_price` and `charge_units_for`](../../../app/services/pricing.py), lines 27–39 | **Verified by code inspection** | Registered pricing is a configured credit allowance. It is not evidence of a cash fee a customer accepted. |
| [`DEFAULT_PRICING`, `COMPUTE_COSTS`, and `EXCHANGE_RATE`](../../../app/services/agent_money.py), lines 37–117 | **Verified hard-coded constants**; actual provider cost not verified | A comment labeling values as actual compute cost does not make them measured cost. Most listed categories are outside the current wedge. |
| [`BillingEngine.charge`](../../../app/services/billing_engine.py), lines 433–434, and `get_arbitrage_report`, lines 797–847 | **Verified by code inspection** | Stored “margin” subtracts configured credit cost from credit charge. The report sums debit rows, does not net refund rows in that aggregation, and omits hosting, support, onboarding, and cash collection. Presenting this as company gross margin would be **misleading**. This is an analysis finding; no code was changed. |
| [`MCP_UPSTREAM_CREDITS_PER_CALL`](../../../app/core/config.py), line 98, defaults to zero | **Verified default**, deployed setting not verified | Even counted remote actions do not establish any positive billed credit volume. Credit/debit counts cannot be promoted to revenue. |
| [Active validation sprint](../../30-day-customer-validation.md), lines 72–79 and pilot acceptance steps | **Verified stated goal**, buyer completion not verified | The useful next commercial observation is a partner-owned pilot and payment/commitment, not a modeled user-count market. |

The current working tree is being edited by the separate launch program. These are observations of the inspected files, not claims about an immutable release or production behavior. No customer contracts, invoices, usage exports, cloud bills, or support logs were supplied to this model.

## Units and boundary

- **Customer:** one purchasing organization. An organization can ultimately require multiple environments; the model assumes one to avoid inventing deployment scope.
- **Tenant:** one isolated supported deployment. Main tables use one customer = one tenant = one configured tool.
- **New logical action:** one distinct business action identifier admitted to the gateway. Retries are additional attempts, not new revenue events. Action volume is not users, agents, requests, or money moved.
- **Cost month:** 30 days for CPU conversion. Infrastructure storage is modeled at a twelve-month retained steady workload, including in the conservative first-month estimate. This is not a retention policy recommendation.
- **External nonlabor cash proxy:** external cloud, assumed Sentinel charges, and $25 shared tools only. It excludes **all labor**, including hires required when work exceeds founder capacity. It is **not total cash requirements, burn, or runway**. Founder labor is not free, and thousands of operator hours cannot be supplied by an unpaid founder.
- **Economic cost:** the nonlabor proxy plus founder/operator hours at an explicit replacement rate. It excludes speculative avoided losses and customer labor. First-month cost expenses all onboarding; the recurring comparison amortizes it over six assumed months. This is still not a complete cash hiring or financing plan.

The upstream tool and agent/LLM costs remain the customer's existing costs and are excluded from vendor COGS. No additional LLM inference charge is assumed for this gateway model. New vendor subscriptions, taxes, financing, acquisition spend, contractual liability, insurance, payment collection charges, and extraordinary security incidents are unquoted/excluded. This is not a financial statement, investment recommendation, or compliance assessment.

## Public price facts and unquoted deployment costs

Retrieved **2026-08-31**: Railway documents RAM at $10/GB-month, CPU at $20/vCPU-month, volume storage at $0.15/GB-month, and service egress at $0.05/GB. These are public resource-price reference points; usage quantities below are invented, and Enterprise negotiated terms could differ. [Official resource pricing](https://docs.railway.com/pricing/plans)

Railway lists Pro at a $20 minimum with included usage and Enterprise as **Custom**. Its pricing page also presents spend commitments for feature bundles. This does **not** establish the contract or per-customer allocation for this repository's Enterprise pilot. Do not quote a supported pilot as “$20 hosting.” [Official Railway pricing](https://railway.com/pricing)

The shared-minimum model uses `cloud = max(hypothetical Enterprise commitment, summed isolated-project resource cost)`. The dedicated-minimum variant uses `cloud = tenants × max(hypothetical commitment per tenant, resource cost per tenant)`. These minimum-includes-usage conventions are **scenarios**, not verified Enterprise billing terms. Both keep databases, credentials, and runtimes isolated. Obtain written quotes for both contract scopes; neither case demonstrates an observed economy of scale. No Pro substitution or deployment-policy change is proposed.

Sentinel's actual fixed, approval, retry, or other pricing was not supplied and is **not verified**. It is modeled as an explicit placeholder per tenant plus per new action. Actual billing triggers must replace that assumption. The zero-cost optimistic Sentinel case means customer-provided/included service, not an asserted free plan.

## Explicit illustrative assumptions

None of these scenario inputs are measured or probability estimates. Scenario labels rank operating conditions; they are not assigned likelihoods.

| Input, per tenant unless stated | Optimistic | Base | Pessimistic | Stress |
|---|---:|---:|---:|---:|
| Hypothetical total monthly Enterprise commitment | $250 | $1,000 | $2,000 | $5,000 |
| Average aggregate used RAM across API/DB/Redis | 1 GB | 2 GB | 4 GB | 8 GB |
| Aggregate baseline used CPU | 0.05 vCPU | 0.10 | 0.25 | 0.50 |
| Incremental CPU seconds/attempt | 0.05 | 0.20 | 1.00 | 5.00 |
| Attempts per new logical action | 1.05 | 1.20 | 1.50 | 3.00 |
| Retained evidence size/new action, before multiplier | 10 KB | 25 KB | 50 KB | 100 KB |
| Routine support/operations hours/month | 1 | 3 | 6 | 10 |
| One-time onboarding hours | 6 | 12 | 24 | 40 |
| Fraction classified uncertain | 0.01% | 0.1% | 0.5% | 2% |
| Vendor review minutes/uncertain action | 2 | 5 | 15 | 30 |
| Partner lookup minutes/uncertain action | 5 | 15 | 30 | 60 |
| Founder/operator replacement cost/hour | $50 | $75 | $100 | $125 |
| Sentinel fixed/month | $0 | $100 | $250 | $500 |
| Sentinel/new action | $0 | $0.002 | $0.01 | $0.05 |

Common assumptions: $25/month shared operating tools; eight shared founder hours/month; 40 founder hours/month available for pilot operations; onboarding amortized over six months; five initial GB/tenant plus twelve months of evidence at a 3× index/backup allowance; 25 KB egress/attempt. CPU includes extra attempts; evidence assumes retained per-action records. Unknown per-replay audit growth and approval retries are reasons to measure storage and Sentinel bills.

Two deliberately nonlinear terms expose scale risk:

1. Each started 100,000-action block above the first adds 0.5 GB of used RAM per tenant. This is a capacity-review cost proxy, **not** benchmarked sizing or a claim that one service sustains that volume.
2. Every started 40-hour block of recurring vendor work above the initial 40 hours adds eight hours of coordination/escalation overhead. This is a labor stress proxy, not a hiring plan. Crossing 40 hours is an overload warning even if the resulting fee looks attractive.

Let `A` be new actions/tenant/month, `T` tenants, `u` uncertain fraction, `m_v` vendor minutes/case, and `m_p` partner minutes/case:

```text
vendor reconciliation hours = T × A × u × m_v / 60
partner reconciliation hours = T × A × u × m_p / 60
economic cost = cloud + Sentinel + shared tools
              + hourly rate × (shared operations + per-tenant support
              + vendor reconciliation + coordination + onboarding / 6)
break-even monthly fee/tenant = economic cost / T
usage-only break-even fee = economic cost / (T × A)
fee at 50% economic contribution = economic cost / (T × 0.5)
```

“50%” is a sensitivity target, not an industry benchmark. The model does not turn retained uncertainty into recovered money or assume it eliminates downstream loss.

## Reproduced workload results

**One isolated tenant. Monthly break-even fee including founder labor and six-month onboarding amortization. All dollar outputs are conditional on the assumptions above.**

| New logical actions/month | Optimistic | Base | Pessimistic | Stress |
|---:|---:|---:|---:|---:|
| 10 | $775 | $2,100 | $4,076 | $8,621 |
| 100 | $775 | $2,101 | $4,089 | $8,738 |
| 1,000 | $775 | $2,108 | $4,210 | $9,908 |
| 10,000 | $777 | $2,183 | $5,425 | $23,608 |
| 100,000 | $792 | $2,925 | $19,975 | $163,608 |
| 1,000,000 | $942 | $11,550 | $163,875 | $1,558,608 |

These are **workload sensitivities, not verified throughput**. There is no defensible conversion from these volumes to 10–1,000,000 customers/users. The large stress values are a reason to reject that operating model, not evidence of an addressable market or a recommendation to hire.

The base scenario's usage-only break-even price falls from $210.01/action at ten actions to $0.21825 at 10,000 and $0.01155 at one million. That decline comes from allocating fixed costs, not demonstrated demand or scale efficiency. A tiny-action pilot should test a fixed service fee. At one million, base vendor operations require **110.33 hours/month**, and the partner needs **250 hours/month** of effect lookup. The founder-capacity constraint has already failed.

At 10,000 base actions, the external nonlabor cash proxy is $1,145; recurring vendor work is 11.83 hours; first-month vendor time is 23.83 hours, of which 15.83 is customer-specific delivery and eight is shared work. The difference between that proxy and $2,182.50 economic cost is labor valued at a replacement rate with onboarding amortized, not spare profit. A 50% economic contribution would require $4,365/month under these assumptions. It is **not verified** that any customer would pay it. At one million stress-case actions, recurring vendor work reaches **12,018 hours/month**: the nonlabor proxy excludes the wages needed to staff that workload and cannot describe its actual cash requirement.

### What actually changes the decision

Enterprise minimum sensitivity, otherwise the base 10,000-action case:

| Assumed total minimum | Monthly economic break-even | First-month equivalent |
|---:|---:|---:|
| $0; resource-only counterfactual | $1,206.63 | $1,956.63 |
| $250 | $1,432.50 | $2,182.50 |
| $1,000 | $2,182.50 | $2,932.50 |
| $2,000 | $3,182.50 | $3,932.50 |
| $5,000 | $6,182.50 | $6,932.50 |

The $0 case is a mathematical lower-bound counterfactual, **not a supported deployment price**. Its $24.13 resource proxy includes no evidence that the assumed resource quantities are adequate.

Uncertainty sensitivity, holding every other base input constant at 10,000 actions:

| Assumed uncertainty fraction | Vendor reconciliation hours | Partner lookup hours | Monthly economic break-even |
|---:|---:|---:|---:|
| 0 | 0 | 0 | $2,120.00 |
| 0.01% | 0.08 | 0.25 | $2,126.25 |
| 0.1% | 0.83 | 2.50 | $2,182.50 |
| 0.5% | 4.17 | 12.50 | $2,432.50 |
| 2% | 16.67 | 50.00 | $3,370.00 |

Uncertainty is durable state, not automatically resolved state. Moving a manual queue to the customer does not remove its cost from customer value.

Tenant sensitivity at 10,000 actions **each**, comparing one shared $1,000 commercial minimum with a separate $1,000 minimum for **each** dedicated tenant. Both use completely separate technical stacks; neither contract scope is verified:

| Customers = isolated tenants | Total actions/month | Break-even/tenant: shared minimum | Break-even/tenant: dedicated minimum | Recurring vendor hours | Hours if all onboard this month |
|---:|---:|---:|---:|---:|---:|
| 1 | 10,000 | $2,182.50 | $2,182.50 | 11.83 | 23.83 |
| 2 | 20,000 | $1,370.00 | $1,870.00 | 15.67 | 39.67 |
| 5 | 50,000 | $882.50 | $1,682.50 | 27.17 | 87.17 |
| 10 | 100,000 | $780.00 | $1,680.00 | 54.33 | 174.33 |

Lower allocated cost does not create founder capacity. Under the assumed 40-hour monthly allocation, two simultaneous base onboardings nearly consume it; five cannot fit. Extra security/procurement work would lower that limit. At ten tenants the dedicated-minimum case costs $9,000/month more, or $900/tenant: the difference between $780 and $1,680 is an unverified contract-allocation assumption, not measured operating efficiency.

## Customer value versus the existing substitute

The strongest substitute is often the customer's current gateway/IAM plus upstream idempotency and an authoritative effect lookup. For a concrete example, Stripe documents returning the saved result for a repeated idempotency key, rejecting changed parameters, and allowing key removal after at least 24 hours. The applicable operation, retention, and business lookup still have to be checked. [Stripe's official idempotency contract](https://docs.stripe.com/api/idempotent_requests)

**Inference:** if that existing path already permits safe autonomous operation and satisfies the buyer's evidence needs, incremental avoided duplication may be close to zero. The repo must then earn its fee through a demonstrable gap in bound authority, dispatch state, uncertainty handling, or portable evidence. Do not assign the full cost of all tool failures to this product's value.

Use a partner-supplied comparison:

```text
incremental customer value/month
  = current manual-control hours actually eliminated × customer labor rate
  + incremental harmful events avoided × loss per event
  - new partner reconciliation hours × customer labor rate
  - customer integration cost amortization
  - added latency/availability/operations burden
```

Avoided-event counts and losses are unmeasured. The following reverse calculation is **not an expected-loss estimate**: with a $2,000 monthly fee and no other benefits or burdens, what loss per incrementally avoided event would just cover it?

| Hypothetical incremental avoided events/month | Required loss/event |
|---:|---:|
| 0.01 | $200,000 |
| 0.1 | $20,000 |
| 1 | $2,000 |

Infrastructure reimbursement, customer labor, and outages increase those thresholds. Reduced human gating can be valuable without an incident history, but the partner must demonstrate hours removed and continued willingness to retain the dependency. No insurance, settlement, or legal-liability claim follows from this arithmetic.

## Smallest paid price experiment

Draft one offer for a **$2,000, 30-day, one-tool staging pilot**, with actual, preapproved isolated cloud/Sentinel charges stated separately. This is an **untested price hypothesis**, not validated willingness to pay. Do not order infrastructure or send the offer from this research task.

The existing customer-validation decision deadline remains **2026-09-11**. The proposed 30-day commercial term does not restart or extend that sprint. Obtain and record whatever paid agreement or written commercial commitment is achievable before September 11, and separately record whether the partner-owned technical acceptance test has actually passed by then. A signed future pilot is commercial evidence, **not completed pilot proof**; unresolved acceptance work remains unresolved at the deadline.

Scope it to one named buyer, one partner engineer, one synthetic/redacted consequential mutation, at most 10,000 new logical actions, and at most **16 customer-specific vendor hours**. The base scenario uses 15.83 such hours, plus eight shared hours. Include the existing acceptance run: effect-then-response-loss, exact replay without another dispatch/debit, authoritative partner reconciliation, and offline verification. Agree a scope stop before exceeding the hours or action cap; no production SLA, open-ended integration work, or outcome indemnity.

At base assumptions, the first-month service cost excluding cloud/Sentinel is $1,812.50, leaving only **$187.50** against the proposed service fee before omitted acquisition and collection costs. This narrow margin is acceptable only as a deliberately capped validation expense. The illustrative external bill is $1,120, so the illustrative total is $3,120, **subject to actual quotes and customer acceptance**. If the mandatory Enterprise contract makes that unacceptable, record deployment economics as a qualification failure; do not silently move the customer onto an unsupported plan.

Invoice manually through the founder's existing business process; no pricing engine or payment integration work is justified to test one offer. Ask for a paid agreement or a written commitment naming the budget owner, total approved amount, and decision date. One accepted pilot demonstrates a transaction, not repeatable SaaS unit economics. If the buyer will pay only for consulting and would remove the gateway afterward, record that distinction.

Collect before drawing a commercial conclusion:

1. A quote/actual bill for the exact Enterprise and Sentinel scope; determine per-account versus per-tenant minimums and what usage is included.
2. Buyer-accepted fee, actual collection, exclusions, procurement effort, and decision to retain or remove the boundary after the pilot.
3. A task log separating onboarding, restore drill, security review, recurring operations, incidents, and reconciliation; record founder hours separately from cash paid.
4. Monthly new actions, total attempts, observed uncertainty classifications, lookup duration, unresolved backlog age, and partner engineer time. A tiny pilot can yield zero observed rare events; that does not establish a zero rate. A controlled fault injection tests semantics, not natural incident probability.
5. Actual CPU/RAM, persisted bytes/action including replay traffic, backup storage, egress, retention needs, p95/p99 added latency, and outage observations. Resource measurements do not replace concurrency correctness tests.
6. The partner's current substitute and the specific human work or blocked action that disappears; customer-owned incident records if available. Do not invent loss severity or attribute unrelated improvements.

Freeze broad catalog pricing, swarm-arbitrage dashboards as commercial proof, user-based TAM arithmetic, and multi-tenant orchestration. Keep configured credit/call accounting where it supports the trust loop. Revisit commercial packaging only after a paid partner shows what they need and what it costs to operate.

## Reproduction and checks

Run from the repo root:

```bash
python3 docs/research/2026-08-31-deep-market-lab/economics_model.py
```

The dependency-free script writes [economics_results.json](economics_results.json). Full inputs and unrounded outputs are included. It checks eight independently derived base-case quantities, monotonic total cost across all four workload scenarios, zero reconciliation cost at zero uncertainty, the labor/memory step boundaries, and four shared-versus-dedicated Enterprise minimum quantities. Decimal arithmetic separately confirms the base nonlabor proxy, recurring economic, first-month figures, and ten-tenant contract-scope comparison. Repeated execution is deterministic. This validates arithmetic and internal behavior, not assumptions, product correctness, market demand, or performance.

- **Files changed:** `economics.md`, `economics_model.py`, `economics_results.json` in this research directory only.
- **What changed:** repo-grounded commercial boundaries, reproducible cost/sensitivity model, conditional price experiment, and measurement plan.
- **Tests run:** model assertions; independent Decimal arithmetic; deterministic output comparison; syntax compilation; Ruff lint/format checks on the model only.
- **What passed:** see the recorded model check output; all final model checks passed.
- **What was not tested:** application behavior, live load, real deployments, Enterprise/Sentinel contracts, actual customer demand, collected revenue, or real unit economics.
- **Remaining risks:** unquoted deployment costs, manual support/reconciliation, founder capacity, substitute sufficiency, unmeasured reliability, and no commercial validation supplied.
- **Recommended next step:** obtain the exact supported-stack quotes and present the bounded paid-pilot offer to one qualified named prospect through the existing customer-validation process; do not add a core capability.
