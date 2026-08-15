# Patent prosecution package — governed MCP trust plane

Working files for a US patent filing covering the trust-plane mechanisms in
this repository. Prepared 2026-08-15.

**These are drafting inputs for a registered patent attorney or agent, not
legal advice and not a filing.** Claim scope, inventorship declarations, and
the duty of disclosure under 37 CFR 1.56 are all counsel's calls. Nothing here
should be filed as-is.

## Read in this order

| File | What it is | Who needs it |
| --- | --- | --- |
| [`01-filing-risks-and-actions.md`](01-filing-risks-and-actions.md) | Four issues that affect whether you can file at all, and in which jurisdictions. **Read before anything else.** | You, this week |
| [`02-prior-art-landscape.md`](02-prior-art-landscape.md) | Closest art, with an honest read on what it forecloses | Counsel |
| [`03-invention-disclosure.md`](03-invention-disclosure.md) | Technical spec, traced to the implementing code | Counsel |
| [`04-claim-sets.md`](04-claim-sets.md) | Three independent claims plus dependents | Counsel |
| [`05-abstract-and-figures.md`](05-abstract-and-figures.md) | Abstract and figure descriptions | Counsel / draftsperson |
| [`06-ids-candidates.md`](06-ids-candidates.md) | References to disclose under 37 CFR 1.97 | Counsel |

## The short version

Four mechanisms in this repo look defensible, and they are **not** the ones a
generic "AI agent authorization" pitch would lead with:

1. **Atomic budget reservation** — a single guarded conditional `UPDATE` that
   enforces a permit's spend cap at the row level, remaining correct on engines
   where advisory row locks are a silent no-op
   (`app/services/permits.py:426`).
2. **Exactly-once debit across a crash** — a charge checkpoint written before
   finalization, plus a reconciler that can tell "never charged" from "charged,
   then finalization crashed" and repair each differently
   (`app/services/idempotency.py:379`, `:408`).
3. **Signature-stable receipt evolution** — additive fields are signed only when
   present, so schema growth does not invalidate historical signatures, with a
   fail-closed legacy fallback (`app/services/receipts.py:312`, `:558`).
4. **Offline verification with a status taxonomy** — every reported field is
   read from the signed bytes rather than the envelope, and an unreachable key
   set is reported differently from a bad signature, so an outage is never read
   as fraud (`b2a_sdk/src/b2a_sdk/receipt_verifier.py`).

The authorization half of the system — scoped, expiring, signed permits for
agent tool calls — is where the closest prior art lives, and is the weakest
place to anchor a claim. See
[`02-prior-art-landscape.md`](02-prior-art-landscape.md).
