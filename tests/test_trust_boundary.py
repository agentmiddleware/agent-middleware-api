"""Architectural guards for the trust-plane boundary.

Two invariants keep the product core honest:

1. The trust package must depend only inward — on shared infrastructure and the
   spine service modules — never on protocol routers or example workloads. If
   the core grew a dependency on, say, the oracle or AWI, it would no longer be
   a self-contained product.
2. The core trust routers must consume the spine through the `app.trust` facade,
   not by importing the underlying services directly — otherwise the facade is
   decorative.

These are enforced by static import analysis so they fail fast on regression.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRUST_DIR = ROOT / "app" / "trust"

# Infrastructure the spine may depend on.
ALLOWED_PACKAGE_PREFIXES = (
    "app.core",
    "app.db",
    "app.schemas",
    "app.policy",
    "app.trust",
)

# The spine service modules the facade is allowed to wrap.
SPINE_SERVICE_MODULES = {
    "app.services.agent_money",
    "app.services.audit_chain",
    "app.services.audit_log",
    "app.services.governance",
    "app.services.idempotency",
    "app.services.permits",
    "app.services.policies",
    "app.services.receipts",
    "app.services.signing_keys",
}

# Core trust routers that must reach the spine through the facade.
CORE_TRUST_ROUTERS = (
    "app/routers/mcp.py",
    "app/routers/permits.py",
    "app/routers/receipts.py",
    "app/routers/evidence.py",
    "app/routers/audit.py",
    "app/routers/me.py",
    "app/routers/keys.py",
)


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    return ".".join(rel.parts)


def _resolve(module_name: str, node: ast.ImportFrom) -> str | None:
    """Resolve an ImportFrom (absolute or relative) to an absolute module path."""
    if node.level == 0:
        return node.module
    # Relative: the anchor is the importing module's containing package.
    containing = module_name.split(".")[:-1]
    ascend = node.level - 1
    base = containing[: len(containing) - ascend] if ascend else containing
    parts = list(base)
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _module_level_imports(path: Path) -> list[str]:
    """Return absolute `app.*` module targets imported at module scope only.

    Relative imports are resolved to absolute form so the guard is independent
    of import style. Imports inside function bodies are intentionally ignored
    (the adapter reaches the MCP router lazily at call time, by design).
    """
    module_name = _module_name(path)
    tree = ast.parse(path.read_text())
    targets: list[str] = []
    for node in tree.body:  # module scope only — function-body imports excluded
        if isinstance(node, ast.ImportFrom):
            resolved = _resolve(module_name, node)
            if resolved and resolved.startswith("app"):
                targets.append(resolved)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app"):
                    targets.append(alias.name)
    return targets


def test_trust_package_only_depends_inward():
    violations: list[str] = []
    for path in sorted(TRUST_DIR.glob("*.py")):
        for module in _module_level_imports(path):
            allowed = module.startswith(ALLOWED_PACKAGE_PREFIXES) or (
                module in SPINE_SERVICE_MODULES
            )
            if not allowed:
                violations.append(f"{path.name} -> {module}")
    assert not violations, (
        f"app/trust must not depend on routers or non-spine workloads: {violations}"
    )


def test_core_trust_routers_use_the_facade():
    violations: list[str] = []
    for rel in CORE_TRUST_ROUTERS:
        path = ROOT / rel
        for module in _module_level_imports(path):
            if module in SPINE_SERVICE_MODULES:
                violations.append(f"{rel} -> {module}")
    assert not violations, (
        "core trust routers must import spine primitives via app.trust, "
        f"not directly: {violations}"
    )
