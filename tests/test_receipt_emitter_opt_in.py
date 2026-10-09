"""The queued receipt emitter must stay opt-in.

``BatchingReceiptEmitter`` (app/trust/receipts.py) holds receipts in memory
between ``enqueue`` and the background flush, so a crash in that window loses
the receipt. Governed invoke paths need receipt-before-response durability and
call ``ReceiptService.create_receipt`` directly instead. These guards enforce
the audit outcome: the emitter stays importable only from its definition
module, the ``app.trust`` facade does not re-export it, and no production
code adopts it.

The checks are static (AST over source) so they run without a database or a
running server, following tests/test_trust_boundary.py.
"""

from __future__ import annotations

import ast
from pathlib import Path

EMITTER_NAME = "BatchingReceiptEmitter"

ROOT = Path(__file__).resolve().parents[1]
DEFINITION_FILE = ROOT / "app" / "trust" / "receipts.py"
FACADE_FILE = ROOT / "app" / "trust" / "__init__.py"

# Shipped production code where adopting the queued emitter would put a
# governed receipt behind a crash window. Tests and examples are excluded:
# tests already exercise the emitter directly, and examples are illustrative.
PRODUCTION_ROOTS = ("app", "framework_integrations", "awi_sdk", "b2a_sdk", "wrappers")

SKIP_DIR_NAMES = {".venv", ".venv-local", "__pycache__", "node_modules"}


def _emitter_references(tree: ast.AST) -> list[str]:
    """Return human-readable hits for real code references to the emitter.

    Covers imports at any scope (module level, function bodies, conditional
    blocks) and attribute access such as ``receipts.BatchingReceiptEmitter``.
    Comments and docstrings are not code and are ignored.
    """
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == EMITTER_NAME or alias.asname == EMITTER_NAME:
                    hits.append(f"line {node.lineno}: imports {EMITTER_NAME}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname == EMITTER_NAME:
                    hits.append(f"line {node.lineno}: imports {EMITTER_NAME}")
        elif isinstance(node, ast.Name):
            if node.id == EMITTER_NAME:
                hits.append(f"line {node.lineno}: uses {EMITTER_NAME}")
        elif isinstance(node, ast.Attribute):
            if node.attr == EMITTER_NAME:
                hits.append(f"line {node.lineno}: uses {EMITTER_NAME}")
    return hits


def _string_literals(tree: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _production_files() -> list[Path]:
    files: list[Path] = []
    for root_name in PRODUCTION_ROOTS:
        root = ROOT / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if path == DEFINITION_FILE:
                continue
            if any(
                part in SKIP_DIR_NAMES or part.startswith(".") for part in path.parts
            ):
                continue
            files.append(path)
    return files


def test_detector_flags_direct_import_and_use() -> None:
    source = (
        "from app.trust.receipts import BatchingReceiptEmitter\n"
        "\n"
        "def make(service):\n"
        "    return BatchingReceiptEmitter(service)\n"
    )
    assert _emitter_references(ast.parse(source))


def test_detector_flags_lazy_import_inside_function() -> None:
    source = (
        "def make(service):\n"
        "    from app.trust.receipts import BatchingReceiptEmitter\n"
        "    return BatchingReceiptEmitter(service)\n"
    )
    assert _emitter_references(ast.parse(source))


def test_detector_flags_attribute_access() -> None:
    source = (
        "from app.trust import receipts\n"
        "\n"
        "def make(service):\n"
        "    return receipts.BatchingReceiptEmitter(service)\n"
    )
    assert _emitter_references(ast.parse(source))


def test_detector_ignores_direct_receipt_writes() -> None:
    source = (
        "from app.services.receipts import get_receipt_service\n"
        "\n"
        "async def write(**kwargs):\n"
        "    return await get_receipt_service().create_receipt(**kwargs)\n"
    )
    assert _emitter_references(ast.parse(source)) == []


def test_detector_ignores_mentions_in_comments_and_docstrings() -> None:
    source = (
        '"""Uses BatchingReceiptEmitter nowhere; create_receipt instead."""\n'
        "# BatchingReceiptEmitter is opt-in only\n"
        "VALUE = 1\n"
    )
    assert _emitter_references(ast.parse(source)) == []


def test_facade_does_not_reexport_emitter() -> None:
    tree = ast.parse(FACADE_FILE.read_text())
    assert _emitter_references(tree) == [], (
        f"{FACADE_FILE} must not re-export {EMITTER_NAME}: "
        "the queued emitter is opt-in only"
    )
    assert EMITTER_NAME not in _string_literals(tree), (
        f"{FACADE_FILE} must not list {EMITTER_NAME} in __all__"
    )


def test_no_production_code_references_emitter() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _production_files():
        hits = _emitter_references(ast.parse(path.read_text()))
        if hits:
            offenders[str(path.relative_to(ROOT))] = hits
    assert not offenders, (
        f"Govern paths must write receipts with ReceiptService.create_receipt, "
        f"never the queued {EMITTER_NAME} (crash between enqueue and flush "
        f"loses the receipt). Offenders: {offenders}"
    )
