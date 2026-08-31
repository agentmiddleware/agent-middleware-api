# Independent decision review

Reviewed 2026-08-31. Scope: challenge the research conclusions, reproduce the two
standard-library models without changing their artifacts, independently check
example arithmetic, and compare relevant state transitions with source. This
review did not run application/database tests, re-open external vendor sources,
contact customers, or change application behavior. Existing engineering work
retains ownership of runtime correctness and launch acceptance.

## Superseding status addendum

After this review's original checkpoint, independent engineering review
accepted all ten bounded local commands on the frozen 572-file source manifest
`f0c7d4236ffc785ca98e002bc4ea3f1759c9d0cc30e972798f37c2a021b5c289`.
That record includes the default-pool 20-call / 20-replay case and the actual
application-pool-size-one suite. The earlier failed logs remain valid historical
evidence of the defect and why the original hold was warranted.

Subsequent concurrent work changed accepted source paths, so the frozen packet
does not qualify the current working tree without renewed source binding and
affected-gate reruns. Production, ingress-size rejection, and partner gate G6
also remain unaccepted. See [the current technical assessment](technical.md)
and [acceptance update](engineering-acceptance-update.md). The commercial
judgment below is unchanged.

**Decision: MODIFY the experiment, CONTINUE bounded customer validation, and
PAUSE new core capability.** Require a comparison against the partner's best
existing controls and measure total partner/operator burden. Do not accelerate
product expansion. The evidence also does not justify a pivot or killing the
business: missing customer records in Git are not proof that no customer
evidence exists elsewhere, and hypothetical costs are not observed losses.
Keep the existing September 11 decision date; a proposed pilot duration does
not restart the validation sprint.

**At this original review checkpoint, runtime pilot acceptance was HELD.** A newly executed existing PostgreSQL
rapid-invoke case failed; read-only inspection of the retained
[final log](/tmp/amw-launch-20260831/logs/final-postgres-rapidfire.log) confirms
connection-pool timeouts and the missing expected receipt envelope. The
[baseline log](/tmp/amw-launch-20260831/logs/baseline-postgres-rapidfire.log) also
reports failure. These logs do not alone establish root cause or whether all
supported remote pilot paths are affected. The existing engineering owner must
resolve/disposition the failure with source-bound evidence before runtime
acceptance. Discovery and commercial qualification can continue during that
hold; earlier passing suites cannot override it.

## Three decision-changing challenges, ranked

| Rank | Challenge | Confidence and evidence level | Observation that changes the decision |
| --- | --- | --- | --- |
| 1 | **A useful implementation may still be an unnecessary purchase.** The combined boundary must remove a restriction that the partner's current controls cannot adequately remove. Network-send count alone is not a fair customer outcome: multiple native-idempotent requests producing one correct effect can be acceptable. | **High confidence in the evidence gap; customer conclusion not verified.** [Customer-product](customer-product.md) found plans/templates/demos, not a completed partner/commercial evidence record. [Market](market.md) distinguishes documented substitute capabilities from untested integrations. No observed substitution win or willingness to pay is established. | A partner runs the same action with its best existing controls and with this gateway, identifies a material difference, accepts the added dependency, and makes a concrete commercial commitment. If the baseline suffices, narrow the product or stop expansion; do not weaken the baseline to manufacture a win. |
| 2 | **The attractive scale economics depend on unverified contract allocation and labor capacity.** Price and cost tables are sensitivity calculations, not unit economics. | **High confidence in arithmetic; low confidence in real-world inputs.** Independently checked [economics results](economics_results.json): at 10 tenants the shared-minimum case is $780/month each; a $1,000 minimum per dedicated tenant makes it $1,680 with all other assumptions unchanged. The same scenario requires 54.33 recurring vendor hours, or 174.33 hours if all ten onboard, against 40 available founder hours. | Obtain written pricing for the actual deployment and log vendor/partner hours during the owned pilot. If the buyer's accepted total price does not cover a repeatable delivery model, change packaging or stop that deployment model. Lower allocated cloud cost cannot solve a capacity shortfall. |
| 3 | **One gateway dispatch trades completion for safety and does not establish business-effect truth.** The buyer may need the action to complete promptly or require stronger effect/value guarantees than this boundary supplies. | **High confidence in the conditional boundary; partner fit not verified.** [Mechanism](mechanism.md), `claim_dispatch` in [dispatch attempts](../../../app/services/mcp_dispatch_attempts.py), and returned-error handling in [the router](../../../app/routers/mcp.py) allow charged uncertainty with no effect and a refunded returned error with an effect. The model assumes the implementation properties needed to prove its finite invariants. | Require stable caller identity, an authoritative effect lookup with appropriate finality, understood error/refund semantics, and acceptance of manual uncertainty handling. Measure the time until work can safely proceed, not just receipt generation. Reject an unsuitable pilot instead of expanding into semantic deduplication, business-value enforcement, or high availability without named-customer evidence. |

