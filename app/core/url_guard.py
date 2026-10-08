"""Outbound-URL guard for agent-driven navigation and proxied requests.

Agent-supplied URLs reach two genuinely dangerous sinks: the AWI Playwright
bridge (a real headless browser that will happily open ``file://`` and
intranet URLs) and the behavioral sandbox's HTTP proxy mode (a raw
``aiohttp`` request). Both run inside our infrastructure, so an unchecked
URL is an SSRF primitive against link-local metadata services, RFC1918
networks, and the host filesystem.

``check_outbound_url`` returns ``None`` when the URL is safe to fetch and a
short machine-readable reason string when it must be blocked. Scheme and
literal-address checks are unconditional; hostname checks resolve DNS and
block names that resolve to non-global addresses. Resolution failure fails
closed (``dns_resolution_failed``): the guard cannot vouch for a name it
could not resolve, and the fetching client (a headless browser with its own
resolver, or a later retry) may well resolve it — possibly to an intranet
address. This matches the upstream MCP URL guard. Tests that exercise
public hostnames pin ``_resolve_host`` instead of relying on live DNS. This
is a pre-flight guard, not a substitute for network-level egress policy,
and it intentionally does not try to defeat DNS rebinding.

Setting ``ALLOW_PRIVATE_NETWORK_TARGETS=true`` (local development against
mock servers) skips only the private-address checks; non-http(s) schemes
such as ``file://`` and ``javascript:`` are never allowed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json as _json
import socket
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import get_settings

_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal")


def _address_blocked(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    # is_global is False for loopback, RFC1918/ULA, link-local (including
    # 169.254.169.254 metadata), CGNAT shared space, reserved, and unspecified
    # addresses. Multicast needs an explicit check: it can be classified global.
    return ip.is_multicast or not ip.is_global


async def _resolve_host(host: str):
    """Resolve a hostname through the event loop; split out for deterministic tests."""

    return await asyncio.get_running_loop().getaddrinfo(
        host, None, type=socket.SOCK_STREAM
    )


async def check_outbound_url(url: str) -> str | None:
    """Return a block reason for an agent-supplied outbound URL, or None."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "unparseable_url"

    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        return "scheme_not_allowed"

    host = parts.hostname
    if not host:
        return "missing_host"

    if get_settings().ALLOW_PRIVATE_NETWORK_TARGETS:
        return None

    host = host.strip("[]").rstrip(".").lower()
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_SUFFIXES):
        return "private_host_blocked"

    if _address_blocked(host):
        return "private_address_blocked"

    try:
        ipaddress.ip_address(host)
    except ValueError:
        # A hostname, not a literal address: resolve it and require every
        # resolved address to be globally routable.
        try:
            infos = await _resolve_host(host)
        except (OSError, UnicodeError):
            # socket.gaierror is an OSError; UnicodeError covers names the
            # IDNA codec rejects (e.g. an over-long label). Fail closed.
            return "dns_resolution_failed"
        for info in infos:
            if _address_blocked(str(info[4][0])):
                return "private_address_blocked"

    return None


# ---------------------------------------------------------------------------
# safe_fetch: the one shared outbound fetcher
# ---------------------------------------------------------------------------
#
# ``check_outbound_url`` above is a pre-flight check only: a plain client
# still re-resolves DNS at connect time (rebinding gap) and reads unbounded
# bodies. Every outbound fetch in app/ must go through ``safe_fetch``,
# which closes those gaps:
#
# - validates each URL (including every redirect hop) with the guard,
# - resolves the hostname itself and opens the connection to that literal
#   IP while keeping the original Host header and TLS SNI, so a changed
#   DNS answer between check and connect cannot steer the request inside,
# - caps the response body (content-length pre-check plus a streaming cap),
# - never follows redirects blindly (each hop is revalidated, limited count).
#
# Transport errors (DNS failure at pin time, connect errors, timeouts)
# propagate as ``httpx.HTTPError`` so callers keep their existing retry and
# logging behavior. Guard, redirect and size violations raise
# ``SafeFetchError`` with a short machine-readable ``reason`` that never
# contains the URL, credentials or body.

SAFE_FETCH_DEFAULT_MAX_BYTES = 1_048_576
SAFE_FETCH_DEFAULT_TIMEOUT_SECONDS = 10.0
SAFE_FETCH_DEFAULT_MAX_REDIRECTS = 3

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_CREDENTIAL_HEADERS = frozenset({"authorization", "cookie", "x-api-key"})


