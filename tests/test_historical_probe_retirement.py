"""Archived diagnostics cannot issue probes or masquerade as an auth gate."""

import importlib.util
from pathlib import Path
import runpy
import sys
import urllib.request

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "docs/research/external-adversarial-2026-09-11/gauntlet.py"
)


def load():
    spec = importlib.util.spec_from_file_location("historical_gauntlet", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archived_transport_refuses_before_network(monkeypatch):
    module = load()

    def forbidden(*args, **kwargs):
        pytest.fail("archived transport must not issue network requests")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    with pytest.raises(RuntimeError, match="retired.*non-gating"):
        module.raw("GET", "/v1/permits")


def test_archived_cli_exits_before_batteries(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("archived CLI must not issue network requests")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "1"])
    with pytest.raises(SystemExit, match="retired.*non-gating"):
        runpy.run_path(str(SCRIPT), run_name="__main__")


def test_historical_counts_are_not_auth_verdicts(capsys):
    module = load()
    module._report(
        "synthetic historical observations", [("noauth /v1/permits", 200, "")]
    )
    output = capsys.readouterr().out
    assert "not an auth-boundary verdict" in output
    assert "0 findings" not in output
    assert "0 diagnostic flags" in output
