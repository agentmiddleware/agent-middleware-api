"""Unit tests for app.services.permit_requests pure helpers.

Covers the request-identity layer without a database or network: the terms
hash the human reviews, the deterministic Sentinel idempotency key, the
timeout/approver settings parsing, the error shapes, and the approver-card
and poll-URL projections. The DB-backed create/advance/mint flow is covered
by tests/test_permit_request_flow.py.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from app.core.config import get_settings
from app.db.models import PermitRequestModel
from app.services import permit_requests as preq
from app.services.permit_requests import (
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_EXPIRED,
    REQUEST_STATUS_FAILED,
    REQUEST_STATUS_MINTING,
    REQUEST_STATUS_PENDING,
    REQUEST_STATUS_REJECTED,
    TERMINAL_STATUSES,
    PermitRequestConflictError,
    PermitRequestError,
    PermitRequestService,
    card_view,
    permit_request_hash,
    poll_url,
    sentinel_request_key,
)


def _terms(**overrides):
    base = {
        "issuer_wallet_id": "wallet_sponsor",
        "subject_wallet_id": "wallet_agent",
        "allowed_tools": ["translate", "fetch-url"],
        "scopes": ["billing:charge", "tool:fetch-url:invoke"],
        "max_credits": Decimal("20"),
        "permit_expires_at": datetime(2035, 1, 1),
        "requires_human_approval": False,
        "justification": "Draft the weekly digest.",
    }
    base.update(overrides)
    return base


def test_permit_request_hash_is_stable():
    assert permit_request_hash(**_terms()) == permit_request_hash(**_terms())


def test_permit_request_hash_ignores_list_ordering():
    unordered = _terms()
    reordered = _terms(
        allowed_tools=["fetch-url", "translate"],
        scopes=["tool:fetch-url:invoke", "billing:charge"],
    )
    assert permit_request_hash(**unordered) == permit_request_hash(**reordered)


def test_permit_request_hash_changes_with_terms():
    assert permit_request_hash(**_terms()) != permit_request_hash(
        **_terms(justification="Something else entirely.")
    )
    assert permit_request_hash(**_terms()) != permit_request_hash(
        **_terms(allowed_tools=["translate", "fetch-url", "send-email"])
    )


def test_sentinel_request_key_shape_and_determinism():
    key = sentinel_request_key(
        "abc123", subject_wallet_id="wallet_agent", idempotency_key="key-1"
    )
    assert key.startswith("mw-preq-")
    assert key == sentinel_request_key(
        "abc123", subject_wallet_id="wallet_agent", idempotency_key="key-1"
    )


def test_sentinel_request_key_varies_with_identity_and_terms():
    base = {"subject_wallet_id": "wallet_agent", "idempotency_key": "key-1"}
    assert sentinel_request_key("hash-a", **base) != sentinel_request_key(
        "hash-b", **base
    )
    assert sentinel_request_key(
        "hash-a", subject_wallet_id="wallet_agent", idempotency_key="key-2"
    ) != sentinel_request_key("hash-a", **base)


def test_error_types_carry_client_facing_reason():
    assert PermitRequestError("human_approval_not_configured").reason == (
        "human_approval_not_configured"
    )
    assert PermitRequestConflictError().reason == "permit_request_terms_conflict"


def test_status_constants_and_terminal_set():
    assert REQUEST_STATUS_PENDING == "pending"
    assert REQUEST_STATUS_MINTING == "minting"
    assert TERMINAL_STATUSES == frozenset(
        {
            REQUEST_STATUS_APPROVED,
            REQUEST_STATUS_REJECTED,
            REQUEST_STATUS_EXPIRED,
            REQUEST_STATUS_FAILED,
        }
    )
    assert REQUEST_STATUS_PENDING not in TERMINAL_STATUSES
    assert REQUEST_STATUS_MINTING not in TERMINAL_STATUSES


def test_timeout_seconds_clamps_to_sentinel_bounds(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "PERMIT_REQUEST_TIMEOUT_SECONDS", 5)
    assert PermitRequestService._timeout_seconds() == 60
    monkeypatch.setattr(settings, "PERMIT_REQUEST_TIMEOUT_SECONDS", 10**9)
    assert PermitRequestService._timeout_seconds() == 86400
    monkeypatch.setattr(settings, "PERMIT_REQUEST_TIMEOUT_SECONDS", 3600)
    assert PermitRequestService._timeout_seconds() == 3600


def test_approvers_parsing_skips_blanks(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        settings, "SENTINEL_APPROVERS", " alice@example.com ,,bob@example.com "
    )
    assert PermitRequestService._approvers() == [
        "alice@example.com",
        "bob@example.com",
    ]
    monkeypatch.setattr(settings, "SENTINEL_APPROVERS", "")
    assert PermitRequestService._approvers() == []


def _model() -> PermitRequestModel:
    return PermitRequestModel(
        request_id="preq-test00000001",
        issuer_wallet_id="wallet_sponsor",
        subject_wallet_id="wallet_agent",
        subject_key_id=None,
        idempotency_key="key-1",
        scopes_json=json.dumps(["billing:charge", "tool:fetch-url:invoke"]),
        allowed_tools_json=json.dumps(["fetch-url"]),
        max_credits=Decimal("20"),
        permit_expires_at=datetime(2035, 1, 1),
        requires_human_approval=False,
        justification="Draft the weekly digest.",
        request_hash="h" * 64,
        original_request_hash="h" * 64,
        status="pending",
        simulated=False,
        reserved_permit_id="permit-test00000001",
        requested_at=datetime(2030, 5, 1),
        expires_at=datetime(2030, 5, 2),
    )


def test_card_view_projects_stored_terms():
    view = card_view(_model())
    assert view.request_id == "preq-test00000001"
    assert view.subject_wallet_id == "wallet_agent"
    assert view.issuer_wallet_id == "wallet_sponsor"
    assert view.allowed_tools == ["fetch-url"]
    assert view.scopes == ["billing:charge", "tool:fetch-url:invoke"]
    assert view.max_credits == Decimal("20")
    assert view.justification == "Draft the weekly digest."
    assert view.decide_by == datetime(2030, 5, 2)
    assert view.status == "pending"


def test_poll_url_points_at_request():
    assert poll_url("preq-test00000001").endswith(
        "/v1/permit-requests/preq-test00000001"
    )


def test_service_caches_sentinel_client():
    service = PermitRequestService()
    assert service._client is None
    assert isinstance(service, PermitRequestService)
    assert preq.get_permit_request_service() is preq.get_permit_request_service()
