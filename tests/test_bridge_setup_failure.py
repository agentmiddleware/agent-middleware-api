"""Pattern 10: a DOM bridge session that never opened must not read as created.

AWIPlaywrightBridge.create_session used to swallow browser setup failures and
return the session, so POST /v1/awi/dom/session answered 201 for a browser
that was never opened. It must raise BridgeSetupError and leave no partial
session behind instead.
"""

from __future__ import annotations

import pytest

from app.services.awi_playwright_bridge import (
    AWIPlaywrightBridge,
    BridgeSetupError,
)

TARGET = "http://localhost:9999/console"


@pytest.fixture()
def bridge(monkeypatch: pytest.MonkeyPatch) -> AWIPlaywrightBridge:
    import app.services.awi_playwright_bridge as bridge_module

    async def allow(_url: str) -> None:
        return None

    async def no_init() -> None:
        return None

    monkeypatch.setattr(bridge_module, "check_outbound_url", allow)
    instance = AWIPlaywrightBridge()
    monkeypatch.setattr(instance, "_init_playwright", no_init)
    return instance


async def test_setup_error_raises_and_evicts_session(
    bridge: AWIPlaywrightBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_context(session, headless, viewport) -> None:
        raise RuntimeError("browser launch failed")

    async def fail_navigate(session, url) -> None:
        raise AssertionError("must not navigate after a failed setup")

    monkeypatch.setattr(bridge, "_create_browser_context", fail_context)
    monkeypatch.setattr(bridge, "_navigate_to", fail_navigate)
    with pytest.raises(BridgeSetupError):
        await bridge.create_session(TARGET)
    assert bridge._sessions == {}


async def test_missing_live_page_raises_and_evicts_session(
    bridge: AWIPlaywrightBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def noop_context(session, headless, viewport) -> None:
        return None

    async def noop_navigate(session, url) -> None:
        return None

    monkeypatch.setattr(bridge, "_create_browser_context", noop_context)
    monkeypatch.setattr(bridge, "_navigate_to", noop_navigate)
    with pytest.raises(BridgeSetupError, match="no live page"):
        await bridge.create_session(TARGET)
    assert bridge._sessions == {}


async def test_live_page_still_creates_session(
    bridge: AWIPlaywrightBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = object()

    async def fake_context(session, headless, viewport) -> None:
        session._page = sentinel
        session.browser_context_id = "ctx-1"
        session.page_id = "page-1"

    async def fake_navigate(session, url) -> None:
        session.current_url = url

    monkeypatch.setattr(bridge, "_create_browser_context", fake_context)
    monkeypatch.setattr(bridge, "_navigate_to", fake_navigate)
    session = await bridge.create_session(TARGET)
    assert session._page is sentinel
    assert bridge._sessions[session.session_id] is session
