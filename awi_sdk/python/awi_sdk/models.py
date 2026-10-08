"""
AWI SDK Models — Phase 8
=========================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AWIStandardAction(str, Enum):
    """Standardized AWI actions."""

    SEARCH_AND_SORT = "search_and_sort"
    ADD_TO_CART = "add_to_cart"
    CHECKOUT = "checkout"
    FILL_FORM = "fill_form"
    LOGIN = "login"
    LOGOUT = "logout"
    NAVIGATE_TO = "navigate_to"
    CLICK_BUTTON = "click_button"
    SCROLL = "scroll"
    SELECT_OPTION = "select_option"
    UPLOAD_FILE = "upload_file"
    EXTRACT_DATA = "extract_data"
    GET_REPRESENTATION = "get_representation"


class AWIRepresentationType(str, Enum):
    """Types of progressive representations."""

    FULL_DOM = "full_dom"
    SUMMARY = "summary"
    EMBEDDING = "embedding"
    LOW_RES_SCREENSHOT = "low_res_screenshot"
    ACCESSIBILITY_TREE = "accessibility_tree"
    JSON_STRUCTURE = "json_structure"
    TEXT_EXTRACTION = "text_extraction"


class AWIActionTier(str, Enum):
    """How directly an action expresses AWI semantic intent."""

    SEMANTIC = "semantic"
    COMPATIBILITY = "compatibility"


class AWIActionStatus(str, Enum):
    """Maturity status for AWI action contracts."""

    STABLE = "stable"
    PROVISIONAL = "provisional"
    DEPRECATED = "deprecated"


class AWIActionRiskLevel(str, Enum):
    """Risk level for policy and human-approval decisions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class AWIActionDefinition:
    """Public AWI action vocabulary entry."""

    action: str
    category: str
    description: str
    parameters: dict[str, dict[str, Any]]
    required_preconditions: list[str]
    postconditions: list[str]
    estimated_cost: float
    tier: AWIActionTier | str
    status: AWIActionStatus | str
    risk_level: AWIActionRiskLevel | str
    sensitive_parameters: list[str]

    def __post_init__(self) -> None:
        """Coerce metadata literals into SDK enums for invalid-value detection."""
        self.tier = AWIActionTier(self.tier)
        self.status = AWIActionStatus(self.status)
        self.risk_level = AWIActionRiskLevel(self.risk_level)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AWIActionDefinition:
        """Build a definition from a ``GET /v1/awi/vocabulary`` entry.

        Unknown or missing fields fall back to safe defaults so a newer
        server vocabulary cannot break older SDK installs.
        """
        if not isinstance(data, dict):
            raise ValueError("action definition must be a dict")
        try:
            tier = AWIActionTier(data.get("tier", AWIActionTier.SEMANTIC))
        except ValueError:
            tier = AWIActionTier.SEMANTIC
        try:
            status = AWIActionStatus(data.get("status", AWIActionStatus.STABLE))
        except ValueError:
            status = AWIActionStatus.STABLE
        try:
            risk = AWIActionRiskLevel(data.get("risk_level", AWIActionRiskLevel.LOW))
        except ValueError:
            risk = AWIActionRiskLevel.LOW
        parameters = data.get("parameters")
        return cls(
            action=str(data.get("action", "")),
            category=str(data.get("category", "")),
            description=str(data.get("description", "")),
            parameters=parameters if isinstance(parameters, dict) else {},
            required_preconditions=list(data.get("required_preconditions") or []),
            postconditions=list(data.get("postconditions") or []),
            estimated_cost=float(data.get("estimated_cost", 0.0) or 0.0),
            tier=tier,
            status=status,
            risk_level=risk,
            sensitive_parameters=list(data.get("sensitive_parameters") or []),
        )


@dataclass
class AWISession:
    """An AWI session."""

    session_id: str
    target_url: str
    status: str
    created_at: datetime
    max_steps: int = 100
    step_count: int = 0


@dataclass
class AWIExecutionResponse:
    """Response from AWI action execution."""

    execution_id: str
    session_id: str
    action: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    representation: dict[str, Any] | None = None
    duration_ms: int | None = None
    cost_estimate: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AWIExecutionResponse:
        """Build a response from a ``POST /v1/awi/execute`` body.

        The receipt envelope and any extra server fields stay out of the
        typed view; callers that need them keep using ``execute`` raw dicts.
        """
        if not isinstance(data, dict):
            raise ValueError("execution response must be a dict")
        result = data.get("result")
        representation = data.get("representation")
        error = data.get("error")
        return cls(
            execution_id=str(data.get("execution_id", "")),
            session_id=str(data.get("session_id", "")),
            action=str(data.get("action", "")),
            status=str(data.get("status", "")),
            result=result if isinstance(result, dict) else None,
            error=error if isinstance(error, str) else None,
            representation=(representation if isinstance(representation, dict) else None),
            duration_ms=data.get("duration_ms"),
            cost_estimate=data.get("cost_estimate"),
        )


@dataclass
class AWIRepresentation:
    """AWI representation response."""

    representation_id: str
    representation_type: str
    content: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    generated_at: datetime | None = None


@dataclass
class AWITaskStatus:
    """Status of an AWI task."""

    task_id: str
    status: str
    priority: int
    progress: float = 0.0
    result: dict[str, Any] | None = None
    error: str | None = None
