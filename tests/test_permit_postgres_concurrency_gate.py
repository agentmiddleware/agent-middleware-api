"""Fail-loudly gate for the PostgreSQL row-lock concurrency proofs.

``tests/test_permit_postgres_concurrency.py`` skips by default (SQLite has no
``SELECT ... FOR UPDATE`` semantics), but CI sets
``REQUIRE_POSTGRES_CONCURRENCY_TESTS=1`` so a missing database or a missing
opt-in flag fails instead of silently skipping. These tests pin that
behavior; they need no database themselves.
"""

from __future__ import annotations

import pytest

from tests.test_permit_postgres_concurrency import _require_opted_in_postgres


def test_concurrency_gate_skips_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RUN_POSTGRES_CONCURRENCY_TESTS", raising=False)
    monkeypatch.delenv("REQUIRE_POSTGRES_CONCURRENCY_TESTS", raising=False)
    with pytest.raises(pytest.skip.Exception):
        _require_opted_in_postgres()


def test_concurrency_gate_fails_loudly_when_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Note: pytest.raises cannot be used here because it re-raises a
    # Skipped outcome instead of reporting a mismatch, which would turn
    # the old silent-skip behavior into a pass-by-skip of this test.
    monkeypatch.delenv("RUN_POSTGRES_CONCURRENCY_TESTS", raising=False)
    monkeypatch.setenv("REQUIRE_POSTGRES_CONCURRENCY_TESTS", "1")
    try:
        _require_opted_in_postgres()
    except pytest.fail.Exception:
        return
    except pytest.skip.Exception:
        pytest.fail(
            "gate silently skipped under "
            "REQUIRE_POSTGRES_CONCURRENCY_TESTS=1; expected a loud failure"
        )
    pytest.fail("gate returned without skipping or failing")
