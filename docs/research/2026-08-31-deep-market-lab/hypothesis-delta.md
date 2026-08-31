# Hypothesis delta since the management program began

Audit date: **2026-08-31**. For a reproducible boundary, this report uses the
explicit operational program record dated 2026-08-31 as the start of the
management cycle. That record is the sole cross-task ownership and decision
record; local workstream reports are evidence inputs rather than independent
completion authorities. [Program boundary](../../aegis/work/2026-08-31-program-control/README.md#operational-validation-program-control)

The status labels are strict:

- **Falsified** means a retained counterexample contradicts the proposition.
- **Supported locally** means source-bound tests or static/model evidence support
  the proposition only within the recorded premises and environment.
- **Untested externally** means no partner-owned observation was located; the
  proposition is neither supported nor falsified by the repository search.

Local tests do not establish customer demand or downstream business-effect
truth, and deterministic pass counts do not establish universal correctness or
commercial conversion. [Claim boundary](../../aegis/work/2026-08-31-program-control/README.md#acceptance-gates)

The supported local claims below bind the frozen 572-file acceptance source. A
later audit found 18 accepted paths changed in the current checkout; those
newer bytes are unqualified until rebound and rerun.

## Falsified or rejected hypotheses

| ID | Proposition tested | Status | Evidence and implication |
|---|---|---|---|
| F1 | Earlier passing suites were enough to call the bounded concurrent-invoke path qualified. | **Falsified by a retained local counterexample; later fixed.** | The first source-bound 20-call rapid-invoke run exhausted the default 5+10 connection pool and timed out, and its baseline comparison showed the same symptom. [Historical candidate failure](/tmp/amw-launch-20260831/logs/final-postgres-rapidfire.log), [historical baseline failure](/tmp/amw-launch-20260831/logs/baseline-postgres-rapidfire.log), [preservation rule](../../aegis/work/2026-08-31-program-control/README.md#operational-validation-program-control). Earlier green totals could not support that workload claim. |
| F2 | Clearing the pool-starvation finding required pool inflation, lock relaxation, or weaker assertions. | **Falsified for the captured local workload.** | The accepted change reused the holder's existing session, and the accepted record states that the fix used no pool inflation, lock relaxation, or assertion weakening. The default-pool regression set passed 65 cases and the actual application pool at size one/overflow zero passed 36 cases. [Mechanism and remedy](../../aegis/work/2026-08-31-program-control/README.md#acceptance-gates), [65-case log](/tmp/amw-launch-20260831/logs/acceptance-regressions.log), [36-case log](/tmp/amw-launch-20260831/logs/acceptance-poolone.log). This rejects those three remedies; it does not prove arbitrary load capacity. |
| F3 | One gateway dispatch or a valid gateway receipt entails exactly one downstream business effect. | **Falsified as a general claim.** | The gateway cannot distinguish a pre-send crash from effect-before-response-loss using durable gateway state alone, and the finite model permits zero or two upstream effects for one send while retaining its gateway invariants. [Indistinguishable histories](mechanism.md#why-uncertainty-trades-progress-for-safety), [model scope and counterexamples](mechanism.md#executed-model-provenance-confidence). Program control therefore requires partner evidence for `E(a) = 1`; it does not infer it from `D(a) <= 1` or a signature. [Effect boundary](../../aegis/work/2026-08-31-program-control/README.md#acceptance-gates) |
| F4 | A point-in-time `not_applied` lookup is enough to make a fresh-key replacement safe. | **Falsified by a valid schedule counterexample.** | A paused or in-flight original send can apply after an empty lookup and after a replacement is created, producing two semantic effects while each gateway identity still satisfies the one-send theorem. Final absence, fencing/cancellation, a terminal provider lifecycle, or durable business-level deduplication is required before replacement can be called safe. [Replacement counterexample](mechanism.md#why-uncertainty-trades-progress-for-safety) This is a composition counterexample, not a reproduced application exploit. |
| F5 | More internal management layers or another desk-research wave are the current decision bottleneck. | **Rejected by the evidence sequence.** | The local program accepted G0-G5 and left only G6 unverified; the bounded engineering run is closed until a concrete external dependency changes. [Gate state](../../aegis/work/2026-08-31-program-control/README.md#acceptance-gates), [current decision](../../aegis/work/2026-08-31-program-control/README.md#operational-validation-program-control). A duplicate management assignment was relinquished and eight overlapping workers were interrupted. [Duplicate-work record](../../aegis/work/2026-08-31-program-control/README.md#chain-of-responsibility) |

## Hypotheses supported only locally or conditionally

| ID | Proposition | Status | Evidence and claim ceiling |
|---|---|---|---|
| S1 | The accepted source clears the specific P10 starvation failure without weakening its intended authorization and accounting checks. | **Supported locally for the frozen 572-file source.** | The final manifest binds 572 files; all ten acceptance commands exited zero; independent review accepted the 36-case singleton-pool, default-pool 20-call plus replay, denial, signature, retry, and cleanup coverage. [Command manifest](/tmp/amw-launch-20260831/logs/acceptance-command-manifest.json), [independent review](/tmp/amw-launch-20260831/logs/acceptance-independent-review.json), [application record](/tmp/amw-launch-20260831/logs/acceptance-application.json). The review expressly excludes production deployment, customer validation, and a universal disable-before-commit guarantee. [Independent review](/tmp/amw-launch-20260831/logs/acceptance-independent-review.json) |
| S2 | For the supported local path and stable action identity, exact replay can preserve at-most-one gateway dispatch/debit while uncertainty remains charged and evidence remains linked. | **Supported locally and conditionally.** | The accepted default-pool set passed 65 cases, separate-process crash testing passed 9, and concurrency testing passed 18; the program accepted local G2-G4 and the joined synthetic effect/response-loss/replay/offline-verification scenario. [Regression log](/tmp/amw-launch-20260831/logs/acceptance-regressions.log), [multiprocess log](/tmp/amw-launch-20260831/logs/acceptance-multiprocess.log), [concurrency log](/tmp/amw-launch-20260831/logs/acceptance-concurrency.log), [G2-G4 and P9](../../aegis/work/2026-08-31-program-control/README.md#acceptance-gates). The theorem still assumes stable identity, one governed path, continuous database history, and trusted signing/operator control. [Exact premises](mechanism.md#exact-conditional-statement) |
| S3 | The accepted application bytes are bound to the tested evidence rather than inferred from a dirty checkout's commit hash. | **Supported for the recorded checkpoint.** | The application record reports 572 matched whitelist files, 22 task-changed paths, seven files applied in the final step, and an unchanged Git-index digest; every one of the ten command receipts records 572 source matches before and after execution. [Application record](/tmp/amw-launch-20260831/logs/acceptance-application.json), [command manifest](/tmp/amw-launch-20260831/logs/acceptance-command-manifest.json). This is evidence for that captured working tree, not later edits or a deployed release. [Program source boundary](../../aegis/work/2026-08-31-program-control/README.md#ownership-and-resources) |
| S4 | The frozen accepted candidate passes the existing broad local quality gates. | **Supported locally for that snapshot.** | The full suite reports 1,688 passed, 65 skipped, and 6 deselected; the separately executed production-posture subset reports 6 passed; Ruff passed; mypy found no issues in 171 source files; the trust release gate passed. [Full suite](/tmp/amw-launch-20260831/logs/acceptance-full.log), [posture subset](/tmp/amw-launch-20260831/logs/acceptance-production.log), [Ruff](/tmp/amw-launch-20260831/logs/acceptance-ruff.log), [mypy](/tmp/amw-launch-20260831/logs/acceptance-mypy.log), [trust gate](/tmp/amw-launch-20260831/logs/acceptance-trust.log). These counts overlap; optional browser coverage is unexecuted, pre-application rejection of a credentialed 10 MiB input remains unverified, and later checkout drift does not inherit these passes. [Acceptance update](engineering-acceptance-update.md) |
| S5 | Credible substitutes already supply important pieces of the proposed boundary, so a generic “nobody else handles retry/ambiguity/governance” position is untenable. | **Supported by current public documentation, not by a partner benchmark.** | Stripe documents idempotent result replay and indeterminate-outcome reconciliation; Temporal documents a one-attempt Activity option and stable idempotency patterns; AgentCore, Portkey, agentgateway, LangGraph, and transactional-outbox patterns document overlapping authority, persistence, gateway, or execution controls. [Seven-source comparison](market.md#seven-meaningful-alternatives). Whether any one partner's assembled baseline is sufficient remains unknown. [Comparison limit](market.md#decision) |

## Hypotheses still untested externally

| ID | Proposition still needing observation | Why it remains untested | Completion evidence required |
|---|---|---|---|
| U1 | A real team has one consequential retry-sensitive write blocked by the exact authority/dispatch/uncertainty problem. | The repository search found no completed interview record, stable prospect commitment, or named partner-owned use case; evidence outside the repository remains unknown rather than disproven. [Customer evidence audit](customer-product.md#evidence-audit) | Stable prospect ID, dated source reference, concrete action, current restriction and consequence, current workaround, owner, and next date. [Required sanitized index](customer-product.md#evidence-audit) |
| U2 | The gateway materially outperforms that partner's strongest current solution. | The market review inspected vendor documentation but ran no vendor or partner benchmark, and the partner's actual idempotency scope, retention, effect lookup, retry configuration, and authority store are unknown. [Documentary limits](market.md#seven-meaningful-alternatives) | Same partner tool and native protections in both arms, the partner's best operated baseline, pre-agreed latency/effort criteria, and retained results even if the baseline wins. [Comparison experiment](market.md#the-killer-comparison-experiment) |
| U3 | A partner can preserve stable identity, route exclusively through the gateway, reconcile final effect truth, and verify the receipt in its own environment. | G6 is explicitly unverified; the accepted P9 run used a synthetic local fixture and earns no partner-validation credit. [G6 and P9](../../aegis/work/2026-08-31-program-control/README.md#acceptance-gates) | Partner-owned agent, staging tool, engineer, effect-before-response-loss, exact replay without a second dispatch/debit, authoritative effect lookup, and offline verification in the partner environment. [Pilot acceptance test](../../30-day-customer-validation.md#pilot-acceptance-test) |
| U4 | A buyer will retain and pay for the inline boundary. | No paid pilot or written commercial commitment was located, and the proposed $2,000 pilot fee is labeled an untested price hypothesis. [Customer audit](customer-product.md#evidence-audit), [price experiment](economics.md#smallest-paid-price-experiment) | Buyer or budget owner, approved amount and cost treatment, decision date, signed/paid commitment level, and a retain/remove decision after comparison. [Commercial evidence requirement](../../30-day-customer-validation.md#buying-and-disconfirming-signals) |
| U5 | The supported managed deployment is acceptable to the buyer's security and operations owners. | The current support boundary is one vendor-managed dedicated stack with synthetic/redacted data, while BYOC/on-prem, regulated production, SLA, RTO and RPO claims are excluded; no partner deployment was observed. [Declared boundary](customer-product.md#evidence-audit) | Partner acceptance of the inline dependency and data boundary, verified staging ingress rejection before application processing, and completion of the required isolated deployment/restore checks. [Current program decision](../../aegis/work/2026-08-31-program-control/README.md#operational-validation-program-control) |
| U6 | The service has measured unit economics, scalable operations, or a repeatable acquisition path. | Enterprise/Sentinel terms, resource use, uncertainty frequency, reconciliation time, customer price, retention, CAC and conversion are unverified; model values are explicit scenarios rather than observations. [Economics evidence boundary](economics.md#what-the-repository-establishes), [illustrative assumptions](economics.md#explicit-illustrative-assumptions), [distribution limits](customer-product.md#acquisition-at-10--100--1000--10000) | Exact vendor quotes/bills, buyer-accepted fee, collected payment, separated operator/partner time, observed action and uncertainty counts, retention/removal decision, and source-to-paid conversion records. [Collection list](economics.md#smallest-paid-price-experiment) |
| U7 | The integrated combination has a defensible standalone moat. | Public sources establish overlapping substitutes, but no observed substitution win, willingness to pay, retention advantage, patent clearance, or partner-specific switching cost was produced. [Market boundary](market.md#viable-niche-versus-incumbent-response) | A fair partner baseline loses on a precommitted material criterion, the partner accepts the added dependency, and commercial evidence shows the advantage matters enough to retain. [Sprint decision rule](../../30-day-customer-validation.md#day-30-decision) |

Absence of external evidence does **not** falsify U1-U7. It means their current
status is unknown and that internal test activity cannot close them. [Evidence
policy](../../30-day-customer-validation.md#business-invariant)

## External evidence actually obtained

| Evidence class | What was obtained | Decision value | What was not obtained |
|---|---|---|---|
| Public substitute documentation | Current primary documentation for seven substitute categories, including Stripe, Temporal, LangGraph, AWS AgentCore, Portkey/Prisma AIRS, agentgateway, and developer-owned outbox/ledger patterns. No accounts were accessed and no outreach was sent. [Research scope](market.md#deep-market-lab-substitutes-and-market-boundary), [source set](market.md#seven-meaningful-alternatives) | It falsifies broad novelty language and defines a fair baseline; it does not show successful integration, customer satisfaction, or equivalent end-to-end behavior. [Evidence labels](market.md#decision) | No partner-specific configuration, runtime result, comparative outcome, or procurement decision. [Known unknowns](market.md#viable-niche-versus-incumbent-response) |
| Public price references | Railway public resource prices and public plan descriptions were collected on 2026-08-31. [Price facts](economics.md#public-price-facts-and-unquoted-deployment-costs) | They bound scenario inputs. [Price facts](economics.md#public-price-facts-and-unquoted-deployment-costs) | No exact Enterprise contract, per-tenant allocation, Sentinel terms, bill, or supported-capacity measurement. [Unquoted costs](economics.md#public-price-facts-and-unquoted-deployment-costs) |
| Distribution-channel response | A private reply-watch task reports that Boardy received the founder's targeting criteria and confirmed it would prioritize people able to authorize a one-tool staging experiment. Program control records task turn `b208c643-5879-49f9-9008-e84f97804fe7`; the original sent and inbound messages were not independently verified in this audit. | Confirms that one introduction channel understood the request. It is not a prospect introduction, partner commitment, or commercial signal. | No specific introduced prospect, tool, engineer, date, or buyer commitment. |
| Partner operational evidence | **None located in the searched repository or obtained by this research wave.** The audit accessed no CRM, customer environment, private calendar, analytics account, or live partner API. [Audit scope](customer-product.md#evidence-audit) | No partner acceptance gate can be credited. [G6](../../aegis/work/2026-08-31-program-control/README.md#acceptance-gates) | Partner-owned tool run, authoritative effect record, partner timing/burden, security acceptance, and independent receipt verification. [Pilot acceptance test](../../30-day-customer-validation.md#pilot-acceptance-test) |
| Commercial evidence | **None located in the searched repository or obtained by this research wave.** No completed paid pilot or written buyer/budget/date commitment was found; private evidence may exist and remains unverified. [Customer evidence audit](customer-product.md#customer-product-and-distribution-audit) | No demand, price, retention, or standalone-business claim can be completed. [Day-30 rule](../../30-day-customer-validation.md#day-30-decision) | Approved amount, budget owner/path, decision date, paid or signed status, actual delivery cost, and retain/remove decision. [Evidence log](../../30-day-customer-validation.md#evidence-log) |

## Decision implication

Stop spending the next cycle on duplicate management, another generic market
scan, new core capability, broad persona work, or an additional local proof
campaign. G0-G5 are accepted for the frozen snapshot, duplicate management work has already
been terminated, and the company invariant freezes new capability without a
named prospect. [Program decision](../../aegis/work/2026-08-31-program-control/README.md#operational-validation-program-control),
[duplicate-work record](../../aegis/work/2026-08-31-program-control/README.md#chain-of-responsibility),
[business invariant](../../30-day-customer-validation.md#business-invariant)

The highest-leverage next action is one evidence-producing partner comparison:
retrieve a sanitized stable prospect ID, exact consequential action, strongest
current baseline, partner engineer and committed date, then run the same staging
mutation through both arms and ask for a dated commercial commitment. [Required
input record](customer-product.md#evidence-audit), [fair comparison](market.md#the-killer-comparison-experiment),
[commercial gate](../../30-day-customer-validation.md#day-30-decision)

Until those external inputs exist, agents can only prepare the packet, verify
that it preserves the fair-baseline and stop rules, and keep the local evidence
binding current; they cannot manufacture U1-U7 from repository activity.
[External gate](../../aegis/work/2026-08-31-program-control/README.md#acceptance-gates)

## Delivery record

- **Files changed:** this report only.
- **What changed:** separated five falsified/rejected propositions, five
  locally supported propositions, seven externally untested propositions, and
  the two classes of public external evidence from the absent partner and
  commercial evidence. [Status definitions](#hypothesis-delta-since-the-management-program-began)
- **Tests run:** direct inspection of the accepted command manifest, application
  record, independent review, result-log tails, program control, and Deep Market
  Lab artifacts; no application suite or external action was run by this audit.
  [Accepted execution set](/tmp/amw-launch-20260831/logs/acceptance-command-manifest.json)
- **What passed:** this audit found evidence sufficient for S1-S5 within their
  stated ceilings. [Supported hypotheses](#hypotheses-supported-only-locally-or-conditionally)
- **What was not tested:** U1-U7 and every partner/commercial completion claim.
  [Untested hypotheses](#hypotheses-still-untested-externally)
- **Remaining risks:** an evidence owner may hold private customer records that
  were not available to this audit; the repository's absence is a retrieval gap,
  not proof of no demand. [Retrieval gap](customer-product.md#evidence-audit)
- **Recommended next step:** collect the exact external inputs and run the fair
  partner A/B test before the existing 2026-09-11 decision date. [Sprint dates
  and decision](../../30-day-customer-validation.md#30-day-customer-validation-sprint)