class SafeFetchError(Exception):
    """Refusal or limit violation from ``safe_fetch``. ``reason`` is stable."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class SafeFetchResponse:
    """Small bounded response from ``safe_fetch``."""

    status_code: int
    url: str
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    _request: httpx.Request | None = field(default=None, repr=False)

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")

    def json(self) -> Any:
        return _json.loads(self.text())

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 600:
            request = self._request or httpx.Request("GET", self.url)
            response = httpx.Response(
                self.status_code,
                headers=self.headers,
                content=self.body,
                request=request,
            )
            raise httpx.HTTPStatusError(
                f"safe fetch returned HTTP {self.status_code}",
                request=request,
                response=response,
            )


async def _pinned_target(url: str) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Return (fetch URL, extra headers, extensions) pinned to one IP.

    Raises ``SafeFetchError`` when the host cannot be pinned to a globally
    routable address. Literal global IPs pass through unchanged.
    """
    parts = urlsplit(url)
    raw_host = parts.hostname or ""
    host = raw_host.strip("[]").rstrip(".").lower()
    try:
        ipaddress.ip_address(host)
        return url, {}, {}
    except ValueError:
        pass
    try:
        infos = await _resolve_host(host)
    except (OSError, UnicodeError):
        raise SafeFetchError("dns_resolution_failed") from None
    pinned: str | None = None
    for info in infos:
        candidate = str(info[4][0])
        if not _address_blocked(candidate):
            pinned = candidate
            break
    if pinned is None:
        raise SafeFetchError("blocked:private_address_blocked")
    parsed = httpx.URL(url)
    # Host header carries hostname and port only, never URL userinfo.
    host_header = host if parts.port is None else f"{host}:{parts.port}"
    target = str(parsed.copy_with(host=pinned))
    extra = {"host": host_header}
    extensions: dict[str, Any] = {}
    if parsed.scheme == "https":
        # Keep TLS SNI on the real hostname while TCP goes to the pinned IP.
        extensions["sni_hostname"] = host
    return target, extra, extensions


def _same_origin(left: str, right: str) -> bool:
    try:
        a, b = urlsplit(left), urlsplit(right)
    except ValueError:
        return False
    return (a.scheme.lower(), a.hostname or "", a.port) == (
        b.scheme.lower(),
        b.hostname or "",
        b.port,
    )


async def safe_fetch(
    url: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    content: bytes | None = None,
    json_body: Any = None,
    timeout: float = SAFE_FETCH_DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = SAFE_FETCH_DEFAULT_MAX_BYTES,
    max_redirects: int = SAFE_FETCH_DEFAULT_MAX_REDIRECTS,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SafeFetchResponse:
    """Fetch one URL with SSRF pinning, redirect revalidation and a size cap."""
    current_url = url
    current_method = method.upper()
    current_content = content
    current_json: Any = json_body
    base_headers = dict(headers or {})
    hops = 0

    # The default client is built from parameters, not an explicit transport,
    # so the established test seam (patching httpx.AsyncClient with a
    # MockTransport-backed factory) keeps working for every caller.
    if transport is None:
        client_cm = httpx.AsyncClient(
            verify=True, trust_env=False, follow_redirects=False, timeout=timeout
        )
    else:
        client_cm = httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            timeout=timeout,
            trust_env=False,
        )
    async with client_cm as client:
        while True:
            block_reason = await check_outbound_url(current_url)
            if block_reason is not None:
                raise SafeFetchError(f"blocked:{block_reason}")
            target, pin_headers, extensions = await _pinned_target(current_url)
            send_headers = dict(base_headers)
            if not _same_origin(url, current_url):
                for name in list(send_headers):
                    if name.lower() in _CREDENTIAL_HEADERS:
                        send_headers.pop(name)
            send_headers.update(pin_headers)
            request = client.build_request(
                current_method,
                target,
                headers=send_headers,
                content=current_content,
                json=current_json,
                extensions=extensions or None,
            )
            response = await client.send(request, stream=True)
            location = response.headers.get("location")
            if response.status_code in _REDIRECT_STATUSES and location:
                await response.aclose()
                if hops >= max_redirects:
                    raise SafeFetchError("redirect_limit")
                hops += 1
                next_url = urljoin(current_url, location)
                if response.status_code == 303 or (
                    response.status_code in (301, 302) and current_method == "POST"
                ):
                    current_method = "GET"
                    current_content = None
                    current_json = None
                current_url = next_url
                continue
            declared = response.headers.get("content-length")
            if declared is not None:
                try:
                    if int(declared) > max_bytes:
                        await response.aclose()
                        raise SafeFetchError("too_large")
                except ValueError:
                    pass
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > max_bytes:
                    await response.aclose()
                    raise SafeFetchError("too_large")
            await response.aclose()
            return SafeFetchResponse(
                status_code=response.status_code,
                url=current_url,
                body=body,
                headers=dict(response.headers),
                _request=request,
            )
