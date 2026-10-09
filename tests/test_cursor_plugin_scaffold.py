"""Scaffold checks for the Cursor plugin (integrations/cursor-plugin-agent-middleware)."""

import json
from pathlib import Path

BASE = (
    Path(__file__).resolve().parent.parent
    / "integrations"
    / "cursor-plugin-agent-middleware"
)
PLUGIN = BASE / "plugins" / "agent-middleware"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def test_marketplace_manifest_matches_plugin():
    marketplace = _load_json(BASE / ".cursor-plugin" / "marketplace.json")
    assert marketplace["plugins"][0]["name"] == "agent-middleware"
    assert marketplace["plugins"][0]["source"] == "./plugins/agent-middleware"
    plugin = _load_json(PLUGIN / ".cursor-plugin" / "plugin.json")
    assert plugin["name"] == "agent-middleware"
    assert plugin["name"] == marketplace["plugins"][0]["name"]
    assert plugin["author"]["name"] == "Chris Sellers"
    assert plugin["license"] == "MIT"
    assert (
        plugin["repository"]
        == "https://github.com/agentmiddleware/agent-middleware-api"
    )
    assert (PLUGIN / plugin["logo"]).is_file()


def test_mcp_config_uses_placeholder_not_real_key():
    raw = (PLUGIN / "mcp.json").read_text()
    assert "${AMW_API_KEY}" in raw
    assert "https://api.thisisatest.tech" in raw
    config = json.loads(raw)
    server = config["mcpServers"]["agent-middleware"]
    assert server["url"] == "https://api.thisisatest.tech/mcp"
    assert server["headers"]["X-API-Key"] == "${AMW_API_KEY}"


def test_skill_has_frontmatter_and_guardrail():
    text = (PLUGIN / "skills" / "amw-permit-receipt" / "SKILL.md").read_text()
    assert text.startswith("---\n")
    frontmatter = text.split("---\n")[1]
    assert "name:" in frontmatter
    assert "description:" in frontmatter
    lowered = text.lower()
    assert "permit" in lowered and "receipt" in lowered
    assert "exactly-once" not in lowered
    assert "exactly once" not in lowered
