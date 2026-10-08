"""Guardrails for gtm-08 trust-plane findings: recorder default and bundle warnings."""

from __future__ import annotations

from app.core.auth import AuthContext
from app.db.database import get_session_factory
from app.db.models import WalletModel
from app.policy.decisions import evaluate_tool_invocation
from app.schemas.policies import PolicyBundleCreate
from app.services.governance import record_governed_action
from app.services.policies import create_policy_bundle, get_policy_bundle


def _auth() -> AuthContext:
    return AuthContext(source="env", raw_key="test-key", is_bootstrap_admin=True)


async def _wallet_row(wallet_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            WalletModel(wallet_id=wallet_id, wallet_type="agent", owner_name="t")
        )
        await session.commit()


async def test_recorder_defaults_to_denied(clean_database):
    """Omitting the verdict must record a denial, never an allow."""
    decision = await record_governed_action(
        event="test.event",
        auth=_auth(),
        wallet_id="wallet-1",
        target="sandbox",
        endpoint="/v1/test",
    )
    assert decision.allowed is False
    assert decision.reason == "denied"


async def test_recorder_honors_explicit_allow(clean_database):
    decision = await record_governed_action(
        event="test.event",
        auth=_auth(),
        wallet_id="wallet-1",
        target="sandbox",
        endpoint="/v1/test",
        allowed=True,
    )
    assert decision.allowed is True
    assert decision.reason == "allowed"


async def test_recorder_honors_explicit_denial_reason(clean_database):
    decision = await record_governed_action(
        event="test.event",
        auth=_auth(),
        wallet_id="wallet-1",
        target="sandbox",
        endpoint="/v1/test",
        allowed=False,
        reason="tool_not_allowed",
    )
    assert decision.allowed is False
    assert decision.reason == "tool_not_allowed"


async def test_open_bundle_returns_warning(clean_database):
    await _wallet_row("wallet-1")
    response = await create_policy_bundle(
        PolicyBundleCreate(wallet_id="wallet-1", name="open")
    )
    assert response.warnings != []
    assert response.warnings[0].startswith("policy_bundle_unrestricted")

    reread = await get_policy_bundle(response.policy_id)
    assert reread is not None
    assert reread.warnings != []


async def test_restricted_bundle_has_no_warnings(clean_database):
    await _wallet_row("wallet-1")
    response = await create_policy_bundle(
        PolicyBundleCreate(
            wallet_id="wallet-1",
            name="tight",
            allowed_tools=["echo"],
            max_cost_per_action=5,
        )
    )
    assert response.warnings == []


def test_ownership_helper_ignores_tool_and_cost():
    """Pin the documented contract: this helper checks wallet ownership only.

    No policy bundle exists for this wallet, the tool is invented, and the
    cost is arbitrary, yet the owner is allowed. Tool, cost, and risk
    enforcement lives in permit validation plus evaluate_wallet_policy.
    """
    auth = AuthContext(
        source="db",
        raw_key="runtime-key",
        key_id="key-1",
        wallet_id="wallet-1",
    )
    decision = evaluate_tool_invocation(
        auth=auth,
        wallet_id="wallet-1",
        tool_name="never-registered-tool",
        estimated_cost=999999.0,
        request_id="req-doc",
    )
    assert decision.allowed is True
    assert decision.reason == "allowed"
