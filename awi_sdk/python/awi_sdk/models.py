"""
AWI SDK Models — Phase 8
=========================
"""

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
