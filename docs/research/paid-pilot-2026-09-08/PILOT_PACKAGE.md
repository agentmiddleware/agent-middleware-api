# One-tool paid-pilot package

**September 8, 2026 • Internal proposal draft • USD • No accepted order**

The next step is one partner-owned staging workflow with a bounded setup fee and measured delivery cost. This package turns the reconsidered economics report into an offer, qualification record, acceptance checklist, and operating tracker. It reuses the existing interview and technical runbooks.

**Current decision: ready for qualification; not ready to begin a paid deployment.** The existing candidate, recorded here as P-001, has expressed interest but has not supplied a specific tool, committed engineer, quantified consequence, budget owner, or decision date. Read-only review of the existing correspondence and a sender search on September 8 found no reply to the September 5 qualification questions. Identifying details and correspondence remain in the private customer system.

## 1. Proposed offer

| Item | Proposed scope |
| --- | --- |
| Setup fee | $2,500, subject to qualification and a final written scope |
| Delivery budget | Up to 20 vendor delivery hours; review scope at 12 hours |
| Intended delivery window | Ten business days after all prerequisites are ready; no customer dates are committed yet |
| Workflow | One partner-owned agent invoking one partner-owned staging MCP tool |
| Data and effects | Synthetic or redacted low-sensitivity data and economically representative test actions |
| Deliverable | Working scoped invocation, stable retry identity, linked debit/dispatch evidence, partner-verified receipt, and operational handoff |
| Acceptance | The partner engineer runs and records the checklist in section 4 |
| Recurring service | Separately scoped; $1,500/month is an internal test price, not a public tier or accepted quote |
| Start conditions | Named workflow and engineer; budget/decision owner; agreed scope and commercial commitment; qualified hosting and backup/restore path |

A short description for a qualified buyer:

> We will integrate one staging tool with your agent and test whether the same persisted operation identity survives retry and restart without another gateway dispatch or ledger debit. Your engineer will verify the receipt in your own environment. The setup is proposed at $2,500 for the agreed one-tool scope, with any ongoing service quoted separately after we measure the operating burden.

The guarantee is at the gateway boundary. Two distinct accepted operation keys remain distinct operations. The gateway does not determine that two independently generated tool-call IDs represent the same business intent. A signed receipt does not prove that an arbitrary upstream effect occurred exactly once.

The setup is a technical integration and evaluation. It does not include production settlement, a full IAM replacement, a regulatory-compliance claim, a customer-VPC deployment, an availability SLA, or new core capability. These limits come from the supported pilot, not from a new product roadmap.

[Supported deployment SOP](../../../docs/deploy-railway.md), [failure semantics](../../../docs/failure-semantics.md), [reconsidered economics](../../../docs/research/unit-economics-reconsidered-2026-09-05/REPORT.md).

## 2. Qualification record for P-001

Use the existing five-question outreach and interview process. General interest does not satisfy a row.

| Question already in qualification | Required answer or evidence | Current status |
| --- | --- | --- |
| Which tool/action? | Exact consequential action, partner agent, staging tool owner, and supported interface | Pending |
| What happens on timeout and retry? | Current behavior; where the operation ID is created and persisted; whether a new ID is generated | Pending |
| How is the original result determined? | Existing upstream record, ledger, status query, or investigation procedure | Pending |
| What does a duplicate or unproven call cost? | Net consequence, frequency/time window, recovery cost, and existing workaround | Pending |
| Who owns integration and the budget decision, and when? | Named engineer and buyer, budget path, next action, decision date | Pending |

Then qualify three practical boundaries: willingness to add an inline dependency, fit with the low-sensitivity staging restriction, and the specific hosting controls required. Keep names, private endpoints, and source correspondence outside the repository; use the stable prospect ID in this package and tracker.

**Fit rule:** proceed only when the current contract addresses a material unmet problem and the partner will provide its own tool and engineer. If an existing upstream idempotency configuration solves the problem adequately, record that result. Do not infer buyer value from the age or sophistication of the codebase.

**Current next action:** send one bounded qualification follow-up through the existing process, then assess any future substantive reply. No follow-up, monitoring job, or calendar invitation was created by this work.

[Existing interview script](../../../docs/partner-interview-script.md), [customer-validation gates](../../../docs/30-day-customer-validation.md).

## 3. Start checklist and delivery budget

Before accepting a fixed scope, record the proposed deployed commit, required plan/contract, one customer-specific infrastructure boundary, source of the upstream tool's test credentials, and a backup/restore qualification approach. Use the existing deployment SOP; this package does not substitute an ordinary plan for its Enterprise requirement.

The resource budget below is a planning allowance. If the required provider commitment or qualification work exceeds it, revise the scope or quote before acceptance. Do not fund an unknown contractual commitment by silently assigning it to future customers.

| Work block | Vendor hour budget | Completion evidence |
| --- | --- | --- |
| Confirm scope, identity contract, and acceptance fixtures | 2 | Written scope and synthetic test action |
| Configure qualified staging and complete restore qualification | 6 | Deployment/restore record with exact commit and isolated services |
| Integrate stable operation identity and run acceptance cases | 6 | Partner agent/tool results linked to checklist |
| Partner verification and operational handoff | 4 | Partner's offline verification and ownership record |
| Economics review and continue/stop decision | 2 | Actual cost/time review and recurring decision |
| Total | 20 | Measured hours recorded in the workbook |

At 12 hours, compare remaining cases with the remaining budget. If completion is unlikely within 20, narrow the scope or prepare a revised proposal before additional planned project work. Do not weaken acceptance criteria or record unrun cases as passed to fit the budget.

