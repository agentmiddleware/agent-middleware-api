"""Branch pushes to CI and image publishing are limited to main."""

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _events(workflow_name: str) -> dict:
    workflow = yaml.load(
        (WORKFLOWS / workflow_name).read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    return workflow["on"]


@pytest.mark.parametrize("workflow_name", ("ci.yml", "docker-publish.yml"))
def test_push_branches_are_main_only(workflow_name: str):
    assert _events(workflow_name)["push"]["branches"] == ["main"]


def test_ci_pull_requests_target_main_only():
    assert _events("ci.yml")["pull_request"]["branches"] == ["main"]
