"""Safety gates for the operator-only live proof publisher."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts import publish_live_proof


class _FakeResponse:
    def __init__(self, payload=None, *, status_code: int = 200):
        self._payload = payload or {}
        self.status_code = status_code
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class _ProofClient:
    def __init__(
        self,
        *,
        cleanup_status: int = 204,
        raise_permit_cleanup: bool = False,
        raise_key_create: bool = False,
        malformed_key_response: bool = False,
    ):
        self.cleanup_status = cleanup_status
        self.raise_permit_cleanup = raise_permit_cleanup
        self.raise_key_create = raise_key_create
        self.malformed_key_response = malformed_key_response
        self.calls: list[tuple[str, str]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def get(self, path, **_kwargs):
        self.calls.append(("GET", path))
        payloads = {
            "/health": {"status": "ok"},
            "/v1/receipts/rcpt-1/portable": {
                "issuer": "https://api.thisisatest.tech",
                "kid": "proof-key",
                "receipt_id": "rcpt-1",
            },
            "/.well-known/trust-keys.json": {"keys": []},
        }
        return _FakeResponse(payloads[path])

    def post(self, path, **_kwargs):
        self.calls.append(("POST", path))
        if path.endswith("/revoke"):
            if self.raise_permit_cleanup:
                raise RuntimeError("simulated cleanup transport failure")
            return _FakeResponse(status_code=self.cleanup_status)
        if path == "/v1/api-keys/emergency-revoke":
            return _FakeResponse(status_code=self.cleanup_status)
        if path == "/v1/api-keys" and self.raise_key_create:
            raise RuntimeError("simulated key-create timeout after commit")
        payloads = {
            "/v1/billing/wallets/sponsor": {"wallet_id": "sponsor-1"},
            "/v1/billing/wallets/agent": {"wallet_id": "agent-1"},
            "/v1/api-keys": {"key_id": "key-1", "api_key": "agent-secret"},
            "/v1/permits": {"permit_id": "permit-1"},
            "/mcp/messages": {"result": {"receipt": {"receipt_id": "rcpt-1"}}},
        }
        if path == "/v1/api-keys" and self.malformed_key_response:
            return _FakeResponse({"key_id": "key-1"})
        return _FakeResponse(payloads[path])


def _patch_successful_proof_run(monkeypatch, client: _ProofClient) -> None:
    monkeypatch.setenv("BOOTSTRAP_KEY", "bootstrap-secret")
    monkeypatch.setattr(
        publish_live_proof.httpx,
        "Client",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        publish_live_proof,
        "verify_bundle",
        lambda *_args, **_kwargs: SimpleNamespace(
            ok=True,
            reason=None,
            claims={
                "tool": "partner.echo",
                "outcome": "success",
                "credits_charged": "1",
                "created_at": "2026-08-11T00:00:00+00:00",
            },
        ),
    )


def test_live_proof_origin_is_pinned_to_canonical_https_host() -> None:
    assert (
        publish_live_proof._canonical_origin("https://api.thisisatest.tech/")
        == "https://api.thisisatest.tech"
    )

    for invalid in (
        "http://api.thisisatest.tech",
        "https://api.thisisatest.tech.attacker.example",
        "https://api.thisisatest.tech/other",
        "https://api.thisisatest.tech:4443",
        "https://user:secret@api.thisisatest.tech",
        "https://api-service-production-433c.up.railway.app",
    ):
        with pytest.raises(RuntimeError):
            publish_live_proof._canonical_origin(invalid)


def test_bootstrap_key_is_read_from_environment_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOOTSTRAP_KEY", raising=False)
    monkeypatch.setenv("VALID_API_KEYS", "first-secret, second-secret")
    assert publish_live_proof._bootstrap_key() == "first-secret"

    monkeypatch.setenv("BOOTSTRAP_KEY", "explicit-secret")
    assert publish_live_proof._bootstrap_key() == "explicit-secret"


def test_public_artifact_writer_refuses_credential_fields(tmp_path) -> None:
    safe_path = tmp_path / "safe.json"
    publish_live_proof._write_public_json(safe_path, {"receipt_id": "rcpt-1"})
    assert json.loads(safe_path.read_text(encoding="utf-8")) == {"receipt_id": "rcpt-1"}

    with pytest.raises(RuntimeError, match="credential"):
        publish_live_proof._write_public_json(
            tmp_path / "unsafe.json", {"api_key": "must-not-write"}
        )
    assert not (tmp_path / "unsafe.json").exists()


def test_cli_requires_explicit_live_confirmation(tmp_path) -> None:
    with pytest.raises(SystemExit) as exc:
        publish_live_proof.main(["--output-dir", str(tmp_path)])
    assert exc.value.code == 2


def test_publish_revokes_permit_and_all_wallet_keys_before_writing_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    client = _ProofClient()
    _patch_successful_proof_run(monkeypatch, client)

    result = publish_live_proof.publish(
        api_url="https://api.thisisatest.tech",
        output_dir=tmp_path,
    )

    assert result["receipt_id"] == "rcpt-1"
    assert ("POST", "/v1/permits/permit-1/revoke") in client.calls
    assert ("POST", "/v1/api-keys/emergency-revoke") in client.calls
    assert (tmp_path / "receipt.json").is_file()
    assert (tmp_path / "trust-keys.json").is_file()
    assert "agent-secret" not in (tmp_path / "receipt.json").read_text()


def test_publish_fails_closed_and_writes_nothing_when_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    client = _ProofClient(cleanup_status=500)
    _patch_successful_proof_run(monkeypatch, client)

    with pytest.raises(RuntimeError, match="authority cleanup failed"):
        publish_live_proof.publish(
            api_url="https://api.thisisatest.tech",
            output_dir=tmp_path,
        )

    assert ("POST", "/v1/permits/permit-1/revoke") in client.calls
    assert ("POST", "/v1/api-keys/emergency-revoke") in client.calls
    assert not (tmp_path / "receipt.json").exists()
    assert not (tmp_path / "trust-keys.json").exists()


def test_publish_still_revokes_all_keys_when_permit_cleanup_request_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    client = _ProofClient(raise_permit_cleanup=True)
    _patch_successful_proof_run(monkeypatch, client)

    with pytest.raises(RuntimeError, match="permit revoke request raised"):
        publish_live_proof.publish(
            api_url="https://api.thisisatest.tech",
            output_dir=tmp_path,
        )

    assert ("POST", "/v1/permits/permit-1/revoke") in client.calls
    assert ("POST", "/v1/api-keys/emergency-revoke") in client.calls
    assert not (tmp_path / "receipt.json").exists()


@pytest.mark.parametrize(
    "client,expected_error",
    [
        (
            _ProofClient(raise_key_create=True),
            "simulated key-create timeout after commit",
        ),
        (
            _ProofClient(malformed_key_response=True),
            "returned no usable API key",
        ),
    ],
)
def test_publish_emergency_revokes_unknown_key_after_key_creation_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: _ProofClient,
    expected_error: str,
) -> None:
    _patch_successful_proof_run(monkeypatch, client)

    with pytest.raises(RuntimeError, match=expected_error):
        publish_live_proof.publish(
            api_url="https://api.thisisatest.tech",
            output_dir=tmp_path,
        )

    assert ("POST", "/v1/api-keys/emergency-revoke") in client.calls
    assert not (tmp_path / "receipt.json").exists()
