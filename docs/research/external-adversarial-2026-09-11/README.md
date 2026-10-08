# External diagnostic archive — 2026-09-11/12

This is a historical, non-gating record. The archived `gauntlet.py` counters
flag errors, server failures and selected text markers; they do not compare
each response with its expected status. In particular, an unauthenticated 200
can produce zero flags. Zero printed findings must not be treated as a passing
auth-boundary test or evidence that no bypass occurred.

The reported external run dates were 2026-09-11/12. `RESULTS.txt` is a
2026-09-14 regeneration of the same harness; the original output was not
retained. The four recorded battery summaries contain 26, 21, 10 and 200
experiments. The swarm summary includes three 503 responses and one timeout.
These are historical diagnostic observations, not current runtime acceptance.
RESULTS.txt is preserved as regenerated on 2026-09-14; the original 2026-09-11/12
output was not retained, so this record cannot be re-run or cited as current.

The harness and its network transport now refuse execution. Its fixed
production target is not authorization to repeat probes. For supported local
checks, use [the security review kit](../../security-review-kit.md) and
[the proof matrix](../../PROOF_MATRIX.md). Any future probe implementation
requires explicit target authorization and per-case expected statuses before
it can be used as a gate.
