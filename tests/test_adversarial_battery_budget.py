"""Live-battery budget check against stubbed HTTP, no deployment needed.

``scripts/adversarial_battery.run_budget_check`` mints a one-call permit and
must PASS only when the over-cap retry is budget-denied with no new debit.
Each case stubs ``battery.req`` and asserts the recorded verdict, so a
regression that weakens the denial or the ledger comparison fails here.
"""

from __future__ import annotations

import pytest

from scripts import adversarial_battery as battery


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setattr(battery, "RESULTS", [])
    monkeypatch.setattr(battery, "BOOTSTRAP_KEY", "bootstrap-for-tests")
    return {
        "wallet_id": "wallet-a",
        "key1": {"api_key": "agent-key-1", "key_id": "key-id-1"},
        "key2": {"api_key": "agent-key-2", "key_id": "key-id-2"},
    }


def stub_transport(monkeypatch, *, cost=True, invokes="deny", ledger="readable"):
    """Stub battery.req with a canned deployment.

    cost: include a creditsPerCall annotation when True.
    invokes: "deny" (second call budget-denied), "allow" (second call
        succeeds), or "seed-fails" (first call fails).
    ledger: "readable", "unreadable", or "extra-debit".
    """
    state = {"invokes": 0, "debits": 1, "ledger_reads": 0}

    def fake_req(method, path, key=None, body=None, extra_headers=None):
        if path == "/mcp/tools.json":
            annotations = {"creditsPerCall": 2.0} if cost else {}
            return 200, {
                "tools": [
                    {"name": "golden-path-echo", "annotations": annotations},
                    {"name": "other-tool", "annotations": {}},
                ]
            }
        if method == "POST" and path == "/v1/permits":
            assert body["max_credits"] == "2.0", body
            return 201, {"permit_id": "permit-budget-1"}
        if path == "/mcp/messages":
            state["invokes"] += 1
            if invokes == "seed-fails":
                return 200, {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"message": "permit_not_found"},
                }
            if invokes == "allow" and state["invokes"] >= 2:
                state["debits"] += 1
                return 200, {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "receipt": {"receipt_id": f"rcpt-{state['invokes']}"},
                    },
                }
            if state["invokes"] == 1:
                return 200, {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"receipt": {"receipt_id": "rcpt-first"}},
                }
            return 200, {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"message": "permit_budget_exceeded"},
            }
        if path == "/v1/billing/ledger/wallet-a":
            if ledger == "unreadable":
                return 403, {"detail": "denied"}
            state["ledger_reads"] += 1
            # In extra-debit mode the denied call lands a second debit, so
            # only reads after the denial see the higher count.
            count = state["debits"]
            if ledger == "extra-debit" and state["ledger_reads"] > 1:
                count += 1
            return 200, {
                "entries": [{"action": "debit"} for _ in range(count)]
                + [{"action": "note"}],
            }
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(battery, "req", fake_req)
    return state


def verdict():
    matches = [r for r in battery.RESULTS if r[0] == "budget_overspend_denied"]
    assert len(matches) == 1, battery.RESULTS
    return matches[0][1]


def test_budget_check_passes_when_over_cap_is_denied_without_new_debit(
    monkeypatch, agent
):
    stub_transport(monkeypatch)
    battery.run_budget_check(agent)
    assert verdict() == "PASS"


def test_budget_check_fails_when_over_cap_call_succeeds(monkeypatch, agent):
    stub_transport(monkeypatch, invokes="allow")
    battery.run_budget_check(agent)
    assert verdict() == "FAIL"


def test_budget_check_fails_when_denied_call_still_debits(monkeypatch, agent):
    stub_transport(monkeypatch, ledger="extra-debit")
    battery.run_budget_check(agent)
    assert verdict() == "FAIL"


def test_budget_check_skips_when_cost_is_not_advertised(monkeypatch, agent):
    stub_transport(monkeypatch, cost=False)
    battery.run_budget_check(agent)
    assert verdict() == "SKIP"


def test_budget_check_skips_when_ledger_is_unreadable(monkeypatch, agent):
    stub_transport(monkeypatch, ledger="unreadable")
    battery.run_budget_check(agent)
    assert verdict() == "SKIP"


def test_budget_check_fails_when_seed_spend_breaks(monkeypatch, agent):
    stub_transport(monkeypatch, invokes="seed-fails")
    battery.run_budget_check(agent)
    assert verdict() == "FAIL"


def test_discover_echo_cost_reads_exact_cost_first(monkeypatch):
    monkeypatch.setattr(
        battery,
        "req",
        lambda *a, **k: (
            200,
            {
                "tools": [
                    {
                        "name": "golden-path-echo",
                        "annotations": {
                            "creditsPerCallExact": "1.5",
                            "creditsPerCall": 2.0,
                        },
                    }
                ]
            },
        ),
    )
    from decimal import Decimal

    assert battery.discover_echo_cost("any-key") == Decimal("1.5")


def test_discover_echo_cost_is_none_without_tool(monkeypatch):
    monkeypatch.setattr(
        battery, "req", lambda *a, **k: (200, {"tools": [{"name": "other"}]})
    )
    assert battery.discover_echo_cost("any-key") is None
