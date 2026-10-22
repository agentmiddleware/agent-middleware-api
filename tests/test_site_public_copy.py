"""Keep published source links and retry copy aligned with the site."""

import json
import re
from pathlib import Path


SITE = Path(__file__).resolve().parents[1] / "site"
PUBLIC_REPO = "https://github.com/agentmiddleware/agent-middleware"
APPROVED_RETRY = (
    "a retry with the same key returns the original receipt instead of "
    "dispatching again"
)
ALLOWED_GITHUB_URLS = {
    "https://github.com/agentmiddleware",
    PUBLIC_REPO,
    "https://github.com/agentmiddleware/amw-demo",
    "https://github.com/agentmiddleware/amw-demo.git",
    "https://github.com/agentmiddleware/amw-paypal-agent-demo",
}


def test_site_source_links_and_retry_copy() -> None:
    for source in SITE.rglob("*"):
        if not source.is_file() or source.suffix not in {
            ".html",
            ".txt",
            ".json",
            ".md",
            ".svg",
            ".js",
        }:
            continue
        content = source.read_text(encoding="utf-8")
        for url in re.findall(
            r"https://github\.com/agentmiddleware(?:/[\w.-]+)?", content
        ):
            assert url.rstrip(".") in ALLOWED_GITHUB_URLS, source
        assert not re.search(
            r"\b(?:source|repository|code) (?:is )?private\b|"
            r"\bsource access on request\b",
            content,
            re.IGNORECASE,
        ), source
        assert not re.search(
            r"\bno second (?:call|charge|dispatch|debit)\b|"
            r"\bwithout a second (?:call|charge|dispatch|debit)\b|"
            r"\bnot charged\s+again\b",
            content,
            re.IGNORECASE,
        ), source

    manifest = json.loads(
        (SITE / ".well-known" / "agent.json").read_text(encoding="utf-8")
    )
    assert manifest["github"] == PUBLIC_REPO
    assert manifest["try_it"]["repository"] == PUBLIC_REPO
    for relative_path in ("index.html", "llm.txt", "llms.txt", "proof/transcript.json"):
        content = (SITE / relative_path).read_text(encoding="utf-8")
        assert APPROVED_RETRY in " ".join(content.split())
