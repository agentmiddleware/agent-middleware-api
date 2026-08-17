# Design-Partner Interview Script

**Purpose:** answer the one question research cannot —
[`market-research-2026-08.md`](market-research-2026-08.md) §7 question 4's
remainder: does anyone *pay* for charge-once semantics, or does everyone patch
their own tool layer and move on?

**Posture:** this is a discovery interview, not a pitch. The rules below exist
because a founder-led interview drifts toward selling within minutes, and a
sold prospect tells you what you want to hear. `ELEVATOR_PITCH.md` already
commits us: *"Existing IAM, gateway, or logging controls may already be
sufficient; the first conversation must establish that they are not before
this product is proposed."* This script is that commitment made operational.

## Rules (read before every call)

1. **Past tense only.** Ask what happened, never "would you use…". A yes to a
   hypothetical is worth nothing; a story about last March is evidence.
2. **The product does not exist until the reveal (§4, ~minute 25).** If
   asked earlier, say "we're researching how teams handle agent tool-call
   failures — I'll show you what we're building at the end if you want."
3. **Chase money and named people, not opinions.** "Who noticed?" and "what
   did it cost?" beat "was it bad?"
4. **Disqualify eagerly.** A clean "this isn't a problem for us" is a
   successful interview. Record it with the same care as an enthusiastic one.
5. **Never supply the vocabulary.** Do not say idempotency, receipt,
   exactly-once, or audit until they do. Note verbatim which words *they*
   reach for — that's the landing-page copy. §4 (the reveal) is the **only**
   section where product vocabulary is permitted, and only after §1–3 are
   done.

## Who to interview

The qualifying shape from `ELEVATOR_PITCH.md`: platform/AI-infrastructure/
security teams already running agents against internal tools where **one tool
call costs real money or causes a real side effect** (payments, ticketing,
provisioning, trades, outbound email). Framework users are the richest pool —
the documented gaps are in LangGraph and CrewAI specifically
(`langchain-ai/langgraph#7417`, `crewAIInc/crewAI#5802`).

Screen out (politely, early): teams whose agent tools are read-only or
idempotent by construction; teams that want an all-tools governance platform
(wrong product); anyone shopping for compliance certifications (send them to
the audit-layer vendors named on `/compare/`).

---

## The script

### 0. Framing (2 min)

> "Thanks for the time. I'm researching how teams run AI agents against tools
> that have real side effects — payments, tickets, emails, infrastructure.
> I'm not going to pitch you anything for the next 25 minutes; I want to hear
> what's actually happened in your stack. Some of it may be embarrassing —
> that's the useful part."

### 1. The incident question (10 min — this is the interview)

Open broad, so a story that doesn't fit our shape still gets told:

> **"Tell me about the last time an agent tool call failed, timed out, or
> got retried."**

Let them finish. Then, if the story didn't already cover it, the pointed
probe:

> **"Has an agent ever retried something expensive — and either double-did it,
> or left you unable to prove afterward what actually ran?"**

If yes to either, excavate the story completely before moving on:

- When? Which framework/orchestrator? Which tool fired twice?
- How did you *find out*? (Alerting? A customer? Reconciliation? Luck?)
- What did it cost — money, hours, trust? Who outside engineering heard
  about it?
