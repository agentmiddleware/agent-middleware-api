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
block names that resolve to non-global addresses. Resolution failure is
treated as allow (the subsequent connection will fail identically, and it
keeps offline test runs deterministic) — this is a pre-flight guard, not a
substitute for network-level egress policy, and it intentionally does not
try to defeat DNS rebinding.

Setting ``ALLOW_PRIVATE_NETWORK_TARGETS=true`` (local development against
mock servers) skips only the private-address checks; non-http(s) schemes
such as ``file://`` and ``javascript:`` are never allowed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

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
    # 169.254.169.254 metadata), CGNAT shared space, multicast, reserved,
    # and unspecified addresses.
    return not ip.is_global


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
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, None, type=socket.SOCK_STREAM
            )
        except socket.gaierror:
            return None
        for info in infos:
            if _address_blocked(str(info[4][0])):
                return "private_address_blocked"

    return None
