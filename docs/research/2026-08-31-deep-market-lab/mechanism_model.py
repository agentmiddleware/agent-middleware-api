"""Finite explanatory model, NOT an application test or implementation proof.

Run from any directory: python3 /absolute/path/to/mechanism_model.py
Uses only the Python standard library, writes mechanism-model-results.json.
One identity, two competing activations, at most two upstream effects per send.
Atomic persistence, identity/payload binding, trusted admission, and continuous
database history are premises encoded by transitions, not properties tested here.
"""

from collections import deque
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path


TERMINAL = {"success", "error", "uncertain", "rejected"}


@dataclass(frozen=True)
class State:
    phase: str = "empty"
    debits: int = 0
    refunds: int = 0
    reserved: bool = False
    owner: int = -1
    right: str = "none"
    alive: tuple = (True, True)
    sends: int = 0
    effects: int = 0
    receipt: bool = False


def successors(s):
    # Replay, payload drift and losing claims have no state-changing transition.
    yield "exact_replay_no_new_execution", s
    yield "changed_payload_rejected", s
    for worker in range(2):
        if s.alive[worker]:
            alive = list(s.alive)
            alive[worker] = False
            right = "lost" if s.owner == worker else s.right
            yield f"worker_{worker}_dies", replace(s, alive=tuple(alive), right=right)
    if s.phase == "empty":
        yield (
            "authorized_reserve_prepare_atomic",
            replace(s, phase="prepared", reserved=True),
        )
    if s.phase == "prepared":
        if s.debits == 0:
            yield "debit_atomic", replace(s, debits=1)
        yield "fenced_pre_dispatch_failure", replace(s, phase="error")
        if s.debits == 1:
            for worker in range(2):
                if s.alive[worker]:
                    for right in ("ready", "ack_lost"):
                        yield (
                            f"worker_{worker}_claims_{right}",
                            replace(s, phase="claimed", owner=worker, right=right),
                        )
    if s.phase == "claimed" and s.right == "ack_lost" and s.alive[s.owner]:
        yield "same_live_owner_recovers_commit_ack", replace(s, right="ready")
    if s.right == "ready" and s.alive[s.owner]:
        # A paused owner may resume after an uncertainty receipt. This does not
        # create a second claim/send; uncertainty is not proof of quiescence.
        yield "owner_sends_once", replace(s, sends=s.sends + 1, right="spent")
    if s.sends and s.effects < 2:
        # The gateway does not constrain how many business effects one tool
        # performs, or whether a previously dispatched effect completes late.
        yield "upstream_commits_effect", replace(s, effects=s.effects + 1)
    if s.phase == "claimed":
        yield "timeout_or_stale_claim", replace(s, phase="uncertain")
        if s.sends:
            for phase in ("success", "error", "rejected"):
                yield f"response_{phase}", replace(s, phase=phase)
    if s.phase == "error":
        if s.debits and not s.refunds:
            yield "exact_correlated_refund", replace(s, refunds=1)
        if s.reserved and s.debits == s.refunds:
            yield "release_credit_reservation_once", replace(s, reserved=False)
    if s.phase in TERMINAL and not s.receipt:
        if s.phase != "error" or (s.debits == s.refunds and not s.reserved):
            yield "sign_terminal_accounting", replace(s, receipt=True)


def observation(s):
    """Persisted abstract gateway observation excludes upstream effect truth."""
    return (s.phase, s.debits, s.refunds, s.reserved, s.owner != -1, s.receipt)


