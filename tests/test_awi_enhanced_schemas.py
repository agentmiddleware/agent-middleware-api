"""Tests for app/schemas/awi_enhanced.py validation behavior."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.awi_enhanced import (
    AWIEnhancedExecutionRequest,
    AWIEnhancedSessionCreate,
    CommandType,
    DOMActionPreviewRequest,
    DOMActionPreviewResponse,
    DOMBridgeSessionRequest,
    DOMElementInfo,
    DOMRepresentationType,
    DOMSessionStatus,
    DOMStateRequest,
    DOMStateResponse,
    DOMSyncRequest,
    DOMSyncResponse,
    MemoryDeleteRequest,
    MemoryIndexRequest,
    MemoryIndexResponse,
    MemorySearchResult,
    PasskeyChallengeRequest,
    PasskeyChallengeResponse,
    PasskeySessionStatus,
    PasskeyStatus,
    PasskeyVerifyRequest,
    PasskeyVerifyResponse,
    PlaywrightCommandInfo,
    RAGQueryRequest,
    RAGQueryResponse,
    SessionContextRequest,
    SessionContextResponse,
    TranslationMode,
)


class TestEnums:
    def test_passkey_status_values(self):
        assert {s.value for s in PasskeyStatus} == {
            "pending",
            "verified",
            "failed",
            "expired",
        }

    def test_dom_status_and_representation_values(self):
        assert {s.value for s in DOMSessionStatus} == {"active", "closed", "error"}
        assert DOMRepresentationType.SUMMARY.value == "summary"
        assert TranslationMode.PLAYWRIGHT.value == "playwright"
        assert CommandType.CLICK.value == "click"


class TestPasskeySchemas:
    def test_challenge_request_round_trip(self):
        req = PasskeyChallengeRequest(session_id="s1", action="withdraw")
        assert req.session_id == "s1"
        assert req.action == "withdraw"

    def test_challenge_request_missing_action_rejected(self):
        with pytest.raises(ValidationError):
            PasskeyChallengeRequest(session_id="s1")  # type: ignore[call-arg]

    def test_challenge_response_defaults(self):
        body = PasskeyChallengeResponse(
            challenge_id="c1",
            challenge="abc",
            rp_id="example.com",
            rp_name="Example",
            timeout=60000,
            public_key_cred_params=[],
            authenticator_selection={},
        )
        assert body.user_verification == "required"
        assert body.exclude_credentials == []

    def test_verify_request_requires_credential(self):
        with pytest.raises(ValidationError):
            PasskeyVerifyRequest(challenge_id="c1")  # type: ignore[call-arg]

    def test_verify_response_default_expiry(self):
        body = PasskeyVerifyResponse(
            verified=True,
            challenge_id="c1",
            session_id="s1",
            action="withdraw",
            verified_at="2026-01-01T00:00:00Z",
        )
        assert body.expires_in_seconds == 300

    def test_session_status_optional_fields_default_none(self):
        status = PasskeySessionStatus(
            session_id="s1", action="withdraw", is_verified=False
        )
        assert status.verified_at is None
        assert status.expires_in_seconds is None


class TestDOMBridgeSchemas:
    def test_session_request_defaults(self):
        req = DOMBridgeSessionRequest(target_url="https://example.com/shop")
        assert req.headless is True
        assert req.viewport_width == 1280
        assert req.viewport_height == 720
        assert req.wallet_id is None

    def test_session_request_viewport_bounds_rejected(self):
        with pytest.raises(ValidationError):
            DOMBridgeSessionRequest(
                target_url="https://example.com", viewport_width=319
            )
        with pytest.raises(ValidationError):
            DOMBridgeSessionRequest(
                target_url="https://example.com", viewport_width=3841
            )
        with pytest.raises(ValidationError):
            DOMBridgeSessionRequest(
                target_url="https://example.com", viewport_height=239
            )
        with pytest.raises(ValidationError):
            DOMBridgeSessionRequest(
                target_url="https://example.com", viewport_height=2161
            )

    def test_session_request_viewport_boundaries_accepted(self):
        low = DOMBridgeSessionRequest(
            target_url="https://example.com",
            viewport_width=320,
            viewport_height=240,
        )
        high = DOMBridgeSessionRequest(
            target_url="https://example.com",
            viewport_width=3840,
            viewport_height=2160,
        )
        assert (low.viewport_width, low.viewport_height) == (320, 240)
        assert (high.viewport_width, high.viewport_height) == (3840, 2160)

    def test_element_info_defaults(self):
        el = DOMElementInfo(tag="button", css_selector=".buy", xpath="//button")
        assert el.text_content == ""
        assert el.attributes == {}
        assert el.is_interactive is False
        assert el.role is None

    def test_command_info_defaults(self):
        cmd = PlaywrightCommandInfo(command_type="click", target=".buy")
        assert cmd.value is None
        assert cmd.options == {}

    def test_sync_request_defaults(self):
        req = DOMSyncRequest(session_id="b1", action="add_to_cart")
        assert req.parameters == {}
        assert req.return_screenshot is False

    def test_sync_response_default_status(self):
        resp = DOMSyncResponse(
            session_id="b1",
            execution_id="e1",
            action="add_to_cart",
            commands_generated=2,
            commands_executed=2,
            state_representation={},
        )
        assert resp.status == "success"
        assert resp.effect_status is None
        assert resp.error is None

    def test_state_request_defaults(self):
        req = DOMStateRequest()
        assert req.representation_type == DOMRepresentationType.SUMMARY
        assert req.include_elements is True

    def test_state_response_holds_elements(self):
        resp = DOMStateResponse(
            session_id="b1",
            url="https://example.com",
            title="Shop",
            representation_type=DOMRepresentationType.SUMMARY,
            page_type="shopping",
            main_content="items",
        )
        assert resp.interactive_elements == []
        assert resp.forms == []

    def test_preview_round_trip(self):
        req = DOMActionPreviewRequest(session_id="b1", action="search")
        assert req.parameters == {}
        resp = DOMActionPreviewResponse(
            session_id="b1", action="search", commands=[], estimated_duration_ms=10
        )
        assert resp.elements_found == {}


class TestRAGMemorySchemas:
    def test_index_request_defaults(self):
        req = MemoryIndexRequest(session_id="s1", session_type="shopping")
        assert req.action_history == []
        assert req.state_snapshots == []
        assert req.metadata == {}

    def test_index_response_sets_indexed_at(self):
        from datetime import timedelta, timezone

        before = datetime.now(timezone.utc).replace(tzinfo=None)
        resp = MemoryIndexResponse(
            memory_id="m1",
            session_id="s1",
            entities_extracted=2,
            intent_inferred="buy shoes",
        )
        assert isinstance(resp.indexed_at, datetime)
        assert abs(resp.indexed_at - before) < timedelta(minutes=1)

    def test_query_request_defaults(self):
        req = RAGQueryRequest(query="shopping for laptops")
        assert req.top_k == 5
        assert req.similarity_threshold == 0.7
        assert req.include_raw_state is False

    def test_query_blank_string_rejected(self):
        with pytest.raises(ValidationError):
            RAGQueryRequest(query="   ")

    def test_query_empty_string_rejected(self):
        with pytest.raises(ValidationError):
            RAGQueryRequest(query="")

    def test_query_top_k_bounds(self):
        with pytest.raises(ValidationError):
            RAGQueryRequest(query="laptops", top_k=0)
        with pytest.raises(ValidationError):
            RAGQueryRequest(query="laptops", top_k=21)
        assert RAGQueryRequest(query="laptops", top_k=1).top_k == 1
        assert RAGQueryRequest(query="laptops", top_k=20).top_k == 20

    def test_query_threshold_bounds(self):
        with pytest.raises(ValidationError):
            RAGQueryRequest(query="laptops", similarity_threshold=1.5)
        with pytest.raises(ValidationError):
            RAGQueryRequest(query="laptops", similarity_threshold=-0.1)

    def test_search_result_defaults(self):
        now = datetime.now().astimezone()
        result = MemorySearchResult(
            memory_id="m1",
            session_id="s1",
            session_type="shopping",
            user_intent="buy shoes",
            similarity_score=0.9,
            created_at=now,
            accessed_at=now,
        )
        assert result.action_sequence == []
        assert result.access_count == 0
        assert result.raw_state is None

    def test_query_response_holds_results(self):
        resp = RAGQueryResponse(query="shoes", results=[], total_found=0)
        assert resp.search_time_ms is None

    def test_context_request_top_k_bounds(self):
        with pytest.raises(ValidationError):
            SessionContextRequest(current_session_id="s1", top_k=0)
        with pytest.raises(ValidationError):
            SessionContextRequest(current_session_id="s1", top_k=11)

    def test_context_response_round_trip(self):
        resp = SessionContextResponse(
            current_session_id="s1",
            current_session_type="shopping",
            relevant_past_sessions=[],
            suggested_next_actions=["search"],
            common_patterns=["sort by price"],
        )
        assert resp.suggested_next_actions == ["search"]

    def test_delete_request_defaults(self):
        req = MemoryDeleteRequest(memory_id="m1")
        assert req.cascade is False


class TestIntegrationSchemas:
    def test_session_create_defaults(self):
        req = AWIEnhancedSessionCreate(target_url="https://example.com")
        assert req.max_steps == 100
        assert req.enable_passkey_gate is True
        assert req.enable_dom_bridge is False
        assert req.enable_rag_indexing is True

    def test_session_create_max_steps_bounds(self):
        with pytest.raises(ValidationError):
            AWIEnhancedSessionCreate(target_url="https://example.com", max_steps=0)
        with pytest.raises(ValidationError):
            AWIEnhancedSessionCreate(target_url="https://example.com", max_steps=1001)
        with pytest.raises(ValidationError):
            AWIEnhancedSessionCreate(
                target_url="https://example.com", timeout_seconds=5
            )

    def test_execution_request_defaults(self):
        req = AWIEnhancedExecutionRequest(session_id="s1", action="search")
        assert req.parameters == {}
        assert req.passkey_verified is False
        assert req.bypass_dom_bridge is False
