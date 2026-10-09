"""Focused unit tests for app/services/agent_intelligence.py.

Uses in-memory fakes for the LLM and the durable store: no network and no
real external services.
"""

import json
from types import SimpleNamespace

import pytest

from app.services import agent_intelligence
from app.services.agent_intelligence import AgentIntelligence, _agent_key


class _FakeLLM:
    """Configurable stand-in for the real LLM service."""

    def __init__(self, content: str):
        self.content = content
        self.calls: list[dict] = []

    async def chat(self, messages=None, system=None, **kwargs):
        self.calls.append({"messages": messages, "system": system})
        return SimpleNamespace(
            content=self.content,
            model="fake",
            usage={},
            finish_reason="stop",
        )


class _MemoryState:
    """Minimal in-memory stand-in for the durable state store."""

    def __init__(self):
        self.data: dict = {}

    async def _ensure_ready(self):
        return None

    async def load_json(self, key):
        return self.data.get(key)

    async def save_json(self, key, value):
        self.data[key] = value
        return True


def make_service(llm_content: str) -> AgentIntelligence:
    service = AgentIntelligence()
    service._llm = _FakeLLM(llm_content)
    service._state = _MemoryState()
    return service


def test_agent_key_namespaces_by_wallet():
    assert _agent_key("bot", None) == "bot"
    assert _agent_key("bot", "agt-abc") == "agt-abc:bot"
    assert _agent_key("bot", "agt-abc") != _agent_key("bot", "agt-other")


@pytest.mark.anyio
async def test_decide_parses_json_response():
    payload = json.dumps(
        {"reasoning": "load is low", "action": "scale_up", "confidence": 0.8}
    )
    service = make_service(payload)
    decision = await service.decide(
        agent_id="bot", context={"load": 0.2}, options=["scale_up", "wait"]
    )
    assert decision.action == "scale_up"
    assert decision.reasoning == "load is low"
    assert decision.confidence == pytest.approx(0.8)
    assert decision.decision_id
    assert decision.timestamp is not None
    stored = service.get_decisions("bot")
    assert [d.decision_id for d in stored] == [decision.decision_id]


@pytest.mark.anyio
async def test_decide_falls_back_on_plain_text_response():
    service = make_service("just do a restart")
    decision = await service.decide(agent_id="bot", context={"load": 0.9})
    assert decision.action == "just do a restart"
    assert decision.reasoning == "just do a restart"
    assert decision.confidence == pytest.approx(0.5)


@pytest.mark.anyio
async def test_diagnose_and_heal_needs_approval_and_roundtrips():
    payload = json.dumps({"diagnosis": "disk full", "fix": "free /tmp"})
    service = make_service(payload)
    result = await service.diagnose_and_heal(
        issue="crash on boot", context={"disk": "99%"}
    )
    assert result.diagnosis == "disk full"
    assert result.code_change == "free /tmp"
    assert result.fix_applied is False
    assert result.success is False
    assert service.get_heal(result.heal_id) is result
    assert service.get_heal("missing-id") is None


@pytest.mark.anyio
async def test_diagnose_and_heal_handles_plain_text_response():
    service = make_service("reboot the box")
    result = await service.diagnose_and_heal(issue="hang", context={})
    assert result.diagnosis == "Could not parse LLM response"
    assert result.code_change == "reboot the box"


@pytest.mark.anyio
async def test_query_learn_remember_and_recall():
    service = make_service("insight: retries help")
    answer = await service.query("what helps?", data_context={"runs": 3})
    assert answer == "insight: retries help"

    learned = await service.learn("bot", {"outcome": "ok"})
    assert learned == "insight: retries help"
    patterns = await service.recall("bot", key="learned_pattern")
    assert len(patterns) == 1
    assert patterns[0]["value"]["experience"] == {"outcome": "ok"}

    await service.remember("bot", "color", "blue")
    await service.remember("bot", "color", "red")
    assert await service.recall("bot", key="color", limit=1) == [
        (await service.recall("bot", key="color"))[-1]
    ]
    assert [m["value"] for m in await service.recall("bot", key="color")] == [
        "blue",
        "red",
    ]
    assert await service.recall("unknown-agent") == []
    assert service.get_decisions("unknown-agent") == []


@pytest.mark.anyio
async def test_wallet_isolation_for_decisions_and_memory():
    service = make_service(
        json.dumps({"reasoning": "r", "action": "wait", "confidence": 0.9})
    )
    await service.decide("bot", {}, owner_wallet_id="agt-one")
    await service.remember("bot", "k", "v1", owner_wallet_id="agt-one")
    await service.remember("bot", "k", "v2", owner_wallet_id="agt-two")

    assert [d.action for d in service.get_decisions("bot")] == []
    assert [
        d.action for d in service.get_decisions("bot", owner_wallet_id="agt-one")
    ] == ["wait"]
    assert service.get_decisions("bot", owner_wallet_id="agt-two") == []
    assert [
        m["value"] for m in await service.recall("bot", owner_wallet_id="agt-one")
    ] == ["v1"]
    assert [
        m["value"] for m in await service.recall("bot", owner_wallet_id="agt-two")
    ] == ["v2"]


@pytest.mark.anyio
async def test_initialize_loads_persisted_decisions():
    service = make_service(
        json.dumps({"reasoning": "r", "action": "wait", "confidence": 0.9})
    )
    await service.decide("bot", {"n": 1})
    saved = dict(service._state.data)

    fresh = AgentIntelligence()
    fresh._llm = _FakeLLM("unused")
    fresh._state = _MemoryState()
    fresh._state.data.update(saved)
    monkey_state = agent_intelligence.get_durable_state
    try:
        agent_intelligence.get_durable_state = lambda: fresh._state
        await fresh.initialize()
    finally:
        agent_intelligence.get_durable_state = monkey_state
    assert [d.action for d in fresh.get_decisions("bot")] == ["wait"]
