# Assumptions, claims, experiments, and stopping rules

As of 2026-08-31. This is the research handoff, not a new operating registry.
Execution ownership remains in the [existing program](../../aegis/work/2026-08-31-program-control/README.md)
and the [customer sprint](../../30-day-customer-validation.md). Role owners and
dates below are proposed unless already committed in those records. No prospect
was contacted and no external experiment was executed by this review.

## Highest-impact assumptions

Impact and uncertainty are ordinal judgments from 1 to 5. Their product is a
triage aid, not a probability, expected return, or scientific measurement. A
low uncertainty score for the local mechanism does not establish production
reliability. Tied priorities do not justify parallel work before dependencies
are available.

| ID | Assumption to test | Proposed owner | Impact × uncertainty | Current evidence and confidence | Status / resolving test |
|---|---|---|---|---|---|
| A01 | A real team has an important write blocked by the specific retry/authority problem | Customer owner | 5 × 5 = 25 | [Customer audit](customer-product.md); high confidence that in-repo evidence is insufficient, actual demand unknown | Not verified; inspect a real incident/restriction with a stable prospect ID |
| A02 | The team's best existing native API/workflow/gateway/ledger is insufficient | Partner engineer | 5 × 5 = 25 | [Seven substitutes](market.md); documented capability is strong, actual fit unknown | Not verified; fair A/B comparison on one mutation |
| A03 | The partner will retain and pay for the difference | Buyer + customer owner | 5 × 5 = 25 | No located priced commitment; private evidence not inspected | Not verified; paid pilot or written buyer/budget/date commitment |
| A04 | The supported managed, public-HTTPS, low-sensitivity deployment is acceptable | Partner + operator | 5 × 5 = 25 | [Support boundary](../../../SECURITY_LIMITATIONS.md:16) is explicit; buyer acceptance unknown | Not verified; qualify before integration |
| A05 | Authoritative effect lookup can safely resolve ambiguity, including late effects | Partner tool owner | 5 × 5 = 25 | [Mechanism limits](mechanism.md); gateway cannot establish final effect truth | Not verified; effect-loss plus claim-before-send/late-completion cases |
| A06 | Reconciliation and charged uncertainty cost less than the autonomy they unlock | Partner operations owner | 5 × 5 = 25 | [Economics model](economics.md) is illustrative; no measured incident frequency or handling times | Hypothesis; measure both vendor and partner time, including false-positive uncertainty |
| A07 | Integration, added latency and an inline dependency are tolerable | Partner engineer | 4 × 5 = 20 | [Runbook](../../partner-first-tool-runbook.md) exists; partner results absent | Not verified; measure actual effort and latency against agreed limits |
| A08 | Contracted cloud/Sentinel costs permit a price the buyer accepts | Commercial owner | 4 × 5 = 20 | Enterprise and Sentinel quotes unknown; [scenario inputs](economics_results.json) are assumptions | Not verified; written cost quote and bounded commercial offer |
| A09 | Founder/operator capacity can support retained accounts | Operator | 4 × 5 = 20 | Dedicated per-customer operations; [nonlinear cost model](economics.md) | Hypothesis; record onboarding, restore, support and reconciliation hours |
| A10 | The founder can reach enough qualified buyers within the remaining sprint | Customer owner | 4 × 5 = 20 | Targets are a plan, not observed funnel conversion | Not verified; reconcile existing evidence and remaining interviews |
| A11 | Gateway state and dedup history survive restores without unsafe replay | Existing engineering owner | 5 × 4 = 20 | Local crash tests do not test database history rollback | Not verified; qualify restore/fencing procedure before a relevant real deployment |
| A12 | Gateway statuses and configured credits are understood as such | Product + partner engineer | 5 × 4 = 20 | [Mechanism review](mechanism.md) found error/effect and replay wording drift | Partially contradicted in prose; correct contract and perform comprehension check |
| A13 | Caller supplies one durable action key across every retry and entrypoint | Partner SDK/tool owner | 5 × 3 = 15 | Enforced exact-key replay; new/omitted keys are distinct actions | Conditional, statically verified; trace real caller behavior across restart/session change |
| A14 | The signed record is sufficiently useful despite trusting the operator and key distribution | Buyer/security reviewer | 3 × 5 = 15 | Offline verification works locally; buying value and trust acceptance unknown | Hypothesis; independent verification followed by removal decision |
| A15 | Ingress and resource limits bound practical abuse | Existing engineering owner | 4 × 4 = 16 | 10 MB test accepts then skips; public production behavior unverified | Partially verified; agree and test input/resource limit before real payloads |
| A16 | The supported gateway preserves its narrow dispatch/accounting invariant and remains usable under the pilot workload | Existing engineering owner | 5 × 3 = 15 | Historical pool-starvation failure; accepted final source passed 65 default-pool PostgreSQL cases including 20 calls/20 replays and 36 actual singleton-pool cases | Verified for the bounded local synthetic source/configuration; partner workload, production, ingress, restore/load/HA remain unverified |
| A17 | The niche can retain value when incumbents bundle supporting features | Company decision owner | 4 × 4 = 16 | [Fresh primary-source landscape](market.md); no established moat | Hypothesis; ask buyer to compare its bundled alternative, not a feature checklist |
| A18 | Ongoing market research is now more valuable than actual partner evidence | Research lead | 3 × 1 = 3 | Missing inputs are access, willingness to deploy, measured burden, and payment | Rejected for the next wave; stop repetitive desk research until new evidence arrives |

