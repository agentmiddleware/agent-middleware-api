"""Safety gates around executing untrusted candidate files.

The judge imports the candidate in-process with the operator's privileges,
so two gates stand in front of that import: the CLI refuses to run without
an explicit review confirmation, and the loader refuses files whose own
source already imports modules the audited party supplies, before executing
them rather than after.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from failure_lab.integration_check import judge


def _write_candidate(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def _import_time_marker_body(marker: Path) -> str:
    return (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n"
    )


def test_load_candidate_refuses_disqualifying_import_before_executing(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "executed.txt"
    candidate = _write_candidate(
        tmp_path,
        "sneaky.py",
        _import_time_marker_body(marker) + "import app\n",
    )
    with pytest.raises(ImportError, match="refusing to execute"):
        judge.load_candidate(candidate)
    assert not marker.exists()


def test_load_candidate_refuses_disqualifying_sibling_import(
    tmp_path: Path,
) -> None:
    _write_candidate(tmp_path, "sneaky_helper.py", "import app\n")
    candidate = _write_candidate(
        tmp_path, "sneaky.py", "import sneaky_helper\nCANDIDATE = None\n"
    )
    with pytest.raises(ImportError, match="refusing to execute"):
        judge.load_candidate(candidate)


def test_load_candidate_still_loads_reference_candidate() -> None:
    candidate = Path(judge.__file__).parent / "reference_candidate.py"
    loaded = judge.load_candidate(candidate)
    assert issubclass(loaded.factory, judge.CandidateIntegration)


def test_parse_args_review_flag_defaults_off() -> None:
    assert judge.parse_args(["--candidate", "x.py"]).i_have_reviewed is False
    assert (
        judge.parse_args(["--candidate", "x.py", "--i-have-reviewed"]).i_have_reviewed
        is True
    )


def test_main_refuses_without_review_confirmation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    marker = tmp_path / "executed.txt"
    candidate = _write_candidate(
        tmp_path, "benign.py", _import_time_marker_body(marker)
    )
    assert judge.main(["--candidate", str(candidate)]) == 2
    assert not marker.exists()
    assert "--i-have-reviewed" in capsys.readouterr().err
