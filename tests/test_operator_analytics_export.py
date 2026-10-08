"""Coverage for scripts/operator_analytics_export.py.

The export runs with a bootstrap admin key, so its failure modes matter:
a remote URL over plaintext HTTP must be refused, a missing credential
must fail closed before any request, and a malformed server response must
produce a clean error, not an AttributeError traceback that hides what
happened.
"""

import httpx
import pytest

from scripts import operator_analytics_export as export_mod


def test_loopback_http_is_accepted():
    assert (
        export_mod._require_safe_api_url("http://localhost:8000/")
        == "http://localhost:8000"
    )


def test_remote_https_is_accepted():
    assert (
        export_mod._require_safe_api_url("https://api.example.test/")
        == "https://api.example.test"
    )


def test_remote_plaintext_http_is_rejected():
    with pytest.raises(SystemExit, match="https"):
        export_mod._require_safe_api_url("http://api.example.test")


def test_missing_scheme_is_rejected():
    with pytest.raises(SystemExit):
        export_mod._require_safe_api_url("api.example.test")


def test_bootstrap_key_prefers_environment(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_KEY", "  env-key  ")
    assert export_mod._bootstrap_key("cli-key") == "env-key"


def test_bootstrap_key_falls_back_to_cli_flag(capsys):
    assert export_mod._bootstrap_key("cli-key") == "cli-key"
    assert "BOOTSTRAP_KEY" in capsys.readouterr().err


def test_missing_bootstrap_key_fails_closed(monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_KEY", raising=False)
    with pytest.raises(SystemExit, match="BOOTSTRAP_KEY"):
        export_mod._bootstrap_key(None)


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class _FakeClient:
    responses: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, path, params=None):
        payload = self.responses[path]
        if isinstance(payload, Exception):
            raise payload
        return payload


def _install_fake(monkeypatch, responses):
    fake = _FakeClient
    fake.responses = responses
    monkeypatch.setattr(export_mod.httpx, "Client", fake)


def _ok_responses():
    return {
        "/health": _FakeResponse({"status": "ok"}),
        "/v1/billing/wallets": _FakeResponse(
            {"wallets": [{"wallet_id": "w-1"}, {"wallet_id": "w-2"}]}
        ),
        "/v1/billing/ledger/w-1": _FakeResponse({"entries": []}),
        "/v1/billing/ledger/w-2": _FakeResponse({"entries": []}),
        "/v1/audit/events": _FakeResponse({"events": []}),
    }


def test_export_bundle_collects_wallets_ledger_and_audit(monkeypatch):
    _install_fake(monkeypatch, _ok_responses())
    bundle = export_mod.export_bundle(
        api_url="https://api.example.test",
        bootstrap_key="bootstrap",
        wallet_id=None,
        audit_limit=50,
        ledger_limit=50,
    )
    assert bundle["api_url"] == "https://api.example.test"
    assert {w["wallet_id"] for w in bundle["wallets"]} == {"w-1", "w-2"}
    assert set(bundle["ledger_by_wallet"]) == {"w-1", "w-2"}
    assert bundle["audit"] == {"events": []}
    assert bundle["exported_at"]


def test_export_bundle_wallet_filter_rejects_unknown_wallet(monkeypatch):
    _install_fake(monkeypatch, _ok_responses())
    with pytest.raises(SystemExit, match="wallet_id not found"):
        export_mod.export_bundle(
            api_url="https://api.example.test",
            bootstrap_key="bootstrap",
            wallet_id="w-missing",
            audit_limit=50,
            ledger_limit=50,
        )


def test_export_bundle_rejects_malformed_wallets_payload(monkeypatch):
    responses = _ok_responses()
    responses["/v1/billing/wallets"] = _FakeResponse(["w-1", "w-2"])
    _install_fake(monkeypatch, responses)
    with pytest.raises(SystemExit, match="/v1/billing/wallets"):
        export_mod.export_bundle(
            api_url="https://api.example.test",
            bootstrap_key="bootstrap",
            wallet_id=None,
            audit_limit=50,
            ledger_limit=50,
        )


def test_export_bundle_surfaces_http_errors(monkeypatch):
    responses = _ok_responses()
    responses["/health"] = _FakeResponse("down", status_code=503)
    _install_fake(monkeypatch, responses)
    with pytest.raises(SystemExit, match="/health"):
        export_mod.export_bundle(
            api_url="https://api.example.test",
            bootstrap_key="bootstrap",
            wallet_id=None,
            audit_limit=50,
            ledger_limit=50,
        )


def test_get_truncates_long_error_bodies(monkeypatch):
    resp = httpx.Response(
        500, text="x" * 2000, request=httpx.Request("GET", "https://h.test/x")
    )

    class _Client:
        def get(self, path, params=None):
            return resp

    with pytest.raises(SystemExit) as exc:
        export_mod._get(_Client(), "/x")
    assert len(str(exc.value)) < 1000
