"""Issuer key-fetch transport guard for b2a-verify-receipt.

Fetching trust keys over plain http lets a network attacker substitute keys,
so the --issuer fetch must require https and allow http only for loopback
hosts. These tests prove the scheme is checked before any network call and
that every refusal steers the user to the --keys offline option.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from b2a_sdk import verify_cli
from b2a_sdk.receipt_verifier import VerificationError


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _install_fake_httpx(monkeypatch, calls: list):
    fake = types.ModuleType("httpx")

    def fake_get(url, timeout=None):
        calls.append(url)
        return _FakeResponse({"keys": []})

    fake.get = fake_get  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "httpx", fake)
    return fake


@pytest.mark.parametrize(
    "issuer",
    [
        "http://api.example.com",
        "http://api.example.com:8000/",
        "http://192.168.1.10",
        "http://10.0.0.5:8000",
        "ftp://api.example.com",
        "api.example.com",
        "",
    ],
)
def test_insecure_or_bare_issuer_refused_before_network(monkeypatch, issuer):
    calls: list = []
    _install_fake_httpx(monkeypatch, calls)
    with pytest.raises(VerificationError, match=r"--keys"):
        verify_cli._fetch_key_document(issuer, 10.0)
    assert calls == []


@pytest.mark.parametrize(
    "issuer",
    [
        "https://api.example.com",
        "https://api.example.com:8443/",
        "http://localhost:8000",
        "http://localhost",
        "http://127.0.0.1:8000",
        "http://127.0.0.2",
        "http://[::1]:8000",
    ],
)
def test_allowed_issuers_reach_network(monkeypatch, issuer):
    calls: list = []
    _install_fake_httpx(monkeypatch, calls)
    document = verify_cli._fetch_key_document(issuer, 10.0)
    assert document == {"keys": []}
    assert len(calls) == 1
    assert calls[0].endswith("/.well-known/trust-keys.json")
    assert calls[0].startswith(issuer.rstrip("/"))


def test_cli_reports_undetermined_for_http_issuer(monkeypatch, tmp_path, capsys):
    calls: list = []
    _install_fake_httpx(monkeypatch, calls)
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps({"receipt_id": "rcpt-1"}), encoding="utf-8")
    code = verify_cli.main(["--bundle", str(bundle), "--issuer", "http://api.example.com"])
    assert code == verify_cli.EXIT_UNDETERMINED
    assert calls == []
    err = capsys.readouterr().err
    assert "--keys" in err
