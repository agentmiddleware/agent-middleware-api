"""QA pass for app/trust/: adapters, receipt batching, evidence helpers.

Covers untested behavior in the trust facade with fast, deterministic tests
(no network, no sleeps, no database). ``app/trust/evidence.py`` is owned by
in-flight work, so these tests only exercise its pure helpers; they change
no product code.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.trust import (
    ReceiptEvidenceCheck,
    ReceiptEvidenceResponse,
    ReceiptResponse,
)
from app.trust.adapters import (
    GovernedRequestInvalid,
    McpGovernedAdapter,
    validate_tools_call_params,
)
from app.trust.evidence import (
    _dispatch_audit_linkage_failures,
    _dispatch_evidence,
    _dispatch_linkage_failures,
    _metadata_from_json,
    build_evidence_bundle,
)
from app.trust.receipts import BatchingReceiptEmitter, ReceiptError


def _params(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"name": "echo", "arguments": {"text": "hi"}}
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# validate_tools_call_params
# --------------------------------------------------------------------------- #


def test_rejects_non_dict_raw() -> None:
    for raw in (["name"], "tools/call", None, 42):
        with pytest.raises(GovernedRequestInvalid):
            validate_tools_call_params(raw)


def test_rejects_non_dict_params_in_envelope() -> None:
    with pytest.raises(
        GovernedRequestInvalid, match="Invalid params: params must be an object"
    ):
        validate_tools_call_params(
            {"jsonrpc": "2.0", "method": "tools/call", "params": ["echo"]}
        )


def test_missing_and_blank_names_are_refused() -> None:
    with pytest.raises(GovernedRequestInvalid, match="Missing tool name"):
        validate_tools_call_params({})
    with pytest.raises(GovernedRequestInvalid, match="Missing tool name"):
        validate_tools_call_params({"name": ""})
    for bad in ("   ", 123, 0, False, ["echo"]):
        with pytest.raises(GovernedRequestInvalid, match="Invalid params: name"):
            validate_tools_call_params({"name": bad})


def test_arguments_null_means_absent_other_shapes_refused() -> None:
    assert validate_tools_call_params(_params(arguments=None))["arguments"] == {}
    assert validate_tools_call_params({"name": "echo"})["arguments"] == {}
    for bad in (["x"], "x", 42):
        with pytest.raises(GovernedRequestInvalid, match="Invalid params: arguments"):
            validate_tools_call_params(_params(arguments=bad))


def test_mcp_context_null_means_absent_other_shapes_refused() -> None:
    assert validate_tools_call_params(_params(mcpContext=None))["mcpContext"] == {}
    for bad in (["wallet"], "wallet", 42):
        with pytest.raises(GovernedRequestInvalid, match="Invalid params: mcpContext"):
            validate_tools_call_params(_params(mcpContext=bad))


def test_non_string_context_fields_are_refused() -> None:
    for field in ("wallet_id", "permit_id", "quote_id", "request_path"):
        with pytest.raises(
            GovernedRequestInvalid, match=f"Invalid params: mcpContext.{field}"
        ):
            validate_tools_call_params(_params(mcpContext={field: 123}))


def test_idempotency_key_passthrough_and_refusals() -> None:
    assert (
        validate_tools_call_params(_params(mcpContext={"idempotency_key": "k-1"}))[
            "mcpContext"
        ]["idempotency_key"]
        == "k-1"
    )
    for bad in (123, "", "   ", "k" * 129, "bad\x01key"):
        with pytest.raises(ValueError):
            validate_tools_call_params(_params(mcpContext={"idempotency_key": bad}))


def test_envelope_with_stray_top_level_name_still_unwraps() -> None:
    envelope = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "name": "not-the-tool",
        "params": {"name": "echo", "arguments": {}},
    }
    assert validate_tools_call_params(envelope)["name"] == "echo"


def test_invalid_is_a_value_error_for_router_mapping() -> None:
    assert issubclass(GovernedRequestInvalid, ValueError)


# --------------------------------------------------------------------------- #
# McpGovernedAdapter.normalize_request / normalize_response (no database)
# --------------------------------------------------------------------------- #

_AUTH = SimpleNamespace(wallet_id="wallet-a", source="test")
_MONEY = SimpleNamespace()


async def _normalize(raw: Any, **context: Any):
    adapter = McpGovernedAdapter()
    return await adapter.normalize_request(raw, auth=_AUTH, money=_MONEY, **context)


@pytest.mark.anyio
async def test_normalize_request_defaults() -> None:
    request = await _normalize(_params())
    assert request.protocol == "mcp"
    assert request.tool_name == "echo"
    assert request.arguments == {"text": "hi"}
    assert request.transport == "adapter"
    assert request.endpoint == "/mcp/messages"
    assert request.idempotency_key is None
    assert request.permit_id is None
    assert request.auth is _AUTH
    assert request.money is _MONEY


@pytest.mark.anyio
async def test_transport_idempotency_key_wins_over_body_key() -> None:
    raw = _params(mcpContext={"idempotency_key": "body-key"})
    assert (await _normalize(raw, idempotency_key="header-key")).idempotency_key == (
        "header-key"
    )
    assert (await _normalize(raw)).idempotency_key == "body-key"


@pytest.mark.anyio
async def test_normalize_request_needs_auth_and_money_wiring() -> None:
    adapter = McpGovernedAdapter()
    with pytest.raises(KeyError):
        await adapter.normalize_request(_params())


@pytest.mark.anyio
async def test_normalize_response_returns_raw_result() -> None:
    adapter = McpGovernedAdapter()
    raw = {"isError": False, "receipt": {"receipt_id": "r-1"}}
    result = SimpleNamespace(protocol="mcp", raw=raw)
    assert await adapter.normalize_response(result) is raw


# --------------------------------------------------------------------------- #
# BatchingReceiptEmitter lifecycle (fake service, no database)
# --------------------------------------------------------------------------- #


class _DictService:
    """Resolves each receipt to a plain dict, recording arrival order."""

    def __init__(self) -> None:
        self.sequence: list[Any] = []

    async def create_receipt(self, **kwargs: Any) -> dict[str, Any]:
        self.sequence.append(kwargs.get("seq"))
        return {"seq": kwargs.get("seq")}


@pytest.mark.anyio
async def test_emitter_start_is_idempotent() -> None:
    service = _DictService()
    emitter = BatchingReceiptEmitter(service, flush_interval=0.0)
    await emitter.start()
    await emitter.start()
    future = await emitter.enqueue(seq=0)
    assert (await future)["seq"] == 0
    await emitter.aclose()


@pytest.mark.anyio
async def test_emitter_enqueue_auto_starts_without_start() -> None:
    service = _DictService()
    emitter = BatchingReceiptEmitter(service, flush_interval=0.0)
    future = await emitter.enqueue(seq=0)
    assert (await future)["seq"] == 0
    await emitter.aclose()


@pytest.mark.anyio
async def test_emitter_aclose_without_start_returns() -> None:
    emitter = BatchingReceiptEmitter(_DictService())
    await emitter.aclose()
    await emitter.aclose()


@pytest.mark.anyio
async def test_emitter_start_after_close_is_refused() -> None:
    emitter = BatchingReceiptEmitter(_DictService())
    await emitter.start()
    await emitter.aclose()
    with pytest.raises(RuntimeError, match="receipt_emitter_closed"):
        await emitter.start()


@pytest.mark.anyio
async def test_emitter_preserves_arrival_order() -> None:
    service = _DictService()
    emitter = BatchingReceiptEmitter(service, max_batch=4, flush_interval=0.05)
    futures = [await emitter.enqueue(seq=i) for i in range(6)]
    assert [(await future)["seq"] for future in futures] == [0, 1, 2, 3, 4, 5]
    assert service.sequence == [0, 1, 2, 3, 4, 5]
    await emitter.aclose()


@pytest.mark.anyio
async def test_emitter_cancel_mid_flight_resolves_future() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class _BlockingService:
        async def create_receipt(self, **kwargs: Any) -> dict[str, Any]:
            entered.set()
            await release.wait()
            return kwargs

    emitter = BatchingReceiptEmitter(
        _BlockingService(), max_batch=1, flush_interval=0.0
    )
    future = await emitter.enqueue(seq=0)
    await asyncio.wait_for(entered.wait(), timeout=5)
    emitter._task.cancel()  # type: ignore[union-attr]
    try:
        await emitter._task  # type: ignore[union-attr]
    except asyncio.CancelledError:
        pass
    with pytest.raises(ReceiptError, match="receipt_emitter_cancelled"):
        await future
    await emitter.aclose()


# --------------------------------------------------------------------------- #
# Evidence pure helpers (app/trust/evidence.py is in-flight: tests only)
# --------------------------------------------------------------------------- #


def _receipt(**overrides: Any) -> ReceiptResponse:
    base: dict[str, Any] = {
        "receipt_id": "r-1",
        "permit_id": "p-1",
        "wallet_id": "w-1",
        "key_id": "k-1",
        "tool": "echo",
        "request_hash": "a" * 64,
        "response_hash": "b" * 64,
        "ledger_entry_id": "le-1",
        "idempotency_record_id": "ir-1",
        "credits_authorized": Decimal("2"),
        "credits_charged": Decimal("2"),
        "outcome": "success",
        "audit_event_id": "ae-1",
        "created_at": datetime.now(timezone.utc),
        "signature": "sig",
        "signature_key_id": "key-1",
    }
    base.update(overrides)
    return ReceiptResponse(**base)


def _attempt(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "attempt_id": "a-1",
        "wallet_id": "w-1",
        "permit_id": "p-1",
        "key_id": "k-1",
        "public_tool_id": "echo",
        "upstream_tool_name": "upstream-echo",
        "upstream_origin": "https://upstream.example/tools",
        "request_hash": "a" * 64,
        "response_hash": "b" * 64,
        "ledger_entry_id": "le-1",
        "idempotency_record_id": "ir-1",
        "credits_authorized": Decimal("2"),
        "credits_charged": Decimal("2"),
        "state": "succeeded",
        "error_code": None,
        "created_at": datetime.now(timezone.utc),
        "dispatched_at": datetime.now(timezone.utc),
        "completed_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_dispatch_linkage_clean_pair_has_no_failures() -> None:
    assert _dispatch_linkage_failures(attempt=_attempt(), receipt=_receipt()) == []


@pytest.mark.parametrize(
    ("attempt_field", "receipt_field", "failure", "different"),
    [
        ("wallet_id", "wallet_id", "dispatch_wallet_mismatch", "DIFFERENT"),
        ("permit_id", "permit_id", "dispatch_permit_mismatch", "DIFFERENT"),
        ("key_id", "key_id", "dispatch_key_mismatch", "DIFFERENT"),
        ("public_tool_id", "tool", "dispatch_tool_mismatch", "DIFFERENT"),
        (
            "request_hash",
            "request_hash",
            "dispatch_request_hash_mismatch",
            "DIFFERENT",
        ),
        (
            "ledger_entry_id",
            "ledger_entry_id",
            "dispatch_ledger_entry_mismatch",
            "DIFFERENT",
        ),
        (
            "response_hash",
            "response_hash",
            "dispatch_response_hash_mismatch",
            "DIFFERENT",
        ),
        (
            "idempotency_record_id",
            "idempotency_record_id",
            "dispatch_idempotency_mismatch",
            "DIFFERENT",
        ),
        (
            "credits_authorized",
            "credits_authorized",
            "dispatch_authorized_credits_mismatch",
            Decimal("99"),
        ),
    ],
)
def test_dispatch_linkage_reports_each_mismatch(
    attempt_field: str, receipt_field: str, failure: str, different: Any
) -> None:
    attempt = _attempt(**{attempt_field: different})
    assert failure in _dispatch_linkage_failures(attempt=attempt, receipt=_receipt())
    receipt = _receipt(**{receipt_field: different})
    assert failure in _dispatch_linkage_failures(attempt=_attempt(), receipt=receipt)


def test_dispatch_linkage_rejects_non_terminal_state() -> None:
    failures = _dispatch_linkage_failures(
        attempt=_attempt(state="dispatched"), receipt=_receipt()
    )
    assert "dispatch_state_not_terminal" in failures


def test_dispatch_linkage_outcome_must_match_terminal_state() -> None:
    failures = _dispatch_linkage_failures(
        attempt=_attempt(state="succeeded"),
        receipt=_receipt(outcome="failed_refunded", credits_charged=Decimal("0")),
    )
    assert "dispatch_outcome_mismatch" in failures


def test_dispatch_linkage_failed_refund_charges_zero() -> None:
    attempt = _attempt(state="returned_error")
    ok_receipt = _receipt(outcome="failed_refunded", credits_charged=Decimal("0"))
    assert "dispatch_refunded_credits_mismatch" not in _dispatch_linkage_failures(
        attempt=attempt, receipt=ok_receipt
    )
    bad_receipt = _receipt(outcome="failed_refunded", credits_charged=Decimal("2"))
    assert "dispatch_refunded_credits_mismatch" in _dispatch_linkage_failures(
        attempt=attempt, receipt=bad_receipt
    )


def test_dispatch_linkage_charged_credits_must_match() -> None:
    failures = _dispatch_linkage_failures(
        attempt=_attempt(credits_charged=Decimal("2")),
        receipt=_receipt(credits_charged=Decimal("1")),
    )
    assert "dispatch_charged_credits_mismatch" in failures


def test_dispatch_evidence_strips_secrets_from_origin() -> None:
    evidence = _dispatch_evidence(
        _attempt(upstream_origin="https://user:secret@upstream.example:8443/path?q=1")
    )
    assert evidence.upstream_origin == "https://upstream.example:8443"
    assert "secret" not in evidence.upstream_origin


def test_dispatch_evidence_invalid_origin_and_error_code() -> None:
    evidence = _dispatch_evidence(
        _attempt(upstream_origin="not a url", error_code="UPSTREAM-TIMEOUT!")
    )
    assert evidence.upstream_origin == "invalid"
    assert evidence.error_code == "upstream_error"


def test_dispatch_evidence_keeps_valid_origin_and_error_code() -> None:
    evidence = _dispatch_evidence(
        _attempt(
            upstream_origin="http://internal:8080/x",
            error_code="upstream_timeout",
        )
    )
    assert evidence.upstream_origin == "http://internal:8080"
    assert evidence.error_code == "upstream_timeout"


def test_dispatch_audit_linkage_matches_signed_metadata() -> None:
    attempt = _attempt()
    metadata = {
        "dispatch_attempt_id": attempt.attempt_id,
        "dispatch_state": attempt.state,
        "upstream_tool_name": attempt.upstream_tool_name,
        "upstream_origin": attempt.upstream_origin,
        "dispatch_response_hash": attempt.response_hash,
        "permit_id": attempt.permit_id,
        "request_hash": attempt.request_hash,
        "ledger_entry_id": attempt.ledger_entry_id,
    }
    assert _dispatch_audit_linkage_failures(attempt=attempt, metadata=metadata) == []
    failures = _dispatch_audit_linkage_failures(attempt=attempt, metadata={})
    assert "audit_dispatch_attempt_mismatch" in failures
    assert "audit_dispatch_state_mismatch" in failures
    assert "audit_dispatch_response_hash_mismatch" in failures


def test_metadata_from_json_shapes() -> None:
    assert _metadata_from_json(None) == {}
    assert _metadata_from_json("") == {}
    assert _metadata_from_json("{not json") == {}
    assert _metadata_from_json("[1, 2]") == {}
    assert _metadata_from_json('{"a": 1}') == {"a": 1}


def _evidence_response(*checks: ReceiptEvidenceCheck) -> ReceiptEvidenceResponse:
    return ReceiptEvidenceResponse(
        receipt_id="r-1",
        valid=all(check.status != "failed" for check in checks),
        checks=list(checks),
        receipt=_receipt(),
    )


def _check(name: str, status: str, reason: str | None = None) -> ReceiptEvidenceCheck:
    return ReceiptEvidenceCheck(name=name, status=status, reason=reason)  # type: ignore[arg-type]


def test_build_evidence_bundle_maps_check_states() -> None:
    bundle = build_evidence_bundle(
        _evidence_response(
            _check("receipt_signature", "passed"),
            _check("permit_signature", "failed", "permit_signature_invalid"),
            _check("audit_chain", "skipped", "no_events"),
        )
    )
    assert bundle.receipt_id == "r-1"
    assert bundle.valid is False
    assert bundle.verification["receipt_signature"] == "ok"
    assert bundle.verification["permit_signature"] == "permit_signature_invalid"
    assert bundle.verification["audit_chain"] == "skipped"
    assert bundle.verification["request_hash"] == "skipped"
    assert bundle.verification["dispatch_linkage"] == "skipped"


def test_build_evidence_bundle_failed_check_without_reason() -> None:
    bundle = build_evidence_bundle(
        _evidence_response(_check("receipt_signature", "failed"))
    )
    assert bundle.verification["receipt_signature"] == "failed"
    assert bundle.valid is False