## Claim → evidence → assumptions → counterevidence → verification

| Claim | Supporting evidence | Necessary assumptions | Counterevidence or limit | Independent verification / current confidence |
|---|---|---|---|---|
| C01: a real durable governed gateway exists | [Source and runtime evidence](technical.md) | Supported path, stable identity, trusted/durable state, correct deployment | Finite fault schedules; no arbitrary DB-failover or malicious-operator proof | Accepted engineering evidence binds 572 files and ten exit-zero commands; strong bounded local evidence, conditional production confidence |
| C02: one logical key cannot create a second gateway dispatch/debit | [Dispatch claim](../../../app/services/mcp_dispatch_attempts.py:798), PG9/PG18/PG64 evidence | Continuous record history, no bypass or fresh key, one send by owner | Semantic duplicates with fresh keys and history rollback remain possible | [Independent formal review/model](mechanism.md); tests support implementation but do not prove every interleaving |
| C03: this implies exactly one downstream business effect | None sufficient | Would require eventual delivery plus provider atomic durable dedup and correct effect semantics | Zero dispatch after claim/crash; multiple effects within one upstream call; delayed completion | Rejected as an unconditional claim; [counterexample model](mechanism-model-results.json) |
| C04: a refund/error or signed receipt establishes effect truth | Gateway response/accounting and signatures exist | Would require a separate authoritative provider contract/observation | Effect may commit before an error; issuer statement is not downstream attestation | Rejected; [router refund branch](../../../app/routers/mcp.py:1949), [mechanism review](mechanism.md) |
| C05: the primitive set is unique and forms a moat | Coherent repo integration and extensive negative tests | Buyer values maintained composition more than alternatives | Native idempotency, Temporal, AgentCore, Portkey and custom ledgers cover substantial portions | Uniqueness unsupported; market analyst and root independently checked core official sources |
| C06: real customers need and will buy it | Clear problem hypothesis and pilot protocol | Named pain, unsuitable substitutes, acceptable deployment, a buyer | No located completed customer/paid-pilot evidence | Unknown; absence from repo does not prove absence outside it |
| C07: existing credit/arbitrage figures establish attractive SaaS margins | Configured credit/debit constants and accounting reports | Credit units would have to equal collected net revenue and fully loaded cost | Refunds, support, deployment commitments, incident burden, and customer acquisition are not captured by those figures | Rejected as business evidence; [cash/effort model](economics.md) separates units and assumptions |
| C08: scaling actions and customers is linear | No benchmark or production cohort establishes this | Fixed workload mix, linear resource cost, negligible support and lock contention | Dedicated stacks, support/reconciliation steps, history growth, shared-wallet contention | Unknown; [deterministic sensitivities](economics_results.json) are not throughput measurements |

## Next ten actions, ranked by decision value

Time boxes are proposed human effort, not measured completion estimates. These
are dependencies and tests, not authorizations to send messages, spend money,
deploy, or create customer data. Existing security/correctness maintenance may
continue in its current workstream.

