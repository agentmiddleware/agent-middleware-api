# TypeSafe evaluation guidance

Reviewed 2026-10-03 against repository base
`bc6178768afa9bdf09245344f0fb83bcb21db20e`.
Status: contributor reference, **not a shipped integration or an approved feature**.
No TypeSafe SDK dependency or runtime call existed in the tracked repository at
that base. The installed coding-agent skill is guidance, not a connected model.

This applies the [TypeSafe documentation](https://docs.typesafe.ai/introduction)
to AMW's existing boundary. The [coverage record](typesafe-documentation-coverage.md)
lists all 111 indexed pages reviewed, plus three linked legal policies.
It does not certify vendor claims, benchmarks, or API behavior.

## Decision for this repository

Keep the [recorded Narrow decision](30-day-customer-validation.md#recorded-decision-narrow-2026-09-16)
and [proof-surface freeze](PROOF_SURFACES.md). This documentation request is not
permission to add a new core capability. A runtime proposal needs a named
prospect, one consequential tool, a workflow blocker, an owner, and a date.

Possible later evaluations are advisory classification of sanitized bug reports,
ranking evidence for a reviewer, or selecting an existing source span. Start
with a manual baseline. Do not introduce TypeSafe merely to replace an exact
comparison, parser, SQL query, or arithmetic operation. It is not a code/prose
generator or a replacement coding-agent model.
Sources: [building guide](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
and [coding agents](https://docs.typesafe.ai/introduction/coding-agents).

Model output must never become authority to execute a tool, accept a credential,
spend money, bypass a tenant check, or activate a dormant route. These existing
code owners stay deterministic:

| Boundary | Existing owner |
|---|---|
| API-key validation | [`APIKeyService.validate_key`](../app/services/api_key_service.py) |
| Wallet access | [`AuthContext.require_wallet_access`](../app/core/auth.py) |
| Permit action constraints | [`PermitService._validate_model_for_action`](../app/services/permits.py) |
| Wallet policy evaluation | [`evaluate_wallet_policy`](../app/services/policies.py) |
| Replay/conflict handling | [`_replay_from_record`](../app/services/idempotency.py) |
| Dispatch claiming | [`McpDispatchAttemptService.claim_dispatch`](../app/services/mcp_dispatch_attempts.py) |
| Ledger debit | [`BillingEngine.charge`](../app/services/billing_engine.py) |
| Receipt and signature verification | [`ReceiptService.verify_model`](../app/services/receipts.py), [`SigningKeyService.verify_payload`](../app/services/signing_keys.py) |
| Chained audit persistence | [`append_chained_audit_event`](../app/services/audit_chain.py) |

A signed record of a model judgment would prove which judgment was recorded,
not that the judgment was correct. Classification is not prompt-injection
protection; retrieved passages remain untrusted.
See [model limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13) and
[the RAG example's security boundary](https://docs.typesafe.ai/cookbooks/classifying_rag_passages).

## Request and answer contract

The [HTTP API](https://docs.typesafe.ai/api) accepts
`POST https://api.typesafe.ai/v1/systemone` with bearer authentication and
`state`, `model`, and a named `questions` map. Supply a minimal text/JSON state;
do not send internal objects wholesale. Question IDs identify answers for code;
write the complete question and relevant state field in `instructions`.

| Primitive | Use | Correct interpretation |
|---|---|---|
| [Choice](https://docs.typesafe.ai/primitives/choice) | One label from an explicit set | `choice` selects the highest probability; `confidence` is answer-level, not a second set of per-option probabilities. Include an unknown/no-match option. |
| [Score](https://docs.typesafe.ai/primitives/score) | One ordered, descriptive dimension | `criteria` is an array of 2–10 independently meaningful levels. `score` is the expected zero-based index, possibly fractional, not a probability or exact measured amount. |
| [Noul](https://docs.typesafe.ai/primitives/noul) | A precisely defined yes/no condition | `noul` is the model's yes probability; near 0.5 is uncertainty, not medium severity. There is no separate `confidence` field. |

Independent questions sharing state belong in one request. Ignore irrelevant
speculative answers in code. Make a second request only when earlier output
actually determines new state or candidates. For composite ranking, normalize
each Score by `len(criteria) - 1` before applying explicit code-owned weights.
Batching is a pattern to evaluate, not a promised AMW latency or cost reduction.
Sources: [fan-out](https://docs.typesafe.ai/patterns/fan-out),
[composite scoring](https://docs.typesafe.ai/patterns/composite-scoring), and
[question dependencies](https://docs.typesafe.ai/primitives#when-one-question-depends-on-another).

### Synthetic request shape, not an executed example

This fictional report contains no customer information. No response or accuracy
result is implied. Model version is pinned to the documented version reviewed;
recheck availability and retest before any later authorized experiment.

```json
{
  "model": "jev-1.13.0",
  "state": {
    "report": "In the local demo, I clicked Verify twice. The second result differed. I did not save the output."
  },
  "questions": {
    "report_kind": {
      "type": "choice",
      "instructions": "What does the supplied report describe?",
      "criteria": {
        "unexpected_behavior": "A result differed from what the reporter expected.",
        "usage_question": "The reporter asks how to use an existing feature.",
        "unknown": "The report is unclear or fits neither description."
      }
    },
    "reproduction_detail": {
      "type": "score",
      "instructions": "How much reproduction detail is stated in the report?",
      "criteria": [
        "No action or environment is identified.",
        "An action is identified but the environment is unspecified.",
        "An action and environment are identified."
      ]
    },
    "output_saved": {
      "type": "noul",
      "instructions": "Does the report explicitly say the observed output was saved?"
    }
  }
}
```

A model classification here could help a human sort reports. It cannot establish
that the verifier is defective; reproduce the report with deterministic tests.

## Uncertainty and validation

[Confidence](https://docs.typesafe.ai/confidence) summarizes a distribution; it
is not proof of correctness. Do not copy cookbook thresholds into AMW. Choose
thresholds on labeled, held-out cases for a specific model and question set.
Preserve probabilities, abstentions, rubric version, and resolved model in
evaluation results. Changing option count, wording, ordering, or model requires
reevaluation. Same-answer repeatability is not accuracy.

Before using any answer, check all requested IDs and expected types, allowed
labels/levels, finite numeric ranges, and distributions. Missing required
input, absent answers, unknown answer types, malformed JSON, provider errors,
or an expired deadline must produce an unavailable/review outcome, never an
implicit pass. Validate schemas and required fields **before** semantic checks.
Keep dates, money, counts, identifiers, permissions, and equality in code.

Do not adopt the [confidence-routing banking example](https://docs.typesafe.ai/patterns/confidence-routing)
as an authorization design: a high-confidence intent still needs the actual
authenticated principal, permit, policy, and any required human approval.

## SDK and data-handling choices for a future approved evaluation

Python is the natural candidate for AMW, not an added dependency in this change.
Use the asynchronous client in asynchronous code, with explicit lifecycle
ownership. Do not let caller data choose a base URL, model, request extensions,
or credentials.

| Documented behavior | Python | JavaScript/TypeScript |
|---|---|---|
| Package and method | `typesafe-sdk`, `AsyncTypeSafeClient.system_one` | `@typesafe-ai/sdk`, `TypeSafeClient.systemOne` |
| Default retries | Two after the initial attempt | Two after the initial attempt |
| Timeout distinction | 10-second HTTP-operation timeout; `RetryPolicy.timeout` documents a 30-second total retry budget | 10-second per-attempt timeout; no built-in total retry budget documented |
| Required application control | Explicit outer deadline, retry/spend cap, cancellation, complete answer validation | Explicit outer deadline, retry/spend cap, cancellation, complete answer validation |

These are documentation defaults, not measured wall-clock guarantees. For an
initial budgeted experiment, disable retries unless its approved budget includes
them. Python `TypeSafeAPIError` alone does not catch connection/timeouts; handle
the documented transport failures as well. Python `extra_body` can override
core request fields; build an allowlisted request instead. Token usage can be
absent and does not establish total cost across retries.
Sources: [Python usage](https://docs.typesafe.ai/sdk/python/usage),
[retry reference](https://docs.typesafe.ai/sdk/python/api/retries),
[exceptions](https://docs.typesafe.ai/sdk/python/api/exceptions),
[async client](https://docs.typesafe.ai/sdk/python/api/clients/async),
[response types](https://docs.typesafe.ai/sdk/python/api/types/responses), and
[JavaScript client](https://docs.typesafe.ai/sdk/javascript/api/classes/TypeSafeClient).

Keep `TYPESAFE_API_KEY` server-side and obtain it through the established secure
credential workflow. Never place it in examples, browser code, commits, or chat.
Both SDKs document header redaction but not request/response-body redaction in
debug logs. Keep body logging off; use synthetic/public, explicitly reviewed
inputs until a separate data-transfer review is complete.

The vendor's no-training statement is not a zero-retention agreement. Verify
retention, subprocessors, transfer terms, and any applicable license restrictions
before sending customer material. This guide makes no legal/compliance approval.
Sources: [models and data handling](https://docs.typesafe.ai/models),
[legal overview](https://docs.typesafe.ai/legal), and its linked policies in the
coverage record.

## Findings from the examples

- The [SDE cascade](https://docs.typesafe.ai/cookbooks/sde_cascade) generates
  field checks by iterating the extracted record. Missing required fields are
  therefore not checked, and its escalation gate excludes the overall question.
  An empty extraction can avoid escalation. A local in-memory helper check with
  a stubbed model class reproduced this; it was not an API or accuracy test.
  Do not copy that gate.
- The [structure-recovery example](https://docs.typesafe.ai/cookbooks/autoformat)
  disagrees with itself on price and equates confidence with winning probability.
  Use the canonical API/confidence contract; obtain fresh pricing before spend.
- The [self-consistency example](https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook)
  trades coverage for repeatability; the
  [skill-suggestion pipeline](https://docs.typesafe.ai/cookbooks/skill_suggestion)
  also introduces errors on previously correct cases. Neither is an AMW result.

## Acceptance gates before runtime adoption

1. Record the named customer's workflow blocker and compare a manual/rule-based
   baseline. If exact code solves it, stop the model proposal.
2. Define a small labeled evaluation with absent/contradictory evidence,
   no-match cases, option-order changes, and benign quoted instruction-like
   text. Test missing/malformed responses, out-of-range values, wrong IDs/types,
   timeouts, and exhausted retries without network access first.
3. Separately authorize any paid synthetic API run and its maximum requests,
   attempts, tokens, wall-clock time, and spend. Do not send private logs or
   customer records under this documentation request.
4. Report held-out precision/recall, abstention and automatic coverage,
   calibration, latency, attempts, and actual cost separately. Tune on a
   development set, not the held-out set. Reject a model that adds cost or
   risk without measured customer benefit.
5. Review the narrow diff and negative-path tests. Keep existing authorization,
   billing, idempotency, signature, and release gates unchanged.

No SDK runtime, live inference, production deployment, or customer-value claim
has been validated by this documentation-only change.
