"""Regression tests for the curated export's test remover."""

import ast
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tools/oss-export/drop_tests.py"


def test_drops_parameterized_and_async_functions_without_corrupting_file(
    tmp_path: Path,
) -> None:
    source = (
        "import pytest\n\n"
        "@pytest.mark.parametrize(\n"
        '    "value", [1, 2],\n'
        ")\n"
        "def test_parameterized(value):\n"
        "    assert value\n\n"
        "@pytest.mark.asyncio\n"
        "async def test_async():\n"
        "    assert True\n\n"
        "def test_keep():\n"
        "    assert True\n"
    )
    test_file = tmp_path / "sample.py"
    test_file.write_text(source)

    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(test_file),
            "test_parameterized",
            "test_async",
        ],
        check=True,
    )

    remaining = test_file.read_text()
    module = ast.parse(remaining)
    assert [
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ] == ["test_keep"]
    assert "@pytest.mark" not in remaining
    assert "assert value" not in remaining
    assert "def test_keep():\n    assert True\n" in remaining


def test_nested_function_is_not_removed_or_written(tmp_path: Path) -> None:
    source = "def test_parent():\n    def test_nested():\n        pass\n"
    test_file = tmp_path / "sample.py"
    test_file.write_text(source)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(test_file), "test_nested"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert test_file.read_text() == source
