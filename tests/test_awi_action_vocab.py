"""Focused unit tests for app.services.awi_action_vocab.

Covers the main public behavior of AWIActionVocabulary with no network
or external services: registry contents, parameter validation (including
the LOGIN credential-handle transition), sensitive-parameter redaction,
precondition checks, cost lookup, custom registration, and the
unknown-action edge cases.
"""

import copy

import pytest

from app.schemas.awi import AWIActionCategory, AWIStandardAction
from app.services.awi_action_vocab import (
    AWIActionDefinition,
    AWIActionVocabulary,
    get_awi_vocabulary,
)


@pytest.fixture
def vocab() -> AWIActionVocabulary:
    return AWIActionVocabulary()


def test_singleton() -> None:
    assert get_awi_vocabulary() is get_awi_vocabulary()


def test_all_standard_actions_registered(vocab: AWIActionVocabulary) -> None:
    registered = {d.action for d in vocab.list_all_actions()}
    assert registered == set(AWIStandardAction)


def test_get_action_known(vocab: AWIActionVocabulary) -> None:
    action_def = vocab.get_action(AWIStandardAction.SEARCH_AND_SORT)
    assert action_def is not None
    assert action_def.category == AWIActionCategory.SEARCH
    assert action_def.required_preconditions == ["page_loaded"]


def test_list_by_category_only_returns_members(
    vocab: AWIActionVocabulary,
) -> None:
    nav = vocab.list_actions_by_category(AWIActionCategory.NAVIGATION)
    assert len(nav) > 0
    assert all(d.category == AWIActionCategory.NAVIGATION for d in nav)
    assert {d.action for d in nav} == {
        AWIStandardAction.NAVIGATE_TO,
        AWIStandardAction.SCROLL,
    }


def test_to_public_dict_shape(vocab: AWIActionVocabulary) -> None:
    action_def = vocab.get_action(AWIStandardAction.CHECKOUT)
    assert action_def is not None
    public = action_def.to_public_dict()
    assert public["action"] == "checkout"
    assert public["category"] == "transaction"
    assert public["risk_level"] == "high"
    assert public["sensitive_parameters"] == ["payment_method"]
    assert set(public) == {
        "action",
        "category",
        "description",
        "parameters",
        "required_preconditions",
        "postconditions",
        "estimated_cost",
        "tier",
        "status",
        "risk_level",
        "sensitive_parameters",
    }


def test_validate_valid_params(vocab: AWIActionVocabulary) -> None:
    ok, error = vocab.validate_parameters(
        AWIStandardAction.SEARCH_AND_SORT, {"query": "laptops"}
    )
    assert (ok, error) == (True, None)


def test_validate_missing_required_param(vocab: AWIActionVocabulary) -> None:
    ok, error = vocab.validate_parameters(AWIStandardAction.SEARCH_AND_SORT, {})
    assert ok is False
    assert error is not None and "query" in error


def test_validate_login_credential_handle(vocab: AWIActionVocabulary) -> None:
    ok, error = vocab.validate_parameters(
        AWIStandardAction.LOGIN, {"credential_handle": "credh_123"}
    )
    assert (ok, error) == (True, None)


def test_validate_login_legacy_credentials(vocab: AWIActionVocabulary) -> None:
    ok, error = vocab.validate_parameters(
        AWIStandardAction.LOGIN,
        {"username": "agent@example.com", "password": "secret"},
    )
    assert (ok, error) == (True, None)


def test_validate_login_missing_password_rejected(
    vocab: AWIActionVocabulary,
) -> None:
    ok, error = vocab.validate_parameters(
        AWIStandardAction.LOGIN, {"username": "agent@example.com"}
    )
    assert ok is False
    assert error is not None and "credential_handle" in error


def test_validate_login_empty_params_rejected(vocab: AWIActionVocabulary) -> None:
    ok, error = vocab.validate_parameters(AWIStandardAction.LOGIN, {})
    assert ok is False
    assert error is not None


def test_validate_unknown_action(vocab: AWIActionVocabulary) -> None:
    del vocab._actions[AWIStandardAction.SCROLL]
    ok, error = vocab.validate_parameters(
        AWIStandardAction.SCROLL, {"direction": "down"}
    )
    assert ok is False
    assert error is not None and "Unknown action" in error


