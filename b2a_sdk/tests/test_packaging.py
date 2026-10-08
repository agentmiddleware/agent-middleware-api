"""Packaging guards for the published ``b2a-sdk`` wheel.

The release version lives in exactly one place, ``b2a_sdk/pyproject.toml``.
``b2a_sdk.__version__`` resolves it from the installed distribution metadata
with a source-checkout fallback. These tests fail loudly if the two drift
apart, which used to ship a wheel whose runtime version string disagreed
with its own metadata, and they lock the publish-readiness properties a
buyer depends on: a working console entry point, a base install that needs
only httpx, and an sdist that contains the files a reinstall needs.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

import b2a_sdk

SDK_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = SDK_ROOT / "pyproject.toml"


def _pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, re.MULTILINE)
    assert match is not None, "pyproject.toml declares no version"
    return match.group(1)


def _source_fallback_version() -> str:
    text = (SDK_ROOT / "src" / "b2a_sdk" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^_FALLBACK_VERSION = "([^"]+)"$', text, re.MULTILINE)
    assert match is not None, "__init__.py declares no _FALLBACK_VERSION"
    return match.group(1)


def test_runtime_version_matches_pyproject() -> None:
    assert b2a_sdk.__version__ == _pyproject_version()


def test_source_fallback_matches_pyproject() -> None:
    assert _source_fallback_version() == _pyproject_version()


def test_installed_metadata_agrees_when_installed() -> None:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        pytest.skip("importlib.metadata unavailable")
    try:
        installed = version("b2a-sdk")
    except PackageNotFoundError:
        pytest.skip("b2a-sdk is not installed in this interpreter")
    assert b2a_sdk.__version__ == installed


def test_verify_cli_entry_point_target_exists() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r"^b2a-verify-receipt = \"([^\"]+)\"$", text, re.MULTILINE)
    assert match is not None, "console script b2a-verify-receipt is not declared"
    module_name, attr = match.group(1).split(":")
    module = pytest.importorskip(module_name)
    target = getattr(module, attr, None)
    assert callable(target), f"{match.group(1)} is not callable"


def test_base_install_needs_only_httpx() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r"^dependencies = \[(.*?)\]$", text, re.MULTILINE | re.DOTALL)
    assert match is not None, "pyproject.toml declares no base dependencies"
    base_deps = match.group(1)
    assert "httpx" in base_deps
    assert "cryptography" not in base_deps, "cryptography must stay in the verify extra"
    assert re.search(r"(?<![\w-])mcp(?![\w-])", base_deps) is None, (
        "mcp must stay in the mcp extra, not the base install"
    )


def test_sdist_declares_required_files() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    for required in ("README.md", "LICENSE", "CHANGELOG.md", "pyproject.toml", "tests"):
        assert required in text, f"sdist include list drops {required}"
        assert (SDK_ROOT / required).exists(), f"{required} is missing from the SDK dir"


def test_package_supports_declared_python_floor() -> None:
    assert sys.version_info >= (3, 10), "test run below the requires-python floor"
    text = PYPROJECT.read_text(encoding="utf-8")
    assert 'requires-python = ">=3.10"' in text
