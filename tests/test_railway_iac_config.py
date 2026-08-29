"""Repository guards for the API-only Railway IaC owner."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IAC_ROOT = REPO_ROOT / ".railway"

EXPECTED_IAC_FILES = {
    "README.md",
    "check.mjs",
    "package-lock.json",
    "package.json",
    "railway.ts",
}

EXPECTED_VARIABLES = {
    "ALLOW_LEGACY_UNPERMITTED_MCP",
    "CORS_ORIGINS",
    "DATABASE_URL",
    "DEBUG",
    "ENABLE_DOGFOOD_TOOL",
    "ENABLE_PROOF_SURFACES",
    "ENABLE_PUBLIC_MCP_ENDPOINT",
    "ENVIRONMENT",
    "MCP_UPSTREAM_BEARER_TOKEN",
    "MCP_UPSTREAM_CREDITS_PER_CALL",
    "MCP_UPSTREAM_ENABLED",
    "MCP_UPSTREAM_PUBLIC_TOOL_ID",
    "MCP_UPSTREAM_TOOL_NAME",
    "MCP_UPSTREAM_URL",
    "PORT",
    "PRODUCTION_URL",
    "PUBLIC_CONTACT_EMAIL",
    "PUBLIC_CONTACT_NAME",
    "PUBLIC_CONTACT_URL",
    "PUBLIC_URL",
    "REDIS_URL",
    "RUN_MIGRATIONS_ON_START",
    "SENTINEL_API_KEY",
    "SENTINEL_API_URL",
    "SIMULATION_MODE_HUMAN_APPROVAL",
    "STATE_BACKEND",
    "TRUST_MODE_ENABLED",
    "TRUST_SIGNING_KEY_ID",
    "TRUST_SIGNING_PRIVATE_KEY_B64",
    "VALID_API_KEYS",
    "WEBAUTHN_ALLOW_MOCK",
}


def test_api_iac_files_replace_retired_config_as_code() -> None:
    for name in EXPECTED_IAC_FILES:
        assert (IAC_ROOT / name).is_file(), f"missing Railway IaC support file: {name}"
    assert not (REPO_ROOT / "railway.json").exists()
    assert not (REPO_ROOT / "railway.toml").exists()


def test_iac_source_pins_the_exact_non_secret_api_posture() -> None:
    source = (IAC_ROOT / "railway.ts").read_text(encoding="utf-8")

    assert (
        'import { defineRailway, preserve, project, service } from "railway/iac";'
        in source
    )
    assert 'export const partial = "api-service";' in source
    assert re.search(r'project\(\s*"agent-middleware-api",\s*{', source)
    assert len(re.findall(r'service\(\s*"api-service",\s*{', source)) == 1
    assert re.search(
        r'build:\s*{\s*builder:\s*"DOCKERFILE",\s*'
        r'dockerfilePath:\s*"Dockerfile",\s*}',
        source,
    )
    assert re.search(
        r'deploy:\s*{\s*healthcheckPath:\s*"/health",\s*'
        r"healthcheckTimeout:\s*300,\s*}",
        source,
    )
    assert "restartPolicyType" not in source
    assert "restartPolicyMaxRetries" not in source
    assert re.search(r'replicas:\s*{\s*"us-west2":\s*1,?\s*}', source)
    assert re.search(r'domains:\s*\[\s*"api\.thisisatest\.tech"\s*\]', source)

    preserved_names = set(
        re.findall(r"^\s+([A-Z][A-Z0-9_]*): preserve\(\),$", source, re.MULTILINE)
    )
    assert preserved_names == EXPECTED_VARIABLES
    assert source.count("preserve()") == len(EXPECTED_VARIABLES)


def test_iac_source_contains_no_source_binding_or_unapproved_string_literal() -> None:
    source = (IAC_ROOT / "railway.ts").read_text(encoding="utf-8")

    assert "source:" not in source
    assert "github(" not in source
    assert "image(" not in source
    assert "template(" not in source
    assert "change-me" not in source.lower()
    assert "postgres://" not in source.lower()
    assert "redis://" not in source.lower()

    allowed_literals = {
        "/health",
        "DOCKERFILE",
        "Dockerfile",
        "agent-middleware-api",
        "api-service",
        "api.thisisatest.tech",
        "railway/iac",
        "us-west2",
    }
    assert set(re.findall(r'"([^"\n]*)"', source)) == allowed_literals


def test_iac_package_is_private_pinned_and_has_no_install_lifecycle() -> None:
    package = json.loads((IAC_ROOT / "package.json").read_text(encoding="utf-8"))
    assert package == {
        "name": "agent-middleware-api-railway-iac",
        "private": True,
        "type": "module",
        "engines": {"node": ">=24"},
        "scripts": {"test": "node check.mjs"},
        "dependencies": {"railway": "3.11.0"},
    }
    assert not {
        "preinstall",
        "install",
        "postinstall",
    }.intersection(package.get("scripts", {}))

    lock = json.loads((IAC_ROOT / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["packages"][""]["dependencies"] == {"railway": "3.11.0"}
    assert lock["packages"][""]["engines"] == {"node": ">=24"}
    assert lock["packages"]["node_modules/railway"]["version"] == "3.11.0"

    checker = (IAC_ROOT / "check.mjs").read_text(encoding="utf-8")
    assert "requireSupportedNodeRuntime(process.versions.node);" in checker
    assert "Node.js 24 or newer is required" in checker


def test_ignore_rules_allowlist_only_iac_source_and_support() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/railway.json" in gitignore
    assert "/railway.toml" in gitignore
    assert "/.railway/*" in gitignore
    assert {line for line in gitignore if line.startswith("!/.railway/")} == {
        f"!/.railway/{name}" for name in EXPECTED_IAC_FILES
    }
    assert (
        ".railway"
        in (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    )

    for ignored_path in (
        ".railway/project.json",
        ".railway/node_modules/railway/package.json",
        "railway.json",
        "railway.toml",
    ):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", ignored_path],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"path must stay ignored: {ignored_path}"