| ID | Question and hypothesis | Method / proposed owner / cost | Success or failure condition | Result and next action |
|---|---|---|---|---|
| E01 | Is customer evidence already available privately? | Customer owner produces sanitized stable-ID evidence index; ≤1 hour; Aug 31–Sep 1 | Dated source, action, restriction, engineer, next date and commercial level; missing entries remain unknown | Partially surfaced: program control reports provisional lead `PW-20260831-01` and an offered call from a private task; inbound/current availability not independently verified. Verify before using the channel |
| E02 | Is this an unmet consequential-write problem? | Complete remaining interviews toward the existing total of 10; ~30 minutes each; customer owner; Sep 1–3 | Real blocked write and failure consequence; existing workaround demonstrably inadequate. No staging-tool commitment after 10 qualified interviews disconfirms the current route | Not executed; qualify 3 real use cases and 2 technical sessions per sprint |
| E03 | Can the prospect use the supported pilot without a platform migration? | One worksheet per best prospect; partner engineer/operator; ~45 minutes | Owned agent, one public HTTPS MCP mutation, synthetic/redacted data, authoritative lookup, fault/reset mechanism, named engineer/date | Not executed; unsupported deployment need is a documented blocker, not permission for speculative BYOC |
| E04 | Does this repo beat the best baseline at acceptable cost? | [Market comparison protocol](market.md#the-killer-comparison-experiment); same tool/actions in both arms; partner engineer; scheduled half-day plus separately logged prep | Both arms judged on business safety; repo must additionally meet its dispatch/debit contract. Partner-precommitted latency and effort limits must hold | Proposed, not executed; retain evidence even if baseline wins |
| E05 | Does the partner understand uncertainty and safe replacement? | Add claim-before-send, effect-then-error, and delayed-effect discussion/tests where safe; partner engineer; 1–2 hours | No inference of no effect from refund/error/empty point-in-time lookup; no replacement key until authoritative finality or effective dedup/fencing makes it safe | Proposed; failed comprehension blocks unsupervised consequential use |
| E06 | Can the operator qualify and package the source without exaggerating it? | Existing technical owner resolves rapid-invoke reliability failure, retains exact skip scope, and records remaining ingress/restore boundaries; bounded by actual pilot | Failure disposition, independent review and unchanged assertions pass on the qualified source/config; no security observation is called a pass | **LOCAL RELIABILITY CLEARED:** P10 is accepted and integrated on frozen `f0c7d423…`; default-pool and singleton-pool assertions passed under independent review. Ingress rejection, restore qualification where relevant, production, and partner acceptance remain open |
| E07 | What does the supported service actually cost? | Commercial/operator owner obtains written Enterprise and Sentinel terms, bills and time logs; ~1 hour initial collection | Known minimums/allocation, monthly costs and onboarding/support effort; model inputs replaced by observed or quoted values | Not executed; do not use illustrative scenario fees as market prices |
| E08 | Is there an acceptable paid offer? | Buyer and founder review one limited paid pilot with scope, cost, outcome, support cap and decision date; ~30 minutes; Sep 9–10 | Paid pilot or written commercial commitment with buyer/budget/date; praise and unsigned curiosity fail | Not executed; price below measured delivery cost requires explicit subsidy decision |
| E09 | Would removing the boundary reintroduce an unacceptable problem? | Partner-operated receipt verification then removal interview; ~30 minutes | Concrete restriction returns and partner chooses to keep the boundary over baseline | Not executed; evidence-format preference alone is insufficient |
| E10 | Continue, narrow, or stop expansion on Sep 11? | Founder records decision against E01–E09 and the existing sprint; ~1 hour | Continue only on partner technical pass plus commercial pull; reframe on repeated documented blocker; stop expansion on sufficient substitutes/unacceptable dependency/no commitment | Pending external evidence; do not reset the calendar or invent a new feature roadmap |

The first useful experiment can be run manually: a worksheet, a controlled
staging mutation, exact-key replay, authoritative effect lookup, a stopwatch,
and the existing offline verifier. No dashboard, multi-agent management layer,
new telemetry system, or customer-simulation engine is required.

## Competing judgments and resolving evidence

**Position A — continue narrow validation:** the implemented composition may
save a team from maintaining its own security-critical action ledger; local
negative/crash evidence is substantial. **Position B — this is better as a
library, integration or incumbent feature:** strong substitutes already exist,
one managed stack per customer costs attention, and no commercial demand is
verified. The disagreement concerns incremental customer value and deployment
fit, not whether signatures or guarded database updates can work.

E04 plus E08 resolves this disagreement better than another internal proof.
The independent reviewer may challenge this judgment in
[independent-review.md](independent-review.md); credible disagreements are
retained rather than averaged into an artificial confidence score.

## Resource allocation and branch termination

- The bounded local reliability run is closed. Reactivate the same engineering
  owner only for a demonstrated defect or concrete pilot qualification need; do
  not create a duplicate runtime pod or approval tier.
- Put the next scarce founder hours into evidence retrieval, qualification and
  the buyer decision. Put partner hours into the comparative staging test.
- Pause new capability, generic market taxonomy, persona multiplication,
  numerical forecasts without input data, and cosmetic launch expansion.
- Stop a research branch when its answer needs unavailable partner data or
  merely reproduces these findings. Reopen only on a new source, prospect,
  measured result, or material technical counterexample.
- No recurrent automation was created. This report does not promise background
  work, future outreach, or scheduled execution.

## Required reporting

- Files changed: this ledger only.
- What changed: 18 ranked assumptions, 8 evidence-linked claims, 10 experiments,
  disagreement and stopping rules.
- Tests run: citations and arithmetic checked during final artifact validation.
- What passed: research reproduction, arithmetic, syntax/lint/format, local
  links and source-manifest comparison; [validation.json](validation.json)
  retains the exact checks. The historical application failure remains
  preserved, and bounded local resolution is accepted.
- What was not tested: all proposed external experiments and commercial claims.
- Remaining risks: absent private evidence and human commitments; ordinal
  rankings and time boxes are judgments.
- Recommended next step: E01, then the already-scoped partner qualification.
