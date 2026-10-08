"""Unit tests for scripts/first_credential.py.

The onboarding review found that minting a first key means piping ``curl``
through inline JSON picks with no error message when provisioning fails.
The helper script must either print ``export`` lines or one readable
error; these tests pin that contract with mocked HTTP so no server is
needed.
"""

from __future__ import annotations

import io
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import first_credential  # noqa: E402


class _FakeBody:
    def __init__(self, payload: str):
        self._payload = payload.encode("utf-8")

    def read(self) -> bytes:
        return self._payload


class _FakeResponse:
    def __init__(self, payload: str):
        self._body = _FakeBody(payload)

    def __enter__(self):
        return self._body

    def __exit__(self, *args):
        return False


def _http_error(code: int, payload: str, url: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url, code, "error", {}, io.BytesIO(payload.encode("utf-8"))
    )


def test_provision_prints_exports(monkeypatch, capsys):
    def fake_urlopen(request, timeout=15):
        assert request.full_url.endswith("/v1/dev-keys/self-provision")
        sent = request.data.decode("utf-8")
        assert "quickstart-stranger" in sent
        return _FakeResponse(
            '{"api_key": "agt-1", "wallet_id": "w-1", "key_id": "k-1"}'
        )

    monkeypatch.setattr(first_credential.urllib.request, "urlopen", fake_urlopen)
    assert first_credential.main(["provision", "--api-url", "http://x:8000"]) == 0
    out = capsys.readouterr().out
    assert "export AGENT_API_KEY=agt-1" in out
    assert "export WALLET_ID=w-1" in out
    assert "export KEY_ID=k-1" in out


def test_provision_404_names_quickstart_only(monkeypatch, capsys):
    def fake_urlopen(request, timeout=15):
        raise _http_error(404, '{"detail": "not found"}', request.full_url)

    monkeypatch.setattr(first_credential.urllib.request, "urlopen", fake_urlopen)
    assert first_credential.main(["provision", "--api-url", "http://x:8000"]) == 2
    err = capsys.readouterr().err
    assert "self-provisioning is not enabled" in err
    assert "make quickstart" in err


def test_provision_unreachable_names_server(monkeypatch, capsys):
    def fake_urlopen(request, timeout=15):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(first_credential.urllib.request, "urlopen", fake_urlopen)
    assert first_credential.main(["provision", "--api-url", "http://x:8000"]) == 2
    assert "cannot reach" in capsys.readouterr().err


def test_provision_missing_fields_is_readable(monkeypatch, capsys):
    def fake_urlopen(request, timeout=15):
        return _FakeResponse('{"wallet_id": "w-1"}')

    monkeypatch.setattr(first_credential.urllib.request, "urlopen", fake_urlopen)
    assert first_credential.main(["provision", "--api-url", "http://x:8000"]) == 2
    assert "without api_key, key_id" in capsys.readouterr().err


def test_permit_builds_body_and_prints_id(monkeypatch, capsys):
    seen = {}

    def fake_urlopen(request, timeout=15):
        assert request.full_url.endswith("/v1/permits")
        assert request.headers["X-api-key"] == "agt-1"
        assert request.headers["Idempotency-key"] == "quickstart-permit-1"
        seen["sent"] = request.data.decode("utf-8")
        return _FakeResponse('{"permit_id": "pmt-1"}')

    monkeypatch.setattr(first_credential.urllib.request, "urlopen", fake_urlopen)
    rc = first_credential.main(
        [
            "permit",
            "--api-url",
            "http://x:8000",
            "--api-key",
            "agt-1",
            "--wallet-id",
            "w-1",
            "--key-id",
            "k-1",
        ]
    )
    assert rc == 0
    assert "export PERMIT_ID=pmt-1" in capsys.readouterr().out
    assert "partner.notes.write" in seen["sent"]
    assert "expires_at" in seen["sent"]


def test_permit_403_names_authority_rule(monkeypatch, capsys):
    def fake_urlopen(request, timeout=15):
        raise _http_error(403, '{"detail": "forbidden"}', request.full_url)

    monkeypatch.setattr(first_credential.urllib.request, "urlopen", fake_urlopen)
    rc = first_credential.main(
        [
            "permit",
            "--api-url",
            "http://x:8000",
            "--api-key",
            "agt-1",
            "--wallet-id",
            "w-1",
            "--key-id",
            "k-1",
        ]
    )
    assert rc == 2
    assert "only permit wallets it has authority over" in capsys.readouterr().err


def test_permit_conflict_is_readable(monkeypatch, capsys):
    def fake_urlopen(request, timeout=15):
        raise _http_error(409, "conflict", request.full_url)

    monkeypatch.setattr(first_credential.urllib.request, "urlopen", fake_urlopen)
    rc = first_credential.main(
        [
            "permit",
            "--api-url",
            "http://x:8000",
            "--api-key",
            "agt-1",
            "--wallet-id",
            "w-1",
            "--key-id",
            "k-1",
        ]
    )
    assert rc == 2
    assert "idempotency key reused" in capsys.readouterr().err


def test_stdout_stays_eval_safe_on_failure(monkeypatch, capsys):
    def fake_urlopen(request, timeout=15):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(first_credential.urllib.request, "urlopen", fake_urlopen)
    assert first_credential.main(["provision", "--api-url", "http://x:8000"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: ")
