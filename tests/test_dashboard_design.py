"""Shared visual contract for the API origin's self-contained operator index."""

from html.parser import HTMLParser
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "static" / "dashboard.html"


def _root_tokens(source: str) -> dict[str, str]:
    root = re.search(r":root\s*\{([^}]+)\}", source)
    assert root, "The design tokens must have a :root declaration."
    return {
        name: value.strip()
        for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", root.group(1))
    }


def test_dashboard_tokens_match_the_shared_site_design() -> None:
    """Catch drift beyond color: typography, page width, radii, and focus."""
    dashboard = DASHBOARD.read_text(encoding="utf-8")
    tokens = _root_tokens(dashboard)
    site_tokens = _root_tokens((ROOT / "site" / "styles.css").read_text())
    required = {
        "--font-display",
        "--font-title",
        "--font-body",
        "--font-mono",
        "--radius",
        "--radius-sm",
        "--page-max",
        "--pad-x",
        "--focus-ring",
    }
    assert required <= tokens.keys()
    assert set(re.findall(r"var\((--[\w-]+)\)", dashboard)) <= tokens.keys()
    for name, value in tokens.items():
        assert name in site_tokens, f"Dashboard-only design token: {name}"
        assert value == site_tokens[name], f"Dashboard token has drifted: {name}"


class _Elements(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag, dict(attrs)))


def test_dashboard_skip_link_reaches_a_focusable_main_without_external_assets() -> None:
    document = _Elements()
    document.feed(DASHBOARD.read_text(encoding="utf-8"))
    links = [attrs for tag, attrs in document.elements if tag == "a"]
    mains = [attrs for tag, attrs in document.elements if tag == "main"]
    assert len(mains) == 1
    assert mains[0].get("tabindex") == "-1"
    assert links[0].get("href") == f"#{mains[0]['id']}"
    assert "skip-link" in (links[0].get("class") or "").split()
    for tag, attrs in document.elements:
        assert tag not in {"script", "iframe", "img", "audio", "video", "source"}
        if tag == "link":
            assert attrs.get("rel") != "stylesheet"
            if attrs.get("rel") == "icon":
                assert (attrs.get("href") or "").startswith("data:")
