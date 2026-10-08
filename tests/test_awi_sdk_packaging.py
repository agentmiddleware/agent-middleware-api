"""The AWI Python SDK ships packaging in this repository.

Regression coverage for the marketplace finding that
``awi_sdk/python`` had no ``pyproject.toml`` or README, so ``pip
install`` from that path failed: the directory must carry a local
distribution definition, the README must document only the
checkout install path, and the importable package version must match
the distribution version.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AWI_SDK_DIR = REPO_ROOT / "awi_sdk" / "python"


def _pyproject() -> dict:
    return tomllib.loads((AWI_SDK_DIR / "pyproject.toml").read_text())


def test_pyproject_defines_the_local_distribution() -> None:
    project = _pyproject()["project"]
    assert project["name"] == "agent-middleware-awi"
    assert project["version"] == "0.1.0"
    assert project["license"] == "MIT"
    assert any(dep.startswith("httpx") for dep in project["dependencies"]), (
        "the client imports httpx, so the distribution must declare it"
    )


def test_package_version_matches_distribution_version() -> None:
    import awi_sdk

    assert awi_sdk.__version__ == _pyproject()["project"]["version"]


def test_package_exposes_the_client_surface() -> None:
    import awi_sdk

    assert awi_sdk.AWIClient is not None
    assert awi_sdk.AWIClientConfig is not None


def test_readme_documents_only_the_checkout_install() -> None:
    readme = (AWI_SDK_DIR / "README.md").read_text()
    assert "pip install -e awi_sdk/python" in readme
    # Built from parts so this file does not itself contain the swept
    # bare-install needle (see test_docs_do_not_advertise_unpublished_installs).
    assert "pip install " + "agent-middleware-awi" not in readme
    assert "not published" in readme.lower()


@pytest.mark.parametrize("path", ["pyproject.toml", "README.md"])
def test_packaging_files_exist(path: str) -> None:
    assert (AWI_SDK_DIR / path).is_file()
