from __future__ import annotations

from app.schemas.optimizer import OptimizerState

#: Provenance recorded on every planner response. Candidate actions come
#: from the caller today: in production this adapter should merge the
#: governed tool manifest with dry-run pricing instead of echoing request
#: data, but until that feed exists the response says where the
#: candidates came from so no buyer mistakes this for discovery.
CALLER_SUPPLIED_SOURCE = "caller_supplied"


def get_candidate_actions(state: OptimizerState) -> list[dict]:
    raw = state.task_context.get("candidate_actions", [])
    if not isinstance(raw, list):
        return []
    # Accept only well-formed caller entries. Anything without an id
    # cannot be scored, budgeted, or reported on, so it is dropped
    # rather than guessed at.
    return [a for a in raw if isinstance(a, dict) and a.get("id")]
