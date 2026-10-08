"""Guards for the destructive filesystem operations in helper scripts.

scripts/quickstart.py --reset deletes the state directory and the shell
script scripts/build_refund_partner_bundle.sh deletes its output directory.
Both used to remove whatever path they were given, so a typo or a bad
default could wipe an unrelated directory. The scripts now resolve the
target and refuse the dangerous cases before anything is removed.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
QUICKSTART_PATH = REPO_ROOT / "scripts" / "quickstart.py"
BUNDLE_SCRIPT = REPO_ROOT / "scripts" / "build_refund_partner_bundle.sh"


def _load_quickstart():
    spec = importlib.util.spec_from_file_location(
        "fleet_quickstart_under_test", QUICKSTART_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


quickstart = _load_quickstart()


# --- scripts/quickstart.py --reset -----------------------------------------


def test_reset_accepts_directory_inside_data_dir():
    target = REPO_ROOT / "data" / "quickstart"
    resolved = quickstart.resolve_state_dir_for_reset(target)
    assert resolved == target.resolve()
    nested = REPO_ROOT / "data" / "quickstart-alt"
    assert quickstart.resolve_state_dir_for_reset(nested) == nested.resolve()


def test_reset_accepts_repo_relative_state_dir():
    resolved = quickstart.resolve_state_dir_for_reset(
        Path("data") / "quickstart-custom"
    )
    assert resolved == (REPO_ROOT / "data" / "quickstart-custom").resolve()


@pytest.mark.parametrize(
    "raw",
    [
        Path("/"),
        Path.home(),
        REPO_ROOT,
        REPO_ROOT / "data",
        Path("/tmp") / "quickstart-outside",
        REPO_ROOT / "data" / ".." / "tests",
        Path("..") / "outside-repo",
        Path("~"),
    ],
)
def test_reset_refuses_paths_outside_data_dir(raw):
    with pytest.raises(ValueError):
        quickstart.resolve_state_dir_for_reset(raw)


def test_reset_refuses_symlink_escaping_data_dir(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = REPO_ROOT / "data" / "quickstart-symlink-probe"
    parent_existed = link.parent.exists()
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
        with pytest.raises(ValueError):
            quickstart.resolve_state_dir_for_reset(link)
    finally:
        if link.is_symlink() or link.exists():
            link.unlink()
        if not parent_existed:
            try:
                link.parent.rmdir()
            except OSError:
                pass


def test_reset_main_refuses_root_without_deleting(tmp_path):
    sentinel = tmp_path / "sentinel"
    sentinel.mkdir()
    marker = sentinel / "keep.txt"
    marker.write_text("do not delete", encoding="utf-8")
    rc = quickstart.main(["--reset", "--state-dir", str(sentinel), "--port", "1"])
    assert rc == 2
    assert marker.exists()


# --- scripts/build_refund_partner_bundle.sh ---------------------------------


def _run_bundle_script(
    *args: str, extra_env: dict | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(BUNDLE_SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_bundle_script_uses_strict_mode():
    text = BUNDLE_SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text


@pytest.mark.parametrize("dangerous", ["root", "home", "repo", "tmp"])
def test_bundle_script_refuses_dangerous_output_dirs(tmp_path, dangerous, monkeypatch):
    if dangerous == "root":
        target = Path("/")
        probe = None
    elif dangerous == "home":
        target = Path.home()
        probe = target / ".fleet-guard-probe"
        probe.mkdir(exist_ok=True)
    elif dangerous == "repo":
        target = REPO_ROOT
        probe = None
    else:
        target = Path(os.environ.get("TMPDIR", "/tmp"))
        probe = None
    try:
        result = _run_bundle_script(str(target))
    finally:
        if probe is not None:
            assert probe.exists()
            shutil.rmtree(probe, ignore_errors=True)
    assert result.returncode != 0
    assert "refusing" in result.stderr


def test_bundle_script_rebuilds_bundle_dir(tmp_path):
    out_dir = tmp_path / "refund-partner-bundle"
    out_dir.mkdir()
    stale = out_dir / "stale.txt"
    stale.write_text("stale", encoding="utf-8")
    result = _run_bundle_script(str(out_dir))
    assert result.returncode == 0, result.stdout + result.stderr
    assert not stale.exists()
    assert (out_dir / "main.py").exists()
    assert (out_dir / "requirements.txt").exists()
    assert (out_dir / "railway.json").exists()


def test_bundle_script_passes_shellcheck():
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        pytest.skip("shellcheck is not installed")
    result = subprocess.run(
        [shellcheck, "-S", "warning", str(BUNDLE_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
