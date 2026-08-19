"""Contracts for the human-first marketing and portable-proof site."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
import runpy

import pytest

from app.routers.well_known import _local_try_it_manifest, get_agent_first_metadata


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
CANONICAL_API = "https://api.thisisatest.tech"
CANONICAL_MARKETING_SITE = "https://www.thisisatest.tech/"
KNOWN_PROVIDER_HOSTS = (
    "api-service-production-433c.up.railway.app",
    "agent-middleware-web.vercel.app",
    "site-tawny-seven-33.vercel.app",
)
PROVIDER_HOST_SUFFIXES = (".railway.app", ".vercel.app")
VALID_TEST_CONTACTS = {
    "PUBLIC_DISPLAY_NAME": "Design Partner Labs LLC",
    "PUBLIC_CONTACT_EMAIL": "operator@design-partner-labs.org",
    "PUBLIC_BOOKING_URL": "https://cal.com/design-partner-labs/one-tool-pilot",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(" ".join(data.split()))


def _page_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return " ".join(parser.parts)


def _render_site(output: Path, contacts: dict[str, str] | None = None):
    environment = dict(os.environ)
    for name in (*VALID_TEST_CONTACTS, "PUBLIC_ENABLE_VERCEL_ANALYTICS"):
        environment.pop(name, None)
    if contacts:
        environment.update(contacts)
    return subprocess.run(
        [sys.executable, str(SITE / "build_site.py"), "--output", str(output)],
        cwd=SITE,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        assert handle.read(8) == b"\x89PNG\r\n\x1a\n"
        length = struct.unpack(">I", handle.read(4))[0]
        assert handle.read(4) == b"IHDR"
        width, height = struct.unpack(">II", handle.read(8))
        assert length == 13
    return width, height


def test_site_build_blocks_missing_and_provisional_contacts(tmp_path) -> None:
    missing = _render_site(tmp_path / "missing")
    assert missing.returncode == 2
    assert "missing required launch contact values" in missing.stderr

    bad_contacts = dict(VALID_TEST_CONTACTS)
    bad_contacts["PUBLIC_CONTACT_EMAIL"] = "test@example.com"
    provisional = _render_site(tmp_path / "provisional", bad_contacts)
    assert provisional.returncode == 2
    assert "contains a provisional value" in provisional.stderr

    for field, value in (
        ("PUBLIC_DISPLAY_NAME", "Test Operator"),
        ("PUBLIC_CONTACT_EMAIL", "operator@company.test"),
        ("PUBLIC_CONTACT_EMAIL", "operator@company.invalid"),
        ("PUBLIC_BOOKING_URL", "https://calendar.company.test/pilot"),
        ("PUBLIC_BOOKING_URL", "https://calendar.invalid/pilot"),
    ):
        reserved = dict(VALID_TEST_CONTACTS)
        reserved[field] = value
        rejected = _render_site(tmp_path / f"reserved-{field}-{len(value)}", reserved)
        assert rejected.returncode == 2


def test_site_build_refuses_repo_and_existing_temp_delete_targets(tmp_path) -> None:
    build_module = runpy.run_path(str(SITE / "build_site.py"))
    launch_configuration_error = build_module["LaunchConfigurationError"]
    validate_output_path = build_module["_validated_output_path"]
    existing_peer = tmp_path / "existing-peer"
    existing_peer.mkdir()
    sentinel = existing_peer / "do-not-delete.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    for dangerous in (
        ROOT,
        SITE,
        ROOT / "app" / "generated-site-build-test",
        SITE / "proof" / "generated-site-build-test",
        existing_peer,
        Path(tempfile.gettempdir()),
    ):
        with pytest.raises(launch_configuration_error):
            validate_output_path(dangerous)

    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_rendered_landing_is_human_first_and_has_a_working_funnel(tmp_path) -> None:
    output = tmp_path / "site"
    result = _render_site(output, VALID_TEST_CONTACTS)
    assert result.returncode == 0, result.stderr

    page = (output / "index.html").read_text(encoding="utf-8")
    text = _page_text(page)
    headline = "Authorize one agent action. Charge it once. Prove what happened."
    failure = (
        "Your agent invokes a costly tool. The request times out. Was it dispatched? "
        "Should the agent retry? Will the retry create another debit?"
    )
    boundary = (
        "Agent Middleware API is a gateway between your agents and your paid MCP "
        "(Model Context Protocol) tools. The first call executes and is charged "
        "once; a retry carrying the same idempotency key cannot dispatch again or "
        "debit again. Every completed call returns a signed receipt you can verify "
        "offline."
    )

    assert headline in text
    assert failure in text
    assert boundary in text
    assert "Book a one-tool pilot" in text
    assert "Verify our receipt yourself — offline" in text
    # One label for the booking CTA everywhere; the shorter "Book a pilot" and
    # "Discuss fit" variants drifted away from the differentiator.
    assert "Book a pilot" not in text
    assert "Discuss fit" not in text
    assert "platform engineering, AI infrastructure, and security teams" in text
    assert f'href="{VALID_TEST_CONTACTS["PUBLIC_BOOKING_URL"]}"' in page
    assert f'href="mailto:{VALID_TEST_CONTACTS["PUBLIC_CONTACT_EMAIL"]}"' in page
    assert VALID_TEST_CONTACTS["PUBLIC_DISPLAY_NAME"] in page

    assert page.index(headline) < page.index('id="pilot"')
    assert page.index('id="pilot"') < page.index('id="machine-discovery"')
    assert page.index('id="proof"') < page.index("Honest limitations")
    assert "@@PUBLIC_" not in page
    assert "Permit provisional" not in page
    for hostname in KNOWN_PROVIDER_HOSTS:
        assert hostname not in page
    for suffix in PROVIDER_HOST_SUFFIXES:
        assert suffix not in page


def test_rendered_site_has_truthful_proof_and_no_browser_secret_storage(
    tmp_path,
) -> None:
    output = tmp_path / "site"
    result = _render_site(output, VALID_TEST_CONTACTS)
    assert result.returncode == 0, result.stderr

    landing = (output / "index.html").read_text(encoding="utf-8")
    proof = (output / "proof" / "index.html").read_text(encoding="utf-8")
    proof_script = (output / "proof" / "proof.js").read_text(encoding="utf-8")
    assert (output / "proof" / "receipt.json").read_bytes() == (
        SITE / "proof" / "receipt.json"
    ).read_bytes()
    assert (output / "proof" / "trust-keys.json").read_bytes() == (
        SITE / "proof" / "trust-keys.json"
    ).read_bytes()

    assert "self-issued live gateway proof, not customer traction" in landing
    assert "This receipt is self-issued from a non-sensitive" in proof
    assert "it is not customer evidence" in proof
    assert "partner.echo" in landing
    assert "/proof/receipt.json" in proof
    assert "/proof/trust-keys.json" in proof
    assert "b2a-verify-receipt" in proof
    assert "--expect-issuer https://api.thisisatest.tech" in proof
    assert 'data-proof-field="receipt_id"' in landing
    assert 'data-proof-field="credits_charged"' in landing
    assert "not published" in proof_script
    assert "No verification claim is being made" in proof_script
    assert "localStorage" not in proof_script
    assert "sessionStorage" not in proof_script
    assert "VALID" not in proof_script
    assert "does not independently authenticate" in proof
    assert "without trusting this page" not in proof


def test_marketing_manifest_points_to_custom_origins_and_local_proof() -> None:
    manifest = json.loads(
        (SITE / ".well-known" / "agent.json").read_text(encoding="utf-8")
    )

    assert manifest["name"] == "agent-middleware-api"
    assert manifest["canonical_api"] == CANONICAL_API
    assert manifest["human_site"] == CANONICAL_MARKETING_SITE
    assert manifest["primary_audience"] == "autonomous_agents"
    assert manifest["buyer_audience"] == [
        "platform_engineering",
        "ai_infrastructure",
        "security_teams_operating_internal_mcp_tools",
    ]
    assert manifest["product_loop"] == get_agent_first_metadata()["product_loop"]
    assert manifest["try_it"] == _local_try_it_manifest()
    # The repository went private in 2026-08; the manifest must say so rather
    # than sending agents to clone a URL that 404s anonymously.
    assert manifest["try_it"]["repository_access"] == "private"
    assert manifest["github_access"] == "private"
    assert manifest["discovery"]["llms_txt"] == f"{CANONICAL_API}/llms.txt"
    assert f"{CANONICAL_API}/llms.txt" in manifest["bootstrap_sequence"]
    assert "awi_manifest" not in manifest["discovery"]


def test_machine_pointer_copies_match_and_state_live_access_boundary() -> None:
    llm_txt = (SITE / "llm.txt").read_text(encoding="utf-8")
    llms_txt = (SITE / "llms.txt").read_text(encoding="utf-8")

    assert llm_txt == llms_txt
    assert "human design-partner site" in llm_txt
    assert "teams operating internal MCP tools are the buyers" in llm_txt
    assert "make prove-trust-plane" in llm_txt
    assert "operator-issued" in llm_txt
    assert "no public self-serve key mint" in llm_txt
    assert CANONICAL_API in llm_txt
    assert CANONICAL_MARKETING_SITE in llm_txt
    for hostname in KNOWN_PROVIDER_HOSTS:
        assert hostname not in llm_txt
    for suffix in PROVIDER_HOST_SUFFIXES:
        assert suffix not in llm_txt


def test_customer_facing_outputs_do_not_publish_provider_origins(tmp_path) -> None:
    output = tmp_path / "site"
    result = _render_site(output, VALID_TEST_CONTACTS)
    assert result.returncode == 0, result.stderr

    public_paths = (
        output / "index.html",
        output / "proof" / "index.html",
        output / "compare" / "index.html",
        output / "concept" / "index.html",
        output / "llm.txt",
        output / "llms.txt",
        output / ".well-known" / "agent.json",
        ROOT / "static" / "llm.txt",
        ROOT / "docs" / "agentmarket-submission.md",
        ROOT / "docs" / "mcp-registry-submission.md",
    )
    for path in public_paths:
        content = path.read_text(encoding="utf-8").casefold()
        for suffix in PROVIDER_HOST_SUFFIXES:
            assert suffix not in content, f"{path} publishes {suffix}"


REPO_URL = "https://github.com/PetrefiedThunder/agent-middleware-api"


def test_public_surfaces_disclose_private_repo_and_avoid_dead_deep_links(
    tmp_path,
) -> None:
    """The source repository went private in 2026-08, so anonymous fetches of
    ``github.com/PetrefiedThunder/...`` return 404. Public surfaces may still
    name the repository as the source of record, but only next to an explicit
    private/request-access disclosure — and never via ``/blob/`` deep links,
    whose targets have live replacements served from the API origin
    (``/WEDGE.md``, ``/SECURITY_LIMITATIONS.md``, ``/DESIGN_PARTNER_GUIDE.md``).
    """
    output = tmp_path / "site"
    result = _render_site(output, VALID_TEST_CONTACTS)
    assert result.returncode == 0, result.stderr

    public_paths = (
        output / "index.html",
        output / "proof" / "index.html",
        output / "compare" / "index.html",
        output / "llm.txt",
        output / "llms.txt",
        output / "llms-full.txt",
        output / ".well-known" / "agent.json",
        output / ".well-known" / "security.txt",
        ROOT / "static" / "llm.txt",
    )
    for path in public_paths:
        content = path.read_text(encoding="utf-8")
        assert f"{REPO_URL}/blob/" not in content, (
            f"{path} deep-links into the private repository; anonymous fetches "
            "404 — link the API-origin copy instead"
        )
        assert "raw.githubusercontent.com" not in content, (
            f"{path} links raw.githubusercontent.com, which 404s on a private "
            "repository"
        )
        if REPO_URL in content:
            lowered = content.casefold()
            assert "private" in lowered and "request" in lowered, (
                f"{path} names the private repository without disclosing that "
                "access must be requested"
            )


def test_dynamic_routes_and_noncanonical_hosts_redirect_correctly() -> None:
    config = json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))
    package = json.loads((SITE / "package.json").read_text(encoding="utf-8"))

    assert config["buildCommand"] == "python3 build_site.py"
    assert config["outputDirectory"] == "dist"
    assert package["private"] is True
    assert package["scripts"]["build"] == config["buildCommand"]

    redirects = config["redirects"]
    dynamic = {entry["source"]: entry for entry in redirects if "has" not in entry}
    expected = {
        "/mcp/tools.json": f"{CANONICAL_API}/mcp/tools.json",
        "/v1/discover": f"{CANONICAL_API}/v1/discover",
        "/openapi.json": f"{CANONICAL_API}/openapi.json",
        "/health/dependencies": f"{CANONICAL_API}/health/dependencies",
    }
    for source, destination in expected.items():
        assert dynamic[source]["destination"] == destination
        assert dynamic[source]["permanent"] is False

    host_redirects = [entry for entry in redirects if "has" in entry]
    by_host = {entry["has"][0]["value"]: entry for entry in host_redirects}
    assert set(by_host) == {
        "thisisatest.tech",
        "agent-middleware-web.vercel.app",
        "site-tawny-seven-33.vercel.app",
    }
    for redirect in by_host.values():
        assert redirect["source"] == "/:path*"
        assert redirect["destination"] == f"{CANONICAL_MARKETING_SITE}:path*"
        assert redirect["permanent"] is True


def test_search_social_and_analytics_contracts(tmp_path) -> None:
    output = tmp_path / "site"
    result = _render_site(output, VALID_TEST_CONTACTS)
    assert result.returncode == 0, result.stderr

    page = (output / "index.html").read_text(encoding="utf-8")
    robots = (output / "robots.txt").read_text(encoding="utf-8")
    sitemap = (output / "sitemap.xml").read_text(encoding="utf-8")
    analytics = (output / "analytics.js").read_text(encoding="utf-8")

    assert '<link rel="canonical" href="https://www.thisisatest.tech/"' in page
    assert 'property="og:url" content="https://www.thisisatest.tech/"' in page
    assert 'name="twitter:card" content="summary_large_image"' in page
    assert "https://www.thisisatest.tech/social-card.png" in page
    assert '<link rel="icon" href="/favicon.svg"' in page
    assert "/_vercel/insights/script.js" not in page
    assert "Sitemap: https://www.thisisatest.tech/sitemap.xml" in robots
    assert "https://www.thisisatest.tech/proof/" in sitemap
    assert "https://www.thisisatest.tech/compare/" in sitemap
    assert _png_dimensions(output / "social-card.png") == (1200, 630)

    for event_name in ("booking_click", "email_click", "proof_click"):
        assert event_name in analytics
        assert f'data-analytics-event="{event_name}"' in page
    assert "dataset.href" not in analytics
    assert "textContent" not in analytics


def test_vercel_insights_loader_requires_explicit_opt_in(tmp_path) -> None:
    """The insights script 404s unless the Vercel project enables analytics."""

    default_output = tmp_path / "default"
    result = _render_site(default_output, VALID_TEST_CONTACTS)
    assert result.returncode == 0, result.stderr
    for relative_path in ("index.html", "proof/index.html", "compare/index.html"):
        page = (default_output / relative_path).read_text(encoding="utf-8")
        assert "/_vercel/insights/script.js" not in page
        assert "/va-init.js" not in page
        assert "@@VERCEL_ANALYTICS_SCRIPTS@@" not in page
        assert '<script defer src="/analytics.js?v=gateway-4"></script>' in page

    enabled_output = tmp_path / "enabled"
    enabled_contacts = dict(VALID_TEST_CONTACTS)
    enabled_contacts["PUBLIC_ENABLE_VERCEL_ANALYTICS"] = "true"
    result = _render_site(enabled_output, enabled_contacts)
    assert result.returncode == 0, result.stderr
    for relative_path in ("index.html", "proof/index.html", "compare/index.html"):
        page = (enabled_output / relative_path).read_text(encoding="utf-8")
        assert '<script defer src="/_vercel/insights/script.js"></script>' in page
        assert '<script src="/va-init.js?v=gateway-4"></script>' in page
        assert "@@VERCEL_ANALYTICS_SCRIPTS@@" not in page

    # "1"/"yes"/"on" aliases are rejected: the documented contract is exactly
    # "true", "false", or unset.
    for invalid_value in ("enable", "1", "yes", "on"):
        invalid_contacts = dict(VALID_TEST_CONTACTS)
        invalid_contacts["PUBLIC_ENABLE_VERCEL_ANALYTICS"] = invalid_value
        rejected = _render_site(tmp_path / f"invalid-{invalid_value}", invalid_contacts)
        assert rejected.returncode == 2, invalid_value
        assert "PUBLIC_ENABLE_VERCEL_ANALYTICS" in rejected.stderr


class _ExternalLinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.missing_rel: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "a":
            return
        attributes = dict(attrs)
        href = (attributes.get("href") or "").strip()
        parsed = urlparse(href)
        # External means an http(s) or protocol-relative href (any scheme
        # casing) pointing at another host; mailto/tel/internal paths are not.
        if parsed.scheme.casefold() not in {"", "http", "https"}:
            return
        if not parsed.netloc:
            return
        if (parsed.hostname or "").casefold() == "www.thisisatest.tech":
            return
        rel_tokens = set((attributes.get("rel") or "").split())
        if not {"noopener", "noreferrer"} <= rel_tokens:
            self.missing_rel.append(href)


def test_external_links_carry_noopener_noreferrer(tmp_path) -> None:
    output = tmp_path / "site"
    result = _render_site(output, VALID_TEST_CONTACTS)
    assert result.returncode == 0, result.stderr

    for relative_path in (
        "index.html",
        "proof/index.html",
        "compare/index.html",
        "concept/index.html",
    ):
        collector = _ExternalLinkCollector()
        collector.feed((output / relative_path).read_text(encoding="utf-8"))
        collector.close()
        assert not collector.missing_rel, (
            f"{relative_path} external links missing rel=noopener noreferrer: "
            f"{collector.missing_rel}"
        )


class _LabeledLinkCollector(HTMLParser):
    """Collect (visible_text, aria_label, href) for every ``<a>`` that carries an
    ``aria-label``. Text inside ``aria-hidden`` descendants (e.g. the decorative
    ``↗`` glyph) is excluded, matching how a screen reader computes the visible
    accessible name.
    """

    def __init__(self) -> None:
        super().__init__()
        self._in_a = False
        self._href = ""
        self._label: str | None = None
        self._text_parts: list[str] = []
        self._hidden_stack: list[bool] = []
        self.labeled_links: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if tag == "a":
            self._in_a = True
            self._href = (attributes.get("href") or "").strip()
            self._label = attributes.get("aria-label")
            self._text_parts = []
            self._hidden_stack = []
        elif self._in_a:
            hidden = str(attributes.get("aria-hidden", "")).strip().lower() == "true"
            self._hidden_stack.append(hidden)

    def handle_data(self, data: str) -> None:
        if self._in_a and not any(self._hidden_stack):
            cleaned = " ".join(data.split())
            if cleaned:
                self._text_parts.append(cleaned)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_a:
            if self._label is not None:
                self.labeled_links.append(
                    (" ".join(self._text_parts), self._label, self._href)
                )
            self._in_a = False
            self._hidden_stack = []
        elif self._in_a and self._hidden_stack:
            self._hidden_stack.pop()


def test_cta_aria_labels_preserve_visible_text_and_booking_url(tmp_path) -> None:
    """WCAG 2.1 Label-in-Name for the rendered CTAs.

    Every ``aria-label`` must contain the link's visible text as a contiguous
    phrase, so voice-control users can still activate a control by speaking its
    visible wording. This is the regression guard for the footer booking CTA,
    whose label once read "Book a 30-minute one-tool pilot call" — which does
    NOT contain the visible phrase "Book a one-tool pilot" — and for every other
    labelled CTA. Booking CTAs must also resolve to the build-time booking URL.
    """
    output = tmp_path / "site"
    result = _render_site(output, VALID_TEST_CONTACTS)
    assert result.returncode == 0, result.stderr

    booking_url = VALID_TEST_CONTACTS["PUBLIC_BOOKING_URL"]
    for relative_path in ("index.html", "proof/index.html", "compare/index.html"):
        collector = _LabeledLinkCollector()
        collector.feed((output / relative_path).read_text(encoding="utf-8"))
        collector.close()
        assert collector.labeled_links, f"{relative_path} exposes no aria-labelled links"
        for visible, label, href in collector.labeled_links:
            assert visible, f"{relative_path}: aria-label {label!r} on a link with no visible text"
            assert visible in label, (
                f"{relative_path}: aria-label {label!r} does not contain the "
                f"visible link text {visible!r} (WCAG 2.1 Label-in-Name)"
            )
            if visible.startswith("Book a"):
                assert href == booking_url, (
                    f"{relative_path}: booking CTA {visible!r} resolves to {href!r}, "
                    f"not the build-time booking URL {booking_url!r}"
                )
        assert any(
            href == booking_url for _visible, _label, href in collector.labeled_links
        ), f"{relative_path}: no CTA resolved to the build-time booking URL"


class _JsonLdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_json_ld = False
        self.payloads: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        self._in_json_ld = tag == "script" and dict(attrs).get("type") == (
            "application/ld+json"
        )

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_json_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_json_ld and data.strip():
            self.payloads.append(data)


def test_pages_publish_valid_json_ld(tmp_path) -> None:
    output = tmp_path / "site"
    result = _render_site(output, VALID_TEST_CONTACTS)
    assert result.returncode == 0, result.stderr

    expected = {
        "index.html": ("WebSite", "https://www.thisisatest.tech/"),
        "proof/index.html": ("WebPage", "https://www.thisisatest.tech/proof/"),
        "compare/index.html": ("WebPage", "https://www.thisisatest.tech/compare/"),
    }
    for relative_path, (schema_type, url) in expected.items():
        collector = _JsonLdCollector()
        collector.feed((output / relative_path).read_text(encoding="utf-8"))
        collector.close()
        assert len(collector.payloads) == 1, f"{relative_path} JSON-LD missing"
        document = json.loads(collector.payloads[0])
        assert document["@context"] == "https://schema.org"
        assert document["@type"] == schema_type
        assert document["url"] == url
        assert document["name"]
        assert document["description"]


class _InlineScriptCollector(HTMLParser):
    """Collect the body of every executable inline ``<script>``.

    ``application/ld+json`` blocks are data, not script: browsers never execute
    them and CSP's ``script-src`` does not block them.
    """

    def __init__(self) -> None:
        super().__init__()
        self._executable = False
        self.inline_scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "script":
            return
        attributes = dict(attrs)
        script_type = (attributes.get("type") or "text/javascript").strip()
        self._executable = "src" not in attributes and script_type in {
            "text/javascript",
            "application/javascript",
            "module",
        }

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._executable = False

    def handle_data(self, data: str) -> None:
        if self._executable and data.strip():
            self.inline_scripts.append(" ".join(data.split())[:80])


def _csp_policy(header_value: str) -> dict[str, str]:
    """Parse a CSP into {directive-name: full-directive}.

    Asserts each directive appears once: a dict keyed on the name silently
    keeps the last, so "style-src *; style-src \'self\'" would pass a test while
    browsers still enforce the permissive first one.
    """

    directives = header_value.split("; ")
    names = [directive.partition(" ")[0] for directive in directives]
    assert len(names) == len(set(names)), f"duplicate CSP directives: {names}"
    return {name: directive for name, directive in zip(names, directives)}


def test_csp_parser_rejects_a_shadowed_directive() -> None:
    """The guard in _csp_policy is what makes every other CSP assertion mean
    something, so it needs a case that actually trips it."""

    with pytest.raises(AssertionError, match="duplicate CSP directives"):
        _csp_policy("style-src *; style-src 'self'")

    # The permissive directive alone must still parse, or the guard would be
    # passing for the wrong reason.
    assert _csp_policy("style-src *")["style-src"] == "style-src *"


def test_site_sends_a_content_security_policy_and_hsts() -> None:
    config = json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))

    global_headers = next(
        entry for entry in config["headers"] if entry["source"] == "/(.*)"
    )
    values = {header["key"]: header["value"] for header in global_headers["headers"]}

    assert "includeSubDomains" in values["Strict-Transport-Security"]
    policy = _csp_policy(values["Content-Security-Policy"])
    assert policy["default-src"] == "default-src 'self'"
    assert policy["object-src"] == "object-src 'none'"
    assert policy["base-uri"] == "base-uri 'none'"
    # The accessibility preload and the analytics shim live in same-origin files
    # precisely so no inline-script escape hatch is needed.
    assert policy["script-src"] == "script-src 'self'"
    assert "'unsafe-inline'" not in values["Content-Security-Policy"]
    # Typography is self-hosted from /fonts, so neither font CDN is permitted.
    assert policy["style-src"] == "style-src 'self'"
    assert policy["font-src"] == "font-src 'self'"
    assert "fonts.googleapis.com" not in values["Content-Security-Policy"]
    assert "fonts.gstatic.com" not in values["Content-Security-Policy"]


def test_pages_carry_no_inline_scripts(tmp_path) -> None:
    """Every executable script must be a same-origin file, for the CSP above."""

    output = tmp_path / "site"
    result = _render_site(output, VALID_TEST_CONTACTS)
    assert result.returncode == 0, result.stderr

    enabled_output = tmp_path / "analytics-on"
    enabled_contacts = dict(VALID_TEST_CONTACTS)
    enabled_contacts["PUBLIC_ENABLE_VERCEL_ANALYTICS"] = "true"
    assert _render_site(enabled_output, enabled_contacts).returncode == 0

    for root in (output, enabled_output):
        for relative_path in (
            "index.html",
            "proof/index.html",
            "compare/index.html",
            "concept/index.html",
            "404.html",
        ):
            collector = _InlineScriptCollector()
            collector.feed((root / relative_path).read_text(encoding="utf-8"))
            collector.close()
            assert not collector.inline_scripts, (
                f"{relative_path} has an inline <script> the CSP would block: "
                f"{collector.inline_scripts}"
            )


def test_static_assets_are_cached_and_html_is_not() -> None:
    config = json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))

    cached_sources = {
        entry["source"]
        for entry in config["headers"]
        for header in entry["headers"]
        if header["key"] == "Cache-Control" and "max-age=604800" in header["value"]
    }
    assert any("styles.css" in source for source in cached_sources)
    assert "/proof/proof.js" in cached_sources

    # Fingerprinting is a query token, so every reference must carry it or the
    # week-long cache would pin visitors to a stale asset. Discover the
    # references rather than listing them: a hand-maintained list silently
    # stops covering each newly added asset, which is exactly the reference
    # that would go stale unnoticed.
    local_asset_reference = re.compile(
        r'(?:src|href)="(/[^"?]+\.(?:css|js))(\?[^"]*)?"'
    )
    for relative_path in (
            "index.html",
            "proof/index.html",
            "compare/index.html",
            "concept/index.html",
            "404.html",
        ):
        page = (SITE / relative_path).read_text(encoding="utf-8")
        references = local_asset_reference.findall(page)
        assert references, f"{relative_path} references no local CSS or JS"
        for asset, query in references:
            assert query.startswith("?v="), (
                f"{relative_path} references {asset} without a ?v= cache token; "
                "returning visitors would keep the old bytes for up to a week"
            )

    # HTML gets no long-lived Cache-Control rule of its own.
    html_rules = [
        entry
        for entry in config["headers"]
        if entry["source"].endswith((".html", "/"))
    ]
    assert not html_rules


def test_trailing_slash_is_canonical_for_subpages() -> None:
    """One canonical URL per subpage, via a redirect rather than the global
    ``trailingSlash`` setting.

    ``trailingSlash: true`` is the obvious way to write this and it is wrong on
    Vercel: it makes every ``/.well-known/*`` entry in ``headers`` stop matching,
    so ``agent.json`` and ``security.txt`` fall back to
    ``max-age=0, must-revalidate`` while every other configured path keeps its
    headers. Confirmed on the deployed site — measured at ``max-age=300`` before
    the setting shipped and ``max-age=0`` after — and on a preview deployment,
    where only the dot-prefixed directory lost its headers.
    """
    config = json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))

    assert "trailingSlash" not in config
    # Because the global setting is off, every directory page needs its own
    # redirect or the un-slashed URL 404s.
    for directory in ("proof", "compare"):
        page = (SITE / directory / "index.html").read_text(encoding="utf-8")
        redirect = next(
            entry
            for entry in config["redirects"]
            if "has" not in entry and entry["source"] == f"/{directory}"
        )
        assert redirect["destination"] == f"/{directory}/"
        assert redirect["permanent"] is True
        assert (
            f'rel="canonical" href="https://www.thisisatest.tech/{directory}/"'
            in page
        )

    # Every dot-prefixed path the headers block configures must actually be
    # served with those headers; a rule that silently stops matching is the
    # failure this test exists to catch.
    configured = {entry["source"] for entry in config["headers"]}
    assert {"/.well-known/agent.json", "/.well-known/security.txt"} <= configured


def test_llms_full_extends_the_short_pointer_without_contradicting_it(
    tmp_path,
) -> None:
    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    short = (output / "llms.txt").read_text(encoding="utf-8")
    full = (output / "llms-full.txt").read_text(encoding="utf-8")

    # The short file has to point at the long one, or nothing will find it.
    assert "https://www.thisisatest.tech/llms-full.txt" in short
    assert len(full) > len(short)
    assert CANONICAL_API in full
    assert CANONICAL_MARKETING_SITE in full
    assert "business-to-agent" in full
    # The long brief must carry the same refusals as the human page, so an agent
    # reading only this file cannot infer past them.
    for limitation in (
        "No customer traction",
        "No production settlement",
        "compliance-grade ledger storage",
        "exactly-once upstream side effects",
        "no public self-serve mint",
    ):
        assert limitation in full
    for suffix in PROVIDER_HOST_SUFFIXES:
        assert suffix not in full


def test_robots_states_an_explicit_ai_crawler_policy(tmp_path) -> None:
    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    robots = (output / "robots.txt").read_text(encoding="utf-8")
    for agent in ("GPTBot", "ClaudeBot", "Google-Extended", "PerplexityBot", "CCBot"):
        assert f"User-agent: {agent}" in robots


def test_sitemap_publishes_lastmod(tmp_path) -> None:
    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    sitemap = (output / "sitemap.xml").read_text(encoding="utf-8")
    assert sitemap.count("<lastmod>") == sitemap.count("<loc>")
    assert "@@BUILD_DATE@@" not in sitemap


def test_security_txt_is_routable_and_unexpired(tmp_path) -> None:
    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    security_txt = (output / ".well-known" / "security.txt").read_text(
        encoding="utf-8"
    )
    contact = VALID_TEST_CONTACTS["PUBLIC_CONTACT_EMAIL"]
    assert f"Contact: mailto:{contact}" in security_txt
    # A plain-text file must carry the raw address, never an HTML entity.
    assert "&#x27;" not in security_txt and "&amp;" not in security_txt

    expires = next(
        line.split(": ", 1)[1].strip()
        for line in security_txt.splitlines()
        if line.startswith("Expires:")
    )
    parsed = datetime.strptime(expires, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    assert parsed > datetime.now(timezone.utc)


def test_branded_404_offers_a_way_back(tmp_path) -> None:
    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    page = (output / "404.html").read_text(encoding="utf-8")
    assert 'name="robots" content="noindex' in page
    assert 'href="/proof/"' in page
    assert 'href="/#machine-discovery"' in page
    assert "@@" not in page


def test_landing_hero_wave_is_progressive_enhancement(tmp_path) -> None:
    """The homepage hero's particle field must never become a dependency.

    The canvas and its static CSS backdrop coexist, the shared renderer ships
    at the site root with a cache token on every reference, and the stylesheet
    keeps the field out of the way for high-contrast users and print.
    """
    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    page = (output / "index.html").read_text(encoding="utf-8")
    assert 'id="wave-canvas"' in page
    assert 'class="wave-fallback"' in page
    assert re.search(r'<script defer src="/wave\.js\?v=[^"]+"></script>', page)
    assert (output / "wave.js").is_file()

    # The funnel's tested copy still leads the page: the wave is a treatment,
    # not a content change.
    text = _page_text(page)
    assert "Authorize one agent action. Charge it once. Prove what happened." in text

    stylesheet = (output / "styles.css").read_text(encoding="utf-8")
    assert 'html[data-a11y-contrast="high"] .wave-canvas' in stylesheet
    assert "html.wave-dead .wave-canvas" in stylesheet


def test_concept_page_is_an_unlisted_design_study(tmp_path) -> None:
    """/concept/ is a visual study of a particle-wave landing treatment.

    It must stay unlisted (noindex, absent from the sitemap, never linked from
    the funnel pages), keep working without JavaScript or WebGL (the canvas is
    progressive enhancement over a static backdrop), and still honor the
    site-wide contracts: build-time contacts, self-hosted typography, and a
    booking CTA whose aria-label contains its visible text.
    """
    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    page = (output / "concept" / "index.html").read_text(encoding="utf-8")
    assert 'name="robots" content="noindex' in page
    assert "@@" not in page

    # Unlisted: no sitemap entry, and the funnel pages do not link it.
    assert "concept" not in (output / "sitemap.xml").read_text(encoding="utf-8")
    for funnel in ("index.html", "proof/index.html", "compare/index.html"):
        assert "/concept" not in (output / funnel).read_text(encoding="utf-8")

    # The animated background is enhancement, not a dependency: the canvas and
    # its static fallback are both present, and the assets actually ship. The
    # renderer is shared with the homepage hero, so it lives at the site root.
    assert 'id="wave-canvas"' in page
    assert 'class="wave-fallback"' in page
    assert re.search(r'<script defer src="/wave\.js\?v=[^"]+"></script>', page)
    assert (output / "wave.js").is_file()
    assert (output / "concept" / "concept.css").is_file()

    # The un-slashed URL must not 404.
    config = json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))
    redirect = next(
        entry
        for entry in config["redirects"]
        if "has" not in entry and entry["source"] == "/concept"
    )
    assert redirect["destination"] == "/concept/"

    # Same typography contract as every other page: self-hosted fonts only.
    assert '<link rel="stylesheet" href="/fonts.css' in page
    for host in ("fonts.googleapis.com", "fonts.gstatic.com"):
        assert host not in page

    # The CTA books the real call, and labels keep their visible text.
    collector = _LabeledLinkCollector()
    collector.feed(page)
    collector.close()
    assert any(
        href == VALID_TEST_CONTACTS["PUBLIC_BOOKING_URL"]
        for _visible, _label, href in collector.labeled_links
    ), "concept page CTA does not resolve to the build-time booking URL"
    for visible, label, _href in collector.labeled_links:
        assert visible and visible in label, (
            f"concept page aria-label {label!r} does not contain the visible "
            f"text {visible!r} (WCAG 2.1 Label-in-Name)"
        )


def test_navigation_is_identical_across_pages(tmp_path) -> None:
    """A visitor on any subpage must reach the same places as one on /."""

    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    landing = (output / "index.html").read_text(encoding="utf-8")
    proof = (output / "proof" / "index.html").read_text(encoding="utf-8")
    compare = (output / "compare" / "index.html").read_text(encoding="utf-8")

    for label in ("Pilot", "Proof", "Compare", "Machine discovery"):
        for page in (landing, proof, compare):
            assert f">{label}</a>" in page
    for anchor in ("/#pilot", "/#proof", "/compare/", "/#machine-discovery"):
        for page in (proof, compare):
            assert f'href="{anchor}"' in page

    # 404 carries the same nav minus the booking CTA, so a visitor who lands on
    # a dead URL can still reach every real page.
    not_found = (output / "404.html").read_text(encoding="utf-8")
    for anchor in ("/#pilot", "/#proof", "/compare/", "/#machine-discovery"):
        assert f'href="{anchor}"' in not_found, f"404.html cannot reach {anchor}"


def _anchor_texts_and_hrefs(markup: str) -> list[tuple[str, str]]:
    """Return ``(visible_text, href)`` for every ``<a>`` in the page."""

    class _Anchors(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.pairs: list[tuple[str, str]] = []
            self._href: str | None = None
            self._parts: list[str] = []

        def handle_starttag(self, tag: str, attrs) -> None:
            if tag == "a":
                self._href = (dict(attrs).get("href") or "").strip()
                self._parts = []

        def handle_data(self, data: str) -> None:
            if self._href is not None and data.strip():
                self._parts.append(" ".join(data.split()))

        def handle_endtag(self, tag: str) -> None:
            if tag == "a" and self._href is not None:
                self.pairs.append((" ".join(self._parts), self._href))
                self._href = None

    parser = _Anchors()
    parser.feed(markup)
    parser.close()
    return parser.pairs


def test_comparison_page_names_alternatives_and_refuses_superlatives(
    tmp_path,
) -> None:
    """The comparison page exists to be trusted by a reader who can check it.

    That imposes three contracts. It must name real alternatives with working
    links, so the reader can go and look. It must concede at least one row —
    a comparison where the author never loses is an advertisement. And it must
    not smuggle in the two claims ``ELEVATOR_PITCH.md`` forbids: an
    unverifiable "only product that…" superlative, or a compliance guarantee.
    """

    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    page = (output / "compare" / "index.html").read_text(encoding="utf-8")
    text = " ".join(_page_text(page).split()).casefold()

    # Naming an alternative in prose is not enough — "independently checkable"
    # means the reader can click through to the project and judge for
    # themselves, so each name must carry an off-site link.
    anchors = _anchor_texts_and_hrefs(page)
    for alternative in ("protect-mcp", "jamjet", "traceagent", "latch"):
        linked = [
            href
            for visible, href in anchors
            if alternative in visible.casefold() and href.startswith("https://")
        ]
        assert linked, (
            f"comparison page names {alternative} without an off-site link the "
            "reader can check"
        )

    # Concedes ground rather than winning every row.
    assert "use something else" in text
    assert "a poor fit" in text

    # Refuses uniqueness superlatives and compliance guarantees in any phrasing,
    # not just the exact wordings that existed when this test was written.
    # WEDGE.md's never-claim list is the contract; these are its normalized form.
    prohibited = (
        r"\b(?:the )?only (?:mcp|gateway|product|tool|one)\b",
        r"\bno competitor\b",
        r"\bnobody else\b",
        r"\bno one else\b",
        r"\bfirst and only\b",
        r"\bcompliance[- ]ready\b",
        r"\b(?:soc ?2|eu ai act|iso ?42001)[- ]compliant\b",
        r"\bguarantees? compliance\b",
        r"\bfully compliant\b",
    )
    for pattern in prohibited:
        assert not re.search(pattern, text), (
            f"comparison page matches prohibited claim pattern {pattern!r} — see "
            "WEDGE.md 'What Not To Claim Yet'"
        )

    # Negative path: the patterns must actually reject offending copy. Without
    # this, a pattern that silently stops matching would leave the page
    # unguarded while the test still passed.
    offending = (
        "we are the only gateway that meters by the call",
        "only product that prevents double charges",
        "nobody else binds the debit",
        "no one else binds the debit",
        "no competitor offers this",
        "we are the first and only gateway for this",
        "we are soc2-compliant and compliance-ready",
        "the service is fully compliant",
        "this guarantees compliance with the eu ai act",
    )
    for sample in offending:
        assert any(re.search(pattern, sample) for pattern in prohibited), (
            f"prohibited-claim patterns fail to reject {sample!r}"
        )
    # …and every pattern must earn its place. Without this, deleting a pattern
    # that has no sample of its own would leave the suite green.
    for pattern in prohibited:
        assert any(re.search(pattern, sample) for sample in offending), (
            f"prohibited-claim pattern {pattern!r} has no negative-path sample"
        )

    # States the compliance boundary rather than dodging the question.
    assert "not on their own" in text
    assert "hold no" in text and "certification" in text


def test_local_site_assets_exist() -> None:
    for path in (
        SITE / "styles.css",
        SITE / "analytics.js",
        SITE / "favicon.svg",
        SITE / "social-card.png",
        SITE / "robots.txt",
        SITE / "sitemap.xml",
        SITE / "llm.txt",
        SITE / "llms.txt",
        SITE / "llms-full.txt",
        SITE / ".well-known" / "agent.json",
        SITE / "proof" / "index.html",
        SITE / "proof" / "proof.js",
        SITE / "compare" / "index.html",
        SITE / "404.html",
        SITE / "a11y-preload.js",
        SITE / "va-init.js",
        SITE / ".well-known" / "security.txt",
        SITE / "fonts.css",
        SITE / "vendor_fonts.py",
    ):
        assert path.is_file(), f"missing landing-page asset: {path}"


def test_typography_is_self_hosted_with_no_third_party_request(tmp_path) -> None:
    """No page may reach a font CDN, and the CSP must not permit one.

    Google Fonts cost two cross-origin handshakes on the critical path
    (googleapis.com for the CSS, then gstatic.com for the files) and put a
    third party between a visitor and a page whose entire pitch is that you can
    verify things yourself.
    """
    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    rendered = [
        output / "index.html",
        output / "proof" / "index.html",
        output / "compare" / "index.html",
        output / "404.html",
    ]
    for page in rendered:
        markup = page.read_text(encoding="utf-8")
        for host in ("fonts.googleapis.com", "fonts.gstatic.com"):
            assert host not in markup, f"{page.name} still requests {host}"
        assert '<link rel="stylesheet" href="/fonts.css' in markup

    config = json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))
    global_headers = next(
        entry for entry in config["headers"] if entry["source"] == "/(.*)"
    )
    values = {header["key"]: header["value"] for header in global_headers["headers"]}
    policy = _csp_policy(values["Content-Security-Policy"])
    assert policy["style-src"] == "style-src 'self'"
    assert policy["font-src"] == "font-src 'self'"

    # The build must actually ship the files the stylesheet points at.
    assert (output / "fonts.css").is_file()
    for face in re.findall(r'url\("(/fonts/[^"]+)"\)', (output / "fonts.css").read_text()):
        assert (output / face.lstrip("/")).is_file(), f"{face} not published"


def test_every_page_loads_the_accessibility_scripts(tmp_path) -> None:
    """Saved accessibility preferences must apply on every page, including 404.

    This is a merge-regression guard. ``a11y-preload.js`` is what stops a
    visitor who has set larger text or higher contrast from getting a flash of
    the default theme, and ``a11y.js`` is what renders the controls at all. A
    page that keeps the shared stylesheet but loses these two scripts looks
    fine in review and silently drops the feature — which is exactly what a
    conflict resolution did to ``404.html`` once.
    """
    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    for relative_path in (
        "index.html",
        "proof/index.html",
        "compare/index.html",
        "concept/index.html",
        "404.html",
    ):
        markup = (output / relative_path).read_text(encoding="utf-8")
        # Blocking, in <head>, before first paint — a deferred preload would
        # not prevent the flash it exists to prevent.
        assert re.search(
            r'<script src="/a11y-preload\.js\?v=[^"]+"></script>', markup
        ), f"{relative_path} does not apply saved accessibility preferences"
        assert "defer" not in re.search(
            r"<script[^>]*a11y-preload[^>]*>", markup
        ).group(0), f"{relative_path} defers a11y-preload.js; it must block"
        assert re.search(
            r'<script defer src="/a11y\.js\?v=[^"]+"></script>', markup
        ), f"{relative_path} does not load the accessibility controls"


def test_font_stylesheet_and_files_agree() -> None:
    """fonts.css and fonts/ are generated together; neither may drift alone.

    This is the half of the vendoring contract that needs no network. Refreshing
    against upstream is `python3 vendor_fonts.py --check`.
    """
    stylesheet = (SITE / "fonts.css").read_text(encoding="utf-8")
    referenced = {
        Path(src).name for src in re.findall(r'url\("(/fonts/[^"]+)"\)', stylesheet)
    }
    committed = {path.name for path in (SITE / "fonts").glob("*.woff2")}

    assert referenced, "fonts.css declares no @font-face src"
    assert referenced == committed, (
        f"fonts.css and fonts/ disagree; only in css: {sorted(referenced - committed)}, "
        f"only on disk: {sorted(committed - referenced)} — re-run vendor_fonts.py"
    )
    for name in committed:
        assert (SITE / "fonts" / name).read_bytes()[:4] == b"wOF2", f"{name} is not woff2"

    # Every family/weight the design system asks for must have a face, or the
    # browser silently synthesises one.
    for family, weight in (
        ("IBM Plex Mono", 400), ("IBM Plex Mono", 500), ("IBM Plex Mono", 600),
        ("Libre Franklin", 700), ("Libre Franklin", 800),
        ("Public Sans", 400), ("Public Sans", 500), ("Public Sans", 600),
    ):
        block = re.search(
            rf'font-family: "{re.escape(family)}";\s*font-style: normal;\s*'
            rf"font-weight: {weight};",
            stylesheet,
        )
        assert block, f"fonts.css has no face for {family} {weight}"


def test_preloaded_fonts_exist_and_are_actually_used(tmp_path) -> None:
    """A preload for a file the page never uses is pure wasted bandwidth."""
    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    stylesheet = (output / "fonts.css").read_text(encoding="utf-8")

    # The 404 page deliberately preloads nothing: it is noindex and is served
    # overwhelmingly to scanners and stale links, so ~70KB of high-priority
    # font fetches per bad URL buys nothing.
    assert 'rel="preload"' not in (output / "404.html").read_text(encoding="utf-8")

    for relative_path in ("index.html", "proof/index.html", "compare/index.html"):
        markup = (output / relative_path).read_text(encoding="utf-8")
        preloads = re.findall(r'<link rel="preload" href="(/fonts/[^"]+)"', markup)
        assert preloads, f"{relative_path} preloads no fonts"
        for href in preloads:
            assert (output / href.lstrip("/")).is_file(), f"{href} missing"
            assert f'url("{href}")' in stylesheet, f"{href} is preloaded but unused"
            # Fonts are CORS-fetched even same-origin; without crossorigin the
            # preload is discarded and the file is fetched twice.
            assert re.search(
                rf'<link rel="preload" href="{re.escape(href)}"[^>]*crossorigin',
                markup,
                re.S,
            ), f"{href} preload is missing crossorigin"

        # The mono family is static: each first-viewport weight is its own file,
        # so preloading only one still leaves the nav links and section kickers
        # swapping in late.
        manifest = json.loads(
            (SITE / "fonts.manifest.json").read_text(encoding="utf-8")
        )
        for weight in (400, 500, 600):
            assert any(
                name.startswith(f"ibm-plex-mono-{weight}-latin.")
                for name in manifest["preload"]
            ), f"IBM Plex Mono {weight} renders in the fold but is not preloaded"


def test_stylesheet_cache_key_tracks_the_generated_css(tmp_path) -> None:
    """A fixed key would strand visitors on a fonts.css naming deleted files.

    vendor_fonts.py removes the hashed woff2 files it replaces. A client holding
    a week-old stylesheet under an unchanged URL would request those deleted
    files and get 404s, so the stylesheet key has to move with its bytes.
    """
    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    digest = hashlib.sha256((SITE / "fonts.css").read_bytes()).hexdigest()[:8]
    for relative_path in ("index.html", "proof/index.html", "404.html"):
        markup = (output / relative_path).read_text(encoding="utf-8")
        assert f'href="/fonts.css?v={digest}"' in markup, relative_path
        assert "@@FONTS_CSS_VERSION@@" not in markup
        # The hand-maintained token must not creep back onto this asset.
        assert 'href="/fonts.css?v=gateway' not in markup


def test_font_filenames_are_content_hashed_so_immutable_is_safe() -> None:
    """Unhashed names plus a long max-age would serve a refreshed font stale.

    The manual `?v=` token the rest of the site uses cannot reach these URLs:
    they live inside fonts.css and the generated preloads, not in hand-written
    markup.
    """
    config = json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))
    rule = next(
        entry for entry in config["headers"] if entry["source"].startswith("/fonts/")
    )
    cache = next(h["value"] for h in rule["headers"] if h["key"] == "Cache-Control")
    assert "immutable" in cache

    for path in (SITE / "fonts").glob("*.woff2"):
        stem, _, extension = path.name.rpartition(".")
        digest = stem.rsplit(".", 1)[1]
        assert re.fullmatch(r"[0-9a-f]{8}", digest), f"{path.name} is not hashed"
        assert hashlib.sha256(path.read_bytes()).hexdigest().startswith(digest), (
            f"{path.name} does not match its own content hash"
        )


def teardown_module() -> None:
    """Keep local focused runs from retaining an interrupted generated build."""

    shutil.rmtree(SITE / "dist", ignore_errors=True)


def test_build_refuses_a_malformed_or_stale_font_manifest(tmp_path) -> None:
    """json.loads accepts a list or a string; manifest.get would then raise
    AttributeError and the build would die with a traceback instead of the
    launch error it documents. A stale entry names a content-hashed file that no
    longer exists, which would ship a <link rel="preload"> that 404s."""

    build_module = runpy.run_path(str(SITE / "build_site.py"))
    launch_error = build_module["LaunchConfigurationError"]
    font_preload_tags = build_module["font_preload_tags"]
    manifest_path = SITE / "fonts.manifest.json"
    original = manifest_path.read_text(encoding="utf-8")

    cases = {
        "top-level list": "[]",
        "top-level string": '"preload"',
        "preload not a list": '{"preload": "one-file.woff2"}',
        "preload not strings": '{"preload": [1, 2]}',
        "preload empty": '{"preload": []}',
        "preload names a missing file": '{"preload": ["not-vendored.woff2"]}',
        "not json at all": "{",
    }
    try:
        for label, payload in cases.items():
            manifest_path.write_text(payload, encoding="utf-8")
            with pytest.raises(launch_error):
                font_preload_tags()
        manifest_path.write_text(original, encoding="utf-8")
        # The real manifest still renders, so the guards are not over-tight.
        assert 'rel="preload"' in font_preload_tags()
    finally:
        manifest_path.write_text(original, encoding="utf-8")


def test_vendored_font_license_is_published(tmp_path) -> None:
    """OFL 1.1 condition 2 asks that the notice and the license itself travel
    with the redistributed fonts.

    The operator README is deliberately withheld from dist/, so the attribution
    lives in a plain-text file that ships beside the woff2 files it covers.
    """
    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    license_text = (output / "fonts" / "OFL.txt").read_text(encoding="utf-8")

    # Each family's own notice, verbatim from its upstream OFL.txt. Asserting
    # the family names alone is not enough: all three were present and all
    # three notices were still wrong — two attributed to a foundry that no
    # longer holds them, and Plex missing its name reservation entirely, which
    # understates the terms the bytes travel under.
    for family, notice in (
        ("IBM Plex Mono", 'Copyright © 2017 IBM Corp. with Reserved Font Name "Plex"'),
        ("Libre Franklin", "Copyright 2020 The Libre Franklin Project Authors"),
        ("Public Sans", "Copyright 2015 The Public Sans Project Authors"),
    ):
        assert family in license_text, f"{family}: not named in the license file"
        assert notice in license_text, f"{family}: upstream notice missing or altered"

    # These fonts are served as standalone files, not embedded in a document or
    # bundled in a program, so OFL 1.1 condition 2 wants the license itself and
    # not a link to it. Assert the operative sections, not just the title: a
    # file that has been quietly reduced back to a URL still says "Open Font
    # License" at the top.
    for clause in (
        "SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007",
        "PREAMBLE",
        "DEFINITIONS",
        "PERMISSION & CONDITIONS",
        "TERMINATION",
        "DISCLAIMER",
        "may be sold by itself",
        "contains the above copyright notice and this license",
        'THE FONT SOFTWARE IS PROVIDED "AS IS"',
    ):
        assert clause in license_text, f"OFL text is missing: {clause}"
    assert len(license_text.splitlines()) > 100

    # The operator note stays internal; the exclusion must not be broader.
    assert not (output / "fonts" / "README.md").exists()
    assert (output / ".well-known" / "security.txt").is_file()
    assert (output / "proof" / "receipt.json").is_file()
