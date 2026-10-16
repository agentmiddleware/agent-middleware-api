"""Release metadata must carry the wrapper's MIT license."""

import tomllib
from importlib.metadata import distribution
from pathlib import Path

# Canonical MIT text (https://opensource.org/license/mit) with this package's
# copyright line. Both the source LICENSE and the wheel copy must match it
# exactly, so a truncated or swapped file cannot pass on its heading alone.
CANONICAL_MIT_LICENSE = """\
MIT License

Copyright (c) 2026 Christopher Sellers

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def test_source_declares_mit_license() -> None:
    package_root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((package_root / "pyproject.toml").read_text())
    project = config["project"]
    license_text = (package_root / "LICENSE").read_text()

    assert project["license"] == "MIT"
    assert "License :: OSI Approved :: MIT License" in project["classifiers"]
    assert "LICENSE" in config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert license_text == CANONICAL_MIT_LICENSE


def test_installed_wheel_carries_mit_license() -> None:
    installed = distribution("crewai-agent-middleware")
    assert installed.metadata["License-Expression"] == "MIT"
    assert "License :: OSI Approved :: MIT License" in installed.metadata.get_all("Classifier", [])
    license_files = [
        file
        for file in installed.files or []
        if file.name == "LICENSE" and ".dist-info/licenses/" in str(file)
    ]
    assert license_files, "installed wheel must include the MIT LICENSE file"
    assert any(
        installed.locate_file(file).read_text() == CANONICAL_MIT_LICENSE for file in license_files
    )
