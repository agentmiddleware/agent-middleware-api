"""Prospective insight capture must never change governed execution."""

import asyncio
import base64
import importlib.util
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, select, text
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import ASGITransport, AsyncClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from app.db.database import get_session_factory

from app.core.config import Settings


def test_event_capture_is_disabled_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.OPERATION_INSIGHTS_EVENTS_ENABLED is False


def test_client_version_only_accepts_configured_exact_tokens() -> None:
    from app.services.operation_insights.events import normalize_client_version

    allowed = frozenset({"sdk-py-1.2", "sdk-ts-2.0"})

    assert normalize_client_version("sdk-py-1.2", allowed) == "sdk-py-1.2"
    assert normalize_client_version("sdk-py-1.2-extra", allowed) is None
    assert normalize_client_version("sdk-py-1.2\nsecret", allowed) is None
    assert normalize_client_version(None, allowed) is None


def test_configured_client_version_must_still_be_a_safe_token() -> None:
    from app.services.operation_insights.events import normalize_client_version

    assert (
        normalize_client_version("unsafe version", frozenset({"unsafe version"}))
        is None
    )


def test_event_reason_codes_are_fixed_allowlist() -> None:
    from app.services.operation_insights.events import (
        InsightEvent,
        allowlisted_reason_code,
    )

    assert allowlisted_reason_code("delivery_uncertain") == "delivery_uncertain"
    assert allowlisted_reason_code("raw-key-shaped-token") is None
    assert allowlisted_reason_code(None) is None
    with pytest.raises(ValueError, match="event_reason_not_allowlisted"):
        InsightEvent(
            event_id="evt-bad-reason",
            kind="terminal",
            occurred_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
            reason_code="raw-key-shaped-token",
        )


@pytest.mark.parametrize(
    "reason",
    (
        "permit_budget_exceeded",
        "permit_budget_exceeds_wallet_balance",
        "permit_constraint_unsupported_for_upstream",
        "permit_max_calls_exceeded",
        "permit_not_found",
        "idempotency_key_required_for_human_approval",
        "permit_expired",
        "permit_revoked",
        "permit_wallet_mismatch",
        "permit_key_mismatch",
        "permit_tool_not_allowed",
        "permit_scope_missing",
        "permit_signature_invalid",
        "permit_aggregate_value_cap_exceeded",
        "permit_forbidden_field",
        "permit_denied",
        "policy_denied",
        "action_permit_denied",
        "action_tool_binding_required",
        "action_quote_unsupported",
    ),
)
def test_established_permit_denial_codes_are_bounded(reason: str) -> None:
    from app.services.operation_insights.events import allowlisted_reason_code

    assert allowlisted_reason_code(reason) == reason
    assert allowlisted_reason_code("permit_forbidden_field:raw-field") is None


@pytest.mark.asyncio
async def test_duplicate_event_is_idempotent_and_conflict_marks_coverage_gap(
    clean_database: None,
) -> None:
    from app.db.models import InsightEventModel
    from app.services.operation_insights.events import InsightEvent, record_event

    event = InsightEvent(
        event_id="evt-fixed-1",
        kind="ingress",
        request_id="req-fixed-1",
        occurred_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        request_disposition="unknown",
    )
    await record_event(event)
    await record_event(event)

    async with get_session_factory()() as session:
        identical = await session.get(InsightEventModel, event.event_id)
        assert identical is not None
        assert identical.duplicate_conflict_at is None

    await record_event(replace(event, request_disposition="execution_intent"))

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert len(rows) == 1
    assert rows[0].request_disposition == "unknown"
    assert rows[0].duplicate_conflict_at is not None


@pytest.mark.asyncio
async def test_stale_ingress_redelivery_preserves_monotone_enrichment(
    clean_database: None,
) -> None:
    from app.db.models import InsightEventModel
    from app.services.operation_insights.events import (
        InsightEvent,
        RequestEventContext,
        enrich_ingress_safely,
        record_event,
    )

    ingress = InsightEvent(
        event_id="evt-ingress-fixed",
        kind="ingress",
        request_id="req-fixed",
        occurred_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        request_disposition="unknown",
    )
    await record_event(ingress)
    await enrich_ingress_safely(
        RequestEventContext(
            request_id="req-fixed",
            ingress_event_id="evt-ingress-fixed",
            request_disposition="execution_intent",
            wallet_id="wallet-verified",
        )
    )
    await record_event(ingress)

    async with get_session_factory()() as session:
        row = await session.get(InsightEventModel, ingress.event_id)

    assert row is not None
    assert row.request_disposition == "execution_intent"
    assert row.wallet_id == "wallet-verified"
    assert row.original_operation_anchor_id == ingress.event_id
    assert row.duplicate_conflict_at is None


async def _deny_request(scope, receive, send) -> None:
    await send({"type": "http.response.start", "status": 401, "headers": []})
    await send({"type": "http.response.body", "body": b""})


@pytest.mark.asyncio
async def test_preauth_capture_uses_server_ids_and_null_wallet(
    clean_database: None,
) -> None:
    from app.db.models import InsightEventModel
    from app.middleware.operation_insight_events import OperationInsightEventsMiddleware

    middleware = OperationInsightEventsMiddleware(_deny_request, enabled=True)
    async with AsyncClient(
        transport=ASGITransport(app=middleware), base_url="http://test"
    ) as client:
        response = await client.post(
            "/mcp/messages",
            headers={"x-request-id": "client-selected", "x-client-version": "unknown"},
        )

    async with get_session_factory()() as session:
        rows = (
            (
                await session.execute(
                    select(InsightEventModel).order_by(InsightEventModel.kind)
                )
            )
            .scalars()
            .all()
        )

    assert response.status_code == 401
    assert [row.kind for row in rows] == ["ingress", "terminal"]
    assert rows[0].request_id == rows[1].request_id
    assert rows[0].request_id != "client-selected"
    assert [row.wallet_id for row in rows] == [None, None]
    assert [row.client_version for row in rows] == [None, None]
    assert rows[1].http_status_code == 401
    assert rows[1].gateway_outcome == "denied"
    assert rows[1].effect_state == "unknown"


