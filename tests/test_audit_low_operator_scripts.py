"""LOW audit fixes for operator scripts: secrets-on-argv, shell strict mode,
seed file permissions, external-upload consent, retirement dry-run plus
backup, and the removed pipe-to-shell installer."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

import scripts.agent_ops_war_room_demo as war_room
import scripts.jev_codebase_review as jev_review
from scripts import retire_owner_keys

REPO_ROOT = Path(__file__).resolve().parent.parent


# 1. Secrets come from env; flags keep working with a deprecation warning.


def test_war_room_prefers_env_over_flag_and_stays_silent(monkeypatch, capsys):
    monkeypatch.setenv("WAR_ROOM_TEST_KEY", "env-secret")

    resolved = war_room._secret_from_env_or_flag(
        env_name="WAR_ROOM_TEST_KEY",
        flag_value="flag-secret",
        flag_name="--test-flag",
    )

    assert resolved == "env-secret"
    assert capsys.readouterr().err == ""


def test_war_room_flag_still_works_but_warns(monkeypatch, capsys):
    monkeypatch.delenv("WAR_ROOM_TEST_KEY", raising=False)

    resolved = war_room._secret_from_env_or_flag(
        env_name="WAR_ROOM_TEST_KEY",
        flag_value="flag-secret",
        flag_name="--test-flag",
    )

    assert resolved == "flag-secret"
    captured = capsys.readouterr()
    assert "prefer WAR_ROOM_TEST_KEY env over --test-flag" in captured.err


def test_war_room_returns_none_when_neither_source_set(monkeypatch):
    monkeypatch.delenv("WAR_ROOM_TEST_KEY", raising=False)

    assert (
        war_room._secret_from_env_or_flag(
            env_name="WAR_ROOM_TEST_KEY",
            flag_value=None,
            flag_name="--test-flag",
        )
        is None
    )


def test_war_room_help_marks_secret_flags_deprecated():
    result = subprocess.run(
        [sys.executable, "scripts/agent_ops_war_room_demo.py", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0
    assert "prefer DATABASE_URL env" in result.stdout
    assert "prefer BOOTSTRAP_KEY env" in result.stdout


# 2 and 3. Shell strict mode and seed file permissions (static + functional).


@pytest.mark.parametrize(
    ("script", "marker"),
    [
        ("scripts/human_preflight.sh", "set -euo pipefail"),
        ("scripts/docker_entrypoint.sh", "set -eu"),
        ("scripts/invariant_attacks/boot_controlled.sh", "set -euo pipefail"),
        ("scripts/invariant_attacks/boot_controlled_uv.sh", "set -euo pipefail"),
        ("scripts/core_quality_gate.sh", "set -euo pipefail"),
        ("scripts/trust_coverage_gate.sh", "set -euo pipefail"),
        ("scripts/trust_release_gate.sh", "set -euo pipefail"),
    ],
)
def test_shell_scripts_use_strict_mode(script, marker):
    content = (REPO_ROOT / script).read_text()

    assert marker in content


def test_boot_controlled_seed_is_private_by_default(tmp_path):
    """Run boot_controlled.sh with stubbed server startup under umask 022."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python"
    fake_python.write_text(
        '#!/bin/sh\nif [ "$1" = "-m" ]; then exit 0; fi\nexec python3 "$@"\n'
    )
    fake_python.chmod(0o755)

    env = {
        # The script needs a real python3 for seed generation; `python`
        # (the server launcher) stays stubbed so nothing is booted.
        "PATH": f"{fake_bin}:/usr/bin:/bin:{Path(sys.executable).parent}",
        "TP_STATE_DIR": str(state_dir),
        "TP_PORT": "8123",
    }
    result = subprocess.run(
        [
            "bash",
            "-c",
            "umask 022; exec bash scripts/invariant_attacks/boot_controlled.sh",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    seed = state_dir / "signing-seed.b64"
    assert seed.is_file()
    mode = stat.S_IMODE(seed.stat().st_mode)
    assert mode == 0o600, oct(mode)


# 4. External-upload consent for the codebase review script.


def test_jev_review_refuses_upload_without_consent(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["jev_codebase_review.py", "app/core"])
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    def _no_network(*args, **kwargs):
        raise AssertionError("no network call is allowed without consent")

    monkeypatch.setattr(jev_review.httpx, "AsyncClient", _no_network)

    assert asyncio.run(jev_review.main()) == 2
    captured = capsys.readouterr()
    assert "refusing to upload source" in captured.err
    assert "--i-understand-this-uploads-code" in captured.err


def test_jev_review_consent_prints_what_will_be_sent_before_key_check(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        sys,
        "argv",
        ["jev_codebase_review.py", "--i-understand-this-uploads-code", "app/core"],
    )
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    def _no_network(*args, **kwargs):
        raise AssertionError("no network call is allowed in this test")

    monkeypatch.setattr(jev_review.httpx, "AsyncClient", _no_network)

    assert asyncio.run(jev_review.main()) == 2
    captured = capsys.readouterr()
    assert "upload target: POST" in captured.out
    assert "/v1/systemone" in captured.out
    assert "upload payload:" in captured.out
    assert "first chunk:" in captured.out
    assert "TYPESAFE_API_KEY is not set" in captured.err


def test_jev_review_dry_run_needs_no_consent(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["jev_codebase_review.py", "--dry-run", "app/core"]
    )

    assert asyncio.run(jev_review.main()) == 0
    assert "chunks" in capsys.readouterr().out


# 5. Credential retirement: dry-run default plus a 0600 backup on apply.


def _seed_legacy_sqlite(db_path: Path, secret: str) -> str:
    sync_url = f"sqlite:///{db_path}"
    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE wallets (wallet_id VARCHAR(50) PRIMARY KEY, "
                "owner_key VARCHAR(255) NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE service_registry (service_id VARCHAR(100) PRIMARY KEY, "
                "owner_key VARCHAR(255) NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE refresh_tokens (jti VARCHAR(64) PRIMARY KEY, "
                "key_id VARCHAR(50), revoked BOOLEAN NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO wallets (wallet_id, owner_key) VALUES ('w1', :secret)"),
            {"secret": secret},
        )
        connection.execute(
            text(
                "INSERT INTO service_registry (service_id, owner_key) "
                "VALUES ('s1', :secret)"
            ),
            {"secret": secret},
        )
        connection.execute(
            text(
                "INSERT INTO refresh_tokens (jti, key_id, revoked) VALUES ('t1', NULL, 0)"
            )
        )
    engine.dispose()
    return f"sqlite+aiosqlite:///{db_path}"


def _owner_keys(sync_url: str) -> list:
    engine = create_engine(sync_url)
    with engine.connect() as connection:
        values = (
            connection.execute(text("SELECT owner_key FROM wallets")).scalars().all()
        )
    engine.dispose()
    return values


def test_retirement_defaults_to_dry_run_and_writes_nothing(
    monkeypatch, capsys, tmp_path
):
    secret = "dry-run-must-keep-me"
    db_path = tmp_path / "dry-run.db"
    async_url = _seed_legacy_sqlite(db_path, secret)
    monkeypatch.setattr(
        retire_owner_keys, "load_public_database_url", lambda: async_url
    )

    async def _must_not_write(_url):
        raise AssertionError("dry-run must not reach the write path")

    monkeypatch.setattr(retire_owner_keys, "retire_owner_keys", _must_not_write)

    assert retire_owner_keys.main([]) == 0

    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert "--apply" in out
    assert secret not in out
    assert _owner_keys(f"sqlite:///{db_path}") == [secret]


def test_retirement_apply_writes_0600_backup_then_scrubs(monkeypatch, capsys, tmp_path):
    secret = "apply-must-back-me-up"
    db_path = tmp_path / "apply.db"
    async_url = _seed_legacy_sqlite(db_path, secret)
    monkeypatch.setattr(
        retire_owner_keys, "load_public_database_url", lambda: async_url
    )
    backup_path = tmp_path / "backup.json"

    assert retire_owner_keys.main(["--apply", "--backup-path", str(backup_path)]) == 0

    assert backup_path.is_file()
    assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600
    backup = json.loads(backup_path.read_text())
    dumped = json.dumps(backup["tables"])
    assert "w1" in dumped and secret in dumped
    assert _owner_keys(f"sqlite:///{db_path}") == [""]

    out = capsys.readouterr().out
    assert "pre-scrub backup at" in out
    assert secret not in out


def test_preview_counts_without_writing(tmp_path):
    secret = "preview-must-keep-me"
    db_path = tmp_path / "preview.db"
    async_url = _seed_legacy_sqlite(db_path, secret)

    preview = asyncio.run(retire_owner_keys.preview_retirement(async_url))

    assert preview == {"wallets": 1, "service_registry": 1, "unbound_refresh_tokens": 1}
    assert _owner_keys(f"sqlite:///{db_path}") == [secret]


# 6. The bootstrap no longer pipes a remote installer to a shell.


def test_install_script_has_no_remote_pipe_to_shell():
    content = (REPO_ROOT / ".cursor" / "install.sh").read_text()

    assert "| sh" not in content
    assert "astral.sh/uv/install.sh |" not in content
    assert "refusing to fetch a remote installer" in content


def test_install_script_explains_manual_uv_setup_without_uv(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    env["PATH"] = "/usr/bin:/bin"
    env["HOME"] = str(home)

    probe = subprocess.run(
        ["bash", "-c", 'export PATH="/usr/bin:/bin"; command -v uv'],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if probe.returncode == 0:
        pytest.skip("uv is on the minimal PATH here; nothing to refuse")

    result = subprocess.run(
        ["bash", ".cursor/install.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 1
    assert "uv is not installed" in result.stderr
    assert "install uv manually" in result.stderr
