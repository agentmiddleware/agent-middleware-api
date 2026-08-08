"""Static-site contracts for the agent-first product thesis and handoff."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

from app.routers.well_known import _local_try_it_manifest, get_agent_first_metadata


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
CANONICAL_API = "https://api-service-production-433c.up.railway.app"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _page_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return " ".join(parser.parts)


def test_landing_leads_with_agent_thesis_and_public_bootstrap() -> None:
    page = (SITE / "index.html").read_text(encoding="utf-8")
    text = _page_text(page)

    assert "Autonomy needs receipts." in text
    assert "The control layer between autonomous agents and tools" in text
    assert text.index("Autonomy needs receipts.") < text.index(
        "One call. One charge. One receipt."
    )
    for path in (
        "/.well-known/agent.json",
        "/mcp/tools.json",
        "/health/dependencies",
    ):
        assert path in page
    for step in (
        "Discover",
        "Authenticate",
        "Authorize",
        "Invoke",
        "Meter",
        "Receipt",
        "Audit",
        "Govern",
    ):
        assert f"<strong>{step}</strong>" in page

    assert "no public key mint" in page
    assert "Production settlement or payments rails" in page
    assert "placeholder" not in page.lower()


def test_marketing_manifest_points_to_canonical_api_and_local_proof() -> None:
    manifest = json.loads(
        (SITE / ".well-known" / "agent.json").read_text(encoding="utf-8")
    )

    assert manifest["canonical_api"] == CANONICAL_API
    assert manifest["human_site"] == "https://agent-middleware-web.vercel.app"
    assert manifest["primary_audience"] == "autonomous_agents"
    assert manifest["product_loop"] == get_agent_first_metadata()["product_loop"]
    assert manifest["try_it"] == _local_try_it_manifest()
    assert manifest["discovery"]["llms_txt"] == f"{CANONICAL_API}/llms.txt"
    assert f"{CANONICAL_API}/llms.txt" in manifest["bootstrap_sequence"]
    assert "awi_manifest" not in manifest["discovery"]


def test_machine_pointer_copies_match_and_state_live_access_boundary() -> None:
    llm_txt = (SITE / "llm.txt").read_text(encoding="utf-8")
    llms_txt = (SITE / "llms.txt").read_text(encoding="utf-8")

    assert llm_txt == llms_txt
    assert "You are the intended reader" in llm_txt
    assert "make prove-trust-plane" in llm_txt
    assert "operator-issued" in llm_txt
    assert "no public self-serve key mint" in llm_txt
    assert CANONICAL_API in llm_txt


def test_dynamic_machine_routes_redirect_to_the_canonical_api() -> None:
    config = json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))
    redirects = {
        redirect["source"]: redirect for redirect in config.get("redirects", [])
    }
    expected = {
        "/mcp/tools.json": f"{CANONICAL_API}/mcp/tools.json",
        "/v1/discover": f"{CANONICAL_API}/v1/discover",
        "/openapi.json": f"{CANONICAL_API}/openapi.json",
        "/health/dependencies": f"{CANONICAL_API}/health/dependencies",
    }

    for source, destination in expected.items():
        assert redirects[source]["destination"] == destination
        assert redirects[source]["permanent"] is False
        assert destination.startswith("https://")


def test_local_site_assets_exist() -> None:
    for path in (
        SITE / "styles.css",
        SITE / "llm.txt",
        SITE / "llms.txt",
        SITE / ".well-known" / "agent.json",
    ):
        assert path.is_file(), f"missing landing-page asset: {path}"
