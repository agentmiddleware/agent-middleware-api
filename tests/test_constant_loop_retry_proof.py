"""Offline tests for the opt-in constant-loop retry evidence mode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import constant_test_loop as loop


PROJECT_URL = "https://api.example.test"
TOOL = "partner.echo"
PAYLOAD = {"message": "approved payload must not be persisted"}
API_KEY = "fake-api-key-secret-canary"
WALLET_ID = "wallet-secret-canary"
KEY_ID = "key-secret-canary"

SUCCESS_RECEIPT = {
    "receipt_id": "receipt-success",
    "dispatch_attempt_id": "dispatch-success",
    "ledger_entry_id": "ledger-success",
    "permit_id": "permit-proof",
    "outcome": "success",
    "credits_charged": "2",
}
DENIAL_RECEIPT = {
    "receipt_id": "receipt-denied",
    "dispatch_attempt_id": None,
    "ledger_entry_id": None,
    "permit_id": "permit-proof",
    "outcome": "denied",
    "reason_code": "permit_max_calls_exceeded",
    "credits_charged": "0",
}


class _Response:
    def __init__(self, status_code: int, data: dict[str, Any]) -> None:
        self.status_code = status_code
        self._data = data
        self.text = json.dumps(data)

    def json(self) -> dict[str, Any]:
        return self._data


class _ProofClient:
    instances: list["_ProofClient"] = []

    def __init__(self, *, base_url: str, headers: dict[str, str], timeout: float):
        self.base_url = base_url
        self.headers = headers
        self.timeout = timeout
        self.posts: list[tuple[str, dict[str, Any], dict[str, str] | None]] = []
        self.gets: list[str] = []
        self.message_calls = 0
        self.__class__.instances.append(self)

    def __enter__(self) -> "_ProofClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(
        self,
        path: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> _Response:
        self.posts.append((path, json, headers))
        if path == "/v1/permits":
            return _Response(
                201,
                {
                    "permit_id": "permit-proof",
                    "spent_credits": "0",
                    "max_calls_per_tool": {TOOL: 1},
                    "allow_identical_repeats": True,
                },
            )
        if path == "/v1/receipts/verify":
            receipt_id = json["receipt_id"]
            receipt = {
                SUCCESS_RECEIPT["receipt_id"]: SUCCESS_RECEIPT,
                DENIAL_RECEIPT["receipt_id"]: DENIAL_RECEIPT,
            }[receipt_id]
            return _Response(200, {"valid": True, "receipt": dict(receipt)})
        if path == "/mcp/messages":
            self.message_calls += 1
            if self.message_calls <= 2:
                return _Response(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": json["id"],
                        "result": {
                            "isError": False,
                            "receipt": dict(SUCCESS_RECEIPT),
                        },
                    },
                )
            return _Response(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": json["id"],
                    "error": {
                        "code": -32003,
                        "message": "permit_max_calls_exceeded",
                        "data": {
                            "details": {"tool": TOOL, "limit": 1, "calls_made": 1},
                            "receipt": dict(DENIAL_RECEIPT),
                        },
                    },
                },
            )
        raise AssertionError(f"unexpected POST {path}")

    def get(self, path: str) -> _Response:
        self.gets.append(path)
        if path == "/mcp/tools.json":
            return _Response(
                200,
                {
                    "tools": [
                        {
                            "name": TOOL,
                            "annotations": {"creditsPerCall": 2},
                            "inputSchema": {"type": "object"},
                        }
                    ]
                },
            )
        if path == "/v1/permits/permit-proof":
            return _Response(200, {"spent_credits": "2"})
        if path == f"/v1/billing/ledger/{WALLET_ID}":
            return _Response(
                200,
                {
                    "entries": [
                        {
                            "entry_id": "ledger-success",
                            "action": "debit",
                            "amount": "-2",
                            "description": f"governed call to {TOOL}",
                        }
                    ]
                },
            )
        if path == "/v1/receipts/receipt-success/evidence":
            return _Response(
                200,
                {
                    "valid": True,
                    "checks": [{"name": "dispatch_linkage", "status": "passed"}],
                    "dispatch": {
                        "attempt_id": "dispatch-success",
                        "state": "succeeded",
                        "ledger_entry_id": "ledger-success",
                        "dispatched_at": "2026-09-28T00:00:00Z",
                    },
                },
            )
        raise AssertionError(f"unexpected GET {path}")


def _confirmation(output: Path) -> dict[str, object]:
    digest = loop.retry_proof_payload_sha256(PAYLOAD)
    return {
        "api_url": PROJECT_URL,
        "tool": TOOL,
        "tool_arguments": PAYLOAD,
        "evidence_output": output,
        "confirmed_target": PROJECT_URL,
        "confirmed_tool": TOOL,
        "confirmed_payload_sha256": digest,
    }


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("confirmed_target", "https://wrong.example.test"),
        ("confirmed_tool", "partner.wrong"),
        ("confirmed_payload_sha256", "0" * 64),
    ],
)
def test_retry_proof_requires_exact_target_tool_and_payload_confirmation(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    values = _confirmation(tmp_path / "proof.json")
    values[field] = replacement

    with pytest.raises(loop.ConfigurationError, match="confirmation"):
        loop.validate_retry_proof_confirmation(**values)

    assert not (tmp_path / "proof.json").exists()


@pytest.mark.parametrize("target", ["ftp://api.example.test", "https://"])
def test_retry_proof_requires_http_origin_with_hostname(
    tmp_path: Path,
    target: str,
) -> None:
    values = _confirmation(tmp_path / "proof.json")
    values["api_url"] = target
    values["confirmed_target"] = target

    with pytest.raises(loop.ConfigurationError, match="canonical API origin"):
        loop.validate_retry_proof_confirmation(**values)


def test_retry_proof_rejects_noncanonical_payload_and_output_paths(
    tmp_path: Path,
) -> None:
    invalid_payload = _confirmation(tmp_path / "proof.json")
    invalid_payload["tool_arguments"] = {"value": float("nan")}
    with pytest.raises(loop.ConfigurationError, match="canonical JSON"):
        loop.validate_retry_proof_confirmation(**invalid_payload)

    wrong_suffix = _confirmation(tmp_path / "proof.txt")
    with pytest.raises(loop.ConfigurationError, match=".json"):
        loop.validate_retry_proof_confirmation(**wrong_suffix)

    missing_parent = _confirmation(tmp_path / "missing" / "proof.json")
    with pytest.raises(loop.ConfigurationError, match="directory does not exist"):
        loop.validate_retry_proof_confirmation(**missing_parent)


def test_retry_proof_refuses_to_overwrite_existing_evidence(tmp_path: Path) -> None:
    output = tmp_path / "proof.json"
    output.write_text("existing evidence\n", encoding="utf-8")

    with pytest.raises(loop.ConfigurationError, match="already exists"):
        loop.validate_retry_proof_confirmation(**_confirmation(output))

    assert output.read_text(encoding="utf-8") == "existing evidence\n"


def test_retry_proof_evidence_write_loses_race_without_overwriting(
    tmp_path: Path,
) -> None:
    output = loop.validate_retry_proof_confirmation(
        **_confirmation(tmp_path / "proof.json")
    )
    output.write_text("racing writer\n", encoding="utf-8")

    with pytest.raises(loop.SmokeTestFailure, match="could not be written"):
        loop._write_retry_evidence(output, {"status": "passed"})

    assert output.read_text(encoding="utf-8") == "racing writer\n"


def test_retry_proof_cli_refuses_missing_confirmations_before_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(loop, "run_constant_test", fail_if_called)

    exit_code = loop.main(
        [
            "--api-url",
            PROJECT_URL,
            "--tool",
            TOOL,
            "--tool-args",
            json.dumps(PAYLOAD),
            "--retry-evidence-output",
            str(tmp_path / "proof.json"),
        ]
    )

    assert exit_code == 2
    assert called is False
    assert "confirmation" in capsys.readouterr().err


def test_retry_proof_cli_refuses_confirmation_flags_without_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(loop, "run_constant_test", fail_if_called)

    exit_code = loop.main(
        [
            "--api-url",
            PROJECT_URL,
            "--tool",
            TOOL,
            "--tool-args",
            json.dumps(PAYLOAD),
            "--confirm-retry-target",
            PROJECT_URL,
        ]
    )

    assert exit_code == 2
    assert called is False
    assert "require --retry-evidence-output" in capsys.readouterr().err


def test_retry_proof_cli_disables_self_provisioning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "proof.json"
    digest = loop.retry_proof_payload_sha256(PAYLOAD)
    called = False
    for name in ("CI_SMOKE_AGENT_KEY", "CI_SMOKE_WALLET_ID", "CI_SMOKE_KEY_ID"):
        monkeypatch.delenv(name, raising=False)

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(loop, "run_constant_test", fail_if_called)

    exit_code = loop.main(
        [
            "--api-url",
            PROJECT_URL,
            "--tool",
            TOOL,
            "--tool-args",
            json.dumps(PAYLOAD),
            "--retry-evidence-output",
            str(output),
            "--confirm-retry-target",
            PROJECT_URL,
            "--confirm-retry-tool",
            TOOL,
            "--confirm-retry-payload-sha256",
            digest,
        ]
    )

    assert exit_code == 2
    assert called is False
    assert "self-provisioning is disabled" in capsys.readouterr().err


def test_retry_proof_cli_forwards_validated_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "proof.json"
    digest = loop.retry_proof_payload_sha256(PAYLOAD)
    seen: dict[str, object] = {}
    monkeypatch.setenv("CI_SMOKE_AGENT_KEY", API_KEY)
    monkeypatch.setenv("CI_SMOKE_WALLET_ID", WALLET_ID)
    monkeypatch.setenv("CI_SMOKE_KEY_ID", KEY_ID)
    monkeypatch.setattr(
        loop,
        "run_constant_test",
        lambda *_args, **kwargs: seen.update(kwargs),
    )

    exit_code = loop.main(
        [
            "--api-url",
            PROJECT_URL,
            "--tool",
            TOOL,
            "--tool-args",
            json.dumps(PAYLOAD),
            "--retry-evidence-output",
            str(output),
            "--confirm-retry-target",
            PROJECT_URL,
            "--confirm-retry-tool",
            TOOL,
            "--confirm-retry-payload-sha256",
            digest,
        ]
    )

    assert exit_code == 0
    assert seen["retry_evidence_output"] == output


def test_retry_proof_proves_replay_and_cap_denial_without_secret_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "proof.json"
    monkeypatch.setattr(loop.httpx, "Client", _ProofClient)
    _ProofClient.instances.clear()

    loop.run_constant_test(
        PROJECT_URL,
        API_KEY,
        WALLET_ID,
        KEY_ID,
        pinned_tool=TOOL,
        tool_arguments=PAYLOAD,
        retry_evidence_output=output,
    )

    client = _ProofClient.instances[-1]
    permit_body = next(
        body for path, body, _headers in client.posts if path == "/v1/permits"
    )
    assert permit_body["max_calls_per_tool"] == {TOOL: 1}
    assert permit_body["allow_identical_repeats"] is True

    calls = [body for path, body, _headers in client.posts if path == "/mcp/messages"]
    assert len(calls) == 3
    assert calls[0] == calls[1]
    assert calls[2]["params"]["arguments"] == calls[0]["params"]["arguments"]
    assert (
        calls[2]["params"]["mcpContext"]["idempotency_key"]
        != calls[0]["params"]["mcpContext"]["idempotency_key"]
    )

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert output.stat().st_mode & 0o777 == 0o600
    assert evidence["status"] == "passed"
    assert evidence["target"] == {
        "origin": PROJECT_URL,
        "tool": TOOL,
        "payload_sha256": loop.retry_proof_payload_sha256(PAYLOAD),
    }
    assert evidence["permit"]["max_calls_per_tool"] == 1
    assert evidence["success"]["dispatch_evidence_valid"] is True
    assert evidence["same_key_replay"] == {
        "same_receipt": True,
        "same_dispatch_attempt": True,
        "additional_debits": 0,
        "additional_spend": "0",
    }
    assert evidence["fresh_key_denial"]["code"] == -32003
    assert evidence["fresh_key_denial"]["reason"] == "permit_max_calls_exceeded"
    assert evidence["fresh_key_denial"]["additional_debits"] == 0
    assert evidence["fresh_key_denial"]["additional_spend"] == "0"

    captured = capsys.readouterr()
    serialized = output.read_text(encoding="utf-8") + captured.out + captured.err
    for forbidden in (
        API_KEY,
        WALLET_ID,
        KEY_ID,
        PAYLOAD["message"],
        calls[0]["params"]["mcpContext"]["idempotency_key"],
        calls[2]["params"]["mcpContext"]["idempotency_key"],
    ):
        assert forbidden not in serialized


def test_retry_proof_does_not_echo_failed_response_or_write_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "provider-response-secret-canary"
    output = tmp_path / "proof.json"

    class FailingClient(_ProofClient):
        def post(self, path: str, *, json: dict[str, Any], headers=None) -> _Response:
            if path == "/v1/permits":
                return _Response(500, {"detail": secret})
            return super().post(path, json=json, headers=headers)

    monkeypatch.setattr(loop.httpx, "Client", FailingClient)

    with pytest.raises(loop.SmokeTestFailure):
        loop.run_constant_test(
            PROJECT_URL,
            API_KEY,
            WALLET_ID,
            KEY_ID,
            pinned_tool=TOOL,
            tool_arguments=PAYLOAD,
            retry_evidence_output=output,
        )

    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert not output.exists()


def test_retry_proof_rejects_denial_not_bound_to_signed_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "proof.json"

    class MismatchedVerifyClient(_ProofClient):
        def post(
            self,
            path: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str] | None = None,
        ) -> _Response:
            if (
                path == "/v1/receipts/verify"
                and json["receipt_id"] == DENIAL_RECEIPT["receipt_id"]
            ):
                return _Response(
                    200,
                    {"valid": True, "receipt": dict(SUCCESS_RECEIPT)},
                )
            return super().post(path, json=json, headers=headers)

    monkeypatch.setattr(loop.httpx, "Client", MismatchedVerifyClient)

    with pytest.raises(loop.SmokeTestFailure, match="signed denial receipt"):
        loop.run_constant_test(
            PROJECT_URL,
            API_KEY,
            WALLET_ID,
            KEY_ID,
            pinned_tool=TOOL,
            tool_arguments=PAYLOAD,
            retry_evidence_output=output,
        )

    assert not output.exists()


def test_retry_proof_rejects_success_not_bound_to_signed_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "proof.json"

    class MismatchedSuccessVerifyClient(_ProofClient):
        def post(
            self,
            path: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str] | None = None,
        ) -> _Response:
            if (
                path == "/v1/receipts/verify"
                and json["receipt_id"] == SUCCESS_RECEIPT["receipt_id"]
            ):
                return _Response(
                    200,
                    {"valid": True, "receipt": dict(DENIAL_RECEIPT)},
                )
            return super().post(path, json=json, headers=headers)

    monkeypatch.setattr(loop.httpx, "Client", MismatchedSuccessVerifyClient)

    with pytest.raises(loop.SmokeTestFailure, match="signed receipt"):
        loop.run_constant_test(
            PROJECT_URL,
            API_KEY,
            WALLET_ID,
            KEY_ID,
            pinned_tool=TOOL,
            tool_arguments=PAYLOAD,
            retry_evidence_output=output,
        )

    assert not output.exists()