def test_redact_direct_and_nested_sensitive_keys(
    vocab: AWIActionVocabulary,
) -> None:
    params = {
        "username": "agent@example.com",
        "password": "secret",
        "remember_me": False,
        "nested": {"items": [{"password": "x", "safe": "visible"}]},
    }
    redacted = vocab.redact_parameters(AWIStandardAction.LOGIN, params)
    assert redacted["username"] == "[REDACTED]"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["remember_me"] is False
    assert redacted["nested"]["items"][0] == {
        "password": "[REDACTED]",
        "safe": "visible",
    }
    assert params["password"] == "secret"


def test_redact_normalizes_key_variants(vocab: AWIActionVocabulary) -> None:
    redacted = vocab.redact_parameters(
        AWIStandardAction.CHECKOUT,
        {
            "paymentMethod": "card-token",
            "access-token": "access-secret",
            "safe": "visible",
        },
    )
    assert redacted == {
        "paymentMethod": "[REDACTED]",
        "access-token": "[REDACTED]",
        "safe": "visible",
    }


def test_redact_global_sensitive_key_without_action_def(
    vocab: AWIActionVocabulary,
) -> None:
    del vocab._actions[AWIStandardAction.LOGIN]
    redacted = vocab.redact_parameters(
        AWIStandardAction.LOGIN, {"api_key": "k", "safe": "visible"}
    )
    assert redacted == {"api_key": "[REDACTED]", "safe": "visible"}


def test_redact_does_not_mutate_caller_params(
    vocab: AWIActionVocabulary,
) -> None:
    params = {"password": "secret"}
    snapshot = copy.deepcopy(params)
    vocab.redact_parameters(AWIStandardAction.LOGIN, params)
    assert params == snapshot


def test_check_preconditions_met(vocab: AWIActionVocabulary) -> None:
    met, unmet = vocab.check_preconditions(
        AWIStandardAction.ADD_TO_CART,
        {"capabilities": ["item_visible", "cart_accessible"]},
    )
    assert (met, unmet) == (True, [])


def test_check_preconditions_unmet_reported(vocab: AWIActionVocabulary) -> None:
    met, unmet = vocab.check_preconditions(
        AWIStandardAction.ADD_TO_CART, {"capabilities": ["item_visible"]}
    )
    assert met is False
    assert unmet == ["cart_accessible"]


def test_check_preconditions_missing_capabilities_key(
    vocab: AWIActionVocabulary,
) -> None:
    met, unmet = vocab.check_preconditions(AWIStandardAction.NAVIGATE_TO, {})
    assert (met, unmet) == (True, [])


def test_check_preconditions_unknown_action(vocab: AWIActionVocabulary) -> None:
    del vocab._actions[AWIStandardAction.SCROLL]
    met, unmet = vocab.check_preconditions(
        AWIStandardAction.SCROLL, {"capabilities": []}
    )
    assert met is False
    assert len(unmet) == 1 and "Unknown action" in unmet[0]


def test_estimated_cost_known_action(vocab: AWIActionVocabulary) -> None:
    assert vocab.get_estimated_cost(AWIStandardAction.CHECKOUT) == 0.01


def test_estimated_cost_unknown_action_is_zero(
    vocab: AWIActionVocabulary,
) -> None:
    del vocab._actions[AWIStandardAction.SCROLL]
    assert vocab.get_estimated_cost(AWIStandardAction.SCROLL) == 0.0


def test_register_custom_action_overrides(vocab: AWIActionVocabulary) -> None:
    replacement = AWIActionDefinition(
        action=AWIStandardAction.SCROLL,
        category=AWIActionCategory.NAVIGATION,
        description="custom scroll",
        parameters={"direction": {"type": "string", "required": True}},
        required_preconditions=[],
        postconditions=["scrolled"],
        estimated_cost=0.123,
    )
    vocab.register_custom_action(replacement)
    assert vocab.get_action(AWIStandardAction.SCROLL) is replacement
    assert vocab.get_estimated_cost(AWIStandardAction.SCROLL) == 0.123