def main():
    initial = State()
    parents: dict[State, tuple[State, str] | None] = {initial: None}
    queue = deque([initial])
    transitions = 0
    while queue:
        source = queue.popleft()
        for event, target in successors(source):
            transitions += 1
            assert 0 <= target.sends <= 1
            assert 0 <= target.refunds <= target.debits <= 1
            assert not target.sends or target.debits == 1
            assert not target.refunds or target.phase == "error"
            assert source.phase not in TERMINAL or target.phase == source.phase
            assert source.owner == -1 or source.owner == target.owner
            if event in {"exact_replay_no_new_execution", "changed_payload_rejected"}:
                assert source == target
            if target not in parents:
                parents[target] = (source, event)
                queue.append(target)

    def trace(s):
        events = []
        last = s
        while (previous := parents[s]) is not None:
            s, event = previous
            events.append(event)
        return {"events": list(reversed(events)), "state": asdict(last)}

    def first(predicate):
        return next(s for s in parents if predicate(s))

    zero = first(
        lambda s: (
            s.phase == "uncertain" and s.receipt and s.effects == 0 and s.sends == 1
        )
    )
    one = first(
        lambda s: (
            observation(s) == observation(zero) and s.sends == 1 and s.effects == 1
        )
    )
    assert observation(zero) == observation(one)
    free_effect = first(
        lambda s: s.phase == "error" and s.refunds == 1 and s.effects == 1 and s.receipt
    )
    multi_effect = first(lambda s: s.sends == 1 and s.effects == 2)
    absent_effect = first(
        lambda s: s.phase == "uncertain" and s.sends == 0 and s.receipt
    )
    paused_owner = first(
        lambda s: (
            s.phase == "uncertain" and s.sends == 0 and s.receipt and s.right == "ready"
        )
    )
    one_effect = first(lambda s: s.sends == 1 and s.effects == 1 and s.receipt)
    root = Path(__file__).resolve().parents[3]
    inspected = [
        "app/routers/mcp.py",
        "app/routers/mcp_standard.py",
        "app/db/models.py",
        "app/services/idempotency.py",
        "app/services/billing_engine.py",
        "app/services/mcp_dispatch_attempts.py",
        "app/services/mcp_dispatch_reconciliation.py",
        "app/services/upstream_mcp.py",
        "app/services/permits.py",
        "app/services/receipts.py",
        "app/services/signing_keys.py",
        "b2a_sdk/src/b2a_sdk/receipt_verifier.py",
        "docs/failure-semantics.md",
        "SECURITY_LIMITATIONS.md",
    ]
    results = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "kind": "exhaustive finite explanatory model; not application validation",
        "bound": "one durable identity; two activations; zero to two effects per dispatch",
        "reachable_states": len(parents),
        "examined_transitions": transitions,
        "assertions": "passed: <=1 send/debit/refund; debit before send; no ambiguity refund; absorbing terminal; fixed owner; replay/drift unchanged",
        "indistinguishable_gateway_observation": {
            "no_effect": trace(zero),
            "one_effect": trace(one),
        },
        "counterexamples": {
            "refunded_does_not_mean_no_business_effect": trace(free_effect),
            "one_send_does_not_mean_one_business_effect": trace(multi_effect),
            "charged_uncertainty_does_not_require_a_send": trace(absent_effect),
            "empty_lookup_does_not_authorize_safe_replacement": {
                "old_identity_prefix": trace(paused_owner),
                "lookup": "At this instant effects=0; a lookup can truthfully say not_applied.",
                "replacement_identity_trace": trace(one_effect),
                "old_identity_late_suffix": [
                    "owner_sends_once",
                    "upstream_commits_effect",
                ],
                "semantic_effects_total": 2,
                "caveat": "Composition of allowed transitions with an external point-in-time lookup; an operational counterexample, not a proven runtime schedule. Safe replacement additionally requires authoritative finality/quiescence or a shared idempotent business identity.",
            },
            "fresh_identity_or_database_restore": {
                "construction": "Run this trace under K1, then under K2 for the same semantic action; or reset gateway history after the first trace while preserving upstream history. Each per-identity invariant holds; total effects=2.",
                "per_identity_trace": trace(one_effect),
                "semantic_effects_total": 2,
                "caveat": "Composition/counterfactual construction, not an enumerated multi-identity or database-failover implementation test.",
            },
        },
        "limits": [
            "No application imports, HTTP requests, database operations, or cryptography.",
            "Atomic SQL, serializable admission, unique identity, and debit fencing are assumed.",
            "No unbounded liveness or implementation refinement proof; a scheduler can starve repair forever.",
            "A refundable error is a business accounting rule, not an upstream rollback guarantee.",
        ],
        "inspected_source_sha256_at_model_run": {
            path: sha256((root / path).read_bytes()).hexdigest() for path in inspected
        },
        "model_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    output = Path(__file__).with_name("mechanism-model-results.json")
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(
        json.dumps(
            {
                "reachable_states": len(parents),
                "examined_transitions": transitions,
                "assertions": "passed",
                "output": str(output),
            }
        )
    )


if __name__ == "__main__":
    main()
