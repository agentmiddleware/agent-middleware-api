"""Focused tests for app/services/awi_playwright_bridge.py.

Covers the bridge's main public behavior without a real browser or
network: selector quoting, credential redaction, scroll bounds, action
dispatch including edge and error cases, session lifecycle, preview
redaction, and failure-path execution results.
"""

import json
from unittest.mock import AsyncMock

import pytest

from app.services import awi_playwright_bridge as bridge_module
from app.services.awi_playwright_bridge import (
    _clamp_scroll,
    _redact_input_values,
    _selector_literal,
    AWIPlaywrightBridge,
    BridgeSession,
    BrowserSessionLimitExceeded,
    CommandType,
    DOMElement,
    PlaywrightCommand,
    TranslationMode,
)


@pytest.fixture
def bridge(monkeypatch):
    """Bridge with outbound URL checks stubbed so no DNS is touched."""
    monkeypatch.setattr(
        bridge_module, "check_outbound_url", AsyncMock(return_value=None)
    )
    return AWIPlaywrightBridge(mode=TranslationMode.CDP_DIRECT)


def _seat(bridge: AWIPlaywrightBridge) -> BridgeSession:
    session = BridgeSession(
        session_id="test-session", current_url="https://example.com"
    )
    bridge._sessions[session.session_id] = session
    return session


def _stub_semantic(monkeypatch, bridge, element):
    async def _find(session, semantic_type):
        return element

    monkeypatch.setattr(bridge, "_find_semantic_element", _find)


def _element(**kwargs):
    kwargs.setdefault("tag", "button")
    kwargs.setdefault("text_content", "Add to cart")
    kwargs.setdefault("attributes", {})
    kwargs.setdefault("xpath", "")
    kwargs.setdefault("css_selector", "#add-cart")
    return DOMElement(**kwargs)


class TestSelectorLiteral:
    def test_round_trips_quotes_and_engine_chains(self):
        hostile = 'a"b >> c'
        assert json.loads(_selector_literal(hostile)) == hostile

    def test_result_is_single_quoted_literal(self):
        literal = _selector_literal("hello")
        assert literal == '"hello"'


class TestSensitiveRedaction:
    def test_password_value_redacted(self):
        inputs = [{"name": "pw", "type": "password", "value": "hunter2"}]
        assert _redact_input_values(inputs)[0]["value"] == "[REDACTED]"

    def test_empty_password_stays_empty(self):
        inputs = [{"name": "pw", "type": "password", "value": ""}]
        assert _redact_input_values(inputs)[0]["value"] == ""

    def test_credential_autocomplete_redacted(self):
        inputs = [
            {
                "name": "card",
                "type": "text",
                "autocomplete": "cc-number",
                "value": "4111111111111111",
            }
        ]
        assert _redact_input_values(inputs)[0]["value"] == "[REDACTED]"

    def test_credential_like_name_redacted(self):
        inputs = [{"name": "api_token", "type": "text", "value": "abc123"}]
        assert _redact_input_values(inputs)[0]["value"] == "[REDACTED]"

    def test_plain_field_untouched(self):
        inputs = [{"name": "nickname", "type": "text", "value": "sam"}]
        assert _redact_input_values(inputs)[0]["value"] == "sam"


