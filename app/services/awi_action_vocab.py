"""
AWI Action Vocabulary — Phase 7
================================
Standardized higher-level action registry based on arXiv:2506.10953v1

Provides a unified vocabulary of web actions that abstract away DOM manipulation:
- Agents use semantic actions (search_and_sort, add_to_cart) instead of clicks
- Each action has defined parameters, preconditions, and postconditions
- Actions can be composed into sequences for complex workflows
"""

import uuid
from typing import Any

from ..schemas.awi import AWIStandardAction, AWIActionCategory


class AWIActionDefinition:
    """Definition of a standardized AWI action."""

    def __init__(
        self,
        action: AWIStandardAction,
        category: AWIActionCategory,
        description: str,
        parameters: dict[str, dict[str, Any]],
        required_preconditions: list[str],
        postconditions: list[str],
        estimated_cost: float = 0.001,
    ):
        self.action = action
        self.category = category
        self.description = description
        self.parameters = parameters
        self.required_preconditions = required_preconditions
        self.postconditions = postconditions
        self.estimated_cost = estimated_cost


class AWIActionVocabulary:
    """
    Registry of standardized AWI actions.

    Based on the paper's principle: "Higher-level unified actions" -
    stop forcing agents to click/type on DOMs; give them abstract,
    standardized actions.
    """

    def __init__(self):
        self._actions: dict[AWIStandardAction, AWIActionDefinition] = {}
        self._register_default_actions()

    def _register_default_actions(self):
        """Register the default standardized action vocabulary."""
        actions = [
            AWIActionDefinition(
                action=AWIStandardAction.SEARCH_AND_SORT,
                category=AWIActionCategory.SEARCH,
                description="Search for items and optionally sort results",
                parameters={
                    "query": {"type": "string", "required": True},
                    "sort_by": {"type": "string", "required": False},
                    "sort_order": {"type": "string", "required": False},
                    "filters": {"type": "object", "required": False},
                },
                required_preconditions=["page_loaded"],
                postconditions=["results_displayed"],
                estimated_cost=0.002,
            ),
            AWIActionDefinition(
                action=AWIStandardAction.ADD_TO_CART,
                category=AWIActionCategory.TRANSACTION,
                description="Add an item to the shopping cart",
                parameters={
                    "item_id": {"type": "string", "required": True},
                    "quantity": {"type": "integer", "required": False},
                    "variant": {"type": "string", "required": False},
                },
                required_preconditions=["item_visible", "cart_accessible"],
                postconditions=["item_in_cart"],
                estimated_cost=0.001,
            ),
            AWIActionDefinition(
                action=AWIStandardAction.CHECKOUT,
                category=AWIActionCategory.TRANSACTION,
                description="Complete the checkout process",
                parameters={
                    "payment_method": {"type": "string", "required": True},
                    "shipping_address": {"type": "object", "required": False},
                    "billing_address": {"type": "object", "required": False},
                },
                required_preconditions=["cart_not_empty", "user_authenticated"],
                postconditions=["order_placed", "payment_processed"],
                estimated_cost=0.01,
            ),
            AWIActionDefinition(
                action=AWIStandardAction.FILL_FORM,
                category=AWIActionCategory.INTERACTION,
                description="Fill out a form with provided data",
                parameters={
                    "form_id": {"type": "string", "required": False},
                    "fields": {"type": "object", "required": True},
                    "submit": {"type": "boolean", "required": False},
                },
                required_preconditions=["form_visible"],
                postconditions=["form_filled", "form_submitted"],
                estimated_cost=0.001,
            ),
            AWIActionDefinition(
                action=AWIStandardAction.LOGIN,
                category=AWIActionCategory.AUTH,
                description="Authenticate with the target website",
                parameters={
                    "username": {"type": "string", "required": True},
                    "password": {"type": "string", "required": True},
                    "remember_me": {"type": "boolean", "required": False},
                },
                required_preconditions=["login_page_visible"],
                postconditions=["user_authenticated", "session_created"],
                estimated_cost=0.002,
            ),
            AWIActionDefinition(
                action=AWIStandardAction.LOGOUT,
                category=AWIActionCategory.AUTH,
                description="End the current session",
                parameters={},
                required_preconditions=["user_authenticated"],
                postconditions=["session_terminated", "logged_out"],
                estimated_cost=0.0005,
            ),
            AWIActionDefinition(
                action=AWIStandardAction.NAVIGATE_TO,
                category=AWIActionCategory.NAVIGATION,
                description="Navigate to a specific URL or page",
                parameters={
                    "url": {"type": "string", "required": True},
                    "wait_for_load": {"type": "boolean", "required": False},
                },
                required_preconditions=[],
                postconditions=["page_loaded"],
                estimated_cost=0.001,
            ),
            AWIActionDefinition(
                action=AWIStandardAction.CLICK_BUTTON,
                category=AWIActionCategory.INTERACTION,
                description="Click a button or interactive element",
                parameters={
                    "button_id": {"type": "string", "required": False},
                    "button_text": {"type": "string", "required": False},
                    "button_selector": {"type": "string", "required": False},
                },
                required_preconditions=["button_visible"],
                postconditions=["button_clicked"],
                estimated_cost=0.0005,
            ),
            AWIActionDefinition(
                action=AWIStandardAction.SCROLL,
                category=AWIActionCategory.NAVIGATION,
                description="Scroll the page",
                parameters={
                    "direction": {"type": "string", "required": True},
                    "amount": {"type": "integer", "required": False},
                },
                required_preconditions=["page_loaded"],
                postconditions=["scrolled"],
                estimated_cost=0.0002,
            ),
            AWIActionDefinition(
                action=AWIStandardAction.SELECT_OPTION,
                category=AWIActionCategory.INTERACTION,
                description="Select an option from a dropdown or list",
                parameters={
                    "select_id": {"type": "string", "required": False},
                    "option_value": {"type": "string", "required": True},
                    "option_text": {"type": "string", "required": False},
                },
                required_preconditions=["select_visible"],
                postconditions=["option_selected"],
                estimated_cost=0.0005,
            ),
            AWIActionDefinition(
                action=AWIStandardAction.UPLOAD_FILE,
                category=AWIActionCategory.INTERACTION,
                description="Upload a file to the page",
                parameters={
                    "file_path": {"type": "string", "required": True},
                    "input_id": {"type": "string", "required": False},
                },
                required_preconditions=["upload_input_visible"],
                postconditions=["file_uploaded"],
                estimated_cost=0.005,
            ),
            AWIActionDefinition(
                action=AWIStandardAction.EXTRACT_DATA,
                category=AWIActionCategory.EXTRACTION,
                description="Extract structured data from the page",
                parameters={
                    "data_type": {"type": "string", "required": True},
                    "selector": {"type": "string", "required": False},
                    "limit": {"type": "integer", "required": False},
                },
                required_preconditions=["data_visible"],
                postconditions=["data_extracted"],
                estimated_cost=0.002,
            ),
            AWIActionDefinition(
                action=AWIStandardAction.GET_REPRESENTATION,
                category=AWIActionCategory.EXTRACTION,
                description="Get a specific representation of the current state",
                parameters={
                    "representation_type": {"type": "string", "required": True},
                    "options": {"type": "object", "required": False},
                },
                required_preconditions=["page_loaded"],
                postconditions=["representation_returned"],
                estimated_cost=0.001,
            ),
        ]

        for action_def in actions:
            self._actions[action_def.action] = action_def

    def get_action(self, action: AWIStandardAction) -> AWIActionDefinition | None:
        """Get the definition of an action."""
        return self._actions.get(action)

    def list_actions_by_category(
        self, category: AWIActionCategory
    ) -> list[AWIActionDefinition]:
        """List all actions in a category."""
        return [a for a in self._actions.values() if a.category == category]

    def list_all_actions(self) -> list[AWIActionDefinition]:
        """List all registered actions."""
        return list(self._actions.values())

    def validate_parameters(
        self, action: AWIStandardAction, params: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """
        Validate parameters for an action.

        Returns (is_valid, error_message).
        """
        action_def = self._actions.get(action)
        if not action_def:
            return False, f"Unknown action: {action}"

        for param_name, param_def in action_def.parameters.items():
            if param_def.get("required", False) and param_name not in params:
                return False, f"Missing required parameter: {param_name}"

        return True, None

    def check_preconditions(
        self, action: AWIStandardAction, session_state: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """
        Check if preconditions are met for an action.

        Returns (met, unmet_preconditions).
        """
        action_def = self._actions.get(action)
        if not action_def:
            return False, [f"Unknown action: {action}"]

        unmet = []
        for precondition in action_def.required_preconditions:
            if precondition not in session_state.get("capabilities", []):
                unmet.append(precondition)

        return len(unmet) == 0, unmet

    def get_estimated_cost(self, action: AWIStandardAction) -> float:
        """Get the estimated cost for an action."""
        action_def = self._actions.get(action)
        return action_def.estimated_cost if action_def else 0.0

    def register_custom_action(self, action_def: AWIActionDefinition):
        """Register a custom action."""
        self._actions[action_def.action] = action_def


_awi_vocabulary: AWIActionVocabulary | None = None


def get_awi_vocabulary() -> AWIActionVocabulary:
    """Get singleton AWI vocabulary instance."""
    global _awi_vocabulary
    if _awi_vocabulary is None:
        _awi_vocabulary = AWIActionVocabulary()
    return _awi_vocabulary
