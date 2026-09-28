"""Offline tests for the opt-in constant-loop retry evidence mode."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

import pytest

from scripts import constant_test_loop as loop


PROJECT_URL = "https://api.example.test"
TOOL = "partner.echo"
PAYLOAD = {"message": "approved payload must not be persisted"}
API_KEY = "fake-api-key-secret-canary"  # pragma: allowlist secret
WALLET_ID = "wallet-secret-canary"
KEY_ID = "key-secret-canary"
PROVIDER_RESPONSE = "provider-only-response-canary"

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
        self.posts.append((path, deepcopy(json), deepcopy(headers)))
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
                            "provider_response": PROVIDER_RESPONSE,
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
        if path in {
            f"/v1/billing/ledger/{WALLET_ID}",
            f"/v1/billing/ledger/{WALLET_ID}?limit=200",
        }:
            entries = []
            if self.message_calls > 0:
                entries.append(
                    {
                        "entry_id": "ledger-success",
                        "action": "debit",
                        "amount": "-2",
                        "description": f"governed call to {TOOL}",
                    }
                )
            return _Response(
                200,
                {"entries": entries},
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


@pytest.mark.parametrize(
    ("option", "replacement"),
    [
        ("--confirm-retry-target", "https://wrong.example.test"),
        ("--confirm-retry-tool", "partner.wrong"),
        ("--confirm-retry-payload-sha256", "0" * 64),
    ],
)
def test_retry_proof_cli_refuses_mismatched_confirmations_before_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    option: str,
    replacement: str,
) -> None:
    called = False
    digest = loop.retry_proof_payload_sha256(PAYLOAD)
    argv = [
        "--api-url",
        PROJECT_URL,
        "--tool",
        TOOL,
        "--tool-args",
        json.dumps(PAYLOAD),
        "--retry-evidence-output",
        str(tmp_path / "proof.json"),
        "--confirm-retry-target",
        PROJECT_URL,
        "--confirm-retry-tool",
        TOOL,
        "--confirm-retry-payload-sha256",
        digest,
    ]
    argv[argv.index(option) + 1] = replacement

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(loop, "run_constant_test", fail_if_called)

    assert loop.main(argv) == 2
    assert called is False
    assert "confirmation does not match" in capsys.readouterr().err


@pytest.mark.parametrize(
    "omitted_option",
    [
        "--confirm-retry-target",
        "--confirm-retry-tool",
        "--confirm-retry-payload-sha256",
    ],
)
def test_retry_proof_cli_refuses_each_omitted_confirmation_before_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    omitted_option: str,
) -> None:
    called = False
    argv = [
        "--api-url",
        PROJECT_URL,
        "--tool",
        TOOL,
        "--tool-args",
        json.dumps(PAYLOAD),
        "--retry-evidence-output",
        str(tmp_path / "proof.json"),
        "--confirm-retry-target",
        PROJECT_URL,
        "--confirm-retry-tool",
        TOOL,
        "--confirm-retry-payload-sha256",
        loop.retry_proof_payload_sha256(PAYLOAD),
    ]
    option_index = argv.index(omitted_option)
    del argv[option_index : option_index + 2]

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(loop, "run_constant_test", fail_if_called)

    assert loop.main(argv) == 2
    assert called is False
    assert "confirmation does not match" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--confirm-retry-target", PROJECT_URL),
        ("--confirm-retry-tool", TOOL),
        ("--confirm-retry-payload-sha256", "0" * 64),
    ],
)
def test_retry_proof_cli_refuses_confirmation_flags_without_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flag: str,
    value: str,
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
            flag,
            value,
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
    monkeypatch.delenv("CI_SMOKE_AGENT_KEY", raising=False)
    monkeypatch.setenv("CI_SMOKE_WALLET_ID", WALLET_ID)
    monkeypatch.setenv("CI_SMOKE_KEY_ID", KEY_ID)

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


def test_retry_proof_runner_refuses_self_provision_before_client_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_constructed = False

    def fail_if_constructed(*_args: object, **_kwargs: object) -> None:
        nonlocal client_constructed
        client_constructed = True
        raise AssertionError("retry proof attempted client construction")

    monkeypatch.setattr(loop.httpx, "Client", fail_if_constructed)

    with pytest.raises(loop.ConfigurationError, match="self-provisioning is disabled"):
        loop.run_constant_test(
            PROJECT_URL,
            "",
            WALLET_ID,
            KEY_ID,
            pinned_tool=TOOL,
            tool_arguments=PAYLOAD,
            retry_evidence_output=tmp_path / "proof.json",
        )

    assert client_constructed is False


@pytest.mark.parametrize("missing_name", ["CI_SMOKE_WALLET_ID", "CI_SMOKE_KEY_ID"])
def test_retry_proof_allows_optional_lookup_ids_to_be_missing_independently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_name: str,
) -> None:
    output = tmp_path / "proof.json"
    seen: dict[str, object] = {}
    monkeypatch.setenv("CI_SMOKE_AGENT_KEY", API_KEY)
    monkeypatch.setenv("CI_SMOKE_WALLET_ID", WALLET_ID)
    monkeypatch.setenv("CI_SMOKE_KEY_ID", KEY_ID)
    monkeypatch.delenv(missing_name)

    def capture_run(*args: object, **kwargs: object) -> None:
        seen["args"] = args
        seen.update(kwargs)

    monkeypatch.setattr(loop, "run_constant_test", capture_run)

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
            loop.retry_proof_payload_sha256(PAYLOAD),
        ]
    )

    assert exit_code == 0
    assert seen["args"] == (PROJECT_URL, API_KEY, "", "")


@pytest.mark.parametrize("flag", ["--api-key", "--wallet-id", "--key-id"])
@pytest.mark.parametrize("argument_style", ["separate", "equals"])
def test_retry_proof_cli_rejects_credential_flags_without_echoing_values(
    flag: str,
    argument_style: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canary = "credential-value-canary"
    credential_args = (
        [flag, canary] if argument_style == "separate" else [f"{flag}={canary}"]
    )

    try:
        exit_code = loop.main(["--api-url", PROJECT_URL, *credential_args])
    except SystemExit as exc:
        exit_code = exc.code

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "credential options are not accepted" in captured.err
    assert canary not in captured.out + captured.err


def test_retry_proof_cli_prescans_process_argv_without_echoing_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canary = "process-argv-credential-canary"
    monkeypatch.setattr(sys, "argv", ["constant_test_loop.py", f"--api-key={canary}"])

    exit_code = loop.main()

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "credential options are not accepted" in captured.err
    assert canary not in captured.out + captured.err


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

    def capture_run(*args: object, **kwargs: object) -> None:
        seen["args"] = args
        seen.update(kwargs)

    monkeypatch.setattr(loop, "run_constant_test", capture_run)

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
    assert seen["args"] == (PROJECT_URL, API_KEY, WALLET_ID, KEY_ID)
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
    assert set(evidence) == {
        "schema_version",
        "generated_at",
        "status",
        "target",
        "permit",
        "success",
        "same_key_replay",
        "fresh_key_denial",
        "limitations",
    }
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
        PROVIDER_RESPONSE,
        calls[0]["params"]["mcpContext"]["idempotency_key"],
        calls[2]["params"]["mcpContext"]["idempotency_key"],
    ):
        assert forbidden not in serialized


def test_retry_proof_rejects_replay_result_marked_as_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "proof.json"

    class ReplayErrorClient(_ProofClient):
        def post(
            self,
            path: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str] | None = None,
        ) -> _Response:
            response = super().post(path, json=json, headers=headers)
            if path == "/mcp/messages" and self.message_calls == 2:
                response._data["result"]["isError"] = True
            return response

    monkeypatch.setattr(loop.httpx, "Client", ReplayErrorClient)

    with pytest.raises(loop.SmokeTestFailure, match="replay.*failed"):
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


def test_retry_proof_refuses_a_saturated_pre_invocation_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "proof.json"

    class SaturatedBaselineClient(_ProofClient):
        def get(self, path: str) -> _Response:
            if (
                path.startswith(f"/v1/billing/ledger/{WALLET_ID}")
                and self.message_calls == 0
            ):
                self.gets.append(path)
                return _Response(
                    200,
                    {
                        "entries": [
                            {
                                "entry_id": f"ledger-existing-{index}",
                                "action": "debit",
                                "amount": "-1",
                                "description": "existing debit",
                            }
                            for index in range(200)
                        ]
                    },
                )
            return super().get(path)

    monkeypatch.setattr(loop.httpx, "Client", SaturatedBaselineClient)

    with pytest.raises(loop.SmokeTestFailure, match="baseline.*saturated"):
        loop.run_constant_test(
            PROJECT_URL,
            API_KEY,
            WALLET_ID,
            KEY_ID,
            pinned_tool=TOOL,
            tool_arguments=PAYLOAD,
            retry_evidence_output=output,
        )

    client = SaturatedBaselineClient.instances[-1]
    assert client.message_calls == 0
    assert [path for path in client.gets if "/billing/ledger/" in path] == [
        f"/v1/billing/ledger/{WALLET_ID}?limit=200"
    ]
    assert not output.exists()


def test_retry_proof_rejects_duplicate_debits_from_the_first_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "proof.json"

    class DuplicateFirstDebitClient(_ProofClient):
        def get(self, path: str) -> _Response:
            if path.startswith(f"/v1/billing/ledger/{WALLET_ID}"):
                self.gets.append(path)
                entries: list[dict[str, Any]] = []
                if self.message_calls > 0:
                    entries = [
                        {
                            "entry_id": "ledger-success",
                            "action": "debit",
                            "amount": "-2",
                            "description": f"governed call to {TOOL}",
                        },
                        {
                            "entry_id": "ledger-duplicate-debit",
                            "action": "debit",
                            "amount": "-2",
                            "description": f"governed call to {TOOL}",
                        },
                    ]
                return _Response(200, {"entries": entries})
            return super().get(path)

    monkeypatch.setattr(loop.httpx, "Client", DuplicateFirstDebitClient)

    with pytest.raises(loop.SmokeTestFailure, match="exactly one.*ledger entry"):
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


def test_retry_proof_rejects_prior_ledger_entry_mutation_during_first_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "proof.json"

    class MutatedBaselineClient(_ProofClient):
        def get(self, path: str) -> _Response:
            if path.startswith(f"/v1/billing/ledger/{WALLET_ID}"):
                self.gets.append(path)
                prior = {
                    "entry_id": "ledger-prior",
                    "action": "credit",
                    "amount": "10",
                    "description": "prior funding",
                }
                entries = [prior]
                if self.message_calls > 0:
                    entries = [
                        {**prior, "amount": "9"},
                        {
                            "entry_id": "ledger-success",
                            "action": "debit",
                            "amount": "-2",
                            "description": f"governed call to {TOOL}",
                        },
                    ]
                return _Response(200, {"entries": entries})
            return super().get(path)

    monkeypatch.setattr(loop.httpx, "Client", MutatedBaselineClient)

    with pytest.raises(loop.SmokeTestFailure, match="prior ledger entry changed"):
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


@pytest.mark.parametrize(
    ("changed_message_count", "expected_failure"),
    [(2, "replay"), (3, "fresh-key denial")],
)
@pytest.mark.parametrize("existing_count", [49, 199])
def test_retry_proof_rejects_a_new_debit_in_a_rotating_ledger_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_message_count: int,
    expected_failure: str,
    existing_count: int,
) -> None:
    output = tmp_path / "proof.json"

    class SaturatedLedgerClient(_ProofClient):
        def __init__(
            self, *, base_url: str, headers: dict[str, str], timeout: float
        ) -> None:
            super().__init__(base_url=base_url, headers=headers, timeout=timeout)

        def get(self, path: str) -> _Response:
            ledger_path = f"/v1/billing/ledger/{WALLET_ID}"
            if path.startswith(ledger_path):
                self.gets.append(path)
                existing = [
                    {
                        "entry_id": f"ledger-existing-{index}",
                        "action": "debit",
                        "amount": "-1",
                        "description": f"governed call to {TOOL}",
                    }
                    for index in range(existing_count)
                ]
                entries = existing
                if self.message_calls > 0:
                    entries = [
                        {
                            "entry_id": "ledger-success",
                            "action": "debit",
                            "amount": "-2",
                            "description": f"governed call to {TOOL}",
                        },
                        *existing,
                    ]
                if self.message_calls == changed_message_count:
                    entries = [
                        {
                            "entry_id": "ledger-unexpected",
                            "action": "debit",
                            "amount": "-2",
                            "description": f"governed call to {TOOL}",
                        },
                        *entries[:-1],
                    ]
                return _Response(200, {"entries": entries})
            return super().get(path)

    monkeypatch.setattr(loop.httpx, "Client", SaturatedLedgerClient)

    with pytest.raises(
        loop.SmokeTestFailure,
        match=rf"{expected_failure}.*ledger",
    ):
        loop.run_constant_test(
            PROJECT_URL,
            API_KEY,
            WALLET_ID,
            KEY_ID,
            pinned_tool=TOOL,
            tool_arguments=PAYLOAD,
            retry_evidence_output=output,
        )

    client = SaturatedLedgerClient.instances[-1]
    ledger_gets = [path for path in client.gets if "/billing/ledger/" in path]
    assert ledger_gets
    assert all(path.endswith("?limit=200") for path in ledger_gets)
    assert not output.exists()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("amount", "-999"),
        ("action", "credit"),
        ("description", f"governed call to {TOOL} mutated"),
    ],
)
@pytest.mark.parametrize(
    ("changed_message_count", "expected_failure"),
    [(2, "replay"), (3, "fresh-key denial")],
)
def test_retry_proof_rejects_same_id_ledger_entry_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: str,
    changed_message_count: int,
    expected_failure: str,
) -> None:
    output = tmp_path / "proof.json"

    class SameIdLedgerMutationClient(_ProofClient):
        def get(self, path: str) -> _Response:
            response = super().get(path)
            if (
                path.startswith(f"/v1/billing/ledger/{WALLET_ID}")
                and self.message_calls == changed_message_count
            ):
                response._data["entries"][0][field] = replacement
            return response

    monkeypatch.setattr(loop.httpx, "Client", SameIdLedgerMutationClient)

    with pytest.raises(
        loop.SmokeTestFailure,
        match=rf"{expected_failure}.*ledger",
    ):
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


@pytest.mark.parametrize(
    "entries",
    [
        [None],
        [{}],
        [{"entry_id": ""}],
        [{"entry_id": "duplicate"}, {"entry_id": "duplicate"}],
    ],
)
@pytest.mark.parametrize("malformed_read", [1, 2, 3, 4])
def test_retry_proof_fails_cleanly_on_malformed_ledger_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entries: list[object],
    malformed_read: int,
) -> None:
    output = tmp_path / "proof.json"

    class MalformedLedgerClient(_ProofClient):
        def __init__(
            self, *, base_url: str, headers: dict[str, str], timeout: float
        ) -> None:
            super().__init__(base_url=base_url, headers=headers, timeout=timeout)
            self.ledger_reads = 0

        def get(self, path: str) -> _Response:
            if path.startswith(f"/v1/billing/ledger/{WALLET_ID}"):
                self.ledger_reads += 1
                if self.ledger_reads == malformed_read:
                    self.gets.append(path)
                    return _Response(200, {"entries": entries})
            return super().get(path)

    monkeypatch.setattr(loop.httpx, "Client", MalformedLedgerClient)

    with pytest.raises(loop.SmokeTestFailure, match="wallet ledger"):
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


@pytest.mark.parametrize(
    ("changed_read", "expected_failure"),
    [(2, "replay"), (3, "fresh-key denial")],
)
def test_retry_proof_rejects_permit_spend_changes_after_the_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_read: int,
    expected_failure: str,
) -> None:
    output = tmp_path / "proof.json"

    class ChangedSpendClient(_ProofClient):
        def __init__(
            self, *, base_url: str, headers: dict[str, str], timeout: float
        ) -> None:
            super().__init__(base_url=base_url, headers=headers, timeout=timeout)
            self.permit_reads = 0

        def get(self, path: str) -> _Response:
            if path == "/v1/permits/permit-proof":
                self.permit_reads += 1
                if self.permit_reads == changed_read:
                    self.gets.append(path)
                    return _Response(200, {"spent_credits": "3"})
            return super().get(path)

    monkeypatch.setattr(loop.httpx, "Client", ChangedSpendClient)

    with pytest.raises(
        loop.SmokeTestFailure,
        match=rf"{expected_failure}.*spend",
    ):
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


@pytest.mark.parametrize(
    ("field", "replacement", "expected_failure"),
    [
        ("attempt_id", "dispatch-other", "attempt"),
        ("state", "failed", "did not succeed"),
        ("ledger_entry_id", "ledger-other", "ledger link"),
        ("dispatched_at", None, "timestamp"),
    ],
)
def test_retry_proof_rejects_invalid_dispatch_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: object,
    expected_failure: str,
) -> None:
    output = tmp_path / "proof.json"

    class InvalidDispatchClient(_ProofClient):
        def get(self, path: str) -> _Response:
            response = super().get(path)
            if path == "/v1/receipts/receipt-success/evidence":
                response._data["dispatch"][field] = replacement
            return response

    monkeypatch.setattr(loop.httpx, "Client", InvalidDispatchClient)

    with pytest.raises(loop.SmokeTestFailure, match=expected_failure):
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


def test_retry_proof_does_not_echo_failed_response_or_write_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "provider-response-secret-canary"  # pragma: allowlist secret
    output = tmp_path / "proof.json"

    class FailingClient(_ProofClient):
        def post(self, path: str, *, json: dict[str, Any], headers=None) -> _Response:
            if path == "/v1/permits":
                return _Response(500, {"detail": secret})
            return super().post(path, json=json, headers=headers)

    monkeypatch.setattr(loop.httpx, "Client", FailingClient)
    monkeypatch.setenv("CI_SMOKE_AGENT_KEY", API_KEY)
    monkeypatch.setenv("CI_SMOKE_WALLET_ID", WALLET_ID)
    monkeypatch.setenv("CI_SMOKE_KEY_ID", KEY_ID)

    with pytest.raises(loop.SmokeTestFailure) as exc_info:
        loop.run_constant_test(
            PROJECT_URL,
            API_KEY,
            WALLET_ID,
            KEY_ID,
            pinned_tool=TOOL,
            tool_arguments=PAYLOAD,
            retry_evidence_output=output,
        )

    direct_output = capsys.readouterr()
    assert secret not in str(exc_info.value)
    assert secret not in direct_output.out + direct_output.err

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
            loop.retry_proof_payload_sha256(PAYLOAD),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert secret not in captured.out + captured.err
    assert not output.exists()


@pytest.mark.parametrize(
    ("receipt_id", "field", "replacement", "expected_failure"),
    [
        ("receipt-success", "credits_charged", "999", "signed receipt"),
        ("receipt-denied", "reason_code", "other_denial", "signed denial receipt"),
    ],
)
def test_retry_proof_rejects_same_id_signed_receipt_field_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receipt_id: str,
    field: str,
    replacement: object,
    expected_failure: str,
) -> None:
    output = tmp_path / "proof.json"

    class SameIdMutationClient(_ProofClient):
        def post(
            self,
            path: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str] | None = None,
        ) -> _Response:
            if path == "/v1/receipts/verify" and json["receipt_id"] == receipt_id:
                source = (
                    SUCCESS_RECEIPT
                    if receipt_id == SUCCESS_RECEIPT["receipt_id"]
                    else DENIAL_RECEIPT
                )
                mutated_receipt = dict(source)
                mutated_receipt[field] = replacement
                assert mutated_receipt["receipt_id"] == receipt_id
                return _Response(
                    200,
                    {"valid": True, "receipt": mutated_receipt},
                )
            return super().post(path, json=json, headers=headers)

    monkeypatch.setattr(loop.httpx, "Client", SameIdMutationClient)

    with pytest.raises(loop.SmokeTestFailure, match=expected_failure):
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
