"""Guards the script-smoke label on script-output tests.

``test_demo_trust_plane`` and ``test_dogfood_trust_plane`` shell out to
scripts and assert on the JSON those scripts print. That proves the script
ran, not that a customer integration works, so both modules must carry the
``script_smoke`` marker (registered in ``pyproject.toml``) and state the
limit in their docstrings. If a new script-output test is added, add its
module to ``SCRIPT_SMOKE_MODULES`` here with the same label.
"""

from __future__ import annotations

import importlib

import pytest

SCRIPT_SMOKE_MODULES = (
    "tests.test_demo_trust_plane",
    "tests.test_dogfood_trust_plane",
)


@pytest.mark.parametrize("module_name", SCRIPT_SMOKE_MODULES)
def test_script_output_module_carries_script_smoke_marker(module_name):
    module = importlib.import_module(module_name)
    raw = getattr(module, "pytestmark", [])
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    marks = {mark.name for mark in raw if hasattr(mark, "name")}
    assert "script_smoke" in marks, (
        f"{module_name} shells out to a script but lacks the script_smoke "
        "marker; a green run would be mistaken for integration proof"
    )


@pytest.mark.parametrize("module_name", SCRIPT_SMOKE_MODULES)
def test_script_output_module_docstring_states_the_limit(module_name):
    module = importlib.import_module(module_name)
    docstring = (module.__doc__ or "").lower()
    assert "script smoke" in docstring
    assert "not that a customer integration works" in docstring
