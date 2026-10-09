from app.core.auth import AuthContext
from app.core.durable_state import _json_default
from app.policy import PolicyDecision, evaluate_tool_invocation, evaluate_wallet_access


def test_bootstrap_admin_can_invoke_for_any_wallet():
    auth = AuthContext(source="env", raw_key="test-key", is_bootstrap_admin=True)

    decision = evaluate_wallet_access(
        auth=auth,
        wallet_id="wallet-any",
        tool_name="echo",
        estimated_cost=2.0,
        request_id="req-1",
    )

    assert decision.allowed is True
    assert decision.reason == "allowed"
    assert decision.wallet_id == "wallet-any"
    assert decision.tool_name == "echo"
    assert decision.estimated_cost == 2.0
    assert decision.request_id == "req-1"
    assert decision.decision_id.startswith("pol-")
    assert isinstance(decision, PolicyDecision)


def test_wallet_key_can_invoke_for_own_wallet():
    auth = AuthContext(
        source="db",
        raw_key="runtime-key",
        key_id="key-1",
        wallet_id="wallet-1",
    )

    decision = evaluate_wallet_access(
        auth=auth,
        wallet_id="wallet-1",
        tool_name="echo",
        estimated_cost=1.0,
        request_id="req-2",
    )

    assert decision.allowed is True
    assert decision.reason == "allowed"
    assert decision.key_id == "key-1"


def test_wallet_key_cannot_invoke_for_other_wallet():
    auth = AuthContext(
        source="db",
        raw_key="runtime-key",
        key_id="key-1",
        wallet_id="wallet-1",
    )

    decision = evaluate_wallet_access(
        auth=auth,
        wallet_id="wallet-2",
        tool_name="echo",
        estimated_cost=1.0,
        request_id="req-3",
    )

    assert decision.allowed is False
    assert decision.reason == "wallet_access_denied"
    assert decision.wallet_id == "wallet-2"


def test_policy_decision_model_dump_accepts_json_mode_for_durable_state():
    auth = AuthContext(source="env", raw_key="test-key", is_bootstrap_admin=True)

    decision = evaluate_wallet_access(
        auth=auth,
        wallet_id="wallet-any",
        tool_name="echo",
        estimated_cost=2.0,
        request_id="req-4",
    )

    assert _json_default(decision) == decision.model_dump(mode="json")


def test_deprecated_tool_invocation_alias_matches_wallet_access():
    auth = AuthContext(
        source="db",
        raw_key="runtime-key",
        key_id="key-1",
        wallet_id="wallet-1",
    )

    canonical = evaluate_wallet_access(
        auth=auth,
        wallet_id="wallet-1",
        tool_name="echo",
        estimated_cost=1.0,
        request_id="req-alias",
    )
    legacy = evaluate_tool_invocation(
        auth=auth,
        wallet_id="wallet-1",
        tool_name="echo",
        estimated_cost=1.0,
        request_id="req-alias",
    )

    assert legacy.allowed == canonical.allowed is True
    assert legacy.reason == canonical.reason == "allowed"
    assert legacy.wallet_id == canonical.wallet_id == "wallet-1"


def test_wallet_access_is_not_full_tool_approval():
    """The helper allows the wallet owner with no permit or policy input.

    This pins the audit finding: a positive result must never be read as
    permit or policy approval. Callers enforce those gates separately.
    """
    auth = AuthContext(
        source="db",
        raw_key="runtime-key",
        key_id="key-1",
        wallet_id="wallet-1",
    )

    decision = evaluate_wallet_access(
        auth=auth,
        wallet_id="wallet-1",
        tool_name="expensive-tool",
        estimated_cost=9999.0,
        request_id="req-scope",
    )

    assert decision.allowed is True
    assert decision.reason == "allowed"
