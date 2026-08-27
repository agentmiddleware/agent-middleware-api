"""Regression tests for fail-closed invariant-attack verdict semantics."""

from __future__ import annotations

import ast
import io
import sys
import threading
from collections import Counter
from pathlib import Path

import pytest


ATTACK_DIR = Path(__file__).resolve().parents[1] / "scripts" / "invariant_attacks"
sys.path.insert(0, str(ATTACK_DIR))

from attacklib import verdict_exit_code  # noqa: E402

import attack4_forgery as attack4  # noqa: E402
import attack5_crash_sqlite as attack5  # noqa: E402
import attack6_key_misuse as attack6  # noqa: E402
import attack_combined as combined  # noqa: E402
import redact_evidence as redactor  # noqa: E402


def _nodes_without_nested_scopes(node: ast.AST) -> list[ast.AST]:
    nodes = [node]
    if isinstance(
        node,
        (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef),
    ):
        return nodes
    for child in ast.iter_child_nodes(node):
        nodes.extend(_nodes_without_nested_scopes(child))
    return nodes


def _is_namespaced_call(node: ast.AST | None, namespace: str, function: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == namespace
        and node.func.attr == function
    )


def _printed_evidence(statement: ast.stmt) -> ast.AST | None:
    if not (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id == "print"
        and len(statement.value.args) == 1
        and not statement.value.keywords
    ):
        return None
    serialized = statement.value.args[0]
    if not (_is_namespaced_call(serialized, "json", "dumps") and serialized.args):
        return None
    return serialized.args[0]


def _written_evidence(statement: ast.stmt) -> ast.AST | None:
    if not isinstance(statement, ast.With):
        return None

    matches: list[ast.AST] = []
    for item in statement.items:
        opened = item.context_expr
        if not (
            isinstance(opened, ast.Call)
            and isinstance(opened.func, ast.Name)
            and opened.func.id == "open"
            and opened.args
            and isinstance(item.optional_vars, ast.Name)
        ):
            continue
        mode = (
            opened.args[1]
            if len(opened.args) > 1
            else next(
                (keyword.value for keyword in opened.keywords if keyword.arg == "mode"),
                None,
            )
        )
        if not (isinstance(mode, ast.Constant) and mode.value == "w"):
            continue

        for body_statement in statement.body:
            if not (
                isinstance(body_statement, ast.Expr)
                and _is_namespaced_call(body_statement.value, "json", "dump")
            ):
                continue
            dumped = body_statement.value
            if not (
                len(dumped.args) >= 2
                and isinstance(dumped.args[1], ast.Name)
                and dumped.args[1].id == item.optional_vars.id
            ):
                continue
            matches.append(dumped.args[0])

    return matches[0] if len(matches) == 1 else None


