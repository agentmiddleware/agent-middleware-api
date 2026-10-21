"""Contracts for the Markdown-generated public documentation."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import runpy
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import pytest


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DOCS_SOURCE = SITE / "docs-src"
SITE_URL = "https://www.agentmiddleware.dev"
LICENSE_LINE = "Apache 2.0 (gateway is Fair Source, FSL-1.1)"
RETRY_WORDING = "a retry with the same key returns the original receipt instead of dispatching again"
SECTION_PAGES = {
    "Start": ("What is AMW", "3 minute quickstart", "Run locally"),
    "Concepts": ("Permits", "Calls and request keys", "Receipts", "Credits"),
    "Guides": (
        "Put a refund tool behind AMW",
        "MCP client setup",
        "LangChain",
        "CrewAI",
        "AutoGen",
        "OpenAI Agents",
        "PayPal sandbox demo",
    ),
    "Reference": (
        "HTTP API",
        "Errors",
        "Python SDK",
        "TS verifier",
        "Receipt spec v0.1",
    ),
    "Trust": ("Limits", "Security limitations", "Proof and published receipts"),
}
PUBLISHED_TITLES = {
    *SECTION_PAGES["Start"],
    *SECTION_PAGES["Concepts"],
    "Limits",
}


def _front_matter(source: Path) -> tuple[dict[str, str], str]:
    text = source.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "---", f"{source} needs front matter"
    assert "---" in lines[1:], f"{source} has no closing front matter marker"
    end = lines.index("---", 1)
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        assert ":" in line, f"{source}: malformed front matter line {line!r}"
        key, value = line.split(":", 1)
        key = key.strip()
        assert key not in fields, f"{source}: duplicate {key}"
        fields[key] = value.strip().strip('"')
    assert set(fields) == {"title", "section", "order", "description"}
    assert all(fields.values()), f"{source}: empty front matter value"
    assert fields["order"].isdigit(), f"{source}: order must be an integer"
    return fields, "\n".join(lines[end + 1 :])


def _manifest_pages() -> list[tuple[str, str, str]]:
    manifest = json.loads((DOCS_SOURCE / "nav.json").read_text(encoding="utf-8"))
    assert set(manifest) == {"sections"}
    sections = manifest["sections"]
    assert [section["title"] for section in sections] == list(SECTION_PAGES)
    entries: list[tuple[str, str, str]] = []
    for section in sections:
        section_name = section["title"]
        assert [page["title"] for page in section["pages"]] == list(
            SECTION_PAGES[section_name]
        )
        for page in section["pages"]:
            assert set(page) == {"title", "slug"}
            assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", page["slug"])
            entries.append((section_name, page["title"], page["slug"]))
    slugs = [slug for _, _, slug in entries]
    assert len(slugs) == len(set(slugs)), "docs slugs must be unique"
    return entries


def _published_pages() -> list[tuple[str, str, str, dict[str, str], str]]:
    pages = []
    for section, title, slug in _manifest_pages():
        source = DOCS_SOURCE / f"{slug}.md"
        if not source.exists():
            continue
        fields, body = _front_matter(source)
        assert fields["title"] == title, f"{source}: manifest title disagrees"
        assert fields["section"] == section, f"{source}: manifest section disagrees"
        pages.append((section, title, slug, fields, body))
    return pages


def _build_site(
    output: Path, *, valid_contacts: bool = True
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    for name in (
        "PUBLIC_DISPLAY_NAME",
        "PUBLIC_CONTACT_EMAIL",
        "PUBLIC_BOOKING_URL",
        "PUBLIC_ENABLE_VERCEL_ANALYTICS",
    ):
        environment.pop(name, None)
    if valid_contacts:
        environment.update(
            PUBLIC_DISPLAY_NAME="Design Partner Labs LLC",
            PUBLIC_CONTACT_EMAIL="operator@design-partner-labs.org",
        )
    return subprocess.run(
        [sys.executable, str(SITE / "build_site.py"), "--output", str(output)],
        cwd=SITE,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def built_docs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("site-docs") / "dist"
    result = _build_site(output)
    assert result.returncode == 0, result.stderr
    return output


class _DocsHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.hrefs: list[str] = []
        self.sidebar_text: list[str] = []
        self._sidebar_depth = 0
        self.unsafe_markup: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if self._sidebar_depth:
            self._sidebar_depth += 1
        elif "docs-sidebar" in (attributes.get("class") or "").split():
            self._sidebar_depth = 1
        if attributes.get("id"):
            self.ids.add(attributes["id"] or "")
        if tag == "a" and attributes.get("href"):
            self.hrefs.append(attributes["href"] or "")
        if tag == "style" or (tag == "script" and not attributes.get("src")):
            self.unsafe_markup.append(f"inline <{tag}>")
        for name in attributes:
            if name == "style" or name.startswith("on"):
                self.unsafe_markup.append(f"{name} attribute")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._sidebar_depth:
            self._sidebar_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._sidebar_depth:
            self.sidebar_text.append(data)


def _parse_page(source: Path) -> _DocsHTML:
    parser = _DocsHTML()
    parser.feed(source.read_text(encoding="utf-8"))
    parser.close()
    return parser


def _prose_only(source: str) -> str:
    """Exclude code and link targets, where syntax hyphens are legitimate."""
    lines = []
    in_fence = False
    for line in source.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(line)
    prose = "\n".join(lines)
    prose = re.sub(r"`[^`]*`", "", prose)
    prose = re.sub(r"\]\([^)]+\)", "]()", prose)
    prose = re.sub(r"https?://\S+", "", prose)
    return prose.replace("*", "")


def test_docs_manifest_and_source_front_matter_match() -> None:
    published = _published_pages()
    assert {title for _, title, _, _, _ in published} == PUBLISHED_TITLES
    assert {source.stem for source in DOCS_SOURCE.glob("*.md")} == {
        slug for _, _, slug, _, _ in published
    }
    for section in SECTION_PAGES:
        orders = [
            int(fields["order"])
            for page_section, _, _, fields, _ in published
            if page_section == section
        ]
        assert orders == sorted(set(orders)), f"{section}: source order disagrees"


def test_docs_copy_rules_hold_for_every_source_page() -> None:
    for _, title, slug, _, body in _published_pages():
        source = DOCS_SOURCE / f"{slug}.md"
        full_text = source.read_text(encoding="utf-8")
        expected_license_lines = 1 if title == "What is AMW" else 0
        assert [line.strip() for line in full_text.splitlines()].count(
            LICENSE_LINE
        ) == expected_license_lines, f"{title}: unexpected license line count"
        prose = _prose_only(full_text)
        lowered = prose.casefold()
        for banned in ("Trust Plane", "b2a", "no second call or charge"):
            assert banned.casefold() not in lowered, (
                f"{title}: banned phrase {banned!r}"
            )
        assert "—" not in prose and "–" not in prose, f"{title}: punctuation dash"
        assert re.search(r"\w\s+--?\s+\w", prose) is None, (
            f"{title}: punctuation dash between words"
        )
        if title == "Calls and request keys":
            assert RETRY_WORDING in body
        if title == "Limits":
            assert (
                "https://github.com/agentmiddleware/agent-middleware/"
                "blob/main/SECURITY_LIMITATIONS.md"
            ) in full_text
        for raw_url in re.findall(r"https?://[^\s)]+", full_text):
            target = urlparse(raw_url)
            if target.hostname == "github.com":
                assert target.path in {
                    "/agentmiddleware",
                    "/agentmiddleware/agent-middleware",
                    "/agentmiddleware/amw-demo.git",
                } or target.path.startswith("/agentmiddleware/agent-middleware/"), (
                    f"{title}: noncanonical repository link {raw_url}"
                )
            elif target.hostname and target.hostname.endswith("agentmiddleware.dev"):
                assert target.hostname == "www.agentmiddleware.dev", (
                    f"{title}: noncanonical site link {raw_url}"
                )
            elif target.hostname and target.hostname.endswith("thisisatest.tech"):
                assert target.hostname == "api.thisisatest.tech", (
                    f"{title}: noncanonical API link {raw_url}"
                )


def test_docs_render_with_shared_chrome_sidebar_and_hashed_css(
    built_docs: Path,
) -> None:
    pages = [("/docs/", built_docs / "docs" / "index.html")]
    pages.extend(
        (f"/docs/{slug}/", built_docs / "docs" / slug / "index.html")
        for _, _, slug, _, _ in _published_pages()
    )
    styles_version = hashlib.sha256((SITE / "styles.css").read_bytes()).hexdigest()[:8]
    for url, path in pages:
        assert path.is_file(), f"{url} is missing"
        markup = path.read_text(encoding="utf-8")
        parsed = _parse_page(path)
        assert 'class="site-nav"' in markup, f"{url}: missing shared nav"
        assert 'class="site-footer"' in markup, f"{url}: missing shared footer"
        assert f"/styles.css?v={styles_version}" in markup, f"{url}: stale CSS hash"
        assert parsed.unsafe_markup == [], f"{url}: {parsed.unsafe_markup}"
        assert "@@" not in markup, f"{url}: unresolved build token"
        expected_license_lines = 1 if url in {"/docs/", "/docs/what-is-amw/"} else 0
        assert markup.count(LICENSE_LINE) == expected_license_lines, (
            f"{url}: unexpected license line count"
        )
        sidebar = " ".join(" ".join(parsed.sidebar_text).split())
        assert sidebar, f"{url}: missing docs sidebar"
        positions = [sidebar.find(section) for section in SECTION_PAGES]
        assert all(position >= 0 for position in positions), (
            f"{url}: sidebar omits a section: {sidebar}"
        )
        assert positions == sorted(positions), f"{url}: sidebar section order changed"


def test_hosted_quickstart_uses_demo_key_and_receipt_example(built_docs: Path) -> None:
    fields, body = _front_matter(DOCS_SOURCE / "three-minute-quickstart.md")
    assert fields["description"] == (
        "Get a free hosted sandbox key, run the demo Call and retry, "
        "and verify its Receipt."
    )
    assert "https://www.agentmiddleware.dev/demo-key/" in body
    assert "curl -s -X POST https://api.thisisatest.tech/v1/demo/keys" in body
    assert "Save `api_key` and `wallet_id`" in body
    assert "Never paste the key into an issue or chat." in body
    assert "git clone https://github.com/agentmiddleware/amw-demo.git" in body
    assert "export AMW_API_KEY='YOUR_DEMO_KEY'" in body
    assert "export AMW_WALLET_ID='YOUR_WALLET_ID'" in body
    assert "python examples/permit_echo_retry.py" in body
    assert RETRY_WORDING in body
    assert "[Receipts](/docs/receipts/)" in body
    assert "https://www.agentmiddleware.dev/proof/" in body
    assert "make quickstart" not in body
    llms = (built_docs / "docs" / "llms.txt").read_text(encoding="utf-8")
    assert (
        f"[3 minute quickstart]({SITE_URL}/docs/three-minute-quickstart/): {fields['description']}"
        in llms
    )


def test_all_internal_docs_links_reach_built_pages_and_anchors(
    built_docs: Path,
) -> None:
    page_paths = [built_docs / "docs" / "index.html"]
    page_paths.extend(
        built_docs / "docs" / slug / "index.html"
        for _, _, slug, _, _ in _published_pages()
    )
    page_ids = {path.resolve(): _parse_page(path).ids for path in page_paths}
    docs_root = (built_docs / "docs").resolve()
    for page_path in page_paths:
        current_url = (
            SITE_URL + "/" + str(page_path.relative_to(built_docs).parent) + "/"
        )
        for href in _parse_page(page_path).hrefs:
            target = urlparse(urljoin(current_url, href))
            if target.netloc != "www.agentmiddleware.dev" or not target.path.startswith(
                "/docs/"
            ):
                continue
            target_path = built_docs / unquote(target.path).lstrip("/")
            if not target_path.suffix:
                target_path = target_path / "index.html"
            target_path = target_path.resolve()
            assert target_path.is_relative_to(docs_root), (
                f"{page_path}: {href} escapes docs"
            )
            assert target_path.is_file(), f"{page_path}: broken docs link {href}"
            if target.fragment and target_path in page_ids:
                assert unquote(target.fragment) in page_ids[target_path], (
                    f"{page_path}: missing docs anchor {href}"
                )


def test_docs_llms_and_sitemap_list_only_published_pages(built_docs: Path) -> None:
    llms = (built_docs / "docs" / "llms.txt").read_text(encoding="utf-8")
    sitemap = (built_docs / "sitemap.xml").read_text(encoding="utf-8")
    expected_urls = set()
    for _, title, slug, fields, _ in _published_pages():
        url = f"{SITE_URL}/docs/{slug}/"
        expected_urls.add(url)
        assert any(
            title in line and url in line and fields["description"] in line
            for line in llms.splitlines()
        ), f"{title}: llms.txt is not derived from front matter"
        assert f"<loc>{url}</loc>" in sitemap
    referenced_urls = set(re.findall(rf"{re.escape(SITE_URL)}/docs/[a-z0-9/-]*", llms))
    assert referenced_urls - {f"{SITE_URL}/docs/"} == expected_urls
    assert f"<loc>{SITE_URL}/docs/</loc>" in sitemap


def test_docs_redirect_and_launch_gate(tmp_path: Path) -> None:
    config = json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))
    assert {
        "source": "/docs",
        "destination": "/docs/",
        "permanent": True,
    } in config["redirects"]
    blocked_output = tmp_path / "blocked-site"
    blocked = _build_site(blocked_output, valid_contacts=False)
    assert blocked.returncode == 2
    assert "missing required launch contact values" in blocked.stderr
    assert not (blocked_output / "docs").exists()


def test_published_docs_pages_redirect_to_trailing_slash() -> None:
    config = json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))
    for _, _, slug, _, _ in _published_pages():
        assert {
            "source": f"/docs/{slug}",
            "destination": f"/docs/{slug}/",
            "permanent": True,
        } in config["redirects"], f"/docs/{slug} needs a trailing-slash redirect"


def test_markdown_renderer_escapes_html_and_unsafe_links() -> None:
    module = runpy.run_path(str(SITE / "build_docs.py"))
    render_markdown = module["render_markdown"]
    rendered = render_markdown(
        "## Safe heading\n\n"
        "<img src=x onerror=alert(1)> and `<b>inline</b>`\n\n"
        "[safe](https://www.agentmiddleware.dev/docs/)\n\n"
        "- One item\n\n"
        "| Name | Value |\n| --- | --- |\n| A | B |\n\n"
        "```html\n<script>alert(1)</script>\n```\n"
    )
    assert '<h2 id="safe-heading">' in rendered
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered
    assert "&lt;b&gt;inline&lt;/b&gt;" in rendered
    assert '<a href="https://www.agentmiddleware.dev/docs/">safe</a>' in rendered
    assert "javascript:" not in html.unescape(rendered)
    assert "<ul>" in rendered and "<li>One item</li>" in rendered
    assert "<table>" in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    parser = _DocsHTML()
    parser.feed(rendered)
    assert parser.unsafe_markup == []
    with pytest.raises(module["DocsBuildError"], match="unsafe Markdown link"):
        render_markdown("[unsafe](javascript:alert(1))")
