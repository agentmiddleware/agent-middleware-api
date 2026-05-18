from app.core.auth import AuthContext
from app.policy.decisions import evaluate_tool_invocation


def test_bootstrap_admin_can_invoke_for_any_wallet():
    auth = AuthContext(source="env", raw_key="test-key", is_bootstrap_admin=True)

    decision = evaluate_tool_invocation(
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


def test_wallet_key_can_invoke_for_own_wallet():
    auth = AuthContext(
        source="db",
        raw_key="runtime-key",
        key_id="key-1",
        wallet_id="wallet-1",
    )

    decision = evaluate_tool_invocation(
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

    decision = evaluate_tool_invocation(
        auth=auth,
        wallet_id="wallet-2",
        tool_name="echo",
        estimated_cost=1.0,
        request_id="req-3",
    )

    assert decision.allowed is False
    assert decision.reason == "wallet_access_denied"
    assert decision.wallet_id == "wallet-2"
