"""Supply-chain pins: Docker base images and the CI secret scanner.

Docker FROM lines must pin an immutable digest so rebuilds cannot silently
pick up a new upstream image. The CI gitleaks install must verify the
downloaded tarball against a pinned SHA-256 taken from the official
gitleaks release checksums before extracting it.
"""

import re

import pytest
import yaml

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent

FROM_PIN = re.compile(r"^FROM\s+\S+@sha256:[0-9a-f]{64}\s*$")
SHA256_HEX = re.compile(r"\b[0-9a-f]{64}\b")


def _dockerfile_from_lines(path):
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().upper().startswith("FROM")
    ]


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "Dockerfile.dev"])
def test_base_image_pinned_to_digest(dockerfile):
    """Every FROM line must pin image and digest, not a floating tag."""
    from_lines = _dockerfile_from_lines(dockerfile)
    assert from_lines, f"{dockerfile} has no FROM line"
    for line in from_lines:
        assert FROM_PIN.match(line), (
            f"{dockerfile} uses a floating base image: {line!r}. "
            "Pin it as <image>:<tag>@sha256:<digest>."
        )


def _secret_scan_install_step():
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["secret_scan"]["steps"]
    return next(
        s for s in steps if s.get("name", "").lower().startswith("install gitleaks")
    )


def _secret_scan_install_script():
    return _secret_scan_install_step()["run"]


def test_gitleaks_install_verifies_checksum():
    """The scanner tarball must be checksum-verified before extraction."""
    script = _secret_scan_install_script()
    assert "sha256sum -c" in script, (
        "gitleaks install does not verify the tarball checksum"
    )
    # Verification must happen before the tarball is unpacked.
    assert script.index("sha256sum -c") < script.index("tar -xzf"), (
        "checksum must be verified before the tarball is extracted"
    )


def test_gitleaks_install_pins_version_and_hash():
    """Version and expected hash must be pinned literals, not floating."""
    step = _secret_scan_install_step()
    env = step.get("env", {})
    assert env.get("GITLEAKS_VERSION") == "8.21.2"
    pinned = env.get("GITLEAKS_SHA256", "")
    assert SHA256_HEX.fullmatch(pinned), (
        "GITLEAKS_SHA256 must be a pinned 64-hex-digit hash"
    )
    # The pinned hash must be the official linux_x64 tarball checksum for
    # gitleaks 8.21.2 (see .github/workflows/ci.yml comment for the source).
    assert pinned == "5bc41815076e6ed6ef8fbecc9d9b75bcae31f39029ceb55da08086315316e3ba"
    # The run script must actually use the pinned hash for verification.
    assert "GITLEAKS_SHA256" in step["run"]
