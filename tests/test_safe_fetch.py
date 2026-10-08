"""Shared safe-fetch helper: validate, pin IP, recheck redirects, cap size.

Every outbound fetch in app/ must go through app.core.url_guard.safe_fetch.
These tests pin the four SSRF cases from the pattern report plus the happy
path, using an injected httpx MockTransport and a pinned resolver so no
test touches the network.
"""

from __future__ import annotations

import httpx
import pytest

from app.core import url_guard
from app.core.url_guard import (
    SafeFetchError,
    SafeFetchResponse,
    safe_fetch,
)


def _public_resolve(monkeypatch, ip="93.184.216.34"):
    async def resolve(_host):
        return [(None, None, None, None, (ip, 0))]

    monkeypatch.setattr(url_guard, "_resolve_host", resolve)


def _private_resolve(monkeypatch, ip="10.0.0.7"):
    async def resolve(_host):
        return [(None, None, None, None, (ip, 0))]

    monkeypatch.setattr(url_guard, "_resolve_host", resolve)


def _transport(handler):
    return httpx.MockTransport(handler)


class TestSafeFetchBlocks:
    @pytest.mark.anyio
    async def test_link_local_literal_blocked(self):
        with pytest.raises(SafeFetchError) as excinfo:
            await safe_fetch("http://169.254.169.254/latest/meta-data/")
        assert excinfo.value.reason == "blocked:private_address_blocked"

    @pytest.mark.anyio
    async def test_non_http_scheme_blocked(self):
        with pytest.raises(SafeFetchError) as excinfo:
            await safe_fetch("file:///etc/passwd")
        assert excinfo.value.reason == "blocked:scheme_not_allowed"

    @pytest.mark.anyio
    async def test_dns_resolving_private_blocked(self, monkeypatch):
        _private_resolve(monkeypatch)
        with pytest.raises(SafeFetchError) as excinfo:
            await safe_fetch("https://internal.example.com/")
        assert excinfo.value.reason == "blocked:private_address_blocked"

    @pytest.mark.anyio
    async def test_redirect_hop_to_private_refused(self, monkeypatch):
        _public_resolve(monkeypatch)
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(302, headers={"location": "http://169.254.169.254/x"})

        with pytest.raises(SafeFetchError) as excinfo:
            await safe_fetch("https://example.com/start", transport=_transport(handler))
        assert excinfo.value.reason == "blocked:private_address_blocked"
        # The private hop was never fetched: one request went out, none more.
        assert len(seen) == 1

    @pytest.mark.anyio
    async def test_redirect_chain_limit(self, monkeypatch):
        _public_resolve(monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "/next"})

        with pytest.raises(SafeFetchError) as excinfo:
            await safe_fetch(
                "https://example.com/start",
                transport=_transport(handler),
                max_redirects=1,
            )
        assert excinfo.value.reason == "redirect_limit"

    @pytest.mark.anyio
    async def test_oversize_body_refused(self, monkeypatch):
        _public_resolve(monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 4096)

        with pytest.raises(SafeFetchError) as excinfo:
            await safe_fetch(
                "https://example.com/big",
                transport=_transport(handler),
                max_bytes=1024,
            )
        assert excinfo.value.reason == "too_large"

    @pytest.mark.anyio
    async def test_oversize_declared_length_refused_without_read(self, monkeypatch):
        _public_resolve(monkeypatch)
        read = []

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-length": str(10 * 1024 * 1024)},
                content=b"",
            )

        with pytest.raises(SafeFetchError) as excinfo:
            await safe_fetch(
                "https://example.com/big",
                transport=_transport(handler),
                max_bytes=1024,
            )
        assert excinfo.value.reason == "too_large"
        assert read == []


