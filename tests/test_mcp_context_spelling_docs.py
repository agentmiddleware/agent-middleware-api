"""Docs must show the canonical call-context spelling, ``mcpContext``.

Every route accepts ``mcpContext`` and the ``mcp_context`` alias
(``tests/test_mcp_idempotency_key_validation.py``), but examples teach one
spelling so copied calls match the OpenAPI schema. Every fenced example is
checked here.
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


def test_doc_examples_use_canonical_context_spelling():
    offenders = []
    for path in _doc_files():
        for block in _code_blocks(path.read_text(encoding="utf-8")):
            rel = path.relative_to(ROOT).as_posix()
            if re.search(r'mcp_context\\?"', block):
                offenders.append(f"{rel}: example uses mcp_context, not mcpContext")
    assert not offenders, "\n".join(offenders)


def test_served_llms_txt_names_the_jsonrpc_context_field():
    text = (ROOT / "static" / "llm.txt").read_text(encoding="utf-8")
    assert '"mcpContext"' in text
