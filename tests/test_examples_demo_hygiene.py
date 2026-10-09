"""Regression tests for the examples-hygiene audit finding.

Covers three small fixes in the demo scripts:

- ``examples/dry_run_example.py`` prints the full traceback on failure
  instead of a one-line hint that hides the cause.
- ``examples/acta_receipt_interop.py`` resolves its proof-artifact paths
  from the script location (not the launch directory) and reports an
  unknown bundle kid as a readable error instead of ``StopIteration``.
- ``examples/mcp_tool_example.py`` builds the demo image URL from a
  stable digest instead of the per-process ``hash()`` value.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    """Import an example script as a module without running its main."""
    spec = importlib.util.spec_from_file_location(
        f"examples_hygiene_{name}", ROOT / "examples" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dry_run = _load("dry_run_example")
interop = _load("acta_receipt_interop")
mcp_example = _load("mcp_tool_example")


def test_generate_image_url_uses_stable_digest() -> None:
    """The demo URL must embed the sha256 of the prompt, not hash()."""
    prompt = "a cat riding a bicycle"
    result = asyncio.run(mcp_example.generate_image(prompt))
    expected = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert result["image_url"] == (f"https://placeholder.com/generated/{expected}.png")


def test_generate_image_url_is_repeatable() -> None:
    """Two calls with the same prompt must produce the same URL."""
    first = asyncio.run(mcp_example.generate_image("same prompt"))
    second = asyncio.run(mcp_example.generate_image("same prompt"))
    assert first["image_url"] == second["image_url"]


def test_dry_run_main_prints_full_error(capsys) -> None:
    """main() must show the traceback, not just a one-line hint."""

    async def _boom():
        raise ValueError("boom-xyz-hygiene")

    monkey_target = dry_run.demo_simulation
    dry_run.demo_simulation = _boom  # type: ignore[assignment]
    try:
        asyncio.run(dry_run.main())
    finally:
        dry_run.demo_simulation = monkey_target  # type: ignore[assignment]
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Traceback" in combined
    assert "ValueError" in combined
    assert "boom-xyz-hygiene" in combined


def test_demo_works_from_another_launch_directory(monkeypatch, tmp_path) -> None:
    """_demo must find its files even when launched from elsewhere."""
    monkeypatch.chdir(tmp_path)
    assert interop._demo("site/proof/receipt.json") == 0


def test_demo_unknown_kid_is_a_readable_error(tmp_path) -> None:
    """An unknown bundle kid must raise TranscodeError naming the kid."""
    bundle = json.loads((ROOT / "site" / "proof" / "receipt.json").read_text())
    bundle["kid"] = "kid-does-not-exist-hygiene"
    bundle_path = tmp_path / "receipt.json"
    bundle_path.write_text(json.dumps(bundle))
    with pytest.raises(interop.TranscodeError, match="kid-does-not-exist-hygiene"):
        interop._demo(str(bundle_path))
