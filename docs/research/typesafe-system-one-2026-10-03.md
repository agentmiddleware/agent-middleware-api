# TypeSafe System One — consumed reference and application map

Date: 2026-10-03. Status: research record, not a product decision.

This file records what the TypeSafe documentation says, in enough detail to
build against it without network access, and where (if anywhere) it fits this
repository. It changes no product behavior. Read
[`AGENTS.md`](../../AGENTS.md) first: the customer-validation invariant and the
proof-surface freeze decide whether anything below is ever implemented.

## Provenance

The documentation site `docs.typesafe.ai` was unreachable from the session
that wrote this (egress policy), so the material was taken from sources that
mirror it:

| Source | Version | What it supplied |
|---|---|---|
| `typesafe-sdk` on PyPI | 0.7.2 | Python client, question/answer types, generated wire schema from `https://api.typesafe.ai/openapi.json`, retry policy, errors |
| `@typesafe-ai/sdk` on npm | 0.6.0 | JavaScript client and type declarations (same API contract) |
| `typesafe-ai/skills` on GitHub (MIT) | main | The agent skill: programming model, design rules, pattern catalogue |
| SDK repository READMEs | main | Quickstarts |

Anything the SDKs do not encode (cookbook thresholds, worked examples, model
cards beyond the alias) is marked "not verified" below. Do not invent it.
Also note: the PyPI name `typesafe` is an unrelated 2010-era library, and
`typesafe-ai` is a defensive redirect shim. The real package is `typesafe-sdk`.

## 1. Programming model

TypeSafe sells **System One models**. The first and flagship is **Jev**
(alias `jev-latest`). A System One model does not generate text or reasoning.
It reads natural-language or JSON **state** and answers named **questions**
with **typed values and probabilities**. Code owns the workflow; the model
supplies a bounded semantic judgment where ordinary code cannot.

The design rules the skill states, condensed:

- Start from the behavior the application needs (show, select, change, hand
  off) and work backward to the judgments. Keep rules, calculations, exact
  lookups, and execution in code.
- Ask one narrow, coherent judgment per question. Split independently useful
  dimensions; do not split a relationship that must be judged as a whole.
- Give each question enough state: source text, identities, relationships,
  policies, current facts. Prefer named JSON fields. Reference nested state
  with backticked paths such as `` `ticket.messages[0].text` ``.
- Put the judgment in `instructions`; define the possible answers in
  `criteria`. Question names are for code and are **not sent to the model**,
  so the question text must carry its full meaning.
- Include a no-match outcome when nothing may fit. For source-value selection,
  the model cannot pick a value that was not offered as a candidate.
- Independent questions over the same state go in **one request**; they run in
  parallel and cannot see each other's answers. Speculative questions are
  fine; state their premise explicitly and let code consume only the
  applicable answers. A second request is warranted only when an answer is
  needed to fetch evidence or construct new state.
- Keep policy explicit and raw judgments reusable. Changing a weight or a
  display threshold must not require re-running inference.
- Typed output guarantees the interface, not the truth. Validate on the
  target domain; cookbook thresholds are examples, not rules.
- Keep API credentials server-side.

Pattern catalogue the skill offers (each names a cookbook on the docs site;
cookbooks not read, not verified): route and fill known arguments; select
instead of generate; find and judge evidence (rerank, hierarchical
classification); turn judgments into reusable data (composite scoring,
feature discovery); verify and escalate (citation checks, extraction
cascades); respond to changing state.

## 2. Primitives

| Primitive | Wire `type` | Answer | Meaning |
|---|---|---|---|
| Choice | `choice` | `choice` (label), `confidence` (0–1), `probabilities` (per label, sum ≈ 1) | One of a defined set. The distribution compares competing options. |
| Noul | `noul` | `noul` (0–1) | Probability that a condition holds. **No separate confidence**: a value near 0.5 means yes and no are similarly likely, not "medium intensity". Use one Noul per label when several labels may apply at once. |
| Score | `score` | `score` (expected value, may fall between levels), `confidence`, `legend`, `probabilities` (per level) | Degree along an ordered rubric. Levels are indexed from zero by position in `criteria`. Each level must describe a concrete situation and stand on its own. |

Request-side shapes (from the generated wire schema):