def _is_main_guard(test: ast.AST) -> bool:
    if not (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
    ):
        return False
    operands = (test.left, test.comparators[0])
    return (
        isinstance(operands[0], ast.Name)
        and operands[0].id == "__name__"
        and isinstance(operands[1], ast.Constant)
        and operands[1].value == "__main__"
    ) or (
        isinstance(operands[1], ast.Name)
        and operands[1].id == "__name__"
        and isinstance(operands[0], ast.Constant)
        and operands[0].value == "__main__"
    )


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        ("HELD", 0),
        ("BROKE", 1),
        ("PARTIAL", 1),
        ("UNKNOWN", 1),
        ("held", 1),
        ("", 1),
        (None, 1),
    ],
)
def test_verdict_exit_code_fails_closed(verdict: str | None, expected: int) -> None:
    assert verdict_exit_code(verdict) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "script_name",
    [
        "attack1_double_charge.py",
        "attack2_budget.py",
        "attack3_scope.py",
        "attack4_forgery.py",
    ],
)
def test_attack_main_returns_shared_verdict_exit_code(script_name: str) -> None:
    tree = ast.parse((ATTACK_DIR / script_name).read_text(encoding="utf-8"))
    main_candidates = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "main"
    ]
    assert len(main_candidates) == 1
    main = main_candidates[0]
    assert isinstance(main, ast.FunctionDef)

    final_statement = main.body[-1]
    assert isinstance(final_statement, ast.Return)
    assert ast.dump(final_statement.value) == ast.dump(
        ast.Call(
            func=ast.Attribute(
                value=ast.Name(id="A", ctx=ast.Load()),
                attr="verdict_exit_code",
                ctx=ast.Load(),
            ),
            args=[ast.Name(id="verdict", ctx=ast.Load())],
            keywords=[],
        )
    )

    main_scope = [
        node
        for statement in main.body
        for node in _nodes_without_nested_scopes(statement)
    ]
    assert [node for node in main_scope if isinstance(node, ast.Return)] == [
        final_statement
    ]
    assert not any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in main_scope)
    assert not any(_is_namespaced_call(node, "sys", "exit") for node in main_scope)

    printed = [
        (index, payload)
        for index, statement in enumerate(main.body[:-1])
        if (payload := _printed_evidence(statement)) is not None
    ]
    written = [
        (index, payload)
        for index, statement in enumerate(main.body[:-1])
        if (payload := _written_evidence(statement)) is not None
    ]
    assert len(printed) == 1
    print_index, printed_payload = printed[0]
    matching_writes = [
        (index, payload)
        for index, payload in written
        if ast.dump(payload) == ast.dump(printed_payload)
    ]
    assert len(matching_writes) == 1
    write_index, _written_payload = matching_writes[0]
    assert print_index < write_index < len(main.body) - 1

    guards = [
        (index, node)
        for index, node in enumerate(tree.body)
        if isinstance(node, ast.If) and _is_main_guard(node.test)
    ]
    assert len(guards) == 1
    guard_index, guard = guards[0]
    assert guard_index == len(tree.body) - 1
    assert guard_index > tree.body.index(main)
    assert guard.orelse == []
    assert len(guard.body) == 1
    assert ast.dump(guard.body[0]) == ast.dump(
        ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="sys", ctx=ast.Load()),
                    attr="exit",
                    ctx=ast.Load(),
                ),
                args=[
                    ast.Call(
                        func=ast.Name(id="main", ctx=ast.Load()),
                        args=[],
                        keywords=[],
                    )
                ],
                keywords=[],
            )
        )
    )


def test_combined_requires_every_storm_variant_to_start() -> None:
    started = Counter({tag: 1 for tag in combined.REQUIRED_STORM_VECTOR_TAGS})

    assert combined.all_required_storm_vectors_started(started)


@pytest.mark.parametrize("missing", combined.REQUIRED_STORM_VECTOR_TAGS)
def test_combined_fails_closed_when_storm_variant_did_not_start(missing: str) -> None:
    started = Counter({tag: 1 for tag in combined.REQUIRED_STORM_VECTOR_TAGS})
    del started[missing]

    assert not combined.all_required_storm_vectors_started(started)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {
                "crash_happened": True,
                "no_double_by_total": True,
                "no_double_by_key": True,
                "no_receipt_without_charge": True,
                "silent_orphan_count": 0,
                "proof_pending_count": 0,
                "worker_error_count": 0,
            },
            "HELD",
        ),
        (
            {
                "crash_happened": True,
                "no_double_by_total": True,
                "no_double_by_key": True,
                "no_receipt_without_charge": True,
                "silent_orphan_count": 0,
                "proof_pending_count": 1,
                "worker_error_count": 0,
            },
            "PARTIAL",
        ),
        (
            {
                "crash_happened": True,
                "no_double_by_total": True,
                "no_double_by_key": True,
                "no_receipt_without_charge": True,
                "silent_orphan_count": 1,
                "proof_pending_count": 0,
                "worker_error_count": 0,
            },
            "BROKE",
        ),
        (
            {
                "crash_happened": False,
                "no_double_by_total": True,
                "no_double_by_key": True,
                "no_receipt_without_charge": True,
                "silent_orphan_count": 0,
                "proof_pending_count": 0,
                "worker_error_count": 0,
            },
            "BROKE",
        ),
    ],
)
def test_attack5_verdict_distinguishes_pending_from_corruption(
    kwargs: dict, expected: str
) -> None:
    assert attack5.classify_verdict(**kwargs) == expected