- What was the ambiguous moment — did you know the call was in flight, or did
  the platform re-dispatch behind your back?
  *(Listening for the `delivery_uncertain` shape: langgraph#7417 is exactly
  this — the platform silently re-ran calls users believed were still
  running. If their story rhymes, note it, don't lead them to it.)*
- What did you change afterward? Show me, roughly — decorator? Redis dedup?
  Manual runbook?

If no, probe once, gently, then believe them:

> "How would you know if it had happened? Walk me through what your logs
> would show for a call that timed out and got retried."

*(A team that cannot answer this may have the problem invisibly — the
practitioner quote from the CrewAI thread was "two tickets, two emails, two
rows, and nothing in the transcript says so." Note whether their answer is
confident or uncomfortable. Do not quote the thread at them.)*

### 2. The current-mitigation question (7 min)

Whatever they built, take it seriously — it is the real competitor. Refer to
it in *their* words from §1 (rule 5 still applies here — if they called it
"the dedup thing," so do you):

- "That safeguard you built at the tool layer — how long did that take?
  Who maintains it? Does it survive a worker restart / a second process?"
- "Have you had to prove to anyone *outside* the team what an agent did and
  what it cost? Who asked? What did you show them? Did they accept it?"
  *(This is the build-vs-buy fork from `/compare/`: an in-process cache is a
  reliability fix; the moment a finance owner, auditor, or customer needs to
  check the record, evidence becomes the product. If nobody outside eng ever
  asks, our wedge may not apply to them — record that honestly.)*
- "What does a tool-call record look like in your system today? Could someone
  alter it after the fact? Does that matter to anyone you answer to?"

### 3. The money questions (5 min — only if §1 surfaced a real incident)

Still past tense. Budgets reveal more than intentions.

- "After the incident, did anyone propose buying something instead of
  building? What happened to that conversation?"
- "What have you already paid for in this general area — observability,
  gateways, audit tooling? Roughly what does that cost you a year?"
- "The last tool you bought in this space — who approved it, whose budget
  did it come out of, and what did procurement put you through?"
  *(This is the buyer question. Adjacent-category spend without a named
  approver and budget is not evidence anyone can buy; record all three.)*
- "Has the fix you built ever broken, or needed a rewrite? What did you
  actually do — rebuild it, or go looking for a vendor?"

**Do not ask "would you pay for X?"** The affirmative answer is worthless and
contaminates the rest of the interview.

### 4. Reveal and test (5 min — optional, only if §1–3 qualified them)

Now, and only now, one paragraph — the debit-first pitch, no superlatives
(the never-claim list in `WEDGE.md` applies verbatim in conversation):

> "What we're building is a gateway you put in front of *one* tool like that.
> One accepted request key permits at most one dispatch and at most one
> debit from an internal budget, no matter how many times the agent retries —
> and every terminal outcome, including denials and failures, gets a signed
> receipt someone can verify without trusting us or you."

Then stop talking. The reactions worth recording:

- Do they map it onto the incident from §1 unprompted?
- Do they object with the *right* objections ("what about the upstream
  tool's own side effect?" — the honest answer is in `ELEVATOR_PITCH.md`)?
- The commitment test — ask for something that costs them, and make it
  observable *on the call*, not aspirational:
  > "We take one design partner at a time: one real tool, one engineer, a
  > staging environment. If retrying deliberately and verifying the receipt
  > in *your* environment doesn't make you want it in prod, we part friends.
  > Who on your team would own that — and can we put their afternoon on the
  > calendar before we hang up?"

  A pass requires all three: a **named engineer**, a **named staging
  environment**, and a **scheduled date** (or a concrete scheduling step
  taken on the call). "Sounds cool, keep me posted" — or a yes with no name
  and no date — is a no; write it down as a no.

### 5. Close (1 min)

> "Last one: who else do you know who's been bitten by this?" *(Referral =
> the problem is talked about; silence = it may be too niche to spread.)*

---

## Scoring — fill in within one hour of the call

| Field | Answer |
|---|---|
| Incident in past tense? (yes / no / **unknown** — couldn't tell from their logs story) | |
| Discovery mechanism (how they found out) | |
| `delivery_uncertain` shape present? | |
| Anyone outside eng needed the record? Who? | |
| Current mitigation, and its owner | |
| Prior spend in the category | |
| Buyer evidence (last approver, budget owner, procurement path) | |
| Their words for the problem (verbatim) | |
| Commitment test: engineer named | |
| Commitment test: staging env named | |
| Commitment test: date scheduled | |
| Disqualified at screening? Why? | |

An interview counts toward the denominator only if it passed screening and
ran through §2 — call that number **qualified_n**. Screen-outs are recorded
but never counted. "Unknown" incident answers count as neither yes nor no.

## Decision rule

Set **before** the interviews, so the results can't be argued with after.
All counts are over **qualified_n = 5** completed, qualified interviews —
keep interviewing until there are five; do not decide on fewer.

- **3+ of 5** surface a past-tense incident **and** **2+ of 5** pass the
  full commitment test (engineer + staging + date) → proceed to a paid-pilot
  conversation with the strongest one. A paid-pilot *conversation* — the
  commitment test proves an engineer's afternoon, not a budget; the pilot
  conversation is where the §3 buyer evidence (approver, budget, procurement)
  gets tested for real.
- Incidents at 3+ but **zero or one** commitments → the problem is real and
  the build-it-yourself answer is winning; revisit whether the wedge is
  evidence (sell to whoever outside eng asks for the record) rather than
  reliability.
- **No past-tense incidents in 5** → stripe/ai#402 and the framework issues
  are ahead of the market; pause the sales motion, keep the gateway as the
  proof asset, and re-interview in a quarter.
- **Any other pattern** — 1–2 incidents, a pile of unknowns, commitments
  without incidents — is not a decision, it's noise. Default action for
  every case not listed above: run five more qualified interviews before
  deciding anything.

What this script must never do: rescue a failing interview with the LangGraph
citation. The evidence in §2 of the research doc is for *us* — to know the
problem is real — and for a qualified prospect who asks "has this happened to
anyone?" It is not a crowbar for manufacturing pain in someone who doesn't
have it.
