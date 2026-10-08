"""Coverage for awi_sdk/python/awi_sdk/models.py.

The SDK models carry the action vocabulary contract between agents and the
governed routes. The valuable behavior here is fail-fast metadata coercion:
an action definition with an unknown tier, status, or risk level must raise
at construction time, not pass a bad value downstream to policy decisions.
"""

import sys
from pathlib import Path

import pytest

_SDK_PATH = str(Path(__file__).resolve().parents[1] / "awi_sdk" / "python")
if _SDK_PATH not in sys.path:
    sys.path.insert(0, _SDK_PATH)

from awi_sdk.models import (
    AWIActionDefinition,
    AWIActionRiskLevel,
    AWIActionStatus,
    AWIActionTier,
    AWIExecutionResponse,
    AWISession,
    AWITaskStatus,
)


def _definition(**overrides):
    fields = {
        "action": "search_and_sort",
        "category": "discovery",
        "description": "search then sort",
        "parameters": {"query": {"type": "string"}},
        "required_preconditions": [],
        "postconditions": [],
        "estimated_cost": 1.0,
        "tier": "semantic",
        "status": "stable",
        "risk_level": "low",
        "sensitive_parameters": [],
    }
    fields.update(overrides)
    return AWIActionDefinition(**fields)


def test_string_literals_coerce_to_enums():
    definition = _definition(
        tier="compatibility", status="provisional", risk_level="high"
    )
    assert definition.tier is AWIActionTier.COMPATIBILITY
    assert definition.status is AWIActionStatus.PROVISIONAL
    assert definition.risk_level is AWIActionRiskLevel.HIGH


def test_enum_members_survive_coercion():
    definition = _definition(
        tier=AWIActionTier.SEMANTIC,
        status=AWIActionStatus.STABLE,
        risk_level=AWIActionRiskLevel.LOW,
    )
    assert definition.tier is AWIActionTier.SEMANTIC


@pytest.mark.parametrize("field", ["tier", "status", "risk_level"])
def test_unknown_metadata_value_raises_value_error(field):
    with pytest.raises(ValueError):
        _definition(**{field: "not-a-real-value"})


def test_empty_metadata_value_raises_value_error():
    with pytest.raises(ValueError):
        _definition(tier="")


def test_session_defaults():
    from datetime import datetime, timezone

    session = AWISession(
        session_id="s-1",
        target_url="https://shop.example.test",
        status="active",
        created_at=datetime.now(timezone.utc),
    )
    assert session.max_steps == 100
    assert session.step_count == 0


def test_execution_response_optional_fields_default_to_none():
    response = AWIExecutionResponse(
        execution_id="e-1", session_id="s-1", action="login", status="ok"
    )
    assert response.result is None
    assert response.error is None
    assert response.representation is None
    assert response.duration_ms is None
    assert response.cost_estimate is None


def test_task_status_defaults():
    status = AWITaskStatus(task_id="t-1", status="queued", priority=5)
    assert status.progress == 0.0
    assert status.result is None
    assert status.error is None
