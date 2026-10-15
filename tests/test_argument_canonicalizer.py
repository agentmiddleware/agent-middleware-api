"""Canonical argument form used by the wallet re-plan guard.

Equivalent re-serializations must hash the same; anything a tool could treat
differently must not.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.services.argument_canonicalizer import (
    CanonicalizationError,
    canonical_decimal,
    canonical_request_hash,
    canonicalize_arguments,
)


def _h(args, tool="t", fold=()):
    return canonical_request_hash(tool, args, casefold_fields=fold)


def test_key_order_does_not_matter_at_any_depth():
    a = {"b": 1, "a": {"y": [1, 2], "x": "v"}}
    b = json.loads('{"a": {"x": "v", "y": [1, 2]}, "b": 1}')
    assert _h(a) == _h(b)
    assert canonicalize_arguments(a) == '{"a":{"x":"v","y":[1,2]},"b":1}'


def test_array_order_matters():
    assert _h({"to": ["a", "b"]}) != _h({"to": ["b", "a"]})


@pytest.mark.parametrize(
    "variant",
    [1, 1.0, Decimal("1.00"), Decimal("1E0"), json.loads("1.000")],
)
def test_numbers_normalize_exactly_through_decimal(variant):
    assert _h({"amount": variant}) == _h({"amount": 1})


def test_decimal_is_exact_not_float_rounded():
    assert canonical_decimal(0.1) == "0.1"
    assert canonical_decimal(Decimal("0.10")) == "0.1"
    assert canonical_decimal(Decimal("1E+3")) == "1000"
    assert canonical_decimal(-0.0) == "0"
    assert canonical_decimal(Decimal("123456789012345678.000000001")) == (
        "123456789012345678.000000001"
    )
    # Distinct values stay distinct even where float would collide.
    assert _h({"n": Decimal("0.30000000000000001")}) != _h({"n": Decimal("0.3")})


def test_amount_changes_are_never_collapsed():
    assert _h({"amount": 100}) != _h({"amount": 100.5})
    assert _h({"amount": 10}) != _h({"amount": 100})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_refused(bad):
    with pytest.raises(CanonicalizationError):
        canonicalize_arguments({"n": bad})


def test_types_stay_distinct():
    hashes = {
        _h({"v": True}),
        _h({"v": 1}),
        _h({"v": "1"}),
        _h({"v": None}),
        _h({"v": "null"}),
        _h({"v": "true"}),
        _h({"v": []}),
        _h({"v": {}}),
    }
    assert len(hashes) == 8


def test_nfkc_normalizes_compatibility_forms_in_keys_and_values():
    # Fullwidth letters and a ligature are NFKC-equivalent to ASCII.
    assert _h({"ｎame": "ﬁle"}) == _h({"name": "file"})
    # Composed vs decomposed accents.
    assert _h({"city": "Café"}) == _h({"city": "Café"})


def test_no_global_lowercasing_or_stripping():
    assert _h({"name": "Bob"}) != _h({"name": "bob"})
    assert _h({"name": "x"}) != _h({"name": " x"})
    assert _h({"name": "x"}) != _h({"name": "x "})
    assert _h({"Name": "x"}) != _h({"name": "x"})


def test_casefold_applies_only_to_configured_entity_fields():
    fold = ("email",)
    assert _h({"email": "Alice@Example.COM"}, fold=fold) == _h(
        {"email": "alice@example.com"}, fold=fold
    )
    # Nested strings under the field fold too.
    assert _h({"email": ["A@X.io"]}, fold=fold) == _h({"email": ["a@x.io"]}, fold=fold)
    # Other fields are untouched, and nothing folds without configuration.
    assert _h({"email": "A", "note": "Hi"}, fold=fold) != _h(
        {"email": "a", "note": "hi"}, fold=fold
    )
    assert _h({"email": "A"}) != _h({"email": "a"})
    # German sharp s: casefold, not lower().
    assert _h({"email": "STRASSE"}, fold=fold) == _h({"email": "straße"}, fold=fold)


def test_tool_name_is_part_of_the_hash():
    assert _h({"a": 1}, tool="x") != _h({"a": 1}, tool="y")


def test_colliding_keys_after_nfkc_are_kept_deterministically():
    a = {"ｆoo": 1, "foo": 2}
    b = {"foo": 2, "ｆoo": 1}
    assert canonicalize_arguments(a) == canonicalize_arguments(b)
    # Nothing is silently dropped: swapping the values is a different request
    # only in which original key held which value, which NFKC erases, but
    # both values are still present.
    assert canonicalize_arguments(a).count('"foo"') == 2
    assert _h({"foo": 1}) != _h(a)


def test_unsupported_types_are_refused():
    with pytest.raises(CanonicalizationError):
        canonicalize_arguments({"v": object()})
    with pytest.raises(CanonicalizationError):
        canonicalize_arguments({1: "x"})


def test_deep_nesting_is_bounded():
    value: dict = {}
    cursor = value
    for _ in range(80):
        cursor["n"] = {}
        cursor = cursor["n"]
    with pytest.raises(CanonicalizationError):
        canonicalize_arguments(value)
