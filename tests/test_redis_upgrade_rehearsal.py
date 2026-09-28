import importlib.util
import re
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).parents[1]
    / "docs"
    / "research"
    / "release-followup-2026-09-09"
    / "redis_upgrade_rehearsal.py"
)


def load_rehearsal_module():
    spec = importlib.util.spec_from_file_location("redis_upgrade_rehearsal", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prepare_workspace_rejects_missing_root_before_temp_dir(tmp_path):
    rehearsal = load_rehearsal_module()
    root = tmp_path / "missing"

    with pytest.raises(
        FileNotFoundError,
        match=re.escape(f"Redis rehearsal workspace root is missing: {root}"),
    ):
        rehearsal.prepare_workspace(root)

    assert not root.exists()


@pytest.mark.parametrize("missing_version", ["8.2.1", "8.2.9"])
def test_prepare_workspace_rejects_each_missing_binary_before_temp_dir(
    tmp_path, missing_version
):
    rehearsal = load_rehearsal_module()
    root = tmp_path / "redis-workspace"
    root.mkdir()
    for version in ("8.2.1", "8.2.9"):
        if version == missing_version:
            continue
        binary = root / f"redis-{version}" / "src" / "redis-server"
        binary.parent.mkdir(parents=True)
        binary.write_text("placeholder")

    missing_binary = root / f"redis-{missing_version}" / "src" / "redis-server"
    with pytest.raises(
        FileNotFoundError,
        match=re.escape(
            f"Expected Redis {missing_version} server binary is missing: "
            f"{missing_binary}"
        ),
    ):
        rehearsal.prepare_workspace(root)

    assert not list(root.glob("synthetic-*"))
