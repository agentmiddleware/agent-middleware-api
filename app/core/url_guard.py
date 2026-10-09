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

Two local-development flags relax the guard without ever lifting the
cloud-metadata blocks:

- ``ALLOW_PRIVATE_NETWORK_TARGETS=true`` allows literal private addresses
  (for example a mock server on ``http://127.0.0.1:8000/``) and names that
  resolve to private addresses, but blocked names and every metadata
  address stay blocked.
- ``ALLOW_PRIVATE_NETWORK_NAMES=true`` allows blocked name shapes such as
  ``localhost`` or ``*.internal``, but names that resolve to private
  addresses still need ``ALLOW_PRIVATE_NETWORK_TARGETS``, and metadata
  hostnames stay blocked.

Non-http(s) schemes such as ``file://`` and ``javascript:`` are never
allowed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from app.core.config import get_settings

_ALLOWED_SCHEMES = {"http", "https"}
# Cloud metadata hostnames stay blocked under either local-dev flag.
# metadata.goog is the short GCP alias for the same metadata server as
# metadata.google.internal.
_METADATA_HOSTNAMES = {"metadata.google.internal", "metadata.goog"}
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "metadata.goog"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal")
# Cloud metadata addresses stay blocked under either local-dev flag, even
# when the address looks globally routable (168.63.129.16, the Azure
# metadata address, is classified global by the stdlib).
_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("168.63.129.16"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)


def _address_blocked(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    # is_global is False for loopback, RFC1918/ULA, link-local (including
    # 169.254.169.254 metadata), CGNAT shared space, reserved, and unspecified
    # addresses. Multicast needs an explicit check: it can be classified global.
    return ip.is_multicast or not ip.is_global


def _is_metadata_address(value: str) -> bool:
    """True when a literal or resolved address is a cloud metadata address."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if ip in _METADATA_ADDRESSES:
        return True
    mapped = getattr(ip, "ipv4_mapped", None)
    return mapped is not None and mapped in _METADATA_ADDRESSES


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

    settings = get_settings()
    host = host.strip("[]").rstrip(".").lower()

    # Metadata hostnames are never allowed, under either local-dev flag.
    if host in _METADATA_HOSTNAMES:
        return "private_host_blocked"
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_SUFFIXES):
        if not settings.ALLOW_PRIVATE_NETWORK_NAMES:
            return "private_host_blocked"

    try:
        ipaddress.ip_address(host)
        is_literal = True
    except ValueError:
        is_literal = False

    if is_literal:
        # Metadata addresses are never allowed, under either local-dev flag.
        if _is_metadata_address(host):
            return "private_address_blocked"
        if _address_blocked(host):
            if not settings.ALLOW_PRIVATE_NETWORK_TARGETS:
                return "private_address_blocked"
        return None

    # A hostname, not a literal address: resolve it and check every
    # resolved address before applying any flag allowance, so a name
    # that resolves to a metadata address stays blocked.
    try:
        infos = await _resolve_host(host)
    except (OSError, UnicodeError):
        # socket.gaierror is an OSError; UnicodeError covers names the
        # IDNA codec rejects (e.g. an over-long label). Fail closed.
        return "dns_resolution_failed"
    for info in infos:
        resolved = str(info[4][0])
        if _is_metadata_address(resolved):
            return "private_address_blocked"
        if _address_blocked(resolved):
            if not settings.ALLOW_PRIVATE_NETWORK_TARGETS:
                return "private_address_blocked"

    return None
