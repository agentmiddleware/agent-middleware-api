"""The curated export must be safe to rerun on its public working copy."""

import os
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "tools" / "oss-export" / "export.sh"
FIX_WORDING = ROOT / "tools" / "oss-export" / "fix_wording.py"


def _export(destination: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(EXPORT)],
        cwd=ROOT,
        env={
            **os.environ,
            "AMW_EXPORT_SRC": str(ROOT),
            "AMW_EXPORT_DST": str(destination),
        },
        capture_output=True,
        text=True,
    )


def test_export_requires_a_git_working_copy_before_deleting_files(tmp_path):
    destination = tmp_path / "not-a-checkout"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("keep")

    result = _export(destination)

    assert result.returncode != 0
    assert "Git working copy" in result.stderr
    assert sentinel.read_text() == "keep"


def test_export_requires_the_public_gateway_license_before_copying(tmp_path):
    destination = tmp_path / "no-license"
    destination.mkdir()
    subprocess.run(["git", "init", "-q", str(destination)], check=True)

    result = _export(destination)

    assert result.returncode != 0
    assert "gateway/LICENSE.md" in result.stderr
    assert not (destination / "gateway" / "app").exists()


def test_export_rerun_purges_stale_gateway_files_and_preserves_public_metadata(
    tmp_path,
):
    destination = tmp_path / "public candidate"
    destination.mkdir()
    subprocess.run(["git", "init", "-q", str(destination)], check=True)
    gateway = destination / "gateway"
    gateway.mkdir()
    gateway_license = gateway / "LICENSE.md"
    gateway_license.write_text("public FSL license")
    sdk_license = destination / "sdk" / "python" / "LICENSE"
    sdk_license.parent.mkdir(parents=True)
    sdk_license.write_text("public Apache license")
    examples_license = destination / "examples" / "LICENSE"
    examples_license.parent.mkdir()
    examples_license.write_text("public Apache examples license")
    spec = destination / "spec" / "manual.md"
    spec.parent.mkdir()
    spec.write_text("hand maintained")

    first = _export(destination)
    assert first.returncode == 0, first.stderr
    assert (gateway / "WEDGE.md").read_bytes() == (ROOT / "WEDGE.md").read_bytes()
    assert (gateway / "DESIGN_PARTNER_GUIDE.md").read_bytes() == (
        ROOT / "DESIGN_PARTNER_GUIDE.md"
    ).read_bytes()
    assert (gateway / "SECURITY_LIMITATIONS.md").read_bytes() == (
        ROOT / "SECURITY_LIMITATIONS.md"
    ).read_bytes()
    assert (
        tomllib.loads((gateway / "pyproject.toml").read_text())["project"]["license"]
        == "LicenseRef-FSL-1.1-ALv2"
    )
    assert "BUSL-1.1" not in (gateway / "pyproject.toml").read_text()
    sdk_project = tomllib.loads(
        (destination / "sdk/python/pyproject.toml").read_text()
    )["project"]
    assert sdk_project["license"] == "Apache-2.0"
    assert (
        "License :: OSI Approved :: Apache Software License"
        in sdk_project["classifiers"]
    )
    assert "License :: OSI Approved :: MIT License" not in sdk_project["classifiers"]
    wrapper_configs = sorted(
        (destination / "integrations").glob("*-agent-middleware/pyproject.toml")
    )
    assert len(wrapper_configs) == 4
    for path in wrapper_configs:
        assert tomllib.loads(path.read_text())["project"]["license"] == "Apache-2.0"

    for name in (
        "test_prepare_railway_release.py",
        "test_publish_live_proof.py",
        "test_repo_guardian.py",
        "test_auto_pr_runner.py",
        "test_railway_preflight.py",
        "test_onboarding_contract.py",
        "test_site_agent_interface.py",
        "test_acta_receipt_interop.py",
        "test_dashboard_design.py",
        "test_proof_verifier.py",
        "test_published_proof.py",
        "test_vendor_fonts.py",
        "test_arcade_regressions.mjs",
        "test_site_design.mjs",
        "test_site_pilot_fit.mjs",
        "test_oss_export.py",
        "test_oss_export_drop_tests.py",
        "test_failure_lab_ci.py",
        "test_historical_probe_retirement.py",
        "test_operator_doc_contracts.py",
        "test_publish_mcp_pinned_download.py",
        "test_railway_iac_config.py",
    ):
        assert not (gateway / "tests" / name).exists()
    assert not (gateway / "site").exists()
    assert (gateway / "tests" / "test_permit_numeric_storage.py").is_file()
    awi_tests = (gateway / "tests" / "test_awi_adapter_sdk_hardening.py").read_text()
    assert (
        "def test_adapter_governance_denial_never_reaches_internal_route(" in awi_tests
    )
    for name in (
        "test_awi_sdk_execute_sends_permit_and_idempotency_headers",
        "test_awi_sdk_execute_rejects_invalid_governance_headers",
        "test_awi_sdk_config_repr_masks_api_key",
        "test_awi_sdk_does_not_follow_cross_host_redirects",
        "test_awi_sdk_governed_execute_end_to_end_and_cross_wallet_denied",
    ):
        assert f"def {name}(" not in awi_tests
    removed_source_cases = {
        "test_ci_second_tool_denial.py": (
            "test_ci_registers_second_tool_and_passes_it_to_constant_test",
            "test_ci_workflow_syntax_is_valid",
        ),
        "test_docker_commit_sha.py": (
            "test_dockerfile_requires_staged_commit_sha",
            "test_local_compose_uses_the_unstamped_development_dockerfile",
            "test_docker_publish_stages_the_checked_out_commit",
        ),
        "test_stale_commit_sha_prevention.py": (
            "test_dockerfile_requires_staged_build_commit_sha_file",
        ),
        "test_wedge_honesty.py": (
            "test_agentmarket_listing_is_wedge_honest",
            "test_feature_request_preserves_customer_identity_privacy",
            "test_readme_does_not_claim_deployment_ready_complete",
        ),
        "test_qa_be100_documentation.py": ("test_be100_pitch_scopes_retry_guarantees",),
    }
    for filename, names in removed_source_cases.items():
        exported = (gateway / "tests" / filename).read_text()
        for name in names:
            assert f"def {name}(" not in exported
    dockerfile = (gateway / "Dockerfile").read_text()
    assert "COPY sdk/python/ /sdk/python/" in dockerfile
    assert "pip install --no-cache-dir /sdk/python" in dockerfile
    assert "COPY gateway/ ." in dockerfile
    assert "COPY gateway/.build_commit_sha /app/.build_commit_sha" in dockerfile
    assert "COPY sdk/python/ /sdk/python/" in (gateway / "Dockerfile.dev").read_text()
    assert (
        "      context: ..\n      dockerfile: gateway/Dockerfile.dev"
        in (gateway / "docker-compose.yml").read_text()
    )
    assert (destination / ".dockerignore").read_bytes() == (
        ROOT / ".dockerignore"
    ).read_bytes()
    quickstart = (gateway / "docs/quickstart.md").read_text()
    assert "From the root of your `agent-middleware` export checkout:" in quickstart
    assert "cd gateway\nmake quickstart" in quickstart
    assert "from the\n`gateway/` directory:" in quickstart
    assert quickstart.count("PYTHONPATH=../sdk/python/src") == 2
    assert "agent-middleware-api.git" not in quickstart
    assert "PYTHONPATH=b2a_sdk/src" not in quickstart

    wording = subprocess.run(
        [sys.executable, str(FIX_WORDING)],
        cwd=destination,
        capture_output=True,
        text=True,
    )
    assert wording.returncode == 0, wording.stderr

    for path in (
        gateway / "app" / "stale.py",
        gateway / "scripts" / "stale.py",
        gateway / "scripts" / "repo_guardian.py",
        gateway / "tests" / "test_repo_guardian.py",
        gateway / "tests" / "test_proof_verifier.py",
        gateway / "tests" / "test_arcade_regressions.mjs",
        gateway / "docs" / "stale.md",
        destination / "sdk" / "python" / "stale.py",
        destination / "examples" / "stale.py",
    ):
        path.write_text("should be purged")

    second = _export(destination)
    assert second.returncode == 0, second.stderr
    for path in (
        gateway / "app" / "stale.py",
        gateway / "scripts" / "stale.py",
        gateway / "scripts" / "repo_guardian.py",
        gateway / "tests" / "test_repo_guardian.py",
        gateway / "tests" / "test_proof_verifier.py",
        gateway / "tests" / "test_arcade_regressions.mjs",
        gateway / "docs" / "stale.md",
        destination / "sdk" / "python" / "stale.py",
        destination / "examples" / "stale.py",
    ):
        assert not path.exists()
    assert (gateway / "WEDGE.md").read_bytes() == (ROOT / "WEDGE.md").read_bytes()
    assert (gateway / "DESIGN_PARTNER_GUIDE.md").read_bytes() == (
        ROOT / "DESIGN_PARTNER_GUIDE.md"
    ).read_bytes()
    assert gateway_license.read_text() == "public FSL license"
    assert sdk_license.read_text() == "public Apache license"
    assert examples_license.read_text() == "public Apache examples license"
    assert spec.read_text() == "hand maintained"