The first two challenges can invalidate the company thesis even if every local
test passes. The third can invalidate a particular tool integration even if
buyers like the general idea. None is evidence that arbitrary new features are
the remedy.

## Arithmetic audit

Eight base-case quantities were calculated independently using `Decimal`, with
declared inputs written directly into the audit rather than importing the
model's calculation function. At one tenant and 10,000 new actions:

| Quantity | Independent calculation | Result |
| --- | --- | ---: |
| Retained storage proxy | 5 GB + 10,000 × 25 KB × 12 months × 3 / 1,000,000 | 14 GB |
| Vendor reconciliation | 10 assumed uncertain actions × 5 minutes / 60 | 0.8333 hours |
| Partner reconciliation | 10 × 15 / 60 | 2.5 hours |
| Nonlabor external-cost proxy | $1,000 + $100 + 10,000 × $0.002 + $25 | $1,145 |
| Recurring vendor work | 8 shared + 3 support + 0.8333 reconciliation | 11.8333 hours |
| Monthly economic cost | $1,145 + (11.8333 + 12/6 onboarding) × $75 | $2,182.50 |
| First-month economic cost | $1,145 + (11.8333 + 12 onboarding) × $75 | $2,932.50 |
| Resource-cost proxy before contractual floor | RAM $20 + baseline CPU $2 + incremental CPU $0.0185185 + volume $2.10 + egress $0.015 | $24.1335185 |

The ten-tenant $780 result and all nine reverse customer-value thresholds were
also independently checked. For example, $2,000 divided by 0.1 incremental
avoided events/month yields $20,000/event. That is a break-even identity, not
an estimated incident probability, expected loss, or verified customer value.

No arithmetic error was found in those quantities. Precision does not improve
input credibility: resource sizing, contract minimums, labor rates, uncertainty
fractions, reconciliation minutes, six-month onboarding amortization and
scenario likelihoods are not measured here. Scenario likelihoods are not
assigned at all. The cost model does not demonstrate throughput or retention.

The initial cash field excluded every labor payment while its name mentioned
only founder pay. Beyond founder capacity, that could be mistaken for a runway
estimate despite requiring paid help or impossible unpaid work. This review
requested an explicit **nonlabor cash proxy**, a separate capacity warning,
and the per-tenant commitment sensitivity. The author added those corrections,
and the updated $780/$1,680 alternatives and all-labor exclusion were
independently verified. The economic report also explicitly preserves the
September 11 deadline. Even corrected, the model is not a funding or hiring
plan.

## State-model audit and corrections

The initial saved model reproduced 340 states and 1,534 transitions. Its replay,
payload-conflict, atomic debit, admission and claim exclusivity behaviors are
encoded premises. Passing assertions do not independently verify the SQL,
authorization, numeric accounting, receipt signatures, or all crash schedules.
The model is useful for exposing consequences and counterexamples under its
premises. It must not be counted as another application test suite or a higher
level of customer evidence.

Two concrete issues were sent to the responsible author:

1. **Lost claim acknowledgment:** the initial model allowed
   `same_live_owner_recovers_commit_ack` after `phase == uncertain`, while
   `McpDispatchAttemptService.claim_dispatch` recovers only a row still in
   `DISPATCH_CLAIMED`. Restrict that recovery transition to `claimed`. A worker
   that already received its send right may still resume after uncertainty;
   retain that separate late-send case.
2. **Permit change versus identity change:** the first risk paragraph initially
   grouped changed permits with changed wallets as ways to create a different
   action identity. `permit_id` belongs to payload hash `H`, not identity `K`.
   A changed permit with the same wallet/endpoint/key conflicts; it does not
   create another dispatch. Fresh keys or changed identity namespaces have
   the different semantics described by the report.

