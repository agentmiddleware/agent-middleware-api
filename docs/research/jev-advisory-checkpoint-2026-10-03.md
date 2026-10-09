# Jev advisory checkpoint: synthetic QA evidence

Date: 2026-10-03. Status: independently reviewed research evidence.

## Decision

Keep `JEV_RISK_GUARD=off` pending customer-specific validation. AMW already
contains an optional Jev guard, with an
[off default](../../app/core/config.py#L150). Its
[enforce path](../../app/routers/mcp.py#L1655) can deny an ungoverned call or
require human approval for a governed call when Jev escalates. That is an
execution gate, not purely advisory metadata.

This synthetic trial does not evaluate or validate that shipped guard and does
not justify enabling enforcement. Its evaluated configuration frequently
accepted claims that the supplied evidence contradicted or did not establish.
Deployment configuration was not inspected or changed by this checkpoint.
Preserve AMW's deterministic authorization, accounting, execution, and release
gates. Any change to the optional guard remains subject to the
customer-validation invariant in [`AGENTS.md`](../../AGENTS.md) and the
existing proof-surface freeze. This record adds no runtime integration or
dependency.

This checkpoint supplements the
[TypeSafe consumed reference](typesafe-system-one-2026-10-03.md). It evaluates
authored synthetic QA narratives, not AMW application behavior or customer
validation. Zero application tests were executed by the inference trial.

## Method

One request to pinned model `jev-1.13.0` contained 36 synthetic cases in a
shared state array. Each case had one three-way Choice question (supports,
contradicts, insufficient evidence) and one Noul asking whether the complete
claim was supported: 72 judgments total, with zero automatic retries.

Expected labels were authored before inference and omitted from the request.
There were twelve cases per relation label; the corresponding support targets
were true, false, and false. The twelve scenario families covered worker
startup, dynamic content, history capacity, cancellation, CI evidence,
TypeScript checks, branch merges, skipped reviews, tree identity, deployment
observations, file preservation, and empty pytest collection.

A fresh reviewer checked all 36 expected labels against the supplied evidence
and rubrics, and independently recomputed scores from the saved request,
expected labels, and response. A separate arithmetic recomputation agreed.
No substantive label, rubric, indexing, or scoring defect explained the errors.

## Results

| Measurement | Recorded result |
| --- | --- |
| Evidence-relation accuracy | 19/36, 52.78% |
| Support accuracy at Noul probability ≥0.5 | 20/36, 55.56% |
| Supported claims accepted | 12/12 |
| Unsupported claims falsely accepted | 16/24, 66.67% |
| False accepts among all accepted claims | 16/28, 57.14% |
| Input / output tokens | 10,581 / 2,328 |
| Estimated usage charge | $0.000444402 |

The estimate is `10581 × 0.042 / 1000000`, using the
[published price](https://docs.typesafe.ai/models) at the checkpoint: $0.042
per million input tokens, with free outputs. It is not a billing receipt.
Choice and Noul each falsely accepted sixteen unsupported claims, but their
case sets differ in cases 07 and 17.

| Expected / predicted relation | Supports | Contradicts | Insufficient |
| --- | ---: | ---: | ---: |
| Supports | 12 | 0 | 0 |
| Contradicts | 9 | 3 | 0 |
| Insufficient | 7 | 1 | 4 |

A material failure was case 19: synthetic evidence said a supplement reached
a feature branch, the prerequisite PR remained open, and main was unchanged.
The model nevertheless classified the claim that the prerequisite PR merged
into main as supported, with Noul probability 0.83.

Abstaining when `0.2 < probability < 0.8` sends 21/36 cases to review. The
remaining fifteen decisions include fourteen correct results and that false
accept. Raising the acceptance threshold to 0.8 still accepts the wrong claim:
eight accepts, one error. Requiring Choice=supports, Choice confidence ≥0.8,
and Noul ≥0.8 accepts only five cases, with no observed errors. These post-hoc
gates are not validated production thresholds.

## Response validation and confidence caveat

The [documented structural contract](https://docs.typesafe.ai/api) checks
passed: the pinned model, exact response fields and all 72 question IDs,
answer types, finite probabilities in range, distributions summing to one,
choices at the maximum probability, and nonnegative integer token usage.

For three Choice options, the
[documented confidence formula](https://docs.typesafe.ai/confidence) is
`(3 × maximum_probability − 1) / 2`. Eleven saved confidences match exactly;
twenty-five differ by 0.005–0.015 in either direction. Cases 18 and 34 differ
by +0.015, exceeding a conservative ±0.0125 allowance for independently
rounding both probability and confidence to two decimals. The origin of the
discrepancy is unestablished; this does not prove a service defect.

The local runner checked confidence range but not that formula. This does not
alter either accuracy score. Recomputing confidence from the displayed
probabilities also leaves the five-case combined gate unchanged.

## Evidence boundaries

The source request and expected labels retained their original bytes. The
submitted body matches the request hash recorded before inference; expected
labels and the runner also match the recorded hashes. The complete response
is retained as JSON with normalized whitespace. These fingerprints identify
the local evidence records; they do not independently prove server origin,
billing, or production behavior.

| Local evidence record | SHA-256 |
| --- | --- |
| Request JSON | `9a4059ff7f0fcbf3ce12f7aa79166b38429e64c069c3c5164131e566f51e3c35` |
| Submitted request body | `e0f27f156b90cb00d4443eb5f1b604c76e1ea8028b13e22c29ec4c1e6cbb0b06` |
| Expected labels | `17a7a9ac43a950cd0395701b114c145a81855efe82ded56f9149e945ab0990eb` |
| Response JSON | `6448b6c80a5724612f269769984a46971c64fc99d8eb233069baf1bba10f9814` |
| Attempt record | `18768b13370f994e0d2145788db394b10f7b148f5bcd41658d7695977ad54dbb` |
| Task runner | `f61280430b1189e4c890fd4824a6d3d2f639763c5a7de27d49f7cc7ad5cb08be` |

The host-specific runner, raw records, credential metadata, and unexecuted
follow-up payload remain task evidence and are not product artifacts. Reusable
evaluation practices are deterministic expected labels, model/schema/usage
validation, bounded attempts, and independent scoring. This publication adds
only the reviewed findings and their provenance fingerprints.

## Limits and next experiment

One fixed-order batch with repeated evidence does not establish general Jev
accuracy, production performance, calibration, or the cause of the errors.
State size, case position, shared context, and option order remain hypotheses.
TypeSafe documents unrelated-state and option-order sensitivity among its
[known limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).

A focused follow-up would reuse the failed merge case with only its own
evidence and claim, preserving criteria and expected labels. That test was
prepared but not executed. It could isolate a context-selection hypothesis;
it would not by itself validate the existing AMW guard. Keep the guard off,
deterministic gates intact, and existing feature freezes in place pending
applicable validation.
