"""Coverage for scripts/generate_static_dev_keys.py.

These keys authenticate as bootstrap admins in local environments, so the
generator must either print exactly the requested number of usable keys or
fail loudly. A silent success that prints nothing would leave an operator
believing keys were minted when none were.
"""

import sys

from scripts import generate_static_dev_keys as gen


def test_generate_prints_prefixed_unique_keys(capsys):
    rc = gen.generate(3)
    assert rc == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 3
    assert len(set(lines)) == 3
    for line in lines:
        assert line.startswith(gen.KEY_PREFIX)
        assert len(line) > len(gen.KEY_PREFIX) + 20


def test_generate_zero_count_fails_instead_of_silent_success(capsys):
    assert gen.generate(0) == 2
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "count" in captured.err.lower()


def test_generate_negative_count_fails(capsys):
    assert gen.generate(-2) == 2
    assert capsys.readouterr().out.strip() == ""


def test_main_rejects_zero_count(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["generate_static_dev_keys.py", "--count", "0"])
    assert gen.main() == 2
    assert capsys.readouterr().out.strip() == ""


def test_main_default_count_prints_two_keys(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["generate_static_dev_keys.py"])
    assert gen.main() == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 2
