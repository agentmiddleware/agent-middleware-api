"""Coverage for the offline parts of scripts/jev_codebase_review.py.

The script ships source code to an external model API, so strip_secrets is
a security boundary: anything it misses leaves the repo in a third-party
request body. chunk_file and rank are the review-quality boundary: dropped
code or misbucketed findings silently weaken the report.
"""

import asyncio
import sys

from scripts import jev_codebase_review as jev


def test_strip_secrets_redacts_private_key_block():
    text = "key:\n-----BEGIN PRIVATE KEY-----\nABCDEF\n-----END PRIVATE KEY-----\n"
    stripped = jev.strip_secrets(text)
    assert "ABCDEF" not in stripped
    assert "[secret]" in stripped


def test_strip_secrets_redacts_token_assignments():
    stripped = jev.strip_secrets("api_key = hunter2value\n")
    assert "hunter2value" not in stripped


def test_strip_secrets_redacts_github_pat():
    stripped = jev.strip_secrets("token github_pat_abcdefghij1234567890 rest")
    assert "github_pat_" not in stripped


def test_strip_secrets_leaves_plain_code_alone():
    code = "def search_markets(query: str) -> list:\n    return []\n"
    assert jev.strip_secrets(code) == code


def test_payload_never_carries_raw_secrets():
    chunk = jev.Chunk("app/x.py", 1, 2, ("f",), "api_key = hunter2value\n")
    body = jev.payload(chunk, "jev-test")
    assert "hunter2value" not in body["state"]["code"]
    assert body["model"] == "jev-test"


def test_chunk_file_small_module_is_single_chunk(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ROOT", tmp_path)
    target = tmp_path / "tiny.py"
    target.write_text("X = 1\n", encoding="utf-8")
    chunks = jev.chunk_file(target)
    assert len(chunks) == 1
    assert chunks[0].names == ("<module>",)
    assert chunks[0].path == "tiny.py"


def test_chunk_file_syntax_error_returns_truncated_module(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ROOT", tmp_path)
    target = tmp_path / "broken.py"
    target.write_text(
        "def broken(:\n" + "x" * (jev.MAX_CHUNK_CHARS + 100), encoding="utf-8"
    )
    chunks = jev.chunk_file(target)
    assert len(chunks) == 1
    assert len(chunks[0].code) <= jev.MAX_CHUNK_CHARS


def test_choice_confidence_prefers_explicit_confidence():
    answer = {"confidence": 0.42, "probabilities": {"a": 0.9}}
    assert jev.choice_confidence(answer) == 0.42


def test_choice_confidence_falls_back_to_top_probability():
    answer = {"probabilities": {"a": 0.3, "b": 0.8}}
    assert jev.choice_confidence(answer) == 0.8


def test_choice_confidence_defaults_to_zero():
    assert jev.choice_confidence({}) == 0.0


def _row(defect, critical=0.9, outside=0.0, reality="verified", conf=0.9):
    return {
        "path": "app/x.py",
        "start": 1,
        "end": 2,
        "names": ["f"],
        "answers": {
            "security_defect": {"noul": defect},
            "security_critical": {"noul": critical},
            "outside_wedge": {"noul": outside},
            "loop_stage": {"choice": "authorize"},
            "reality_level": {"choice": reality, "confidence": conf},
        },
    }


def test_rank_flags_high_defect_probability():
    buckets = jev.rank([_row(0.9)])
    assert len(buckets["defects"]) == 1
    assert buckets["uncertain"] == []


def test_rank_holds_critical_uncertain_for_human_pass():
    buckets = jev.rank([_row(0.5, critical=0.8)])
    assert buckets["defects"] == []
    assert len(buckets["uncertain"]) == 1


def test_rank_flags_demo_only_reality():
    buckets = jev.rank([_row(0.1, reality="demo_only", conf=0.9)])
    assert len(buckets["not_real"]) == 1


def test_rank_sorts_defects_by_probability_descending():
    buckets = jev.rank([_row(0.7), _row(0.95)])
    probs = [r["answers"]["security_defect"]["noul"] for r in buckets["defects"]]
    assert probs == [0.95, 0.7]


def test_dry_run_with_no_chunks_exits_nonzero_instead_of_crashing(
    tmp_path, monkeypatch, capsys
):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(
        sys, "argv", ["jev_codebase_review.py", "--dry-run", str(empty)]
    )
    rc = asyncio.run(jev.main())
    assert rc == 2
    assert "no python" in capsys.readouterr().err.lower()


def test_report_counts_loop_stages():
    rows = [_row(0.9), _row(0.1)]
    text = jev.report(rows, jev.rank(rows), "jev-test")
    assert "authorize" in text
    assert "jev-test" in text
