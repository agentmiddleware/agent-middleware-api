"""Coverage for scripts/rotate_api_keys.py.

The verifier is the last gate in the rotation runbook, so its failure
semantics matter more than its happy path: a rotation is only complete when
the retired key is rejected AND the replacement authenticates, and the
script must exit non-zero on every other combination.
"""

import importlib.util
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "rotate_api_keys", REPO_ROOT / "scripts" / "rotate_api_keys.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def rotate():
    return _load_module()


def _env(monkeypatch, url="https://api.example.test", old="old-key-value", new="new-key-value"):
    monkeypatch.setenv("AGENT_MIDDLEWARE_API_URL", url)
    monkeypatch.setenv("OLD_API_KEY", old)
    monkeypatch.setenv("NEW_API_KEY", new)


def _fake_probe(status_by_key):
    def probe(base_url, api_key):
        return httpx.Response(
            status_by_key[api_key], request=httpx.Request("GET", base_url)
        )

    return probe


def test_generate_prints_distinct_prefixed_keys(rotate, capsys):
    assert rotate.generate(3) == 0
    keys = capsys.readouterr().out.strip().splitlines()
    assert len(keys) == 3
    assert len(set(keys)) == 3
    for key in keys:
        assert key.startswith(rotate.KEY_PREFIX)
        # token_urlsafe(32) yields 43 chars; anything shorter means the
        # entropy constant was accidentally lowered.
        assert len(key) >= len(rotate.KEY_PREFIX) + 43


def test_verify_requires_env(rotate, monkeypatch):
    for var in ("AGENT_MIDDLEWARE_API_URL", "OLD_API_KEY", "NEW_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert rotate.verify() == 2


def test_verify_passes_when_old_dead_and_new_live(rotate, monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(
        rotate, "_probe", _fake_probe({"old-key-value": 403, "new-key-value": 200})
    )
    assert rotate.verify() == 0


def test_verify_fails_when_old_key_still_authenticates(rotate, monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(
        rotate, "_probe", _fake_probe({"old-key-value": 200, "new-key-value": 200})
    )
    assert rotate.verify() == 1


def test_verify_fails_when_new_key_rejected(rotate, monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(
        rotate, "_probe", _fake_probe({"old-key-value": 403, "new-key-value": 403})
    )
    assert rotate.verify() == 1
