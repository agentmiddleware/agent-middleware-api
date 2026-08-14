"""Contracts for the human-first marketing and portable-proof site."""

from __future__ import annotations

import json
import os
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
    for relative_path in ("index.html", "proof/index.html"):
        page = (default_output / relative_path).read_text(encoding="utf-8")
        assert "/_vercel/insights/script.js" not in page
        assert "/va-init.js" not in page
        assert "@@VERCEL_ANALYTICS_SCRIPTS@@" not in page
        assert '<script defer src="/analytics.js?v=gateway-2"></script>' in page

    enabled_output = tmp_path / "enabled"
    enabled_contacts = dict(VALID_TEST_CONTACTS)
    enabled_contacts["PUBLIC_ENABLE_VERCEL_ANALYTICS"] = "true"
    result = _render_site(enabled_output, enabled_contacts)
    assert result.returncode == 0, result.stderr
    for relative_path in ("index.html", "proof/index.html"):
        page = (enabled_output / relative_path).read_text(encoding="utf-8")
        assert '<script defer src="/_vercel/insights/script.js"></script>' in page
        assert '<script src="/va-init.js?v=gateway-2"></script>' in page
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

    for relative_path in ("index.html", "proof/index.html"):
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
    for relative_path in ("index.html", "proof/index.html"):
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


def test_site_sends_a_content_security_policy_and_hsts() -> None:
    config = json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))

    global_headers = next(
        entry for entry in config["headers"] if entry["source"] == "/(.*)"
    )
    values = {header["key"]: header["value"] for header in global_headers["headers"]}

    assert "includeSubDomains" in values["Strict-Transport-Security"]
    policy = {
        directive.split(" ")[0]: directive
        for directive in values["Content-Security-Policy"].split("; ")
    }
    assert policy["default-src"] == "default-src 'self'"
    assert policy["object-src"] == "object-src 'none'"
    assert policy["base-uri"] == "base-uri 'none'"
    # The accessibility preload and the analytics shim live in same-origin files
    # precisely so no inline-script escape hatch is needed.
    assert policy["script-src"] == "script-src 'self'"
    assert "'unsafe-inline'" not in values["Content-Security-Policy"]
    assert "https://fonts.googleapis.com" in policy["style-src"]
    assert "https://fonts.gstatic.com" in policy["font-src"]


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
        for relative_path in ("index.html", "proof/index.html", "404.html"):
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
    # week-long cache would pin visitors to a stale stylesheet.
    for relative_path in ("index.html", "proof/index.html", "404.html"):
        page = (SITE / relative_path).read_text(encoding="utf-8")
        for asset in ("/styles.css", "/a11y.js", "/a11y-preload.js"):
            assert f'{asset}?v=' in page, f"{relative_path} references {asset} unversioned"

    # HTML gets no long-lived Cache-Control rule of its own.
    html_rules = [
        entry
        for entry in config["headers"]
        if entry["source"].endswith((".html", "/"))
    ]
    assert not html_rules


def test_trailing_slash_is_canonical_for_the_proof_page() -> None:
    config = json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))
    proof = (SITE / "proof" / "index.html").read_text(encoding="utf-8")

    assert config["trailingSlash"] is True
    assert 'rel="canonical" href="https://www.thisisatest.tech/proof/"' in proof


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


def test_navigation_is_identical_across_pages(tmp_path) -> None:
    """A visitor on /proof/ must reach the same places as one on /."""

    output = tmp_path / "site"
    assert _render_site(output, VALID_TEST_CONTACTS).returncode == 0

    landing = (output / "index.html").read_text(encoding="utf-8")
    proof = (output / "proof" / "index.html").read_text(encoding="utf-8")

    for label in ("Pilot", "Proof", "Machine discovery"):
        assert f">{label}</a>" in landing
        assert f">{label}</a>" in proof
    for anchor in ("/#pilot", "/#proof", "/#machine-discovery"):
        assert f'href="{anchor}"' in proof


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
        SITE / ".well-known" / "agent.json",
        SITE / "proof" / "index.html",
        SITE / "proof" / "proof.js",
        SITE / "404.html",
        SITE / "a11y-preload.js",
        SITE / "va-init.js",
        SITE / ".well-known" / "security.txt",
    ):
        assert path.is_file(), f"missing landing-page asset: {path}"


def teardown_module() -> None:
    """Keep local focused runs from retaining an interrupted generated build."""

    shutil.rmtree(SITE / "dist", ignore_errors=True)