class TestScrollSafety:
    def test_clamp_bounds(self):
        assert _clamp_scroll(999999) == 20000
        assert _clamp_scroll(-999999) == -20000
        assert _clamp_scroll(300) == 300

    @pytest.mark.asyncio
    async def test_scroll_clamps_huge_amount(self, bridge):
        session = _seat(bridge)
        commands = await bridge.translate_action(
            session_id=session.session_id,
            action="scroll",
            parameters={"direction": "down", "amount": 999999},
        )
        assert commands[0].target == "window.scrollBy(0, 20000)"

    @pytest.mark.asyncio
    async def test_scroll_up_negates(self, bridge):
        session = _seat(bridge)
        commands = await bridge.translate_action(
            session_id=session.session_id,
            action="scroll",
            parameters={"direction": "up", "amount": 300},
        )
        assert commands[0].target == "window.scrollBy(0, -300)"

    @pytest.mark.asyncio
    async def test_scroll_rejects_non_integer_amount(self, bridge):
        session = _seat(bridge)
        with pytest.raises(ValueError, match="integer"):
            await bridge.translate_action(
                session_id=session.session_id,
                action="scroll",
                parameters={"amount": "far"},
            )

    def test_scroll_offsets_reject_arbitrary_evaluate(self):
        command = PlaywrightCommand(
            command_type=CommandType.EVALUATE, target="alert(1)"
        )
        with pytest.raises(ValueError, match="not permitted"):
            AWIPlaywrightBridge._scroll_offsets(command)

    def test_scroll_offsets_reject_out_of_range_evaluate(self):
        command = PlaywrightCommand(
            command_type=CommandType.EVALUATE,
            target="window.scrollBy(0, 50000)",
        )
        with pytest.raises(ValueError, match="out of range"):
            AWIPlaywrightBridge._scroll_offsets(command)

    def test_scroll_offsets_reject_malformed_expression(self):
        command = PlaywrightCommand(
            command_type=CommandType.EVALUATE,
            target="window.scrollBy(0, 999999)",
        )
        with pytest.raises(ValueError, match="not permitted"):
            AWIPlaywrightBridge._scroll_offsets(command)

    def test_scroll_offsets_accept_server_generated_expression(self):
        command = PlaywrightCommand(
            command_type=CommandType.EVALUATE,
            target="window.scrollBy(0, 300)",
        )
        assert AWIPlaywrightBridge._scroll_offsets(command) == (0, 300)

    def test_scroll_offsets_reject_non_integer_scroll_value(self):
        command = PlaywrightCommand(
            command_type=CommandType.SCROLL, target="", value="300"
        )
        with pytest.raises(ValueError, match="integer"):
            AWIPlaywrightBridge._scroll_offsets(command)


class TestTranslateDispatch:
    @pytest.mark.asyncio
    async def test_unknown_session_raises(self, bridge):
        with pytest.raises(ValueError, match="not found"):
            await bridge.translate_action(
                session_id="missing", action="scroll", parameters={}
            )

    @pytest.mark.asyncio
    async def test_unsupported_action_raises(self, bridge):
        session = _seat(bridge)
        with pytest.raises(ValueError, match="Unsupported AWI action"):
            await bridge.translate_action(
                session_id=session.session_id,
                action="do_anything",
                parameters={},
            )

    @pytest.mark.asyncio
    async def test_add_to_cart_without_element_raises(self, bridge, monkeypatch):
        session = _seat(bridge)
        _stub_semantic(monkeypatch, bridge, None)
        with pytest.raises(ValueError, match="No add-to-cart element"):
            await bridge.translate_action(
                session_id=session.session_id,
                action="add_to_cart",
                parameters={},
            )

    @pytest.mark.asyncio
    async def test_add_to_cart_with_element_clicks(self, bridge, monkeypatch):
        session = _seat(bridge)
        _stub_semantic(monkeypatch, bridge, _element())
        commands = await bridge.translate_action(
            session_id=session.session_id,
            action="add_to_cart",
            parameters={},
        )
        assert len(commands) == 1
        assert commands[0].command_type == CommandType.CLICK
        assert commands[0].target == "#add-cart"

    @pytest.mark.asyncio
    async def test_navigate_to_requires_url(self, bridge):
        session = _seat(bridge)
        with pytest.raises(ValueError, match="URL required"):
            await bridge.translate_action(
                session_id=session.session_id,
                action="navigate_to",
                parameters={},
            )

    @pytest.mark.asyncio
    async def test_navigate_to_blocked_url_raises(self, bridge, monkeypatch):
        session = _seat(bridge)
        monkeypatch.setattr(
            bridge_module,
            "check_outbound_url",
            AsyncMock(return_value="private_host_blocked"),
        )
        with pytest.raises(ValueError, match="navigation blocked"):
            await bridge.translate_action(
                session_id=session.session_id,
                action="navigate_to",
                parameters={"url": "https://example.com/"},
            )

    @pytest.mark.asyncio
    async def test_explicit_selector_actions_require_selector(self, bridge):
        session = _seat(bridge)
        for action in ("click_element", "fill_field", "hover_element"):
            with pytest.raises(ValueError, match="selector required"):
                await bridge.translate_action(
                    session_id=session.session_id,
                    action=action,
                    parameters={},
                )


