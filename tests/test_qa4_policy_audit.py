"""Deep QA for the policy, audit, pricing and shadow-ledger slice.

Covers untested behavior in ``app/services/audit_log.py``,
``app/services/shadow_ledger.py``, ``app/services/pricing.py``, the pure
helpers in ``app/policy/jev_guard.py`` and ``app/policy/decisions.py``.

All tests are fast and deterministic: no sleeps, no network. The shadow
ledger tests use a fresh in-memory ``ShadowLedger`` per test with unique
wallet ids, so they never share state.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.core.config import DuplicateGuardMode, get_settings
from app.policy import jev_guard
from app.policy.decisions import evaluate_governed_action
from app.schemas.billing import ServiceCategory
from app.services.audit_log import (
    count_audit_events,
    count_audit_events_grouped,
    list_audit_events,
    record_audit_event,
    summarize_audit_events,
)
from app.services.pricing import DEFAULT_PRICING, charge_units_for
from app.services.shadow_ledger import ShadowLedger


def _ledger() -> ShadowLedger:
    return ShadowLedger()


# --- shadow ledger: units validation -------------------------------------------
# The real charge path (BillingEngine.charge) refuses non-finite and
# non-positive units before any debit. The shadow path must refuse them too:
# a negative simulation otherwise raises the virtual balance, and NaN crashes
# the comparison with InvalidOperation.


@pytest.mark.anyio
@pytest.mark.parametrize("units", [-5.0, -0.5, 0.0])
async def test_simulate_charge_refuses_non_positive_units(units):
    ledger = _ledger()
    session = await ledger.create_session("qa4-units-w1", Decimal("100"))

    with pytest.raises(ValueError, match="units"):
        await ledger.simulate_charge(
            session.session_id, ServiceCategory.TELEMETRY_PM, units=units
        )

    fresh = await ledger.get_session(session.session_id)
    assert fresh is not None
    assert fresh.total_simulated == Decimal("0")
    assert fresh.virtual_balance == Decimal("100")


@pytest.mark.anyio
@pytest.mark.parametrize("units", [float("nan"), float("inf"), float("-inf")])
async def test_simulate_charge_refuses_non_finite_units(units):
    ledger = _ledger()
    session = await ledger.create_session("qa4-units-w2", Decimal("100"))

    with pytest.raises(ValueError, match="units"):
        await ledger.simulate_charge(
            session.session_id, ServiceCategory.TELEMETRY_PM, units=units
        )

    fresh = await ledger.get_session(session.session_id)
    assert fresh is not None
    assert fresh.total_simulated == Decimal("0")


@pytest.mark.anyio
async def test_simulate_charge_accepts_positive_units():
    ledger = _ledger()
    session = await ledger.create_session("qa4-units-w3", Decimal("100"))

    result = await ledger.simulate_charge(
        session.session_id, ServiceCategory.TELEMETRY_PM, units=2.0
    )

    assert result.would_succeed is True
    assert result.credits_would_charge == Decimal("2.0")
    assert result.simulated_balance_after == Decimal("98.0")


# --- shadow ledger: session lifecycle -------------------------------------------


@pytest.mark.anyio
async def test_simulate_charge_unknown_session():
    with pytest.raises(ValueError, match="Session not found"):
        await _ledger().simulate_charge(
            "no-such-session", ServiceCategory.TELEMETRY_PM, units=1.0
        )


@pytest.mark.anyio
async def test_commit_unknown_session_reports_not_found():
    result = await _ledger().commit_session("no-such-session", SimpleNamespace())

    assert result.success is False
    assert result.wallet_id == ""
    assert result.message == "Session not found"
    assert result.committed_charges == 0


@pytest.mark.anyio
async def test_commit_empty_session_is_noop_success():
    ledger = _ledger()
    session = await ledger.create_session("qa4-empty-w", Decimal("50"))

    result = await ledger.commit_session(session.session_id, SimpleNamespace())

    assert result.success is True
    assert result.message == "No charges to commit"
    assert result.real_balance_before == result.real_balance_after == Decimal("50")


@pytest.mark.anyio
async def test_second_commit_of_same_session_finds_nothing():
    ledger = _ledger()
    session = await ledger.create_session("qa4-double-w", Decimal("100"))
    await ledger.simulate_charge(
        session.session_id, ServiceCategory.TELEMETRY_PM, units=1.0
    )

    charged_units = []

    class FakeMoney:
        async def charge(self, **kwargs):
            charged_units.append(kwargs["units"])
            return SimpleNamespace(entry_id="e1")

        async def get_wallet(self, wallet_id):
            assert wallet_id == "qa4-double-w"
            return SimpleNamespace(balance=Decimal("99"))

    first = await ledger.commit_session(session.session_id, FakeMoney())
    assert first.success is True
    assert first.committed_charges == 1
    assert first.total_credits_deducted == Decimal("1.0")
    assert charged_units == [Decimal("1.0")]

    second = await ledger.commit_session(session.session_id, FakeMoney())
    assert second.success is False
    assert second.message == "Session not found"


@pytest.mark.anyio
async def test_simulate_after_end_reports_not_found():
    ledger = _ledger()
    session = await ledger.create_session("qa4-ended-w", Decimal("100"))
    assert await ledger.end_session(session.session_id) is not None

    with pytest.raises(ValueError, match="Session not found"):
        await ledger.simulate_charge(
            session.session_id, ServiceCategory.TELEMETRY_PM, units=1.0
        )


@pytest.mark.anyio
async def test_blocked_charge_records_nothing():
    ledger = _ledger()
    session = await ledger.create_session("qa4-blocked-w", Decimal("100"))

    result = await ledger.simulate_charge(
        session.session_id,
        ServiceCategory.TELEMETRY_PM,
        units=1.0,
        blocked_reason="wallet_expired",
    )

    assert result.would_succeed is False
    assert result.reason == "wallet_expired"
    fresh = await ledger.get_session(session.session_id)
    assert fresh is not None
    assert fresh.total_simulated == Decimal("0")


@pytest.mark.anyio
async def test_insufficient_simulated_funds_records_nothing():
    ledger = _ledger()
    session = await ledger.create_session("qa4-poor-w", Decimal("1"))

    result = await ledger.simulate_charge(
        session.session_id, ServiceCategory.TELEMETRY_PM, units=5.0
    )

    assert result.would_succeed is False
    assert result.reason == "insufficient_simulated_funds"
    fresh = await ledger.get_session(session.session_id)
    assert fresh is not None
    assert fresh.total_simulated == Decimal("0")
    assert fresh.virtual_balance == Decimal("1")


@pytest.mark.anyio
async def test_list_sessions_is_scoped_to_wallet():
    ledger = _ledger()
    mine = await ledger.create_session("qa4-list-mine", Decimal("10"))
    await ledger.create_session("qa4-list-other", Decimal("10"))

    sessions = await ledger.list_sessions("qa4-list-mine")

    assert [s.session_id for s in sessions] == [mine.session_id]


# --- audit log ------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("event_id", ["", "x" * 51])
async def test_record_audit_event_rejects_bad_event_id(clean_database, event_id):
    with pytest.raises(ValueError, match="audit_event_id_invalid"):
        await record_audit_event(event="mcp.invoke", event_id=event_id)


@pytest.mark.anyio
async def test_count_and_grouped_counts_cover_every_filter(clean_database):
    await record_audit_event(
        event="mcp.invoke",
        wallet_id="qa4-a-w1",
        tool="echo",
        key_id="k1",
        endpoint="/mcp/messages",
        policy_decision_id="pol-1",
        request_id="req-1",
        ok=True,
    )
    await record_audit_event(
        event="mcp.invoke",
        wallet_id="qa4-a-w1",
        tool="echo",
        key_id="k1",
        endpoint="/mcp/messages",
        policy_decision_id="pol-1",
        request_id="req-2",
        ok=False,
        error="denied",
    )
    await record_audit_event(
        event="billing.charge",
        wallet_id="qa4-a-w2",
        tool="billing",
        key_id="k2",
        endpoint="/v1/billing/charge",
        request_id="req-3",
        ok=True,
    )

    assert await count_audit_events() == 3
    assert await count_audit_events(wallet_id="qa4-a-w1") == 2
    assert await count_audit_events(ok=False) == 1
    assert await count_audit_events(key_id="k2") == 1
    assert await count_audit_events(tool="echo", endpoint="/mcp/messages") == 2
    assert await count_audit_events(policy_decision_id="pol-1") == 2
    assert await count_audit_events(request_id="req-3") == 1
    assert await count_audit_events(event="no.such.event") == 0

    grouped = await count_audit_events_grouped()
    totals = {(b.event, b.wallet_id, b.ok): b.count for b in grouped}
    assert totals == {
        ("mcp.invoke", "qa4-a-w1", True): 1,
        ("mcp.invoke", "qa4-a-w1", False): 1,
        ("billing.charge", "qa4-a-w2", True): 1,
    }

    listed = await list_audit_events(ok=False)
    assert len(listed) == 1
    assert listed[0].error == "denied"
    assert await list_audit_events(key_id="k2", limit=5) != []
    assert await list_audit_events(request_id="req-1") != []
    assert await list_audit_events(endpoint="/mcp/messages") != []
    assert await list_audit_events(policy_decision_id="pol-1") != []


@pytest.mark.anyio
async def test_summarize_audit_events_scopes_to_wallet(clean_database):
    await record_audit_event(
        event="mcp.invoke",
        wallet_id="qa4-s-w1",
        ok=True,
        metadata={"policy_reason": "allowed"},
    )
    await record_audit_event(
        event="mcp.invoke",
        wallet_id="qa4-s-w1",
        ok=False,
        error="wallet_access_denied",
    )
    await record_audit_event(
        event="billing.charge",
        wallet_id="qa4-s-w2",
        ok=True,
        metadata={"policy_reason": "allowed"},
    )

    summary = await summarize_audit_events(wallet_id="qa4-s-w1")

    assert summary["total"] == 2
    assert summary["by_event"] == {"mcp.invoke": 2}
    assert summary["by_outcome"] == {"ok": 1, "error": 1}
    assert summary["by_wallet"] == {"qa4-s-w1": 2}
    assert summary["by_policy_reason"] == {
        "allowed": 1,
        "wallet_access_denied": 1,
    }
    assert summary["by_policy_reason_truncated"] is False

    full = await summarize_audit_events()
    assert full["total"] == 3
    assert full["by_wallet"] == {"qa4-s-w1": 2, "qa4-s-w2": 1}


# --- pricing --------------------------------------------------------------------


def test_every_service_category_has_a_positive_price():
    for category in ServiceCategory:
        _, price, _ = DEFAULT_PRICING[category]
        assert price.is_finite()
        assert price > 0


def test_charge_units_for_known_conversion():
    assert charge_units_for(Decimal("4"), ServiceCategory.IOT_BRIDGE) == Decimal("2")


def test_charge_units_for_round_trips_through_default_price():
    for category in ServiceCategory:
        default_price = DEFAULT_PRICING[category][1]
        units = charge_units_for(Decimal("10"), category)
        assert units * default_price == Decimal("10")


# --- jev guard pure helpers (no network) -----------------------------------------


def test_strip_secrets_redacts_key_like_text():
    assert jev_guard.strip_secrets("key sk-live-abcdefgh12345678 here") == (
        "key [secret] here"
    )
    assert jev_guard.strip_secrets("nothing sensitive here") == (
        "nothing sensitive here"
    )


def test_safe_state_redacts_secret_fields_and_truncates():
    state = {
        "tool": {"name": "t", "description": "d"},
        "permit": {"scope_description": "scope"},
        "agent_purpose": "purpose",
        "arguments": {
            "api_key": "sk-live-abcdefgh12345678",
            "note": "lorem ipsum dolor sit amet. " * 30,
        },
    }

    safe = jev_guard._safe_state(state, "operator-key-123")

    assert safe["arguments"]["api_key"] == "[secret]"
    assert len(safe["arguments"]["note"]) == jev_guard.MAX_STRING_CHARS
    assert "sk-live" not in str(safe)


def test_reasons_fire_only_at_their_thresholds():
    base = {
        "injected_instructions": 0.0,
        "outside_scope": 0.0,
        "purpose_mismatch_averaged": {"different_action": 0.0},
        "risk_understated": 0.0,
        "blast_radius": 0.0,
        "irreversible": 0.0,
        "moves_money": 0.0,
    }

    assert jev_guard._reasons(dict(base), "low", False) == []

    just_below = dict(
        base,
        injected_instructions=jev_guard.INJECTED_INSTRUCTIONS_THRESHOLD - 0.01,
    )
    assert jev_guard._reasons(just_below, "low", False) == []

    at_threshold = dict(
        base, injected_instructions=jev_guard.INJECTED_INSTRUCTIONS_THRESHOLD
    )
    assert jev_guard._reasons(at_threshold, "low", False) == ["injected_instructions"]

    # Purpose mismatch is strictly greater than its threshold.
    boundary = dict(
        base,
        purpose_mismatch_averaged={
            "different_action": jev_guard.PURPOSE_MISMATCH_THRESHOLD
        },
    )
    assert jev_guard._reasons(boundary, "low", False) == []
    above = dict(
        base,
        purpose_mismatch_averaged={
            "different_action": jev_guard.PURPOSE_MISMATCH_THRESHOLD + 0.01
        },
    )
    assert jev_guard._reasons(above, "low", False) == ["purpose_mismatch"]


def test_number_refuses_bool_non_finite_and_out_of_range():
    for bad in (True, False, "0.5", None, float("nan"), float("inf"), -0.1, 1.1):
        with pytest.raises(ValueError, match="bad_response"):
            jev_guard._number(bad, 1)
    assert jev_guard._number(0.5, 1) == 0.5


def test_answer_summary_rejects_malformed_model_output():
    def answers_for(kind_payload):
        out = {}
        for name, question in jev_guard.QUESTIONS.items():
            kind = question["type"]
            if kind == "noul":
                out[name] = {"type": kind, "noul": 0.0}
            elif kind == "choice":
                out[name] = {
                    "type": kind,
                    "choice": "no_purpose_given",
                    "probabilities": {
                        "carries_out": 0.0,
                        "different_action": 0.0,
                        "no_purpose_given": 1.0,
                    },
                }
            else:
                out[name] = {"type": kind, "score": 0.0}
        out.update(kind_payload)
        return out

    with pytest.raises(ValueError, match="bad_response"):
        jev_guard._answer_summary(
            answers_for({"irreversible": {"type": "noul", "noul": "high"}})
        )
    with pytest.raises(ValueError, match="bad_response"):
        jev_guard._answer_summary(
            answers_for(
                {
                    "purpose_mismatch": {
                        "type": "choice",
                        "choice": "no_purpose_given",
                        "probabilities": {
                            "carries_out": 0.5,
                            "different_action": 0.5,
                            "no_purpose_given": 0.5,
                        },
                    }
                }
            )
        )
    with pytest.raises(ValueError, match="bad_response"):
        jev_guard._answer_summary("not-a-dict")


# --- policy decisions: governed actions -------------------------------------------


def test_governed_action_anonymous_caller_is_denied():
    decision = evaluate_governed_action(
        auth=None, wallet_id="qa4-g-w1", action_type="invoke", target="echo"
    )

    assert decision.allowed is False
    assert decision.reason == "wallet_access_denied"
    assert decision.wallet_id == "qa4-g-w1"
    assert decision.auth_source == "anonymous"
    assert decision.decision_id.startswith("pol-")


# --- known unfixed bugs (xfail) ------------------------------------------------------
# These reproduce real defects that are deliberately left unfixed (each needs a
# larger change or a C.Lee decision; see Notes for the reviewer). They fail
# today and must flip to XPASS once the underlying bug is fixed.


class _ScriptedFakeRedis:
    """Minimal Redis stand-in that replays the shadow ledger's Redis calls.

    The first ``get`` of the session key belongs to the first simulation: it
    pauses until the second simulation has run to completion, so the first
    simulation's write lands on a stale read. Fully deterministic, no sleeps.
    """

    def __init__(self):
        self.store: dict = {}
        self.get_calls = 0
        self.second_finished: asyncio.Event | None = None

    async def setex(self, key, ttl, value):
        self.store[key] = value

    async def sadd(self, key, member):
        self.store.setdefault(key, set()).add(member)

    async def get(self, key):
        self.get_calls += 1
        # Snapshot now, like a real GET: the value is fixed at call time even
        # if this coroutine is paused before it returns it.
        snapshot = self.store.get(key)
        if self.get_calls == 1:
            assert self.second_finished is not None
            await self.second_finished.wait()
        return snapshot

    async def set(self, key, value, ex=None, xx=False):
        if xx and key not in self.store:
            return None
        self.store[key] = value
        return True


@pytest.mark.anyio
@pytest.mark.xfail(
    strict=True,
    reason="shadow_ledger concurrent simulate_charge lost update: "
    "overlapping simulations read-modify-write the charge list, "
    "so the last write drops the other charge",
)
async def test_concurrent_simulate_charges_keep_both_charges():
    ledger = ShadowLedger()
    ledger._redis_url = "fake://qa4-race"
    fake = _ScriptedFakeRedis()
    fake.second_finished = asyncio.Event()
    ledger._redis = fake

    session = await ledger.create_session("qa4-race-w", Decimal("100"))

    async def second_simulation():
        try:
            return await ledger.simulate_charge(
                session.session_id, ServiceCategory.TELEMETRY_PM, units=1.0
            )
        finally:
            fake.second_finished.set()

    first, second = await asyncio.gather(
        ledger.simulate_charge(
            session.session_id, ServiceCategory.TELEMETRY_PM, units=1.0
        ),
        second_simulation(),
    )

    assert first.would_succeed is True
    assert second.would_succeed is True
    final = await ledger.get_session(session.session_id)
    assert final is not None
    assert len(final.simulated_charges) == 2
    assert final.total_simulated == Decimal("2.0")


@pytest.mark.anyio
@pytest.mark.xfail(
    strict=True,
    reason="jev_guard swallows asyncio.CancelledError: evaluate_jev_guard "
    "answers skipped instead of propagating cancellation",
)
async def test_jev_guard_propagates_cancellation(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "JEV_RISK_GUARD", DuplicateGuardMode.ENFORCE)
    monkeypatch.setattr(settings, "JEV_RISK_GUARD_TIERS", "medium,high")
    monkeypatch.setattr(settings, "TYPESAFE_API_KEY", SecretStr("jev-test-key"))

    async def cancelled_post(**kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(jev_guard, "_post", cancelled_post)

    with pytest.raises(asyncio.CancelledError):
        await jev_guard.evaluate_jev_guard(
            tool_name="echo",
            tool_description="a reversible echo",
            service_category="agent_comms",
            risk_tier="medium",
            permit_scope="scope",
            requires_human_approval=False,
            arguments={},
            agent_purpose=None,
        )


def test_governed_action_explicit_override_is_respected():
    decision = evaluate_governed_action(
        auth=None,
        wallet_id="qa4-g-w2",
        action_type="invoke",
        target="echo",
        allowed=True,
        reason="operator_override",
    )

    assert decision.allowed is True
    assert decision.reason == "operator_override"
    assert decision.model_dump()["reason"] == "operator_override"