- `instructions`: string, JSON object, JSON array, or null. Optional for all
  three primitives.
- Choice `criteria`: object mapping label → description (string, object,
  array, or null). A null description means "interpreted by its name alone".
- Noul `criteria`: optional `{ "true": …, "false": … }` describing the yes
  and no outcomes.
- Score `criteria`: ordered non-empty array of level descriptions. The JS SDK
  requires at least two levels; the Python SDK requires at least one; the
  server schema says `min_length=1`.

Confidence semantics: Choice and Score `confidence` summarize how concentrated
the distribution is. It is not overall workflow correctness and not permission
to act. Several acceptable alternatives can spread probability without the
answer being wrong. Ignore uncertainty on branches code does not use.

## 3. HTTP API contract

| Item | Value |
|---|---|
| Base URL | `https://api.typesafe.ai` (override `TYPESAFE_BASE_URL`) |
| Auth | `Authorization: Bearer <api key>` (env `TYPESAFE_API_KEY`) |
| Judgments | `POST /v1/systemone` |
| Models | `GET /v1/models` → `{ "models": [ { "name", "description", "release_date" } ] }` |
| Default model | `jev-latest` (override `TYPESAFE_DEFAULT_MODEL`) |
| Request id | response header `x-typesafe-request-id` |
| Rate limiting | 429 with `retry-after` or `retry-after-ms` |
| Validation errors | 422 with FastAPI-style `detail: [{ loc, msg, type, input, ctx }]` |

Request body:

```json
{
  "state": "text, or a JSON object, or a JSON array",
  "model": "jev-latest",
  "questions": {
    "billing": { "type": "noul", "instructions": "Is this message about billing?" },
    "tone": { "type": "choice", "instructions": "What is the tone?",
              "criteria": { "calm": null, "angry": "An upset or hostile message" } },
    "urgency": { "type": "score", "instructions": "How urgent is this message?",
                 "criteria": ["Can wait", "Needs attention this week", "Needs attention today"] }
  }
}
```

Response body:

```json
{
  "model": "jev-latest",
  "answers": {
    "billing": { "type": "noul", "noul": 0.98 },
    "tone":    { "type": "choice", "choice": "angry", "confidence": 0.9,
                 "probabilities": { "angry": 0.8, "calm": 0.2 } },
    "urgency": { "type": "score", "score": 1.7, "confidence": 0.9,
                 "legend": { "0": "Can wait", "1": "Needs attention this week", "2": "Needs attention today" },
                 "probabilities": { "0": 0.1, "1": 0.1, "2": 0.8 } }
  },
  "usage": { "input_tokens": 120, "output_tokens": 12 }
}
```

`model` in the response may differ from the alias sent. Input tokens are
billable; the schema says output tokens are currently free. Price per token:
not verified.

## 4. SDK usage

Python (`pip install typesafe-sdk`, Python ≥ 3.10; depends on `httpx2`,
`pydantic ≥ 2.12`, `tenacity`):

```python
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score, RetryPolicy

async with AsyncTypeSafeClient(timeout=10.0, retry=RetryPolicy(max_retries=2)) as client:
    result = await client.system_one(
        state={"ticket": {"subject": "Duplicate charge", "body": "I was charged twice."}},
        questions={
            "billing": Noul(instructions="Is `ticket` about billing?"),
            "route": Choice(
                instructions="Which team should handle `ticket`?",
                criteria={"billing": None, "technical": None, "none_of_these": "No listed team fits"},
            ),
        },
    )
    result.nouls["billing"].noul          # float 0–1
    result.choices["route"].choice        # label
    result.choices["route"].probabilities # dict[label, float]
```

`TypeSafeClient` is the synchronous twin. Questions may also be passed as
plain dicts with a `type` key. `response_model=` accepts a custom Pydantic
model for the response body. Errors: `TypeSafeAPIError` subclasses by status
(400, 401, 403, 404, 422, 429 with `retry_after_ms`, 5xx),
`TypeSafeAPIConnectionError`, `TypeSafeAPITimeoutError`,
`TypeSafeAPIResponseValidationError` (names the first bad field path).
Default retry: 2 retries, 0.5 s initial backoff doubling to 5 s with 25 %
jitter, on 408, 429, 5xx, connection errors, and timeouts; honors
`Retry-After`. Default per-attempt timeout 10 s. The SDK logger is
`typesafe_sdk`; credential headers are redacted, bodies are not.