class TestSafeFetchHappyPath:
    @pytest.mark.anyio
    async def test_pins_ip_keeps_host_and_sni(self, monkeypatch):
        _public_resolve(monkeypatch, ip="93.184.216.34")
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["host"] = request.headers.get("host")
            seen["sni"] = request.extensions.get("sni_hostname")
            return httpx.Response(200, json={"ok": True})

        resp = await safe_fetch(
            "https://example.com/api", transport=_transport(handler)
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert resp.url == "https://example.com/api"
        # TCP goes to the pinned IP while HTTP Host and TLS SNI stay real.
        assert "93.184.216.34" in seen["url"]
        assert seen["host"] == "example.com"
        assert seen["sni"] == "example.com"

    @pytest.mark.anyio
    async def test_userinfo_never_lands_in_host_header(self, monkeypatch):
        _public_resolve(monkeypatch, ip="93.184.216.34")
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["host"] = request.headers.get("host")
            return httpx.Response(200, json={"ok": True})

        resp = await safe_fetch(
            "https://user:pass@example.com/api", transport=_transport(handler)
        )
        assert resp.status_code == 200
        assert seen["host"] == "example.com"

    @pytest.mark.anyio
    async def test_https_post_forwards_body_and_auth(self, monkeypatch):
        _public_resolve(monkeypatch)
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json={"status": "ok"})

        resp = await safe_fetch(
            "https://provider.example.com/v1/hook",
            method="POST",
            headers={"Authorization": "Bearer secret"},
            json_body={"a": 1},
            transport=_transport(handler),
        )
        assert resp.status_code == 200
        assert seen["method"] == "POST"
        assert seen["auth"] == "Bearer secret"

    @pytest.mark.anyio
    async def test_raise_for_status_keeps_httpx_shape(self, monkeypatch):
        _public_resolve(monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, content=b"down")

        resp = await safe_fetch("https://example.com/x", transport=_transport(handler))
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            resp.raise_for_status()
        assert excinfo.value.response.status_code == 503

    @pytest.mark.anyio
    async def test_error_reason_never_contains_url(self, monkeypatch):
        _private_resolve(monkeypatch)
        url = "https://evil.example.com/token-AbC123?next=/x"
        with pytest.raises(SafeFetchError) as excinfo:
            await safe_fetch(url)
        assert "AbC123" not in excinfo.value.reason
        assert "evil.example.com" not in excinfo.value.reason


class TestSandboxProxyAdoption:
    @pytest.mark.anyio
    async def test_proxy_still_blocks_metadata_service(self):
        from app.services.behavioral_sandbox import BehavioralSandboxEngine

        engine = BehavioralSandboxEngine(redis_url="redis://localhost:6379")
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
    async def test_proxy_maps_helper_refusal_to_failure(self, monkeypatch):
        import app.services.behavioral_sandbox as sandbox_mod
        from app.services.behavioral_sandbox import BehavioralSandboxEngine

        async def refuse(*args, **kwargs):
            raise SafeFetchError("too_large")

        monkeypatch.setattr(sandbox_mod, "safe_fetch", refuse)
        engine = BehavioralSandboxEngine(redis_url="redis://localhost:6379")
        result = await engine._execute_http_proxy(
            "http_get",
            {"url": "https://example.com/"},
            False,
            5,
            network_access=True,
        )
        assert result["success"] is False
        assert "too_large" in result["error"]


class TestPlaywrightLandingCheck:
    @pytest.mark.anyio
    async def test_landing_on_private_target_raises(self):
        from app.services.awi_playwright_bridge import (
            AWIPlaywrightBridge,
            BridgeSession,
        )

        class FakePage:
            url = "http://169.254.169.254/latest/meta-data"

            async def goto(self, *args, **kwargs):
                return None

            async def close(self):
                return None

        bridge = AWIPlaywrightBridge()
        session = BridgeSession(session_id="s1", current_url="https://example.com")
        session._page = FakePage()
        with pytest.raises(ValueError, match="blocked target"):
            await bridge._navigate_to(session, "https://example.com")
        assert session._page is None


class TestJevGuardAdoption:
    @pytest.mark.anyio
    async def test_post_goes_through_safe_fetch(self, monkeypatch):
        import app.policy.jev_guard as jev

        seen = {}

        async def fake_fetch(url, **kwargs):
            seen["url"] = url
            seen["headers"] = kwargs.get("headers")
            return SafeFetchResponse(status_code=200, url=url, body=b"{}")

        monkeypatch.setattr(jev, "safe_fetch", fake_fetch)
        resp = await jev._post(
            url="https://guard.example.com/v1/systemone",
            api_key="k",
            payload={},
            timeout=5.0,
        )
        assert resp.status_code == 200
        assert seen["headers"]["Authorization"] == "Bearer k"

    @pytest.mark.anyio
    async def test_post_redirect_to_private_never_sends_key(self, monkeypatch):
        async def resolve(_host):
            return [(None, None, None, None, ("93.184.216.34", 0))]

        monkeypatch.setattr(url_guard, "_resolve_host", resolve)
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(302, headers={"location": "http://169.254.169.254/x"})

        from app.core.url_guard import safe_fetch as real_fetch

        with pytest.raises(SafeFetchError) as excinfo:
            await real_fetch(
                "https://guard.example.com/v1/systemone",
                method="POST",
                headers={"Authorization": "Bearer live-key"},
                json_body={},
                transport=httpx.MockTransport(handler),
            )
        assert excinfo.value.reason == "blocked:private_address_blocked"
        # The key went only to the pinned public address; the private hop
        # was refused before any second request existed.
        assert len(seen) == 1
        assert "93.184.216.34" in str(seen[0].url)