Both corrections are now present. Independent re-execution of the corrected
model reproduced **340 states and 1,526 transitions**, matching the updated
result artifact. Three targeted checks confirmed recovery exists while
claimed, recovery is absent after uncertainty, and an already-authorized
paused owner still has its one send. The mechanism report now explicitly says
changing only the permit under the same `K` conflicts. These were abstraction
and wording corrections, not newly discovered application defects.

Existing product-document contradictions were independently confirmed and
forwarded without modifying source: [failure semantics](../../failure-semantics.md)
said revoked permits cannot read replay evidence, whereas
`PermitService.validate_replay_access` deliberately ignores mutable revocation
and expiry while enforcing stable identity/signature binding. Returned-error
refunds in the router also do not query or undo the business effect. Correction
belongs with the existing documentation owner, not a change to financial policy
or evidence access to fit inaccurate prose.

Model executions were captured in memory by intercepting their result-file
writes. Both regenerated results matched their saved content, excluding the
mechanism timestamp and independently compared source-hash snapshot. The
recorded mechanism source hashes had no drift at that observation. This is
not an atomic source freeze.

Final model file SHA-256 values at this review:

- `economics_model.py`: `3c4e35b8a5e156c1e50598b0d4e68fb8adf157680729cb6fc106a20c3f00d90e`
- `mechanism_model.py`: `1a8af6e9cdcee1b64b53bc53b483ce499a2e8c60cbd934462d42813595e30e00`

The final mechanism digest includes root-applied formatting and a subsequent
mypy correction: explicit `parents` value typing and local-variable narrowing
in trace reconstruction. The root reported unchanged Python AST for the
formatting step; the typing correction does not change state transitions.
This reviewer inspected that correction and independently re-executed the
final mechanism in memory: saved results match, with 340 states, 1,526
transitions and the three targeted recovery/late-send checks still passing.
Both models had also reproduced their saved results after formatting.

## Evidence-level judgment

[Technical](technical.md) appropriately separates source-bound local test
evidence from production and customer validation; its suite counts overlap and
must not be summed. This independent review did not certify those application
runs. The PostgreSQL failure established an unresolved qualification limit at
this checkpoint; the addendum records its later bounded local resolution
without deleting the failure. [Market](market.md) is a primary-source
document comparison, not an
executed vendor benchmark. [Customer-product](customer-product.md) labels
personas, acquisition mechanisms and onboarding friction as hypotheses, not
interviews or observed behavior. [Economics](economics.md) describes a proposed
commercial experiment, not revenue. Preserve those distinctions in any shorter
README, pitch or decision summary.

The [research README](README.md) and [decision ledger](decision-ledger.md) were
checked at the original checkpoint and later reconciled to the accepted frozen
engineering result. They preserve the failed runs as history, treat commercial
evidence as unverified, and preserve the corrected model counts and
hypothetical economics. Root-owned artifact validation is recorded separately
in `validation.json`.

The most useful next artifact is a sanitized customer-evidence index and one
partner-owned comparison result, not a larger market model. A stable prospect
ID with a dated private source reference is sufficient; private names,
payloads, contracts and credentials do not belong in this research directory.

## Work record

- **Files changed:** this review only.
- **What changed:** independent arithmetic/state-model audit, three ranked
  decision challenges, correction requests and explicit decision limits.
- **Tests run:** in-memory re-execution of both pure standard-library models;
  eight independent base `Decimal` checks; both ten-tenant contract variants;
  all nine reverse-value thresholds; three corrected claim-recovery/late-send
  checks; targeted source/log inspection and report checks.
- **What passed:** sampled arithmetic and final model-content comparisons;
  mechanism source hashes matched when checked; corrected model reports 340
  states and 1,526 transitions. The application rapid-invoke failure was not a
  pass at this checkpoint; its later accepted resolution belongs to the
  engineering review cited in the addendum.
- **What was not tested:** application/DB behavior, vendors, live deployment,
  customer systems, actual costs, acquisition, payments, demand or production
  reliability. External market citations were read in the reports but not
  independently re-opened by this reviewer.
- **Remaining risks:** unverified commercial inputs; partner identity/finality
  obligations; conflating conditional mechanism evidence with purchase value;
  current-source drift, ingress/production qualification, and concurrent
  changes outside captured observations.
- **Recommended next step:** preserve the September 11 decision gate, bind the
  exact pilot candidate, verify staging ingress rejection, and qualify one
  partner against its best existing controls before approving any new core
  capability.
