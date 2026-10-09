"""--bootstrap-key is local-only in both operator scripts.

``scripts/partner_api_key_bootstrap.py`` and
``scripts/operator_analytics_export.py`` already prefer the BOOTSTRAP_KEY env
var, but the ``--bootstrap-key`` flag (visible in process listings) was still
accepted for any target. The flag now works only for loopback targets; env
still wins everywhere.
"""

import pytest

import scripts.operator_analytics_export as export
import scripts.partner_api_key_bootstrap as bootstrap

MODULES = [bootstrap, export]
LOOPBACK_URLS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "https://localhost:8000",
]
REMOTE_URL = "https://api.example.test"


@pytest.mark.parametrize("module", MODULES)
def test_env_key_wins_for_any_target(module, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_KEY", "env-secret")

    assert module._bootstrap_key("flag-secret", api_url=REMOTE_URL) == "env-secret"


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("api_url", LOOPBACK_URLS)
def test_flag_key_accepted_for_loopback(module, monkeypatch, capsys, api_url):
    monkeypatch.delenv("BOOTSTRAP_KEY", raising=False)

    assert module._bootstrap_key("flag-secret", api_url=api_url) == "flag-secret"
    assert "prefer BOOTSTRAP_KEY env" in capsys.readouterr().err


@pytest.mark.parametrize("module", MODULES)
def test_flag_key_refused_for_remote_target(module, monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_KEY", raising=False)

    with pytest.raises(SystemExit, match="local-only"):
        module._bootstrap_key("flag-secret", api_url=REMOTE_URL)


@pytest.mark.parametrize("module", MODULES)
def test_missing_key_still_fails_closed(module, monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_KEY", raising=False)

    with pytest.raises(SystemExit, match="BOOTSTRAP_KEY"):
        module._bootstrap_key(None, api_url="http://127.0.0.1:8000")
