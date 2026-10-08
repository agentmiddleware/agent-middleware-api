"""Constraint-coverage map and action-permit remedy details (gtm-07).

Core validation does not enforce every permit constraint: recipient domain
and repeat rules live downstream. These tests pin the coverage map that says
so, and pin that the single-use action path names the constraint it rejects
so an agent gets a remedy instead of a bare reason.
"""

import pytest

from app.services import action_permits
from app.services.permits import PERMIT_CONSTRAINT_COVERAGE, PermitService
from tests.test_action_invocation import action_permit
from tests.test_action_permits import BINDING


def test_coverage_map_names_every_downstream_constraint():
    assert "recipient_domain" in PERMIT_CONSTRAINT_COVERAGE
    assert "repeat window and identical repeats" in PERMIT_CONSTRAINT_COVERAGE
    assert (
        "mcp_dispatch_attempts"
        in PERMIT_CONSTRAINT_COVERAGE["repeat window and identical repeats"]
    )
    assert "mcp.py" in PERMIT_CONSTRAINT_COVERAGE["recipient_domain"]
    for constraint, layer in PERMIT_CONSTRAINT_COVERAGE.items():
        assert layer.strip(), constraint


def test_validate_for_action_docstring_discloses_downstream_layers():
    doc = PermitService.validate_for_action.__doc__ or ""
    assert "recipient_domain" in doc
    assert "repeat" in doc
    assert "PERMIT_CONSTRAINT_COVERAGE" in doc


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("changes", "named"),
    [
        ({"recipient_domain": "fixture.invalid"}, "recipient_domain"),
        ({"repeat_window_seconds": 60}, "repeat_window_seconds"),
        ({"aggregate_value_cap": 5}, "aggregate_value_cap"),
        ({"forbidden_fields_json": '["secret"]'}, "forbidden_fields"),
        ({"requires_human_approval": True}, "requires_human_approval"),
        ({"allow_identical_repeats": True}, "allow_identical_repeats"),
    ],
)
async def test_action_gate_denial_names_constraint_and_remedy(
    monkeypatch, changes, named
):
    from datetime import timedelta
    from unittest.mock import AsyncMock

    from app.core.time import utc_now
    from app.services.permits import get_permit_service

    args = {"amount_minor": 1, "recipient": "alice"}
    model = action_permit(
        **changes,
        expires_at=utc_now() + timedelta(hours=1),
        subject_key_id=None,
        scopes_json='["tool:partner.pay:invoke","billing:charge"]',
    )
    model.action_payload_hash = action_permits.action_payload_hash(
        BINDING, model.subject_wallet_id, args
    )
    monkeypatch.setattr(
        get_permit_service(), "verify_signature", AsyncMock(return_value=True)
    )
    result = await action_permits.validate_action_request(
        model, BINDING, model.subject_wallet_id, None, args, "replay"
    )
    assert not result.allowed
    assert result.reason == "unsupported_action_constraints"
    assert result.details is not None
    assert named in result.details["unsupported_constraints"]
    assert result.details["remedy"]