@pytest.mark.asyncio
async def test_client_version_invalid_wire_bytes_are_not_allowlisted(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.models import InsightEventModel
    from app.middleware.operation_insight_events import OperationInsightEventsMiddleware

    monkeypatch.setattr(
        get_settings(), "OPERATION_INSIGHTS_ALLOWED_CLIENT_VERSIONS", "sdk-py-1.2"
    )
    middleware = OperationInsightEventsMiddleware(_deny_request, enabled=True)
    async with AsyncClient(
        transport=ASGITransport(app=middleware), base_url="http://test"
    ) as client:
        await client.post(
            "/mcp/messages",
            headers=[(b"x-client-version", b"\xffsdk-py-1.2")],
        )

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert len(rows) == 2
    assert all(row.client_version is None for row in rows)


@pytest.mark.asyncio
async def test_build_metadata_failure_does_not_abort_business_request(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models import InsightEventModel
    from app.middleware import operation_insight_events as middleware_module
    from app.services.operation_insights import events

    def fail_metadata() -> str:
        raise OSError("synthetic metadata read failure")

    monkeypatch.setattr(events, "get_build_commit_sha", fail_metadata)
    middleware = middleware_module.OperationInsightEventsMiddleware(
        _deny_request, enabled=True
    )
    async with AsyncClient(
        transport=ASGITransport(app=middleware), base_url="http://test"
    ) as client:
        response = await client.post("/mcp/messages")

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert response.status_code == 401
    assert len(rows) == 2
    assert all(row.server_release is None for row in rows)


@pytest.mark.asyncio
async def test_mismatched_build_sources_withhold_release_attribution(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models import InsightEventModel
    from app.middleware import operation_insight_events as middleware_module
    from app.services.operation_insights import events

    monkeypatch.setattr(events, "get_build_commit_sha", lambda: "a" * 40)
    monkeypatch.setattr(events, "get_build_provenance", lambda: "mismatch")
    middleware = middleware_module.OperationInsightEventsMiddleware(
        _deny_request, enabled=True
    )
    async with AsyncClient(
        transport=ASGITransport(app=middleware), base_url="http://test"
    ) as client:
        response = await client.post("/mcp/messages")

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert response.status_code == 401
    assert len(rows) == 2
    assert all(row.server_release is None for row in rows)


@pytest.mark.asyncio
async def test_disabled_middleware_writes_no_event(clean_database: None) -> None:
    from app.db.models import InsightEventModel
    from app.middleware.operation_insight_events import OperationInsightEventsMiddleware

    middleware = OperationInsightEventsMiddleware(_deny_request, enabled=False)
    async with AsyncClient(
        transport=ASGITransport(app=middleware), base_url="http://test"
    ) as client:
        response = await client.post("/mcp/messages")

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert response.status_code == 401
    assert rows == []


@pytest.mark.asyncio
async def test_observer_sink_failure_does_not_change_business_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.middleware.operation_insight_events import OperationInsightEventsMiddleware
    from app.services.operation_insights import events

    before = events.get_delivery_metrics()["failures"]

    async def fail_write(_event) -> None:
        raise RuntimeError

    monkeypatch.setattr(events, "record_event", fail_write)
    middleware = OperationInsightEventsMiddleware(_deny_request, enabled=True)
    async with AsyncClient(
        transport=ASGITransport(app=middleware), base_url="http://test"
    ) as client:
        response = await client.post("/mcp/messages")

    assert response.status_code == 401
    assert events.get_delivery_metrics()["failures"] - before == 2


@pytest.mark.asyncio
async def test_stalled_ingress_sink_does_not_hold_business_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.middleware.operation_insight_events import OperationInsightEventsMiddleware
    from app.services.operation_insights import events

    release = asyncio.Event()
    reached = asyncio.Event()

    async def stalled_write(_event) -> None:
        reached.set()
        await release.wait()

    monkeypatch.setattr(events, "record_event", stalled_write)
    middleware = OperationInsightEventsMiddleware(_deny_request, enabled=True)
    before = events.get_delivery_metrics()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=middleware), base_url="http://test"
        ) as client:
            response = await asyncio.wait_for(client.post("/mcp/messages"), 0.5)
        assert reached.is_set()
        assert response.status_code == 401
    finally:
        release.set()
        await events.wait_for_pending_events()

    after = events.get_delivery_metrics()
    assert after["generated"] == before["generated"] + 2
    assert after["failures"] >= before["failures"] + 2
    assert after["pending"] == before["pending"]


@pytest.mark.asyncio
async def test_crash_after_attempt_keeps_request_open_without_terminal(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.models import InsightEventModel
    from app.middleware.operation_insight_events import OperationInsightEventsMiddleware
    from app.services.operation_insights.events import observe_attempt

    monkeypatch.setattr(get_settings(), "OPERATION_INSIGHTS_EVENTS_ENABLED", True)

    async def interrupted(scope, receive, send) -> None:
        await observe_attempt(
            attempt_id="loc-interrupted",
            wallet_id="wallet-verified",
            tool="partner.notes.write",
            logical_operation_id="idem-interrupted",
        )
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError

    middleware = OperationInsightEventsMiddleware(interrupted, enabled=True)
    async with AsyncClient(
        transport=ASGITransport(app=middleware), base_url="http://test"
    ) as client:
        with pytest.raises(RuntimeError):
            await client.post("/mcp/messages")

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert sorted(row.kind for row in rows) == ["attempt", "ingress"]
    assert {row.original_operation_anchor_id for row in rows} == {"idem-interrupted"}


def test_application_registers_observer_middleware() -> None:
    from app.main import app
    from app.middleware.operation_insight_events import OperationInsightEventsMiddleware

    assert any(
        middleware.cls is OperationInsightEventsMiddleware
        for middleware in app.user_middleware
    )


@pytest.mark.asyncio
async def test_verified_handler_classifies_ingress_without_new_request_id(
    clean_database: None,
) -> None:
    from app.db.models import InsightEventModel
    from app.middleware.operation_insight_events import OperationInsightEventsMiddleware
    from app.services.operation_insights.events import mark_current_request

    async def classified(scope, receive, send) -> None:
        mark_current_request(
            disposition="non_execution_read",
            wallet_id="wallet-verified",
        )
        await _deny_request(scope, receive, send)

    middleware = OperationInsightEventsMiddleware(classified, enabled=True)
    async with AsyncClient(
        transport=ASGITransport(app=middleware), base_url="http://test"
    ) as client:
        response = await client.post("/mcp/messages")

    async with get_session_factory()() as session:
        rows = (
            (
                await session.execute(
                    select(InsightEventModel).order_by(InsightEventModel.kind)
                )
            )
            .scalars()
            .all()
        )

    assert response.status_code == 401
    assert len(rows) == 2
    assert [row.request_disposition for row in rows] == [
        "non_execution_read",
        "non_execution_read",
    ]
    assert [row.wallet_id for row in rows] == ["wallet-verified", "wallet-verified"]
    assert rows[0].request_id == rows[1].request_id
    assert [row.original_operation_anchor_id for row in rows] == [None, None]


@pytest.mark.asyncio
async def test_trusted_logical_id_becomes_shared_original_anchor(
    clean_database: None,
) -> None:
    from app.db.models import InsightEventModel
    from app.middleware.operation_insight_events import OperationInsightEventsMiddleware
    from app.services.operation_insights.events import mark_current_request

    async def admitted(scope, receive, send) -> None:
        mark_current_request(
            disposition="execution_intent",
            wallet_id="wallet-verified",
            logical_operation_id="idem-verified",
        )
        await _deny_request(scope, receive, send)

    async with AsyncClient(
        transport=ASGITransport(
            app=OperationInsightEventsMiddleware(admitted, enabled=True)
        ),
        base_url="http://test",
    ) as client:
        await client.post("/mcp/messages")

    async with get_session_factory()() as session:
        rows = (
            (
                await session.execute(
                    select(InsightEventModel).order_by(InsightEventModel.kind)
                )
            )
            .scalars()
            .all()
        )

    assert [row.original_operation_anchor_id for row in rows] == [
        "idem-verified",
        "idem-verified",
    ]
    assert [row.ownership_epoch_id for row in rows] == [None, None]


@pytest.mark.asyncio
async def test_verified_denial_without_idempotency_uses_ingress_anchor(
    clean_database: None,
) -> None:
    from app.db.models import InsightEventModel
    from app.middleware.operation_insight_events import OperationInsightEventsMiddleware
    from app.services.operation_insights.events import mark_current_request

    async def denied_after_wallet_check(scope, receive, send) -> None:
        mark_current_request(
            disposition="execution_intent", wallet_id="wallet-verified"
        )
        await _deny_request(scope, receive, send)

    async with AsyncClient(
        transport=ASGITransport(
            app=OperationInsightEventsMiddleware(
                denied_after_wallet_check, enabled=True
            )
        ),
        base_url="http://test",
    ) as client:
        await client.post("/mcp/messages")

    async with get_session_factory()() as session:
        rows = (
            (
                await session.execute(
                    select(InsightEventModel).order_by(InsightEventModel.kind)
                )
            )
            .scalars()
            .all()
        )

    assert rows[0].original_operation_anchor_id == rows[0].event_id
    assert rows[1].original_operation_anchor_id == rows[0].event_id


@pytest.mark.asyncio
async def test_attempt_observation_is_default_off(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models import InsightEventModel
    from app.services.operation_insights.events import observe_attempt
    from app.services.operation_insights import events

    monkeypatch.setattr(
        events.get_settings(), "OPERATION_INSIGHTS_EVENTS_ENABLED", False
    )
    await observe_attempt(
        attempt_id="dsp-1",
        wallet_id="wallet-1",
        tool="partner.notes.write",
        logical_operation_id="idem-1",
    )

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert rows == []


@pytest.mark.asyncio
async def test_claim_boundary_observation_is_durable_and_idempotent(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models import InsightEventModel
    from app.services.operation_insights import events

    monkeypatch.setattr(
        events.get_settings(), "OPERATION_INSIGHTS_EVENTS_ENABLED", True
    )
    for _ in range(2):
        await events.observe_attempt(
            attempt_id="dsp-1",
            wallet_id="wallet-1",
            tool="partner.notes.write",
            logical_operation_id="idem-1",
        )

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert len(rows) == 1
    assert rows[0].kind == "attempt"
    assert rows[0].attempt_id == "dsp-1"
    assert rows[0].logical_operation_id == "idem-1"
    assert rows[0].wallet_id == "wallet-1"
    assert rows[0].original_operation_anchor_id == "idem-1"


@pytest.mark.asyncio
async def test_attempt_without_request_context_withholds_mismatched_release(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models import InsightEventModel
    from app.services.operation_insights import events

    monkeypatch.setattr(
        events.get_settings(), "OPERATION_INSIGHTS_EVENTS_ENABLED", True
    )
    monkeypatch.setattr(events, "get_build_commit_sha", lambda: "a" * 40)
    monkeypatch.setattr(events, "get_build_provenance", lambda: "mismatch")

    await events.observe_attempt(
        attempt_id="dsp-mismatched-release",
        wallet_id="wallet-verified",
        tool="partner.notes.write",
        logical_operation_id="idem-verified",
    )

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert len(rows) == 1
    assert rows[0].kind == "attempt"
    assert rows[0].server_release is None


@pytest.mark.asyncio
async def test_dispatch_claim_observes_only_after_claim_and_ignores_sink_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import mcp_dispatch_attempts

    service = mcp_dispatch_attempts.McpDispatchAttemptService()
    attempt = SimpleNamespace(
        attempt_id="dsp-verified",
        wallet_id="wallet-verified",
        public_tool_id="partner.notes.write",
        idempotency_record_id="idem-verified",
    )
    seen: list[str] = []

    async def committed_claim(_self, attempt_id: str):
        seen.append("committed")
        assert attempt_id == "dsp-verified"
        return attempt

    def failing_observer(**kwargs) -> None:
        seen.append("observer")
        assert kwargs["attempt_id"] == "dsp-verified"
        raise RuntimeError

    monkeypatch.setattr(
        mcp_dispatch_attempts.McpDispatchAttemptService,
        "_claim_dispatch",
        committed_claim,
        raising=False,
    )
    monkeypatch.setattr(
        mcp_dispatch_attempts, "schedule_attempt", failing_observer, raising=False
    )

    returned = await service.claim_dispatch("dsp-verified")

    assert returned is attempt
    assert seen == ["committed", "observer"]


@pytest.mark.asyncio
async def test_failed_dispatch_claim_emits_no_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import mcp_dispatch_attempts

    service = mcp_dispatch_attempts.McpDispatchAttemptService()
    seen: list[str] = []

    async def denied_claim(_self, _attempt_id: str):
        raise mcp_dispatch_attempts.DispatchClaimUnavailableError(
            "dispatch_claim_unavailable"
        )

    def observe(**_kwargs) -> None:
        seen.append("observer")

    monkeypatch.setattr(
        mcp_dispatch_attempts.McpDispatchAttemptService,
        "_claim_dispatch",
        denied_claim,
        raising=False,
    )
    monkeypatch.setattr(
        mcp_dispatch_attempts, "schedule_attempt", observe, raising=False
    )

    with pytest.raises(
        mcp_dispatch_attempts.DispatchClaimUnavailableError,
        match="dispatch_claim_unavailable",
    ):
        await service.claim_dispatch("dsp-verified")

    assert seen == []


@pytest.mark.asyncio
async def test_stalled_event_sink_cannot_hold_claimed_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import mcp_dispatch_attempts
    from app.services.operation_insights import events

    monkeypatch.setattr(
        events.get_settings(), "OPERATION_INSIGHTS_EVENTS_ENABLED", True
    )
    service = mcp_dispatch_attempts.McpDispatchAttemptService()
    attempt = SimpleNamespace(
        attempt_id="dsp-stalled",
        wallet_id="wallet-verified",
        public_tool_id="partner.notes.write",
        idempotency_record_id="idem-stalled",
    )
    release = asyncio.Event()

    async def committed_claim(_self, _attempt_id: str):
        return attempt

    async def stalled_sink(_event) -> None:
        await release.wait()

    monkeypatch.setattr(
        mcp_dispatch_attempts.McpDispatchAttemptService,
        "_claim_dispatch",
        committed_claim,
    )
    monkeypatch.setattr(events, "record_event", stalled_sink)
    before = events.get_delivery_metrics()

    try:
        returned = await asyncio.wait_for(service.claim_dispatch("dsp-stalled"), 0.2)
        await asyncio.sleep(0)
        during = events.get_delivery_metrics()
        assert returned is attempt
        assert during["generated"] == before["generated"] + 1
        assert during["pending"] == before["pending"] + 1
    finally:
        release.set()
        await events.wait_for_pending_events()

    assert events.get_delivery_metrics()["pending"] == before["pending"]


@pytest.mark.asyncio
async def test_tools_list_is_read_only_and_jsonrpc_id_is_not_server_identity(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.models import InsightEventModel
    from app.main import app

    settings = get_settings()
    monkeypatch.setattr(settings, "OPERATION_INSIGHTS_EVENTS_ENABLED", True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/mcp/messages",
            headers={"X-API-Key": settings.VALID_API_KEYS.split(",")[0]},
            json={"jsonrpc": "2.0", "id": "client-777", "method": "tools/list"},
        )

    async with get_session_factory()() as session:
        rows = (
            (
                await session.execute(
                    select(InsightEventModel).order_by(InsightEventModel.kind)
                )
            )
            .scalars()
            .all()
        )

    assert response.status_code == 200
    assert [row.kind for row in rows] == ["ingress", "terminal"]
    assert [row.request_disposition for row in rows] == [
        "non_execution_read",
        "non_execution_read",
    ]
    assert rows[0].request_id != "client-777"


@pytest.mark.asyncio
async def test_verified_wallet_denial_uses_server_ingress_anchor(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.models import InsightEventModel
    from app.main import app
    from tests.test_trust_helpers import provision_agent_wallet

    monkeypatch.setattr(get_settings(), "OPERATION_INSIGHTS_EVENTS_ENABLED", True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        provisioned = await provision_agent_wallet(client)
        response = await client.post(
            "/mcp/messages",
            headers=provisioned["agent_headers"],
            json={
                "jsonrpc": "2.0",
                "id": "client-call-1",
                "method": "tools/call",
                "params": {
                    "name": "missing-tool",
                    "arguments": {},
                    "mcpContext": {"wallet_id": provisioned["agent_wallet_id"]},
                },
            },
        )

    async with get_session_factory()() as session:
        rows = (
            (
                await session.execute(
                    select(InsightEventModel).order_by(InsightEventModel.kind)
                )
            )
            .scalars()
            .all()
        )

    assert response.status_code == 200
    assert [row.kind for row in rows] == ["ingress", "terminal"]
    assert [row.wallet_id for row in rows] == [
        provisioned["agent_wallet_id"],
        provisioned["agent_wallet_id"],
    ]
    assert rows[0].original_operation_anchor_id == rows[0].event_id
    assert rows[1].original_operation_anchor_id == rows[0].event_id
    assert rows[1].gateway_outcome == "denied"
    assert rows[1].reason_code == "request_validation_denied"


@pytest.mark.asyncio
async def test_standard_mcp_read_and_early_wallet_denial_are_classified(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.models import InsightEventModel
    from app.main import app
    from tests.test_trust_helpers import provision_agent_wallet

    settings = get_settings()
    monkeypatch.setattr(settings, "OPERATION_INSIGHTS_EVENTS_ENABLED", True)
    monkeypatch.setattr(settings, "ENABLE_STANDARD_MCP_ENDPOINT", True)
    mcp_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        provisioned = await provision_agent_wallet(client)
        listed = await client.post(
            "/mcp",
            headers={"X-API-Key": settings.VALID_API_KEYS.split(",")[0], **mcp_headers},
            json={"jsonrpc": "2.0", "id": "list-client-id", "method": "tools/list"},
        )
        denied = await client.post(
            "/mcp",
            headers={**provisioned["agent_headers"], **mcp_headers},
            json={
                "jsonrpc": "2.0",
                "id": "call-client-id",
                "method": "tools/call",
                "params": {"name": "missing-tool", "arguments": {}},
            },
        )

    async with get_session_factory()() as session:
        rows = (
            (
                await session.execute(
                    select(InsightEventModel).order_by(InsightEventModel.occurred_at)
                )
            )
            .scalars()
            .all()
        )

    assert listed.status_code == 200
    assert denied.status_code == 200
    assert len(rows) == 4
    by_request = {row.request_id for row in rows}
    assert len(by_request) == 2
    read_rows = [row for row in rows if row.request_disposition == "non_execution_read"]
    call_rows = [row for row in rows if row.request_disposition == "execution_intent"]
    assert len(read_rows) == len(call_rows) == 2
    assert all(row.wallet_id is None for row in read_rows)
    assert all(row.wallet_id == provisioned["agent_wallet_id"] for row in call_rows)
    ingress = next(row for row in call_rows if row.kind == "ingress")
    assert all(
        row.original_operation_anchor_id == ingress.event_id for row in call_rows
    )
    terminal = next(row for row in call_rows if row.kind == "terminal")
    assert terminal.gateway_outcome == "denied"
    assert terminal.reason_code == "tool_not_found"


@pytest.mark.asyncio
async def test_standard_list_validation_error_is_not_recorded_as_success(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.models import InsightEventModel
    from app.main import app
    from app.routers import mcp_standard as standard_router

    settings = get_settings()
    monkeypatch.setattr(settings, "OPERATION_INSIGHTS_EVENTS_ENABLED", True)
    monkeypatch.setattr(settings, "ENABLE_STANDARD_MCP_ENDPOINT", True)

    async def invalid_manifest(_params):
        return {"tools": [{}]}

    monkeypatch.setattr(standard_router, "_handle_tools_list", invalid_manifest)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/mcp",
            headers={
                "X-API-Key": settings.VALID_API_KEYS.split(",")[0],
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "id": "list-client-id", "method": "tools/list"},
        )

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert response.status_code == 200
    assert "error" in response.json()
    assert len(rows) == 2
    terminal = next(row for row in rows if row.kind == "terminal")
    assert terminal.request_disposition == "non_execution_read"
    assert terminal.gateway_outcome == "failed"
    assert terminal.reason_code == "internal_error"


@pytest.mark.asyncio
async def test_standard_call_validation_emits_no_success_observation(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.models import InsightEventModel
    from app.main import app
    from app.routers import mcp_standard as standard_router
    from tests.test_trust_helpers import provision_agent_wallet

    settings = get_settings()
    monkeypatch.setattr(settings, "OPERATION_INSIGHTS_EVENTS_ENABLED", True)
    monkeypatch.setattr(settings, "ENABLE_STANDARD_MCP_ENDPOINT", True)

    async def invalid_result(**_kwargs):
        return {"content": "invalid", "isError": False}

    observed_outcomes: list[str] = []
    real_mark = standard_router.mark_current_request

    def capture_outcome(**kwargs):
        outcome = kwargs.get("gateway_outcome")
        if outcome is not None:
            observed_outcomes.append(outcome)
        real_mark(**kwargs)

    monkeypatch.setattr(standard_router, "_governed_tools_call", invalid_result)
    monkeypatch.setattr(standard_router, "mark_current_request", capture_outcome)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        provisioned = await provision_agent_wallet(client)
        response = await client.post(
            "/mcp",
            headers={
                **provisioned["agent_headers"],
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": "invalid-result-call",
                "method": "tools/call",
                "params": {"name": "synthetic.tool", "arguments": {}},
            },
        )

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32603
    assert observed_outcomes == ["failed"]
    assert len(rows) == 2
    terminal = next(row for row in rows if row.kind == "terminal")
    assert terminal.gateway_outcome == "failed"
    assert terminal.reason_code == "internal_error"


@pytest.mark.asyncio
async def test_standard_mcp_invalid_key_is_a_terminal_denial(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.models import InsightEventModel
    from app.main import app
    from tests.test_trust_helpers import provision_agent_wallet

    settings = get_settings()
    monkeypatch.setattr(settings, "OPERATION_INSIGHTS_EVENTS_ENABLED", True)
    monkeypatch.setattr(settings, "ENABLE_STANDARD_MCP_ENDPOINT", True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        provisioned = await provision_agent_wallet(client)
        response = await client.post(
            "/mcp",
            headers={
                **provisioned["agent_headers"],
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "Idempotency-Key": " ",
            },
            json={
                "jsonrpc": "2.0",
                "id": "client-selected",
                "method": "tools/call",
                "params": {"name": "missing-tool", "arguments": {}},
            },
        )

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32602
    assert len(rows) == 2
    assert all(row.request_disposition == "execution_intent" for row in rows)
    assert all(row.wallet_id == provisioned["agent_wallet_id"] for row in rows)
    terminal = next(row for row in rows if row.kind == "terminal")
    assert terminal.gateway_outcome == "denied"
    assert terminal.reason_code == "request_validation_denied"


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ("jsonrpc", "rest"))
@pytest.mark.parametrize(
    ("reason", "receipt_reason", "expected_reason"),
    (
        ("permit_budget_exceeded", None, "permit_budget_exceeded"),
        ("permit_max_calls_exceeded", None, "permit_max_calls_exceeded"),
        ("permit_not_found", None, "permit_not_found"),
        ("permit_forbidden_field:synthetic-field", None, "tool_permission_denied"),
        ("permit_not_found", "unknown_receipt_reason", "tool_permission_denied"),
        (
            "permit_max_calls_exceeded",
            "permit_budget_exceeded",
            "permit_budget_exceeded",
        ),
    ),
)
async def test_permit_denial_uses_only_authoritative_fixed_reason(
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
    transport: str,
    reason: str,
    receipt_reason: str | None,
    expected_reason: str,
) -> None:
    from app.core.config import get_settings
    from app.db.models import InsightEventModel
    from app.main import app
    from app.routers import mcp as mcp_router
    from app.routers.mcp import ToolPermissionDenied
    from app.services.operation_insights.events import mark_current_request
    from tests.test_trust_helpers import provision_agent_wallet

    monkeypatch.setattr(get_settings(), "OPERATION_INSIGHTS_EVENTS_ENABLED", True)

    async def normalize_request(*_args, **_kwargs):
        return object()

    async def denied(_request):
        mark_current_request(wallet_id=wallet_id)
        raise ToolPermissionDenied(
            reason,
            receipt=(
                {"reason_code": receipt_reason} if receipt_reason is not None else None
            ),
        )

    monkeypatch.setattr(mcp_router._mcp_adapter, "normalize_request", normalize_request)
    monkeypatch.setattr(mcp_router._mcp_adapter, "invoke", denied)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        provisioned = await provision_agent_wallet(client)
        wallet_id = provisioned["agent_wallet_id"]
        if transport == "jsonrpc":
            response = await client.post(
                "/mcp/messages",
                headers=provisioned["agent_headers"],
                json={
                    "jsonrpc": "2.0",
                    "id": "denied-call",
                    "method": "tools/call",
                    "params": {
                        "name": "synthetic.tool",
                        "arguments": {},
                        "mcpContext": {"wallet_id": wallet_id},
                    },
                },
            )
        else:
            response = await client.post(
                "/mcp/tools/synthetic.tool/invoke",
                headers=provisioned["agent_headers"],
                json={
                    "name": "synthetic.tool",
                    "arguments": {},
                    "mcp_context": {"wallet_id": wallet_id},
                },
            )

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert response.status_code == (200 if transport == "jsonrpc" else 403)
    assert len(rows) == 2
    terminal = next(row for row in rows if row.kind == "terminal")
    assert terminal.gateway_outcome == "denied"
    assert terminal.reason_code == expected_reason
    assert terminal.wallet_id == wallet_id


@pytest.mark.asyncio
async def test_standard_human_approval_key_denial_keeps_reason(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.models import InsightEventModel
    from app.main import app
    from app.routers import mcp_standard as standard_router
    from app.schemas.billing import ServiceCategory
    from app.services.service_registry import get_service_registry
    from tests.test_trust_helpers import provision_agent_wallet

    settings = get_settings()
    monkeypatch.setattr(settings, "OPERATION_INSIGHTS_EVENTS_ENABLED", True)
    monkeypatch.setattr(settings, "ENABLE_STANDARD_MCP_ENDPOINT", True)

    async def approval_required(_wallet_id):
        return True

    monkeypatch.setattr(
        standard_router, "wallet_human_approval_required", approval_required
    )
    registry = get_service_registry()
    tool_name = "insight.synthetic.approval"
    registry.register_local(
        service_id=tool_name,
        name="Synthetic approval tool",
        description="Synthetic approval fixture",
        category=ServiceCategory.AGENT_COMMS,
        func=lambda: {"ok": True},
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            provisioned = await provision_agent_wallet(client)
            response = await client.post(
                "/mcp",
                headers={
                    **provisioned["agent_headers"],
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": "approval-call",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": {}},
                },
            )
    finally:
        registry.unregister_local(tool_name)

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32003
    assert len(rows) == 2
    terminal = next(row for row in rows if row.kind == "terminal")
    assert terminal.gateway_outcome == "denied"
    assert terminal.reason_code == "idempotency_key_required_for_human_approval"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "at_mint", "expected_code"),
    (
        ("permit_max_calls_exceeded", False, -32003),
        ("permit_budget_exceeds_wallet_balance", True, -32004),
    ),
)
async def test_standard_early_permit_denial_keeps_reason(
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    at_mint: bool,
    expected_code: int,
) -> None:
    from app.core.config import get_settings
    from app.db.models import InsightEventModel
    from app.main import app
    from app.routers import mcp_standard as standard_router
    from app.routers.mcp import ToolPermissionDenied
    from app.schemas.billing import ServiceCategory
    from app.services.permits import PermitError
    from app.services.service_registry import get_service_registry
    from tests.test_trust_helpers import provision_agent_wallet

    settings = get_settings()
    monkeypatch.setattr(settings, "OPERATION_INSIGHTS_EVENTS_ENABLED", True)
    monkeypatch.setattr(settings, "ENABLE_STANDARD_MCP_ENDPOINT", True)

    async def no_approval(_wallet_id):
        return False

    async def synthetic_permit(**_kwargs):
        if at_mint:
            raise standard_router._permit_error(PermitError(reason))
        return "permit-synthetic"

    async def denied_call(*_args, **_kwargs):
        raise ToolPermissionDenied(reason)

    monkeypatch.setattr(standard_router, "wallet_human_approval_required", no_approval)
    monkeypatch.setattr(standard_router, "_mint_auto_permit", synthetic_permit)
    monkeypatch.setattr(standard_router, "_handle_tools_call", denied_call)
    registry = get_service_registry()
    tool_name = "insight.synthetic.permit-denial"
    registry.register_local(
        service_id=tool_name,
        name="Synthetic permit denial tool",
        description="Synthetic permit denial fixture",
        category=ServiceCategory.AGENT_COMMS,
        func=lambda: {"ok": True},
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            provisioned = await provision_agent_wallet(client)
            response = await client.post(
                "/mcp",
                headers={
                    **provisioned["agent_headers"],
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": "permit-denial-call",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": {}},
                },
            )
    finally:
        registry.unregister_local(tool_name)

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert response.status_code == 200
    assert response.json()["error"]["code"] == expected_code
    assert len(rows) == 2
    terminal = next(row for row in rows if row.kind == "terminal")
    assert terminal.gateway_outcome == "denied"
    assert terminal.reason_code == reason


@pytest.mark.asyncio
async def test_standard_delivery_uncertain_result_is_unknown_terminal(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.models import InsightEventModel
    from app.main import app
    from app.services.operation_insights.events import wait_for_pending_events
    from app.services.service_registry import get_service_registry
    from tests.test_standard_mcp_endpoint import _register_ambiguous_upstream
    from tests.test_trust_helpers import provision_agent_wallet

    settings = get_settings()
    monkeypatch.setattr(settings, "OPERATION_INSIGHTS_EVENTS_ENABLED", True)
    monkeypatch.setattr(settings, "ENABLE_STANDARD_MCP_ENDPOINT", True)

    tool_name = "insight.ambiguous.upstream"
    executor = _register_ambiguous_upstream(tool_name)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            provisioned = await provision_agent_wallet(client)
            response = await client.post(
                "/mcp",
                headers={
                    **provisioned["agent_headers"],
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                    "Idempotency-Key": uuid.uuid4().hex,
                },
                json={
                    "jsonrpc": "2.0",
                    "id": "client-uncertain",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": {"test": "value"}},
                },
            )
    finally:
        get_service_registry().unregister_local(tool_name)

    await wait_for_pending_events()

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert response.status_code == 200
    assert response.json()["result"]["isError"] is True
    assert len(rows) == 3
    assert executor.dispatch_count == 1
    terminal = next(row for row in rows if row.kind == "terminal")
    assert terminal.request_disposition == "execution_intent"
    assert terminal.gateway_outcome == "unknown"
    assert terminal.reason_code == "delivery_uncertain"
    assert terminal.effect_state == "unknown"


@pytest.mark.asyncio
async def test_rest_success_has_gateway_outcome_without_effect_claim(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.models import InsightEventModel
    from app.main import app
    from app.routers import mcp as mcp_router
    from tests.test_trust_helpers import provision_agent_wallet

    monkeypatch.setattr(get_settings(), "OPERATION_INSIGHTS_EVENTS_ENABLED", True)

    async def normalize_request(*_args, **_kwargs):
        return object()

    async def invoke(_request):
        return object()

    async def normalize_response(_result):
        return {"content": [], "isError": False}

    monkeypatch.setattr(mcp_router._mcp_adapter, "normalize_request", normalize_request)
    monkeypatch.setattr(mcp_router._mcp_adapter, "invoke", invoke)
    monkeypatch.setattr(
        mcp_router._mcp_adapter, "normalize_response", normalize_response
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        provisioned = await provision_agent_wallet(client)
        response = await client.post(
            "/mcp/tools/synthetic-tool/invoke",
            headers=provisioned["agent_headers"],
            json={
                "name": "synthetic-tool",
                "arguments": {},
                "mcp_context": {"wallet_id": provisioned["agent_wallet_id"]},
            },
        )

        async def insufficient_funds(_request):
            raise ValueError("insufficient_funds")

        monkeypatch.setattr(mcp_router._mcp_adapter, "invoke", insufficient_funds)
        denied = await client.post(
            "/mcp/tools/synthetic-tool/invoke",
            headers=provisioned["agent_headers"],
            json={
                "name": "synthetic-tool",
                "arguments": {},
                "mcp_context": {"wallet_id": provisioned["agent_wallet_id"]},
            },
        )

    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()

    assert response.status_code == 200
    assert denied.status_code == 402
    assert len(rows) == 4
    terminal = next(
        row for row in rows if row.kind == "terminal" and row.http_status_code == 200
    )
    assert terminal.gateway_outcome == "succeeded"
    assert terminal.effect_state == "unknown"
    denied_terminal = next(
        row for row in rows if row.kind == "terminal" and row.http_status_code == 402
    )
    assert denied_terminal.gateway_outcome == "denied"
    assert denied_terminal.reason_code == "insufficient_funds"


@pytest.mark.asyncio
async def test_governed_local_replay_adds_one_attempt_and_shared_logical_anchor(
    clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.models import IdempotencyRecordModel, InsightEventModel
    from app.main import app
    from app.routers import mcp as mcp_router
    from app.schemas.billing import ServiceCategory
    from app.services.idempotency import (
        GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
        IdempotencyInProgressError,
    )
    from app.services.operation_insights.events import wait_for_pending_events
    from app.services.service_registry import get_service_registry
    from app.services.signing_keys import get_signing_key_service
    from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

    settings = get_settings()
    monkeypatch.setattr(settings, "OPERATION_INSIGHTS_EVENTS_ENABLED", True)
    monkeypatch.setattr(settings, "TRUST_MODE_ENABLED", True)
    monkeypatch.setattr(settings, "ALLOW_LEGACY_UNPERMITTED_MCP", False)
    private_key = Ed25519PrivateKey.generate().private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    monkeypatch.setattr(
        settings,
        "TRUST_SIGNING_PRIVATE_KEY_B64",
        base64.b64encode(private_key).decode(),
    )
    get_signing_key_service()._private_key = None

    calls: list[int] = []

    def local_tool() -> dict[str, bool]:
        calls.append(1)
        return {"ok": True}

    tool_name = "insight.local.write"
    registry = get_service_registry()
    registry.register_local(
        service_id=tool_name,
        name="Insight local tool",
        description="Synthetic governed local operation",
        category=ServiceCategory.AGENT_COMMS,
        func=local_tool,
        credits_per_unit=2.0,
        unit_name="call",
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            provisioned = await provision_agent_wallet(client)
            permit = await create_tool_permit(
                client,
                wallet_id=provisioned["agent_wallet_id"],
                key_id=provisioned["key_id"],
                tool_name=tool_name,
            )
            body = {
                "jsonrpc": "2.0",
                "id": "client-call-2",
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {},
                    "mcpContext": {
                        "wallet_id": provisioned["agent_wallet_id"],
                        "permit_id": permit["permit_id"],
                        "idempotency_key": uuid.uuid4().hex,
                    },
                },
            }
            first = await client.post(
                "/mcp/messages", headers=provisioned["agent_headers"], json=body
            )
            replay = await client.post(
                "/mcp/messages", headers=provisioned["agent_headers"], json=body
            )

            async def held_record(**_kwargs):
                raise IdempotencyInProgressError("idempotency_in_progress")

            monkeypatch.setattr(
                mcp_router, "_begin_governed_mcp_idempotency", held_record
            )
            pending = await client.post(
                "/mcp/messages", headers=provisioned["agent_headers"], json=body
            )
    finally:
        registry.unregister_local(tool_name)

    await wait_for_pending_events()
    async with get_session_factory()() as session:
        rows = (await session.execute(select(InsightEventModel))).scalars().all()
        owner = (
            (
                await session.execute(
                    select(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.wallet_id
                        == provisioned["agent_wallet_id"],
                        IdempotencyRecordModel.endpoint
                        == GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
                    )
                )
            )
            .scalars()
            .first()
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert pending.status_code == 200
    assert pending.json()["error"]["code"] == -32005
    assert calls == [1]
    assert [row.kind for row in rows].count("attempt") == 1
    assert [row.kind for row in rows].count("ingress") == 3
    assert [row.kind for row in rows].count("terminal") == 3
    assert [row.request_disposition for row in rows].count("same_key_replay") == 2
    assert [row.request_disposition for row in rows].count("status_read") == 2
    assert owner is not None
    assert {
        row.original_operation_anchor_id
        for row in rows
        if row.request_disposition != "status_read"
    } == {owner.record_id}
    assert all(
        row.original_operation_anchor_id is None
        for row in rows
        if row.request_disposition == "status_read"
    )
    assert all(
        row.gateway_outcome == "succeeded" and row.effect_state == "unknown"
        for row in rows
        if row.kind == "terminal"
        and row.request_disposition in {"execution_intent", "same_key_replay"}
    )


def test_local_event_migration_matches_model_and_preserves_retained_rows(
    tmp_path: Path,
) -> None:
    from app.db.models import InsightEventModel

    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/045_amw_insights_events.py"
    )
    spec = importlib.util.spec_from_file_location("insight_event_migration", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "amw_insights_events_20261010"
    assert module.down_revision == "amw_insights_authority_20261010"

    engine = create_engine(f"sqlite:///{tmp_path / 'insight-events.db'}")
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert set(
            sa_inspect(connection).get_columns("operation_insight_events")[i]["name"]
            for i in range(len(InsightEventModel.__table__.columns))
        ) == set(InsightEventModel.__table__.columns.keys())
        connection.execute(
            text(
                "INSERT INTO operation_insight_events "
                "(event_id, kind, occurred_at, ingested_at, classification_version) "
                "VALUES ('evt-retained', 'terminal', '2026-10-10', '2026-10-10', 1)"
            )
        )
        with pytest.raises(RuntimeError, match="insight_events_retained"):
            module.downgrade()
        connection.execute(text("DELETE FROM operation_insight_events"))
        module.downgrade()
        assert (
            "operation_insight_events" not in sa_inspect(connection).get_table_names()
        )