class TestSessionLifecycle:
    @pytest.mark.asyncio
    async def test_create_and_destroy_session(self, bridge):
        session = await bridge.create_session("https://example.com")
        assert session.current_url == "https://example.com"
        assert await bridge.destroy_session(session.session_id) is True
        assert await bridge.destroy_session(session.session_id) is False

    @pytest.mark.asyncio
    async def test_create_session_rejects_bad_viewport(self, bridge):
        with pytest.raises(ValueError, match="viewport"):
            await bridge.create_session("https://example.com", viewport=(10, 10))

    @pytest.mark.asyncio
    async def test_create_session_enforces_max_sessions(self, monkeypatch):
        monkeypatch.setattr(
            bridge_module, "check_outbound_url", AsyncMock(return_value=None)
        )
        small = AWIPlaywrightBridge(mode=TranslationMode.CDP_DIRECT, max_sessions=1)
        first = await small.create_session("https://example.com")
        with pytest.raises(BrowserSessionLimitExceeded):
            await small.create_session("https://example.org")
        assert await small.destroy_session(first.session_id) is True

    @pytest.mark.asyncio
    async def test_list_sessions(self, bridge):
        session = await bridge.create_session("https://example.com")
        listed = await bridge.list_sessions()
        assert [entry["session_id"] for entry in listed] == [session.session_id]
        assert await bridge.destroy_session(session.session_id) is True


class TestPreviewAndHelpers:
    @pytest.mark.asyncio
    async def test_preview_redacts_sensitive_fill(self, bridge, monkeypatch):
        session = _seat(bridge)

        async def _find(session, semantic_type):
            if semantic_type == "password_input":
                return _element(
                    tag="input",
                    text_content="",
                    attributes={"type": "password"},
                    css_selector="#pw",
                )
            return None

        monkeypatch.setattr(bridge, "_find_semantic_element", _find)
        preview = await bridge.preview_action(
            session_id=session.session_id,
            action="fill_form",
            parameters={"data": {"password": "hunter2"}},
        )
        assert preview["commands"][0]["value"] == "[REDACTED]"

    @pytest.mark.asyncio
    async def test_execute_unknown_session_fails(self, bridge):
        result = await bridge.execute_commands(session_id="missing", commands=[])
        assert result.success is False
        assert result.commands_executed == 0

    def test_classify_page_type(self, bridge):
        assert (
            bridge._classify_page_type(
                BridgeSession(session_id="s", current_url="https://example.com/login")
            )
            == "login"
        )
        assert (
            bridge._classify_page_type(
                BridgeSession(
                    session_id="s", current_url="https://example.com/checkout"
                )
            )
            == "checkout"
        )
        assert (
            bridge._classify_page_type(
                BridgeSession(session_id="s", current_url="https://example.com/about")
            )
            == "generic"
        )

    def test_sort_mapping_known_and_unknown(self, bridge):
        assert bridge._get_sort_option_value("price_low") == "price-asc"
        assert bridge._get_sort_option_value("something_new") == "something_new"

    def test_element_id_stable_short_hex(self):
        element = _element()
        first = element.element_id
        assert len(first) == 12
        assert element.element_id == first
        assert element.element_id != _element(text_content="Other").element_id
