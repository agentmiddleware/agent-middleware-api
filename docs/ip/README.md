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
| [`07-provisional-specification.md`](07-provisional-specification.md) | `03-` and `05-` assembled into one continuous §112(a) written description, in filing order. A draft to edit, **not** a filing — see its header for the four things counsel must do before it can be filed. | Counsel |

## The short version

Four mechanisms in this repo look defensible, and they are **not** the ones a
generic "AI agent authorization" pitch would lead with:

1. **Atomic budget reservation** — a single guarded conditional `UPDATE` that
   enforces a permit's spend cap at the row level, remaining correct on engines
   where advisory row locks are a silent no-op
   (`app/services/permits.py:426`, and the upstream dispatch path at
   `app/services/mcp_dispatch_attempts.py:463`).
2. **Exactly-once debit across a crash** — a charge checkpoint written before
   finalization, plus a reconciler that can tell "never charged" from "charged,
   then finalization crashed" and repair each differently
   (`app/services/idempotency.py:379`, `:408`).
3. **Signature-stable receipt evolution** — additive fields are signed only when
   present, so schema growth does not invalidate historical signatures, with a
   fail-closed legacy fallback (`app/services/receipts.py:312`, `:558`).
4. **Offline verification with a status taxonomy** — every reported claim value
   is read from the signed bytes rather than the envelope, and a key the
   verifier does not hold resolves to `UNKNOWN_KEY` rather than to a tampering
   verdict, so a key-distribution problem is never read as fraud
   (`b2a_sdk/src/b2a_sdk/receipt_verifier.py`). Note the verifier performs no
   key retrieval and so cannot itself observe a fetch outage; see §4.6 of the
   disclosure for the precise boundary.

The authorization half of the system — scoped, expiring, signed permits for
agent tool calls — is where the closest prior art lives, and is the weakest
place to anchor a claim. See
[`02-prior-art-landscape.md`](02-prior-art-landscape.md).

## What changed after the 2026-08 research pass

The list above is ordered as originally drafted. **It is no longer the order of
strength.** PRs #285 and #288 added verified, primary-source research to the
repository — `docs/market-research-2026-08.md` and new rows in
`docs/related-work.md` — and changed no file in `docs/ip/`. Folding it in
(§§5–7 of `02-`) moved things:

- **The settlement mechanisms held.** Exactly-once debit across a crash (2) is
  now the strongest: nothing in the new art classifies a crashed record the way
  the reconciler does.
- **The evidence mechanisms weakened.** Offline-verifiable Ed25519 receipts at a
  network boundary are occupied — protect-mcp emits receipts verifiable without
  calling the issuer, and its author has an Internet-Draft,
  `draft-farley-acta-signed-receipts`, whose `-02` adds a `spending_authority`
  receipt type. What survives of (4) is the **status taxonomy** specifically:
  that a key the verifier does not hold resolves to `UNKNOWN_KEY` rather than to
  a tampering verdict.
- **Mechanism 1 has a named general technique**: optimistic concurrency control
  (Kung & Robinson, 1981). Draft it around the classification of the zero-row
  outcome, not around the conditional `UPDATE`.

Read [`02-prior-art-landscape.md`](02-prior-art-landscape.md) §§5–7 before
relying on the ordering above, and
[`06-ids-candidates.md`](06-ids-candidates.md) §§C.1–C.2 for what that research
added to the disclosure list.
