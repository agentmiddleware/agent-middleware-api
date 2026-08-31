# Duplication and kill/freeze audit

Audit date: **2026-08-31**. “Since Quantum Management began” is bounded here
to the operating program recorded in
[program control](../../aegis/work/2026-08-31-program-control/README.md). This
is a source-and-record audit of work allocation and product scope. It does not
claim that a source file disappeared merely because work on it was frozen.

## Objective delta: duplication already eliminated

| Delta | Reality level | Completion evidence | Critical-path effect |
|---|---|---|---|
| One operating registry replaced competing management plans. | **Verified in the canonical program record.** | Program control declares itself the single cross-task ownership and decision record (`README.md:3-6`). The later executive task explicitly declined to create another registry, scheduler, automation, or execution pod (`README.md:74-83`). | One owner can accept or reject a gate; agents no longer need to reconcile parallel management decisions. |
| A second engineering pod was not created. | **Verified in the canonical program record.** | Six peer kickoff roots were inventoried; the existing eight-specialist engineering pod was reused; duplicate management from `e2-6aeb` and duplicate engineering from `e0-9564` were consolidated (`README.md:276-283`). `e2-6aeb` relinquished its duplicate assignment and `e0-9564` interrupted eight overlapping workers (`README.md:85-89`). | Preserved engineering capacity for one source-bound fix and one independent review chain. |
| Runtime and test execution acquired one owner. | **Verified in the canonical program record.** | The setup-only child ran no tests; execution transferred to `df-ba0b`, which became sole owner of application suites, crash runs, and reproduction probes (`README.md:118-120`, `README.md:283`). | Removed competing database/test ownership and made one accepted run set possible. |
| Two replacement provenance audits were cancelled after one completed result arrived. | **Verified in the canonical program record.** | Both proposed replacement audits were cancelled; the existing audit was retained as the single approval result (`README.md:304-315`). The packet was frozen after a metadata-only check and needs no unchanged-source acceptance rerun (`README.md:316-329`). | Prevents repeated acceptance work from delaying external validation. |
| Broad proof-surface work lost production authorization. | **Verified freeze; code remains.** | `ENABLE_PROOF_SURFACES` defaults false and production-like configurations must keep it false ([config](../../../app/core/config.py), lines 78-87). Eighteen proof routers mount only behind that flag ([application](../../../app/main.py), lines 563-590; [inventory](../../PROOF_SURFACES.md), lines 27-49). | Keeps the partner experiment on one tool and stops eighteen demo domains from becoming parallel product work. |
| Four old roadmap branches were explicitly made historical or frozen. | **Verified document state; files remain.** | [Sprint plan](../../SPRINT_PLAN.md), [gap-closure plan](../../GAP_CLOSURE_PLAN.md), [competitive analysis](../../COMPETITIVE_ANALYSIS.md), and [production-beta roadmap](../../production-beta-roadmap.md) each carry a superseded/frozen banner. | Their unchecked boxes are no longer valid reasons to allocate engineering. |

No product module was deleted by these management deltas. The current source
still contains the frozen routers, stubs, legacy plans, two SDK trees, and broad
core mounting described below. “Eliminated” above means duplicate ownership or
active authorization ended, except where an explicit cancellation is recorded.

## Duplication and low-value scope that remains