@pytest.mark.parametrize(
    ("refund", "expected_correlated", "expected_orphan"),
    [
        (
            {
                "entry_id": "refund-ledger-1",
                "amount": 2,
                "correlation_id": "ledger-1",
            },
            1,
            0,
        ),
        (None, 0, 1),
        (
            {
                "entry_id": "refund-wrong-ledger",
                "amount": 2,
                "correlation_id": "ledger-1",
            },
            0,
            1,
        ),
        (
            {
                "entry_id": "refund-ledger-1",
                "amount": 3,
                "correlation_id": "ledger-1",
            },
            0,
            1,
        ),
    ],
)
def test_attack5_refunds_must_correlate_to_the_exact_debit(
    monkeypatch, refund, expected_correlated: int, expected_orphan: int
) -> None:
    def fake_db_rows(query: str, params=()):
        if "action='debit'" in query:
            return [{"entry_id": "ledger-1", "amount": -2, "operation_key": "idem-1"}]
        if "action='refund'" in query:
            return [refund] if refund else []
        return []

    monkeypatch.setattr(attack5.A, "db_rows", fake_db_rows)

    analysis = attack5.ledger_analysis("agt-test", {"idem-1"})

    assert analysis["correlated_refunded_debits"] == expected_correlated
    assert analysis["silent_orphan_debits"] == expected_orphan


def test_attack5_worker_failure_prevents_held_verdict() -> None:
    launch_hist = Counter()
    worker_errors = Counter()

    def fail_request():
        raise RuntimeError("injected worker failure")

    attack5.run_worker_request(
        "idem-failed",
        fail_request,
        launch_hist,
        worker_errors,
        threading.Lock(),
    )

    assert worker_errors == {"idem-failed": 1}
    assert (
        attack5.classify_verdict(
            crash_happened=True,
            no_double_by_total=True,
            no_double_by_key=True,
            no_receipt_without_charge=True,
            silent_orphan_count=0,
            proof_pending_count=0,
            worker_error_count=sum(worker_errors.values()),
        )
        == "BROKE"
    )


def test_combined_treats_linux_zombie_as_stopped(monkeypatch) -> None:
    monkeypatch.setattr(
        combined,
        "open",
        lambda *_args, **_kwargs: io.StringIO("4321 (python worker) Z 1 2 3"),
        raising=False,
    )

    def unexpected_signal_probe(_pid, _signal):
        raise AssertionError("zombie must be classified before the signal probe")

    monkeypatch.setattr(combined.os, "kill", unexpected_signal_probe)

    assert not combined.alive(4321)


def test_combined_proc_stat_parser_handles_comm_parenthesis_and_malformed_input() -> (
    None
):
    assert combined.proc_stat_state("4321 (python) worker) Z 1 2 3") == "Z"
    assert combined.proc_stat_state("malformed proc stat without delimiter") is None


def test_attack6_requires_exact_status_and_reason() -> None:
    expected = {"status": 403, "json": {"detail": {"error": "invalid_api_key"}}}

    assert attack6.matches_response(expected, status=403, reason="invalid_api_key")
    assert not attack6.matches_response(
        {**expected, "status": None}, status=403, reason="invalid_api_key"
    )
    assert not attack6.matches_response(
        {**expected, "status": 500}, status=403, reason="invalid_api_key"
    )
    assert not attack6.matches_response(
        expected, status=403, reason="missing_credentials"
    )
    assert attack6.matches_response({"status": 204}, status=204)


def test_forgery_cases_include_ledger_binding_and_fail_closed_if_missing() -> None:
    bundle = {
        "receipt": {
            "wallet_id": "agt-victim",
        },
        "signing_input": '{"ledger_entry_id":"ledger-original"}',
    }

    tampers = attack4.A.signed_receipt_tamper_cases(bundle)

    assert tampers["ledger_entry_id"] == (
        "ledger-original",
        "ledger-forged-entry",
    )
    missing = attack4.A.signed_receipt_tamper_cases({"receipt": {}})
    assert missing["ledger_entry_id"][0] == "<missing-ledger-entry-id>"


def test_evidence_redaction_removes_credentials_and_wallets() -> None:
    credential = "b2a_" + "A" * 32
    evidence = {
        "victim_wallet": "agt-secret-tenant",
        "nested": {
            "api_key": credential,
            "message": f"leaked {credential} for agt-deadbeef1234",
        },
        "receipt_id": "rcpt-public-proof-reference",
    }

    redacted = redactor.redact_evidence(evidence)

    assert redacted["victim_wallet"] == "<redacted>"
    assert redacted["nested"]["api_key"] == "<redacted>"
    assert redacted["nested"]["message"] == (
        "leaked <redacted-credential> for <redacted-wallet>"
    )
    assert redacted["receipt_id"] == "rcpt-public-proof-reference"
    assert not redactor.contains_full_credential(redacted)
    assert not redactor.contains_wallet_identifier(redacted)
