"""The publish-mcp workflow holds registry publishing credentials, so the
mcp-publisher binary it downloads must be pinned and checksum verified."""

import re

WORKFLOW_PATH = ".github/workflows/publish-mcp.yml"


def _workflow():
    with open(WORKFLOW_PATH, encoding="utf-8") as handle:
        return handle.read()


def test_no_latest_download_url():
    """The binary must not be fetched from a floating latest release."""
    assert "releases/latest/download" not in _workflow()


def test_download_uses_pinned_version():
    """The download URL must reference a pinned release version."""
    workflow = _workflow()
    assert "releases/download/" in workflow
    assert re.search(r"MCP_PUBLISHER_VERSION:\s*v\d+\.\d+\.\d+", workflow)


def test_checksum_verified_before_extraction():
    """The downloaded archive must pass a SHA-256 check before extraction."""
    workflow = _workflow()
    install_step = workflow.split("Install mcp-publisher", 1)[1]
    verify_at = install_step.find("sha256sum -c")
    extract_at = install_step.find("tar xz")
    assert verify_at != -1
    assert extract_at != -1
    assert verify_at < extract_at


def test_pinned_hashes_are_well_formed():
    """Both pinned architecture hashes must be full SHA-256 hex digests."""
    workflow = _workflow()
    hashes = re.findall(r"MCP_PUBLISHER_SHA256_\w+:\s*([0-9a-f]+)", workflow)
    assert len(hashes) >= 2
    for digest in hashes:
        assert len(digest) == 64


def test_no_floating_action_refs():
    """No step may track a floating branch or major-version action ref."""
    for line in _workflow().splitlines():
        stripped = line.strip()
        if stripped.startswith("uses:"):
            ref = stripped.split("uses:", 1)[1].strip()
            assert not ref.endswith("@main")
            assert not ref.endswith("@master")
            assert re.search(r"@[0-9a-f]{40}(\s|#|$)", ref), ref
