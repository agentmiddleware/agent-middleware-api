"""Canonical form of tool arguments for wallet-scoped duplicate detection.

Two argument objects that a tool would treat as the same request should hash
the same, so that an agent which re-plans (rebuilds its arguments, reorders
keys, re-serializes numbers) under a new idempotency key or a new permit is
still recognised as repeating itself. Two objects that a tool could treat
differently must never hash the same. The rules lean towards the second
promise: a missed duplicate costs one extra dispatch, a false duplicate denies
a legitimate call.

Rules:

- Object keys are sorted (by code point, after normalization). Array order is
  kept: ``[a, b]`` and ``[b, a]`` are different requests.
- Every string, key or value, is Unicode NFKC-normalized. Nothing is stripped
  and nothing is lowercased globally: ``"Bob"`` and ``"bob"``, or ``"x"`` and
  ``" x"``, stay distinct.
- Case-folding applies only to string values (including strings nested in
  arrays/objects) under a field whose normalized name is in the explicit
  ``casefold_fields`` set — e.g. ``email``. It is never inferred.
- Numbers are normalized exactly through ``Decimal``, never through float
  arithmetic: ``1``, ``1.0`` and ``1.00`` are one number, ``0.1`` is
  ``Decimal("0.1")``. A float the JSON parser already produced is read
  through its shortest round-trip ``repr``, which is the literal the client
  sent for every value a float can hold exactly. Non-finite numbers are
  refused.
- Types stay distinct: ``true`` is not ``1``, ``"1"`` is not ``1``, and
  ``null`` is not ``"null"``.
- If two distinct keys normalize to the same key (``"ｆoo"`` and ``"foo"``)
  both are kept, ordered by their canonical value, so the result is
  deterministic and nothing is silently dropped.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

# Bounds the recursion; request bodies are already depth-limited upstream
# (_MAX_JSON_NESTING_DEPTH), this is defence in depth for direct callers.
_MAX_DEPTH = 64

_HASH_DOMAIN = b"amw:replan-canonical-args:v1\x00"


class CanonicalizationError(ValueError):
    """The value cannot be canonicalized (non-finite number, unsupported type)."""


def _nfkc(value: str) -> str:
    return unicodedata.normalize("NFKC", value)


def _fold(value: str) -> str:
    # casefold() can leave a string that is not NFKC-stable; renormalize.
    return _nfkc(_nfkc(value).casefold())


def canonical_decimal(value: int | float | Decimal) -> str:
    """Exact, exponent-free decimal text for a JSON number."""
    if isinstance(value, bool):  # bool is an int subclass; never a number here
        raise CanonicalizationError("bool_is_not_a_number")
    try:
        if isinstance(value, float):
            number = Decimal(repr(value))
        else:
            number = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise CanonicalizationError("number_not_decimal") from exc
    if not number.is_finite():
        raise CanonicalizationError("number_not_finite")
    if number.is_zero():
        return "0"  # -0, 0.0, 0E+3 are all zero
    normalized = number.normalize()
    text = format(normalized, "f")
    return text


def _encode(
    value: Any, *, folding: bool, fold_fields: frozenset[str], depth: int
) -> str:
    if depth > _MAX_DEPTH:
        raise CanonicalizationError("nesting_too_deep")
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        text = _fold(value) if folding else _nfkc(value)
        return json.dumps(text, ensure_ascii=False)
    if isinstance(value, (int, float, Decimal)):
        return canonical_decimal(value)
    if isinstance(value, Mapping):
        entries: list[tuple[str, str]] = []
        for raw_key, child in value.items():
            if not isinstance(raw_key, str):
                raise CanonicalizationError("object_key_not_string")
            key = _nfkc(raw_key)
            entries.append(
                (
                    key,
                    _encode(
                        child,
                        folding=folding or key in fold_fields,
                        fold_fields=fold_fields,
                        depth=depth + 1,
                    ),
                )
            )
        entries.sort()
        body = ",".join(
            f"{json.dumps(key, ensure_ascii=False)}:{encoded}"
            for key, encoded in entries
        )
        return "{" + body + "}"
    if isinstance(value, (list, tuple)):
        return (
            "["
            + ",".join(
                _encode(item, folding=folding, fold_fields=fold_fields, depth=depth + 1)
                for item in value
            )
            + "]"
        )
    raise CanonicalizationError(f"unsupported_type:{type(value).__name__}")


def normalize_fold_fields(fields: Iterable[str]) -> frozenset[str]:
    """Normalize configured field names the same way object keys are."""
    return frozenset(_nfkc(field) for field in fields if field)


def canonicalize_arguments(
    arguments: Any, *, casefold_fields: Iterable[str] = ()
) -> str:
    """Return the canonical text of ``arguments`` (deterministic, lossless-ish)."""
    return _encode(
        arguments,
        folding=False,
        fold_fields=normalize_fold_fields(casefold_fields),
        depth=0,
    )


def canonical_request_hash(
    tool_name: str, arguments: Any, *, casefold_fields: Iterable[str] = ()
) -> str:
    """SHA-256 over the tool name and canonical arguments, domain-separated."""
    canonical = canonicalize_arguments(arguments, casefold_fields=casefold_fields)
    digest = hashlib.sha256()
    digest.update(_HASH_DOMAIN)
    digest.update(_nfkc(tool_name).encode("utf-8"))
    digest.update(b"\x00")
    digest.update(canonical.encode("utf-8"))
    return digest.hexdigest()
