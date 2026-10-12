"""Docs must spell the call context the way each route accepts it.

JSON-RPC ``tools/call`` takes ``params.mcpContext`` and refuses ``mcp_context``;
the deprecated REST invoke takes ``mcp_context`` and refuses ``mcpContext``
(``tests/test_mcp_idempotency_key_validation.py``). An outside tester copied
the wrong spelling from the docs, so every fenced example is checked here.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Dated QA artifacts and implementation plans are historical records.
EXCLUDED = ("docs/qa/", "docs/superpowers/")
FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def _doc_files() -> list[Path]:
    files = [*ROOT.glob("*.md"), *ROOT.glob("docs/**/*.md")]
    files += [*ROOT.glob("static/*.txt"), *ROOT.glob("site/*.txt")]
    return [
        path
        for path in files
        if not any(path.relative_to(ROOT).as_posix().startswith(p) for p in EXCLUDED)
    ]


def _code_blocks(text: str) -> list[str]:
    # A file with no fences (plain-text discovery docs) is checked whole.
    return FENCE.findall(text) or [text]


def test_doc_examples_use_route_specific_context_spelling():
    offenders = []
    for path in _doc_files():
        for block in _code_blocks(path.read_text(encoding="utf-8")):
            rel = path.relative_to(ROOT).as_posix()
            is_jsonrpc = "tools/call" in block
            is_rest = "/invoke" in block and not is_jsonrpc
            if is_jsonrpc and re.search(r'mcp_context\\?"', block):
                offenders.append(f"{rel}: JSON-RPC example uses mcp_context")
            if is_rest and re.search(r'mcpContext\\?"', block):
                offenders.append(f"{rel}: REST invoke example uses mcpContext")
    assert not offenders, "\n".join(offenders)


def test_served_llms_txt_names_the_jsonrpc_context_field():
    text = (ROOT / "static" / "llm.txt").read_text(encoding="utf-8")
    assert '"mcpContext"' in text
