"""Coverage for scripts/export_openapi.py.

The committed docs/openapi.json is consumed by agents and mirrors, so the
--check gate must reliably detect drift, and a fresh export must round-trip
through --check. Write mode must honor an explicit --output path.
"""

from scripts import export_openapi


def test_check_reports_missing_file(tmp_path, capsys):
    missing = tmp_path / "openapi.json"
    rc = export_openapi.main(["--check", "--output", str(missing)])
    assert rc == 1
    assert "Missing" in capsys.readouterr().err


def test_write_then_check_round_trips(tmp_path, capsys):
    out = tmp_path / "openapi.json"
    assert export_openapi.main(["--output", str(out)]) == 0
    assert out.is_file()
    capsys.readouterr()
    assert export_openapi.main(["--check", "--output", str(out)]) == 0


def test_check_detects_stale_file(tmp_path, capsys):
    out = tmp_path / "openapi.json"
    assert export_openapi.main(["--output", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    out.write_text(text.replace("3.1.0", "9.9.9-stale"), encoding="utf-8")
    assert export_openapi.main(["--check", "--output", str(out)]) == 1


def test_relative_output_resolves_under_repo_root(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(export_openapi, "_REPO_ROOT", tmp_path)
    rc = export_openapi.main(["--output", "sub/openapi.json"])
    assert rc == 0
    assert (tmp_path / "sub" / "openapi.json").is_file()
    capsys.readouterr()
