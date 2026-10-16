"""Release metadata must carry the wrapper's MIT license."""

import tomllib
from importlib.metadata import distribution
from pathlib import Path


def test_source_declares_mit_license() -> None:
    package_root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((package_root / "pyproject.toml").read_text())
    project = config["project"]
    license_text = (package_root / "LICENSE").read_text()

    assert project["license"] == "MIT"
    assert "License :: OSI Approved :: MIT License" in project["classifiers"]
    assert "LICENSE" in config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert license_text.startswith("MIT License\n")


def test_installed_wheel_carries_mit_license() -> None:
    package_root = Path(__file__).resolve().parents[1]
    license_text = (package_root / "LICENSE").read_text()
    installed = distribution("crewai-agent-middleware")
    assert installed.metadata["License-Expression"] == "MIT"
    assert "License :: OSI Approved :: MIT License" in installed.metadata.get_all("Classifier", [])
    license_files = [
        file
        for file in installed.files or []
        if file.name == "LICENSE" and ".dist-info/licenses/" in str(file)
    ]
    assert license_files, "installed wheel must include the MIT LICENSE file"
    assert any(installed.locate_file(file).read_text() == license_text for file in license_files)
