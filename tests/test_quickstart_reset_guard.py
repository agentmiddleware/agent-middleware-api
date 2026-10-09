"""Guards against --reset and the bundle script deleting arbitrary paths.

``scripts/quickstart.py --reset`` used to call ``shutil.rmtree`` on any
``--state-dir`` it was given, and ``scripts/build_refund_partner_bundle.sh``
used to ``rm -rf`` any output dir it was given. These tests prove both now
refuse dangerous targets instead of deleting them.
"""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_quickstart():
    spec = importlib.util.spec_from_file_location(
        "quickstart", REPO_ROOT / "scripts" / "quickstart.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


quickstart = _load_quickstart()


def test_reset_refuses_filesystem_root():
    assert quickstart.reset_refusal(Path("/")) is not None


def test_reset_refuses_home_repo_and_temp_root(tmp_path):
    from pathlib import Path as P

    assert quickstart.reset_refusal(P.home()) is not None
    assert quickstart.reset_refusal(REPO_ROOT) is not None
    assert quickstart.reset_refusal(REPO_ROOT.parent) is not None
    assert quickstart.reset_refusal(REPO_ROOT / "data" / "quickstart") is None
    assert quickstart.reset_refusal(P(tempfile.gettempdir())) is not None
    missing = tmp_path / "fresh-state-dir"
    assert quickstart.reset_refusal(missing) is None


def test_reset_refuses_directory_with_foreign_files(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    sentinel = state_dir / "important.txt"
    sentinel.write_text("do not delete", encoding="utf-8")
    refusal = quickstart.reset_state_dir(state_dir)
    assert refusal is not None
    assert "unexpected files" in refusal
    assert sentinel.exists()


def test_reset_clears_directory_with_only_expected_files(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for name in ("api.db", "api.db-wal", "state.db", "signing-seed.b64", "server.log"):
        (state_dir / name).write_text("x", encoding="utf-8")
    assert quickstart.reset_state_dir(state_dir) is None
    assert not state_dir.exists()


def test_main_reset_refuses_foreign_dir_without_deleting(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    sentinel = state_dir / "notes.txt"
    sentinel.write_text("keep me", encoding="utf-8")
    code = quickstart.main(
        ["--reset", "--state-dir", str(state_dir), "--port", "18099"]
    )
    assert code == 2
    assert sentinel.exists()


def _run_bundle_script(*args):
    return subprocess.run(
        ["sh", str(REPO_ROOT / "scripts" / "build_refund_partner_bundle.sh"), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_bundle_script_refuses_dangerous_dirs(tmp_path):
    from pathlib import Path as P

    for dangerous in ("/", str(P.home()), str(REPO_ROOT), str(REPO_ROOT.parent)):
        result = _run_bundle_script(dangerous)
        assert result.returncode != 0, dangerous
    assert P.home().exists()
    assert (REPO_ROOT / "scripts" / "quickstart.py").exists()


def test_bundle_script_builds_into_a_fresh_dir(tmp_path):
    out_dir = tmp_path / "refund-partner-bundle"
    result = _run_bundle_script(str(out_dir))
    assert result.returncode == 0, result.stderr
    assert (out_dir / "main.py").exists()
    assert (out_dir / "requirements.txt").exists()
    assert (out_dir / "railway.json").exists()
