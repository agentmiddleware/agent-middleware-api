"""Guard against reintroducing the dead production scope helper.

Audit finding (low): ``app/core/scopes.py`` shipped a ``require_scope``
permission decorator with zero production callers. A helper nobody calls is
a trap for the first future caller: its wallet and permission semantics were
never reconciled with the real authorization paths (API-key callers bypassed
scope checks entirely while JWT callers were scope-checked, and the scope
names it accepted had no parity with the names the token endpoint mints).

The fix deleted the production helper. The JWT scope behaviors themselves
are still covered, through an explicitly test-only guard in
``tests/support/scope_guard.py`` that no production module may import.

These tests fail if the dead helper (or any production reference to it)
comes back.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DELETED_MODULE = REPO_ROOT / "app" / "core" / "scopes.py"


def test_dead_scope_helper_module_is_gone():
    assert not DELETED_MODULE.exists(), (
        "app/core/scopes.py is back: the dead require_scope helper must stay "
        "deleted until a reconciled design lands. See tests/support/scope_guard.py."
    )


def test_no_production_reference_to_require_scope():
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "app").rglob("*.py")
        if "require_scope" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"production code references require_scope again: {offenders}. "
        "The test-only guard lives in tests/support/scope_guard.py."
    )
