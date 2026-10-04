"""Ask Jev (TypeSafe System One) typed judgments about every module under app/.

Jev does not write prose reviews. It answers bounded questions with typed
values and probabilities, so this script owns the workflow: it chunks each
source file by top-level definition, asks the same independent questions of
every chunk in one request, persists the raw answers next to the chunk they
describe, and then ranks the chunks in code. Thresholds live in RANKING so a
re-rank never needs another model call.

Usage:
    python scripts/jev_codebase_review.py --dry-run          # no network
    TYPESAFE_API_KEY=... python scripts/jev_codebase_review.py

Outputs (under --out, default docs/research/jev-codebase-review-<date>/):
    answers.jsonl   one line per chunk: path, span, questions' raw answers, usage
    report.md       ranked findings plus uncertain chunks for a human pass
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import datetime as dt
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]

# Same patterns as app.policy.jev_guard.SECRET_PATTERNS, copied so this script
# needs only httpx and not the app's FastAPI import chain.
SECRET_PATTERNS = [
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    r"\b(sk|pk|rk)[-_](live|test|proj|ant)?[-_]?[A-Za-z0-9_-]{16,}",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}",
    r"\bgithub_pat_[A-Za-z0-9_]{20,}",
    r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bAIza[0-9A-Za-z_-]{30,}",
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*\S+",
    r"\b[A-Fa-f0-9]{32,}\b",
    r"\b[A-Za-z0-9+/]{40,}={0,2}",
]
_SECRETS = [re.compile(p) for p in SECRET_PATTERNS]


def strip_secrets(text: str) -> str:
    for pattern in _SECRETS:
        text = pattern.sub("[secret]", text)
    return text


DEFAULT_MODEL = os.environ.get("TYPESAFE_DEFAULT_MODEL", "jev-1.13.0")
BASE_URL = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/")
MAX_CHUNK_CHARS = 10_000  # app/policy/jev_guard.py caps state at 12_000
LOOP_STAGES = {
    "discover": "Lists or describes tools, capabilities, or endpoints an agent may call.",
    "authenticate": "Establishes who the caller is: API keys, wallets, sessions, signatures on requests.",
    "authorize": "Decides whether a caller may perform an action: permits, scopes, policy, delegation, budgets.",
    "invoke": "Dispatches an authorized action to a tool or upstream and tracks its outcome.",
    "meter": "Counts, prices, or debits usage against a wallet, budget, or ledger.",
    "receipt": "Signs or persists evidence that an action happened, or verifies such evidence.",
    "audit": "Records or exposes an append-only history of actions for later inspection.",
    "govern": "Lets an operator revoke, freeze, approve, or change policy over agents or tools.",
    "none_of_these": "Supports none of the stages above (configuration, demos, UI, marketing, unrelated features).",
}
QUESTIONS: dict[str, Any] = {
    "loop_stage": {
        "type": "choice",
        "instructions": (
            "Which stage of the loop discover -> authenticate -> authorize -> invoke -> meter -> "
            "receipt -> audit -> govern does `code` chiefly implement? Judge the code, not `path`."
        ),
        "criteria": LOOP_STAGES,
    },
    "security_critical": {
        "type": "noul",
        "instructions": (
            "Does `code` handle any of: authentication, authorization, tenant isolation, permits, "
            "delegations, receipts, billing or metering, audit logs, tool execution, secrets, or "
            "database migrations?"
        ),
    },
    "security_defect": {
        "type": "noul",
        "instructions": (
            "Does `code` contain a concrete defect an attacker could use: a missing or bypassable "
            "authorization check, a cross-tenant read or write, a replayable request, a path that "
            "could charge or debit twice, unsafe handling of tool arguments, or a secret written to "
            "logs or responses? Answer from what the code does, not from what comments claim."
        ),
        "criteria": {
            "true": "A specific line or branch in `code` has such a flaw.",
            "false": "No such flaw is visible in `code`; checks that must happen elsewhere do not count as flaws here.",
        },
    },
    "reality_level": {
        "type": "choice",
        "instructions": (
            "How real is the behavior `code` implements, compared with what its names and "
            "docstrings claim?"
        ),
        "criteria": {
            "verified": "The code performs the claimed behavior end to end with real persistence or I/O.",
            "partial": "Part of the claimed behavior is real; the rest is missing, hard-coded, or not wired.",
            "stubbed": "Functions return fixed values, raise NotImplementedError, or only log.",
            "demo_only": "Works only with sample data, in-memory state, or a flag that production refuses.",
            "misleading": "Names or docstrings claim something materially different from what the code does.",
        },
    },
    "outside_wedge": {
        "type": "noul",
        "instructions": (
            "Is `code` a product feature that does not support scoped, authorized, metered, "
            "receipted, auditable agent-to-tool actions, and could be frozen or deleted without "
            "weakening that loop? Shared infrastructure (config, logging, DB sessions, tests) is "
            "not a feature and does not count."
        ),
    },
    "maintainability": {
        "type": "score",
        "instructions": "How hard would `code` be for a new engineer to change safely?",
        "criteria": [
            "Short, single-purpose, obvious control flow.",
            "Readable but with some duplicated logic or long functions.",
            "Long functions, many branches, or implicit coupling to other modules through globals or ordering.",
            "Tangled: mixed responsibilities, hidden side effects, or state that several code paths mutate.",
        ],
    },
}
# Code-owned policy. Change these without re-running inference.
RANKING = {
    "defect_flag": 0.60,
    "critical_flag": 0.70,
    "uncertain_lo": 0.35,
    "uncertain_hi": 0.65,
    "outside_wedge_flag": 0.70,
    "low_confidence": 0.55,
}


@dataclass(frozen=True)
class Chunk:
    path: str
    start: int
    end: int
    names: tuple[str, ...]
    code: str


def chunk_file(path: Path) -> list[Chunk]:
    source = path.read_text(encoding="utf-8")
    rel = str(path.relative_to(ROOT))
    if len(source) <= MAX_CHUNK_CHARS:
        return [Chunk(rel, 1, source.count("\n") + 1, ("<module>",), source)]
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [
            Chunk(
                rel, 1, source.count("\n") + 1, ("<module>",), source[:MAX_CHUNK_CHARS]
            )
        ]
    lines = source.splitlines(keepends=True)
    chunks: list[Chunk] = []
    buf: list[str] = []
    names: list[str] = []
    start = 1
    prev_end = 0
    for node in tree.body:
        node_end = node.end_lineno or node.lineno
        text = "".join(
            lines[prev_end:node_end]
        )  # include gaps/comments before the node
        if buf and sum(map(len, buf)) + len(text) > MAX_CHUNK_CHARS:
            chunks.append(Chunk(rel, start, prev_end, tuple(names), "".join(buf)))
            buf, names, start = [], [], prev_end + 1
        buf.append(text[:MAX_CHUNK_CHARS])
        names.append(getattr(node, "name", type(node).__name__))
        prev_end = node_end
    if buf:
        chunks.append(Chunk(rel, start, prev_end, tuple(names), "".join(buf)))
    return chunks


def collect(paths: list[Path]) -> list[Chunk]:
    files = sorted(
        p for root in paths for p in root.rglob("*.py") if "__pycache__" not in p.parts
    )
    return [c for f in files for c in chunk_file(f)]


def payload(chunk: Chunk, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "state": {
            "path": chunk.path,
            "definitions": list(chunk.names),
            "code": strip_secrets(chunk.code),
        },
        "questions": QUESTIONS,
    }


async def ask(
    client: httpx.AsyncClient, chunk: Chunk, model: str, sem: asyncio.Semaphore
) -> dict[str, Any]:
    body = payload(chunk, model)
    async with sem:
        for attempt in range(3):
            resp = await client.post("/v1/systemone", json=body)
            if resp.status_code == 429 and attempt < 2:
                wait = float(resp.headers.get("retry-after-ms", 1000)) / 1000
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            break
    data = resp.json()
    return {
        **asdict(chunk),
        "code": None,
        "model": data.get("model"),
        "answers": data["answers"],
        "usage": data.get("usage"),
        "request_id": resp.headers.get("x-typesafe-request-id"),
    }


def rank(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {
        "defects": [],
        "uncertain": [],
        "outside_wedge": [],
        "not_real": [],
    }
    for r in rows:
        a = r["answers"]
        defect = a["security_defect"]["noul"]
        critical = a["security_critical"]["noul"]
        reality = a["reality_level"]
        if defect >= RANKING["defect_flag"]:
            out["defects"].append(r)
        elif (
            RANKING["uncertain_lo"] <= defect <= RANKING["uncertain_hi"]
            and critical >= RANKING["critical_flag"]
        ):
            out["uncertain"].append(r)
        if a["outside_wedge"]["noul"] >= RANKING["outside_wedge_flag"]:
            out["outside_wedge"].append(r)
        if (
            reality["choice"] in {"stubbed", "misleading", "demo_only"}
            and reality["confidence"] >= RANKING["low_confidence"]
        ):
            out["not_real"].append(r)
    out["defects"].sort(key=lambda r: -r["answers"]["security_defect"]["noul"])
    out["outside_wedge"].sort(key=lambda r: -r["answers"]["outside_wedge"]["noul"])
    return out


def report(
    rows: list[dict[str, Any]], buckets: dict[str, list[dict[str, Any]]], model: str
) -> str:
    def loc(r: dict[str, Any]) -> str:
        return f"`{r['path']}:{r['start']}-{r['end']}` ({', '.join(r['names'][:4])})"

    tokens = sum((r.get("usage") or {}).get("input_tokens", 0) for r in rows)
    stages: dict[str, int] = {}
    for r in rows:
        stages[r["answers"]["loop_stage"]["choice"]] = (
            stages.get(r["answers"]["loop_stage"]["choice"], 0) + 1
        )
    lines = [
        f"# Jev codebase review — {dt.date.today().isoformat()}",
        "",
        f"Model: `{model}`. Chunks judged: {len(rows)}. Input tokens: {tokens}.",
        "",
        "Jev returns typed probabilities, not explanations. Every row below is a *ranking signal* "
        "for a human reader; a flagged chunk is a place to look, not a confirmed finding, and an "
        "unflagged chunk is not a clean bill. Thresholds are in `RANKING` in the script.",
        "",
        "## Loop-stage coverage",
        "",
        "| stage | chunks |",
        "|---|---:|",
        *[f"| {k} | {v} |" for k, v in sorted(stages.items(), key=lambda kv: -kv[1])],
        "",
        f"## Possible security defects (P ≥ {RANKING['defect_flag']})",
        "",
        "| P(defect) | P(critical) | location |",
        "|---:|---:|---|",
        *[
            f"| {r['answers']['security_defect']['noul']:.2f} | {r['answers']['security_critical']['noul']:.2f} | {loc(r)} |"
            for r in buckets["defects"]
        ],
        "",
        "## Security-critical and uncertain (needs a human pass)",
        "",
        *[
            f"- {loc(r)} — P(defect)={r['answers']['security_defect']['noul']:.2f}"
            for r in buckets["uncertain"]
        ],
        "",
        f"## Outside the wedge (P ≥ {RANKING['outside_wedge_flag']}) — freeze/delete candidates",
        "",
        *[
            f"- {loc(r)} — P={r['answers']['outside_wedge']['noul']:.2f}"
            for r in buckets["outside_wedge"]
        ],
        "",
        "## Stubbed, demo-only, or misleading",
        "",
        *[
            f"- {loc(r)} — {r['answers']['reality_level']['choice']} (conf {r['answers']['reality_level']['confidence']:.2f})"
            for r in buckets["not_real"]
        ],
        "",
    ]
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "paths", nargs="*", default=["app"], help="directories to review (default: app)"
    )
    ap.add_argument("--out", default=None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument(
        "--dry-run", action="store_true", help="chunk and size only; send nothing"
    )
    args = ap.parse_args()

    chunks = collect([ROOT / p for p in args.paths])
    files = len({c.path for c in chunks})
    chars = sum(len(c.code) for c in chunks)
    print(
        f"{files} files -> {len(chunks)} chunks, {chars:,} chars (~{chars // 4:,} input tokens est.)"
    )
    if args.dry_run:
        biggest = max(chunks, key=lambda c: len(c.code))
        print(
            f"largest chunk: {biggest.path}:{biggest.start}-{biggest.end} {len(biggest.code):,} chars"
        )
        print(json.dumps(payload(chunks[0], args.model), indent=1)[:1500])
        return 0

    key = os.environ.get("TYPESAFE_API_KEY", "")
    if not key:
        print("TYPESAFE_API_KEY is not set", file=sys.stderr)
        return 2
    out = Path(
        args.out
        or ROOT
        / "docs"
        / "research"
        / f"jev-codebase-review-{dt.date.today().isoformat()}"
    )
    out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers={"Authorization": f"Bearer {key}"}, timeout=30.0
    ) as client:
        rows = await asyncio.gather(*(ask(client, c, args.model, sem) for c in chunks))
    with (out / "answers.jsonl").open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    (out / "report.md").write_text(report(rows, rank(rows), args.model))
    print(f"wrote {out / 'answers.jsonl'} and {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