JavaScript (`npm install @typesafe-ai/sdk`, Node ≥ 20):

```ts
import { TypeSafeClient, choice, noul, score } from "@typesafe-ai/sdk";
const client = new TypeSafeClient();            // reads TYPESAFE_API_KEY
const { answers } = await client.systemOne({
  state: { document: text },
  questions: { route: choice("Which handler?", { a: null, b: null, none: "Nothing fits" }) },
});
answers.route.choice;                           // typed from the criteria keys
```

Answer types are inferred from the question literals. Browser use is refused
unless `dangerouslyAllowBrowser` is set, because it exposes the key.

## 5. Where it fits this repository

The product wedge is **deterministic**: scoped permit, at-most-one gateway
dispatch and debit per accepted idempotency key, signed receipt. None of the
core loop (`discover → authenticate → authorize → invoke → meter → receipt →
audit → govern`) needs a semantic judgment, and inserting a probabilistic
step into authorization, metering, or receipting would weaken the claim the
product makes. **TypeSafe does not belong in the core loop.**

Where semantic judgments already exist, they are prompt-and-parse calls on
frozen proof surfaces:

| Site | Today | Fit | Action |
|---|---|---|---|
| `AgentIntelligence.decide` (`app/services/agent_intelligence.py`) | Generative chat prompt asks for `reasoning`, `action`, `confidence`; `json.loads` on free text; fallback takes the first line as the action | **Exact fit for Choice.** `options` is a closed set; add a `none_of_these` label; the model's `confidence` and `probabilities` replace the self-reported 0–1 number the parser hopes for | Frozen proof surface. Do not change without an unfreeze decision. |
| `AgentIntelligence.diagnose_and_heal`, `.query`, `.learn` | Generative explanations and summaries | Not a judgment; output is prose | None. |
| `content_factory_generation.generate_text` | Generative text via `/chat/completions` | Not a judgment | None. |
| `app/services/llm.py` | Multi-provider chat client (OpenAI-compatible) with a mock when `LLM_API_KEY` is unset | A System One request is not a chat completion; a `typesafe` value for `LLM_PROVIDER` would be the wrong shape | Would need a separate, tiny adapter, not a provider branch. |

Candidate judgments on the **supported** surface, none of which may be built
without the evidence `AGENTS.md` requires (one named prospect, one
consequential tool, a documented workflow blocker, an owner and date):

1. **Human-approval triage.** When a `REQUIRE_APPROVAL` policy fires
   (`docs/human-approval-gate.md`), a Noul "do `arguments` match the stated
   `intent` for `tool`?" plus a Score of blast radius could order the
   approver's queue. The judgment never approves; it ranks. The permit is
   still minted only by the human-bound path.
2. **Denial remediation routing.** `authority_required` envelopes
   (`docs/authority-required-flow.md`) carry a fixed remediation type chosen
   by code. A Choice over the remediation set would only matter if the set
   grows beyond what rules decide, which it has not.
3. **Partner intake.** Pilot inquiries arrive by email; a Choice over the
   intake questions in `site/build_site.py` (`PILOT_EMAIL_BODY`) could
   pre-fill a triage sheet. This is an internal operations tool, not product.

If one of these is unfrozen, the shape that respects the repository's rules is
a single `judgments` service wrapping `AsyncTypeSafeClient` behind a feature
flag that production-like environments refuse (same pattern as
`ENABLE_DEV_KEY_SELF_PROVISION`), with the raw answers persisted next to the
decision they informed so the audit chain records the evidence, and with
tests for the no-match label, a low-confidence answer, a 429, and a timeout.
Add `typesafe-sdk` only at that point; it pulls `httpx2`, which this
repository does not use.

## 6. What this record does not establish

- No cookbook, pricing, rate-limit, or model-card page was read.
- No request was sent to `api.typesafe.ai`; the contract above is the
  SDK-encoded OpenAPI schema, not observed behavior.
- This reference-only session performed no accuracy evaluation. A later
  [independently reviewed synthetic QA checkpoint](jev-advisory-checkpoint-2026-10-03.md)
  records observed results and limitations; it does not validate AMW behavior
  or authorize a product integration.
