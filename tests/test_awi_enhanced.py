"""Coverage for the AWI enhanced router (passkey, DOM bridge, RAG memory).

Tests only; no production code changes. All doubles are in memory, no
network, no database, no real browser.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from pydantic import ValidationError

from app.core.auth import AuthContext
from app.routers import awi_enhanced as router_module
from app.routers.awi_enhanced import (
    _not_found,
    _rag_owner_scope,
    _require_owner_or_not_found,
    router,
)
from app.schemas.awi_enhanced import DOMBridgeSessionRequest, RAGQueryRequest
from app.services.awi_playwright_bridge import BrowserSessionLimitExceeded
from app.services.webauthn_provider import WebAuthnProvider


def _auth(wallet_id=None, admin=False):
    return AuthContext(
        source="test", raw_key="k", wallet_id=wallet_id, is_bootstrap_admin=admin
    )


def _missing(kind="Session", resource_id="s1"):
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": f"{kind} {resource_id} not found"},
    )


@pytest.fixture(autouse=True)
def _clean_dom_wallets(monkeypatch):
    monkeypatch.setattr(router_module, "_DOM_SESSION_WALLETS", {})
    return router_module._DOM_SESSION_WALLETS


def _fake_session_manager(session=None):
    manager = SimpleNamespace()
    manager.get_session = AsyncMock(return_value=session)
    manager.attach_dom_bridge = AsyncMock()
    manager.detach_dom_bridge = AsyncMock()
    manager.get_dom_bridge_status = AsyncMock()
    return manager


# Helpers


def test_not_found_body_shape():
    exc = _not_found("Memory", "m1")
    assert exc.status_code == 404
    assert exc.detail == {"error": "not_found", "message": "Memory m1 not found"}


def test_owner_passes_wallet_check():
    _require_owner_or_not_found(_auth("w1"), "w1", _missing())


def test_foreign_wallet_answers_not_found_without_owner_name():
    with pytest.raises(HTTPException) as caught:
        _require_owner_or_not_found(_auth("w1"), "w2", _missing())
    assert caught.value.status_code == 404
    assert caught.value.detail == {
        "error": "not_found",
        "message": "Session s1 not found",
    }


def test_ownerless_resource_needs_bootstrap_admin():
    with pytest.raises(HTTPException) as caught:
        _require_owner_or_not_found(_auth("w1"), None, _missing())
    assert caught.value.status_code == 404
    _require_owner_or_not_found(_auth(admin=True), None, _missing())


def test_non_forbidden_errors_are_reraised(monkeypatch):
    auth = _auth("w1")
    monkeypatch.setattr(
        auth,
        "require_wallet_access",
        lambda wallet_id: (_ for _ in ()).throw(
            HTTPException(status_code=500, detail="boom")
        ),
    )
    with pytest.raises(HTTPException) as caught:
        _require_owner_or_not_found(auth, "w2", _missing())
    assert caught.value.status_code == 500


def test_rag_owner_scope_adds_ownerless_only_for_admins():
    assert _rag_owner_scope("w1", _auth("w1")) == {"w1"}
    assert _rag_owner_scope("w1", _auth("w1", admin=True)) == {"w1", None}


# Passkey endpoints (real in-memory provider, fake session manager)


@pytest.mark.asyncio
async def test_verify_unknown_challenge_rejected_before_governance(monkeypatch):
    from app.services import webauthn_provider as provider_module

    provider = WebAuthnProvider(verification_validity_seconds=60)
    monkeypatch.setattr(provider_module, "_webauthn_provider", provider)
    request = SimpleNamespace(challenge_id="no-such-challenge", credential={})
    with pytest.raises(HTTPException) as caught:
        await router_module.verify_passkey(request, _auth("w1"))
    assert caught.value.status_code == 400
    assert caught.value.detail["error"] == "verification_failed"


@pytest.mark.asyncio
async def test_passkey_status_and_invalidate_round_trip(monkeypatch):
    from app.services import awi_session as session_module
    from app.services import webauthn_provider as provider_module

    provider = WebAuthnProvider(verification_validity_seconds=60)
    monkeypatch.setattr(provider_module, "_webauthn_provider", provider)
    monkeypatch.setattr(
        session_module,
        "get_awi_session_manager",
        lambda: _fake_session_manager(SimpleNamespace(wallet_id="w1")),
    )
    auth = _auth("w1")

    before = await router_module.check_passkey_status("sess", "checkout", auth)
    assert before.is_verified is False

    assert (await router_module.invalidate_passkey("sess", None, auth))[
        "invalidated_count"
    ] == 0


@pytest.mark.asyncio
async def test_passkey_status_forbidden_to_foreign_wallet(monkeypatch):
    from app.services import awi_session as session_module
    from app.services import webauthn_provider as provider_module

    provider = WebAuthnProvider(verification_validity_seconds=60)
    monkeypatch.setattr(provider_module, "_webauthn_provider", provider)
    monkeypatch.setattr(
        session_module,
        "get_awi_session_manager",
        lambda: _fake_session_manager(SimpleNamespace(wallet_id="owner")),
    )
    with pytest.raises(HTTPException) as caught:
        await router_module.check_passkey_status("sess", "checkout", _auth("other"))
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_list_high_risk_actions_reports_provider_set(monkeypatch):
    from app.services import webauthn_provider as provider_module

    provider = WebAuthnProvider()
    monkeypatch.setattr(provider_module, "_webauthn_provider", provider)
    body = await router_module.list_high_risk_actions(_auth("w1"))
    assert body["actions"] == sorted(provider.HIGH_RISK_ACTIONS)
    assert body["count"] == len(provider.HIGH_RISK_ACTIONS)


# DOM bridge endpoints with fake bridge / session manager


def _fake_bridge():
    bridge = SimpleNamespace()
    bridge.create_session = AsyncMock()
    bridge.get_session = AsyncMock()
    bridge.destroy_session = AsyncMock()
    bridge.list_sessions = AsyncMock()
    bridge.extract_state_representation = AsyncMock()
    bridge.preview_action = AsyncMock()
    return bridge


@pytest.mark.asyncio
async def test_create_dom_session_admin_and_wallet_gating(monkeypatch):
    from app.services import awi_playwright_bridge as bridge_module

    bridge = _fake_bridge()
    bridge.create_session.return_value = SimpleNamespace(
        session_id="dom1", current_url="https://example.com"
    )
    monkeypatch.setattr(bridge_module, "get_playwright_bridge", lambda: bridge)

    request = DOMBridgeSessionRequest(target_url="https://example.com")
    with pytest.raises(HTTPException) as caught:
        await router_module.create_dom_session(request, _auth("w1"))
    assert caught.value.status_code == 403

    body = await router_module.create_dom_session(request, _auth(admin=True))
    assert body.session_id == "dom1"

    owned = DOMBridgeSessionRequest(target_url="https://example.com", wallet_id="w1")
    body = await router_module.create_dom_session(owned, _auth("w1"))
    assert router_module._DOM_SESSION_WALLETS[body.session_id] == "w1"


@pytest.mark.asyncio
async def test_create_dom_session_limit_and_bad_url_mapping(monkeypatch):
    from app.services import awi_playwright_bridge as bridge_module

    bridge = _fake_bridge()
    monkeypatch.setattr(bridge_module, "get_playwright_bridge", lambda: bridge)
    request = DOMBridgeSessionRequest(target_url="https://example.com", wallet_id="w1")

    bridge.create_session.side_effect = BrowserSessionLimitExceeded("full")
    with pytest.raises(HTTPException) as caught:
        await router_module.create_dom_session(request, _auth("w1"))
    assert caught.value.status_code == 429

    bridge.create_session.side_effect = ValueError("bad url")
    with pytest.raises(HTTPException) as caught:
        await router_module.create_dom_session(request, _auth("w1"))
    assert caught.value.status_code == 400


@pytest.mark.asyncio
async def test_destroy_unknown_dom_session_answers_404(monkeypatch):
    from app.services import awi_playwright_bridge as bridge_module

    bridge = _fake_bridge()
    bridge.get_session.return_value = SimpleNamespace(session_id="dom1")
    bridge.destroy_session.return_value = False
    monkeypatch.setattr(bridge_module, "get_playwright_bridge", lambda: bridge)
    router_module._DOM_SESSION_WALLETS["dom1"] = "w1"
    with pytest.raises(HTTPException) as caught:
        await router_module.destroy_dom_session("dom1", _auth("w1"))
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_list_dom_sessions_scoped_to_caller_wallet(monkeypatch):
    from app.services import awi_playwright_bridge as bridge_module

    bridge = _fake_bridge()
    bridge.list_sessions.return_value = [
        {"session_id": "a"},
        {"session_id": "b"},
    ]
    monkeypatch.setattr(bridge_module, "get_playwright_bridge", lambda: bridge)
    router_module._DOM_SESSION_WALLETS.update({"a": "w1", "b": "w2"})

    mine = await router_module.list_dom_sessions(_auth("w1"))
    assert mine == {"sessions": [{"session_id": "a"}], "count": 1}

    everything = await router_module.list_dom_sessions(_auth(admin=True))
    assert everything["count"] == 2


@pytest.mark.asyncio
async def test_dom_state_missing_session_answers_404(monkeypatch):
    from app.services import awi_playwright_bridge as bridge_module

    bridge = _fake_bridge()
    bridge.get_session.return_value = None
    monkeypatch.setattr(bridge_module, "get_playwright_bridge", lambda: bridge)
    with pytest.raises(HTTPException) as caught:
        await router_module.get_dom_state("ghost", auth=_auth(admin=True))
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_preview_action_failure_maps_to_400(monkeypatch):
    from app.services import awi_playwright_bridge as bridge_module

    bridge = _fake_bridge()
    bridge.get_session.return_value = SimpleNamespace(session_id="dom1")
    bridge.preview_action.side_effect = ValueError("unknown action")
    monkeypatch.setattr(bridge_module, "get_playwright_bridge", lambda: bridge)
    router_module._DOM_SESSION_WALLETS["dom1"] = "w1"
    request = SimpleNamespace(session_id="dom1", action="nope", parameters={})
    with pytest.raises(HTTPException) as caught:
        await router_module.preview_action(request, _auth("w1"))
    assert caught.value.status_code == 400


@pytest.mark.asyncio
async def test_attach_dom_bridge_error_mapping(monkeypatch):
    from app.services import awi_session as session_module

    request = SimpleNamespace(session_id="sess", target_url=None)

    manager = _fake_session_manager(SimpleNamespace(wallet_id="w1"))
    manager.attach_dom_bridge.side_effect = BrowserSessionLimitExceeded("full")
    monkeypatch.setattr(session_module, "get_awi_session_manager", lambda: manager)
    with pytest.raises(HTTPException) as caught:
        await router_module.attach_dom_bridge(request, _auth("w1"))
    assert caught.value.status_code == 429

    manager = _fake_session_manager(SimpleNamespace(wallet_id="w1"))
    manager.attach_dom_bridge.side_effect = ValueError("gone")
    monkeypatch.setattr(session_module, "get_awi_session_manager", lambda: manager)
    with pytest.raises(HTTPException) as caught:
        await router_module.attach_dom_bridge(request, _auth("w1"))
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_detach_dom_bridge_failure_maps_to_500(monkeypatch):
    from app.services import awi_session as session_module

    manager = _fake_session_manager(SimpleNamespace(wallet_id="w1"))
    manager.detach_dom_bridge.side_effect = RuntimeError("boom")
    monkeypatch.setattr(session_module, "get_awi_session_manager", lambda: manager)
    with pytest.raises(HTTPException) as caught:
        await router_module.detach_dom_bridge("sess", _auth("w1"))
    assert caught.value.status_code == 500


# RAG memory endpoints with fake engine


def _memory(memory_id="mem1", session_id="sess", owner="w1"):
    from app.core.time import utc_now

    now = utc_now()
    return SimpleNamespace(
        memory_id=memory_id,
        session_id=session_id,
        session_type="shopping",
        user_intent="buy shoes",
        action_sequence=["search"],
        key_entities=["shoes"],
        page_summaries=[],
        relevance_tags=[],
        created_at=now,
        accessed_at=now,
        access_count=0,
    )


def _patch_memory_world(monkeypatch, session, memory=None):
    from app.services import awi_rag_engine as rag_module
    from app.services import awi_session as session_module

    rag = SimpleNamespace()
    rag.get_memory = AsyncMock(return_value=memory)
    rag.delete_memory = AsyncMock(return_value=True)
    rag.get_session_memories = AsyncMock(return_value=[])
    rag.delete_session_memories = AsyncMock(return_value=0)
    rag.get_stats = AsyncMock(return_value={"total_memories": 0})
    monkeypatch.setattr(rag_module, "get_awi_rag_engine", lambda: rag)
    monkeypatch.setattr(
        session_module,
        "get_awi_session_manager",
        lambda: _fake_session_manager(session),
    )
    return rag


@pytest.mark.asyncio
async def test_get_memory_missing_answers_404(monkeypatch):
    _patch_memory_world(monkeypatch, SimpleNamespace(wallet_id="w1"), memory=None)
    with pytest.raises(HTTPException) as caught:
        await router_module.get_memory("ghost", _auth("w1"))
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_get_memory_foreign_owner_answers_404_without_leak(monkeypatch):
    _patch_memory_world(
        monkeypatch,
        SimpleNamespace(wallet_id="owner"),
        memory=_memory(session_id="sess"),
    )
    with pytest.raises(HTTPException) as caught:
        await router_module.get_memory("mem1", _auth("other"))
    assert caught.value.status_code == 404
    assert "owner" not in str(caught.value.detail)


@pytest.mark.asyncio
async def test_get_memory_round_trip_and_session_memories(monkeypatch):
    rag = _patch_memory_world(
        monkeypatch,
        SimpleNamespace(wallet_id="w1"),
        memory=_memory(),
    )
    rag.get_session_memories.return_value = [_memory()]
    body = await router_module.get_memory("mem1", _auth("w1"))
    assert body["memory_id"] == "mem1"
    assert body["user_intent"] == "buy shoes"

    listing = await router_module.get_session_memories("sess", _auth("w1"))
    assert listing["count"] == 1
    assert listing["memories"][0]["memory_id"] == "mem1"

    removed = await router_module.delete_session_memories("sess", _auth("w1"))
    assert removed == {"session_id": "sess", "deleted_count": 0}


@pytest.mark.asyncio
async def test_delete_memory_missing_after_load_answers_404(monkeypatch):
    rag = _patch_memory_world(
        monkeypatch, SimpleNamespace(wallet_id="w1"), memory=_memory()
    )
    rag.delete_memory.return_value = False
    with pytest.raises(HTTPException) as caught:
        await router_module.delete_memory("mem1", _auth("w1"))
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_rag_stats_requires_bootstrap_admin(monkeypatch):
    _patch_memory_world(monkeypatch, SimpleNamespace(wallet_id="w1"))
    with pytest.raises(HTTPException) as caught:
        await router_module.get_rag_stats(_auth("w1"))
    assert caught.value.status_code == 403
    stats = await router_module.get_rag_stats(_auth(admin=True))
    assert stats == {"total_memories": 0}


@pytest.mark.asyncio
async def test_session_context_missing_session_answers_404(monkeypatch):
    _patch_memory_world(monkeypatch, None)
    with pytest.raises(HTTPException) as caught:
        await router_module.get_session_context("ghost", auth=_auth(admin=True))
    assert caught.value.status_code == 404


# Route table and schema edges


def test_router_exposes_passkey_dom_and_rag_paths():
    paths = {(r.path, next(iter(r.methods))) for r in router.routes}
    for path, method in [
        ("/v1/awi/passkey/challenge", "POST"),
        ("/v1/awi/passkey/verify", "POST"),
        ("/v1/awi/passkey/status/{session_id}/{action}", "GET"),
        ("/v1/awi/passkey/invalidate/{session_id}", "DELETE"),
        ("/v1/awi/passkey/high-risk-actions", "GET"),
        ("/v1/awi/dom/session", "POST"),
        ("/v1/awi/dom/session/{session_id}", "DELETE"),
        ("/v1/awi/dom/sessions", "GET"),
        ("/v1/awi/dom/state/{session_id}", "GET"),
        ("/v1/awi/rag/index", "POST"),
        ("/v1/awi/rag/query", "POST"),
        ("/v1/awi/rag/memory/{memory_id}", "GET"),
        ("/v1/awi/rag/stats", "GET"),
    ]:
        assert (path, method) in paths


@pytest.mark.parametrize("query", ["", "   ", "\t\n"])
def test_blank_rag_query_rejected(query):
    with pytest.raises(ValidationError):
        RAGQueryRequest(query=query)


def test_dom_viewport_bounds_rejected():
    with pytest.raises(ValidationError):
        DOMBridgeSessionRequest(target_url="https://example.com", viewport_width=10)
    with pytest.raises(ValidationError):
        DOMBridgeSessionRequest(target_url="https://example.com", viewport_height=99999)