The prospective recurring offer assumes at most four routine vendor service hours per month. Incident responsibility, escalation, usage, and retention must be expressly scoped before it becomes a quote. A $1,500 monthly scenario with $70 resource/other costs, four routine hours plus 0.125 expected exception hours at $75/hour, and the report's collection/reserve assumptions leaves about $1,061.83 contribution, or 70.8%. That is a planning case, not an obligation to provide unlimited urgent support.

## 4. Partner acceptance checklist

All rows start **Pending**. A vendor demonstration cannot substitute for partner execution. Keep receipts and evidence in the partner's approved storage; record references rather than payloads in the tracker.

| ID | Case | Required observation |
| --- | --- | --- |
| A01 | Ownership and environment | Partner owns the agent/tool; named partner engineer operates the session; supported synthetic staging boundary |
| A02 | Ordinary success | One permitted invocation produces the expected gateway accounting and a verifiable receipt |
| A03 | Identical replay | Same accepted key and payload return the same receipt with no additional gateway dispatch/debit |
| A04 | Worker restart | Partner persists operation identity before the network call; restart resumes that same identity and does not create a new dispatch/debit |
| A05 | Conflicting payload | Reused key with changed input fails closed; no additional dispatch/debit |
| A06 | Scope and budget denial | Existing out-of-scope and insufficient-budget paths deny with appropriate evidence and no unauthorized dispatch/debit |
| A07 | Auth/permit boundary | Missing, revoked, expired, or wrong-bound authority is rejected in the relevant supported cases |
| A08 | Post-dispatch uncertainty | Controlled synthetic response loss yields the documented uncertain outcome; debit retained; no automatic redispatch |
| A09 | Independent verification | Partner engineer verifies the exported receipt offline in the partner environment; tampering is rejected |
| A10 | Operating burden | Integration hours, added latency, retained record size, failures, and investigation work are recorded with matching scope |
| A11 | Value and commercial decision | Partner explains the unmet consequence, names the buyer and decision date, and accepts a paid continuation or records a decline |

For A04, use the partner's actual orchestration retry path, not just two manual HTTP requests. For A08, use a mutually agreed synthetic fixture and the existing failure-semantics procedure; do not create uncontrolled external effects. A11 is a commercial gate and stays separate from technical acceptance.

Use the existing [first-tool runbook](../../../docs/partner-first-tool-runbook.md) and [design-partner guide](../../../DESIGN_PARTNER_GUIDE.md). This checklist adds the identity and economics acceptance record, not a new integration protocol.

## 5. Recording economics

Generate `pilot-tracker.xlsx` with `build_tracker.py` before using the tracker. The
generated workbook is intentionally not stored in this curated source set.

The Plan sheet contains editable hypotheses. Actuals stays **Pending** until the operator selects a complete period and explicitly confirms the relevant records are complete. Zero records after confirmation mean an observed zero; before confirmation they mean unknown. The Example sheet is fictional and excluded from actual totals.

Record delivery time in Time, attributable expenses in Costs, earned platform fees and cash collection separately in Revenue, and matched operational counts in Usage. Select Setup or Recurring in Actuals; acquisition and shared expenses belong to their own phases and are not silently mixed into delivery contribution.

Cost and revenue accrual dates can differ from their cash dates. Enter the service-period amount and cash amount in their separate columns. Refunds or credits reduce the appropriate revenue/cash amount; exclude pass-through tax. The tracker is an operating analysis, not a general ledger or accounting-policy decision.

Provider expenses must reconcile to the actual bill. For a creditable workspace minimum, allocate actual usage and any unabsorbed minimum once. Do not enter both the entire minimum and the same included usage as additional expenses. Keep a record of the allocation basis.

The plan includes a 1% reserve assumption. Actual contribution does not subtract that hypothetical reserve; actual concessions, refunds, and expenses belong in the underlying records. This prevents a planning allowance from being presented as observed cost.

## 6. Closeout decision

**Technical acceptance:** A01–A10 pass with partner-owned evidence, or a specific failed/unrun case is documented. An incomplete checklist is not a technical pass.

**Commercial acceptance:** A11 records an explicit paid or written commercial commitment, with buyer and date. Setup payment alone does not establish recurring demand.

**Economic review:** compare actual setup effort to the 20-hour budget; reconcile provider costs; estimate the recurring obligation from observed work. Investigate any negative contribution or inability to bound future service effort before offering ongoing service.

**Continue:** a partner-owned pass, a concrete buying reason, and a viable scoped recurring offer.

**Narrow:** a real problem exists, but only a smaller integration or limited service is valued.

**Decline or stop:** existing controls suffice, identity cannot be preserved, the supported boundary is unacceptable, the buyer will not commit a tool/engineer, or the needed price exceeds value.

The existing sprint ends September 11. Record the actual evidence available on that date; a pending prospect reply should remain pending rather than extending or satisfying the milestone by assumption. Any later follow-up should retain its real evidence date.

## 7. Work record

- **Files changed:** this source package, its reproducible generators, and validation record. The generated workbook is intentionally excluded from the curated set.
- **What changed:** research recommendations became a scoped offer, evidence-based qualification state, partner acceptance checklist, and actual-cost tracking workflow.
- **Tests run / what passed:** see VALIDATION.md for completed workbook recalculation, scenario and filter checks, and document checks.
- **What was not tested:** partner integration, performance, production deployment, payment, or customer acceptance.
- **Remaining risks:** P-001 qualification is incomplete; provider terms and delivery effort are unresolved; all offer prices remain hypotheses.
- **Recommended next step:** send the qualification follow-up, assess any future reply, then fill the workflow/owner/date fields and finalize scope before starting delivery.