| Priority | Remaining duplication or scope | Evidence | Kill/freeze decision | Expected effect |
|---|---|---|---|---|
| 0 | Unchanged-state heartbeat reporting | The heartbeat was reduced only after successive unchanged checks, yet remains active every four hours ([program control](../../aegis/work/2026-08-31-program-control/README.md), lines 693-709 and 740-748). | **Kill periodic no-delta polling.** Resume on a concrete partner input, a source change, or a reproduced defect. | Directly enforces delta-only reporting and returns agent capacity to partner qualification. |
| 0 | New technical pods, acceptance reruns, or extra approval layers on the accepted source | All ten final commands passed; the 572-file snapshot and packet are frozen; no further unchanged-source acceptance rerun is required ([program control](../../aegis/work/2026-08-31-program-control/README.md), lines 8-27 and 291-348). | **Kill all standing engineering/test/audit allocation.** Reserve one engineer and one independent reviewer, activated only by a changed source, failed ingress check, or partner-discovered defect. | Prevents local proof from displacing the only open company gate, partner-owned G6. |
| 0 | Multiple documents mirroring current gate status | Program control says it is the single operating record. The dated [research decision ledger](decision-ledger.md) says it is a handoff, not a new registry; the [customer sprint](../../30-day-customer-validation.md) is the company milestone. | **Kill live status mirroring in research reports.** Freeze this dated package after reconciliation; link to program control for technical state and to one private/sanitized customer evidence index for external state. | Prevents a technical fix from leaving contradictory “held” or stale source-count claims in several reports. |
| 0 | More desk research, persona work, forecasts, and internal mechanism proofs without partner inputs | Assumption A18 rejects another market-research wave; the next experiment needs partner access, baseline configuration, burden, and payment evidence ([decision ledger](decision-ledger.md), A18 and “Resource allocation”). The comparison is already specified and explicitly unexecuted ([market report](market.md#the-killer-comparison-experiment)). | **Kill the research branch until new external evidence arrives.** Do not update TAM, personas, economics, or vendor matrices from the same inputs. | Converts the next cycle from another report into a decision-changing comparison. |
| 0 | Live-looking engineering roadmaps that bypass the customer-evidence gate | [Technical recommendations](../../../TECH_RECOMMENDATIONS.md) still labels P0/P1 work as having no gate (lines 18-39 and 65-73). [Tech-debt remediation](../../tech-debt-remediation-plan.md) tells agents to execute phases (lines 1-15). The active sprint forbids new core work without named-prospect evidence ([customer sprint](../../30-day-customer-validation.md), lines 19-40). | **Kill their status as active plans.** Retain them only as defect inventories; execute an item solely when it is a reproduced security/correctness issue, keeps a release gate green, or blocks the selected partner pilot. | Removes an easy path for agents to manufacture internal work while G6 is open. |
| 1 | A broad production-facing core surface alongside a narrow product claim | `CORE_TRUST_ROUTERS` still includes 24 modules, including KYC, planner, dev keys, three MCP routers, webhooks, and broad billing ([application](../../../app/main.py), lines 536-561). The generated [OpenAPI](../../openapi.json) has 99 paths in this working tree, including KYC, planner, arbitrage, fiat top-up, transfer, dev-key, AWI-manifest, and multiple MCP invocation paths. The root payload still describes a broad “operational control plane” and advertises KYC/planner and demo services ([application](../../../app/main.py), lines 627-669). | **Freeze code work now; kill exposure in the partner environment.** Before staging exposure, use an ingress allowlist for the one supported route set and verify the body limit. After the September 11 decision, remove non-wedge mounts and advertising from the default application if the narrow wedge continues. | Reduces pilot attack and comprehension surface without delaying partner selection for a speculative refactor. |
| 1 | Multiple governed invocation variants with different recovery limits | The accepted backlog says local-tool recovery differs from the SDK result and standard MCP replay can depend on live registration; the selected pilot path is explicit-permit remote JSON-RPC with stable registration ([program control](../../aegis/work/2026-08-31-program-control/README.md), lines 213-233). | **Freeze all nonselected invocation variants for the pilot.** Do not generalize or reconcile them until a named partner needs one. After the experiment, retain one documented canonical path and deprecate redundant entry points based on observed use. | Shrinks the identity/replay contract the partner must understand and keeps the A/B comparison source-bound. |
| 2 | Two SDK identities | Both `awi_sdk/` and `b2a_sdk/` remain tracked. The [AWI guide](../../awi-adoption-guide.md) calls AWI a frozen, partly aspirational proof surface and says its SDK is not installable (lines 1-8 and 28-43); the root [README](../../../README.md) documents `b2a_sdk` as the tested trust SDK (lines 637-668). | **Kill active maintenance and promotion of `awi_sdk`.** Keep `b2a_sdk` only for the partner flow and offline verifier. Archive or delete the AWI tree after the day-30 decision rather than paying for a rename/collapse now. | Removes a second integration identity while preserving the verifier required by the acceptance test. |
| 2 | Frozen proof code and stubs still create repository maintenance surface | The frozen inventory lists 18 routers and four accept/freeze stubs, and explicitly prefers deleting unused stubs over growing them ([proof-surface inventory](../../PROOF_SURFACES.md), lines 17-79). | **Keep frozen through the decision; do not test or improve them for this cycle.** If the narrow wedge continues, delete unselected proof surfaces in a separate reviewed cleanup. If the company stops core expansion, archive the repository state instead of funding cleanup. | Avoids a risky deletion wave before customer evidence while preventing dormant demos from consuming the cycle. |
| 2 | Historical plans remain searchable beside the active plan | The old sprint, gap, beta, competitive, and product-strategy documents are retained for history; several contain detailed unchecked work and broad positioning even though their headers disclaim it. | **Kill all updates and active links that imply execution.** Keep one archive index and the banners; do not convert historical checklists into issues. | Lowers the chance that a future agent restarts superseded work. |

## What to kill now, what to preserve

Kill now:

1. Periodic unchanged-state heartbeat work and activity-only reports.
2. Standing technical/research agents after they deliver this delta package.
3. Acceptance reruns or new internal proofs against the unchanged accepted
   manifest.
4. Execution authority for `TECH_RECOMMENDATIONS.md`, the tech-debt phase plan,
   and every superseded roadmap unless a documented exception satisfies the
   customer-evidence gate.
5. Public partner-environment access to routes outside the selected one-tool
   experiment.

Execution receipt: automation `amw-operational-validation-management` was
changed from `ACTIVE` to `PAUSED` after this audit. Its four-hour no-delta poll
will no longer consume cycles; the saved prompt and target task remain intact
for a deliberate resume when concrete partner evidence arrives.

Preserve:

1. The accepted gateway transaction path, its negative-path tests, and the
   historical failure logs. Deleting failed evidence would weaken the audit.
2. The `b2a_sdk` offline verifier and partner worksheet because the partner must
   operate both.
3. Security/correctness maintenance triggered by a reproduced defect.
4. One program record and one external evidence index with stable prospect IDs;
   private identities and payloads stay outside the repository.

Do not spend this cycle physically deleting broad application modules. First
remove them from the partner deployment boundary. Source deletion is a separate
security-critical cleanup only after the day-30 product decision; otherwise it
would create more internal test work before the external hypothesis is resolved.

## Reallocation to the critical path

| Capacity | Allocation now | Activation / completion evidence |
|---|---|---|
| Founder/customer owner | Schedule the reported 20-minute qualification for stable prospect `PW-20260831-01`; obtain the exact action, current restriction, strongest baseline, buyer/budget path, and decision date. | The lead and offered next step are reported but not independently verified, and no partner experiment is committed ([program control](../../aegis/work/2026-08-31-program-control/README.md), lines 720-734). Completion requires a dated stable-ID evidence row, not another status note. |
| Partner engineer + operator | Only after qualification, fill the comparison packet for one tool: endpoint, synthetic payload schema, authoritative effect lookup, response-loss fault/reset method, durable action-key behavior, and accepted latency/burden limits. | Entry criteria come from the [customer sprint](../../30-day-customer-validation.md#pilot-acceptance-test) and the [fair A/B protocol](market.md#the-killer-comparison-experiment). |
| One existing engineer | Remain idle until the tool is selected, then verify the restricted staging route set and a pre-application oversized-body `413`. | The local program is closed; the ingress limit is the explicit unverified exposure control ([program control](../../aegis/work/2026-08-31-program-control/README.md), lines 520-537). |
| One independent reviewer | Activate only for new source or after the completed partner run; verify evidence binding and no claim inflation. | The accepted local audit is complete and replacement audits were cancelled; partner-owned G6 is still not accepted. |
| Market, economics, mechanism, QA, and additional management agents | **Idle.** | Reopen only on new partner evidence, changed source, or a material counterexample. |

The single highest-leverage action is to complete the offered qualification with
`PW-20260831-01` and leave with a committed partner engineer, one consequential
staging mutation, a date, the partner's strongest existing control stack, an
authoritative effect lookup, permission for the controlled response-loss case,
and a buyer/budget decision path. That one record unlocks the ingress check, the
fair comparison, and the commercial test. Without it, more agents can only
produce duplicate internal evidence.

## Evidence and limits of this audit

- **Files changed:** this audit only.
- **What changed:** recorded verified coordination duplication already removed;
  separated remaining duplicate work from dormant source; ranked the immediate
  kill/freeze decisions; and mapped all remaining capacity to the external gate.
- **Tests run:** read-only source/document inspection; current OpenAPI path
  count; router and SDK inventory; local-link and whitespace validation.
- **What passed:** the cited local files exist; the current working-tree OpenAPI
  contains 99 paths; `PROOF_SURFACE_ROUTERS` contains the 18 modules listed in
  the freeze inventory; and the program record contains the cited owner,
  cancellation, accepted-run, and external-gate evidence.
- **What was not tested:** no application suite was rerun, no deployment or
  external message was sent, no active private lead identity was inspected, and
  no partner comparison or commercial conversation occurred in this audit.
- **Remaining risks:** the checkout is dirty and current source/public OpenAPI
  can change; manager-recorded task cancellation was not independently replayed;
  route reduction can break an undocumented dependency; and the reported lead
  may not be available or qualified.
- **Recommended next step:** stop all no-delta internal work and have the
  founder complete the `PW-20260831-01` qualification record; activate the
  operator and one engineer only after the action, partner engineer, baseline,
  and date are committed.
