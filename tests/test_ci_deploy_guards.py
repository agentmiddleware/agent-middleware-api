"""Guards for the CI/build/deploy slice (gtm-38-api-ci-deploy).

These tests pin the small hardening steps, not the product loop:
- the auto-PR workflow stays manual-only and does not persist credentials,
- every release validation summary names the in-container private-posture
  command, so the dogfood posture cannot silently go unverified,
- the local compose stack lets a developer mirror production guardrails.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent


def _load_workflow(name: str) -> dict:
    with open(REPO_ROOT / ".github" / "workflows" / name, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict)
    return data


def test_auto_pr_is_manual_only():
    """The write-permission auto-PR surface must stay manually triggered."""
    workflow = _load_workflow("auto-pr.yml")
    # PyYAML reads the YAML 1.1 `on` key as boolean True.
    triggers = workflow.get("on", workflow.get(True, {}))
    assert set(triggers) == {"workflow_dispatch"}, triggers


def test_auto_pr_checkout_does_not_persist_credentials():
    """Checkout must not leave the token in git config; the PR step passes
    its own explicit token input instead."""
    workflow = _load_workflow("auto-pr.yml")
    steps = workflow["jobs"]["analyze-and-fix"]["steps"]
    checkouts = [
        s for s in steps if str(s.get("uses", "")).startswith("actions/checkout")
    ]
    assert checkouts, "expected an actions/checkout step"
    for step in checkouts:
        assert step.get("with", {}).get("persist-credentials") is False


def test_release_summary_names_in_container_private_check():
    """The release validation summary must print the exact in-container
    private-posture command, since CI cannot reach the private network."""
    text = (REPO_ROOT / ".github" / "workflows" / "railway-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert "--runtime-posture --strict" in text
    assert "railway ssh --service api-service" in text


def test_compose_debug_is_overridable():
    """Local compose must allow DEBUG=false so developers can mirror
    production guardrails instead of always running permissive."""
    with open(REPO_ROOT / "docker-compose.yml", encoding="utf-8") as f:
        compose = yaml.safe_load(f)
    api_env = compose["services"]["api"]["environment"]
    assert "DEBUG=${DEBUG:-true}" in api_env
