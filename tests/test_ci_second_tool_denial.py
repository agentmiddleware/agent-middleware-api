"""Test that CI configuration exercises out-of-scope denial with the second tool.

Verifies the constant test loop in CI actually uses the second dogfood tool
to prove permit scope enforcement rather than silently skipping the check.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONSTANT_TEST_SCRIPT = ROOT / "scripts" / "constant_test_loop.py"


def test_ci_registers_second_tool_and_passes_it_to_constant_test():
    """CI config must wire the second tool through to the denial check.
    
    Regression: ENABLE_DOGFOOD_SECOND_TOOL=true registers partner.notes.count
    but if the loop invocation doesn't pass --other-tool, the out-of-scope
    denial check silently skips and never proves permit scoping.
    """
    ci_config = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    
    # The local constant test section must enable the second tool
    assert "ENABLE_DOGFOOD_SECOND_TOOL" in ci_config, (
        "CI must register the second dogfood tool"
    )
    local_section_start = ci_config.find("name: Run local trust-plane constant test loop")
    assert local_section_start > 0, "CI constant test section not found"
    
    # Find the next section boundary (the production test or next job)
    next_section = ci_config.find("name: Run production constant test loop", local_section_start)
    if next_section < 0:
        next_section = len(ci_config)
    
    local_section = ci_config[local_section_start:next_section]
    
    # Verify ENABLE_DOGFOOD_SECOND_TOOL is set to true
    assert 'ENABLE_DOGFOOD_SECOND_TOOL: "true"' in local_section, (
        "Second tool must be enabled in local CI test"
    )
    
    # Verify the invocation passes --other-tool
    assert "--other-tool" in local_section, (
        "constant_test_loop.py invocation must pass --other-tool to exercise "
        "out-of-scope denial; registering the tool but not using it silently "
        "skips the permit scoping check"
    )
    
    # Verify it's passed the correct tool ID
    assert "partner.notes.count" in local_section, (
        "CI must pass --other-tool partner.notes.count to exercise denial "
        "with the second registered dogfood tool"
    )


def test_constant_test_loop_accepts_other_tool_flag():
    """The script must accept --other-tool and use it for the denial check."""
    # Import the script to verify the argument is defined
    import importlib.util
    
    spec = importlib.util.spec_from_file_location(
        "constant_test_loop", CONSTANT_TEST_SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    # Verify the CLI parser includes --other-tool
    import inspect
    source = inspect.getsource(module)
    assert "--other-tool" in source, "CLI must accept --other-tool flag"
    assert "CI_SMOKE_OTHER_TOOL" in source, (
        "Script must support CI_SMOKE_OTHER_TOOL environment variable"
    )


def test_second_tool_is_distinct_from_first():
    """partner.notes.count must differ from partner.notes.write.
    
    The companion tool selection logic rejects a pin equal to the governed
    tool because that would assert a denial that should never happen.
    """
    from app.services.dogfood_tool import DOGFOOD_TOOL_ID, DOGFOOD_SECOND_TOOL_ID
    
    assert DOGFOOD_TOOL_ID != DOGFOOD_SECOND_TOOL_ID, (
        "The second dogfood tool must differ from the first to prove "
        "permit scoping; using the same tool would skip the check"
    )
    assert DOGFOOD_TOOL_ID == "partner.notes.write"
    assert DOGFOOD_SECOND_TOOL_ID == "partner.notes.count"


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="CI workflow test only runs on Linux (GitHub Actions environment)",
)
def test_ci_workflow_syntax_is_valid():
    """The CI workflow file must be valid YAML."""
    import yaml
    
    ci_path = ROOT / ".github" / "workflows" / "ci.yml"
    with ci_path.open() as f:
        try:
            yaml.safe_load(f)
        except yaml.YAMLError as e:
            pytest.fail(f"CI workflow YAML is invalid: {e}")
