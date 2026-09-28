"""Reproduce report scenarios with the standard library; no application imports.

Run: python docs/research/unit-economics-2026-09-05/model.py
Inputs are illustrative. This writes scenario CSV, report tables and a JSON
snapshot. It does not read customer data or alter application billing.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def account(a: dict, s: dict, enterprise: float | None = None) -> dict:
    n = s["actions"]
    revenue = (
        a["base_monthly_fee"]
        + max(0, n - a["included_actions"]) * a["overage_per_action"]
    )
    machine = n * s["machine_per_action"]
    support = s["support_hours"] * s["hourly_cost"]
    exception_hours = (
        n * s["exception_rate"] * s["human_fraction"] * s["hours_per_case"]
    )
    exceptions = exception_hours * s["hourly_cost"]
    e = a["enterprise_allocation"] if enterprise is None else enterprise
    fees = revenue * a["card_percent"] + a["card_fixed"]
    reserve = revenue * a["reserve_percent"]
    nonrevenue_cost = s["infra_fixed"] + machine + support + exceptions + e
    cogs = nonrevenue_cost + fees + reserve
    gross = revenue - cogs
    denominator = 1 - a["target_margin"] - a["card_percent"] - a["reserve_percent"]
    return {
        "name": s["name"],
        "actions": n,
        "revenue": revenue,
        "infra_fixed": s["infra_fixed"],
        "machine": machine,
        "support": support,
        "exception_hours": exception_hours,
        "exceptions": exceptions,
        "enterprise": e,
        "payment_fees": fees,
        "reserve": reserve,
        "cogs": cogs,
        "contribution": gross,
        "margin": gross / revenue,
        "cogs_per_1000": cogs / n * 1000,
        "revenue_per_1000": revenue / n * 1000,
        "required_revenue_target": (nonrevenue_cost + a["card_fixed"]) / denominator,
        "cash_like_cogs_excluding_unpaid_labor": cogs - support - exceptions,
    }


def money(x: float, decimals: int = 2) -> str:
    return f"-${abs(x):,.{decimals}f}" if x < 0 else f"${x:,.{decimals}f}"


def table(headers: list[str], rows: list[list]) -> str:
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(map(str, row)) + " |" for row in rows),
        ]
    )


def build_tables(a: dict, accounts: list[dict]) -> dict[str, str]:
    base = a["scenarios"][1]
    b = accounts[1]
    tables = {}
    tables["SCENARIOS"] = table(
        [
            "Monthly scenario",
            "Lean pilot",
            "Base account",
            "Volume account",
            "Troubled account",
        ],
        [
            [label, *[fmt(x[key]) for x in accounts]]
            for label, key, fmt in [
                ("Unique governed attempts", "actions", lambda x: f"{x:,}"),
                ("Revenue (hypothesis)", "revenue", money),
                ("Baseline infrastructure", "infra_fixed", money),
                ("Incremental machine cost", "machine", money),
                ("Routine delivery/support labor", "support", money),
                ("Exception-handling labor", "exceptions", money),
                ("Payment fees", "payment_fees", money),
                ("Service concession/loss allowance", "reserve", money),
                ("Enterprise allocation: EXCLUDED", "enterprise", money),
                ("Delivery cost incl. labor", "cogs", money),
                ("Monthly delivery contribution", "contribution", money),
                ("Contribution margin", "margin", lambda x: f"{x:.1%}"),
                ("Revenue per 1,000 attempts", "revenue_per_1000", money),
                ("Delivery cost per 1,000 attempts", "cogs_per_1000", money),
            ]
        ],
    )
    ent = [account(a, base, e) for e in [0, 200, 500, 1000, 2000, 5000]]
    tables["ENTERPRISE"] = table(
        [
            "Incremental Enterprise allocation / customer-month",
            "Contribution at $2,400 revenue",
            "Margin",
            "Revenue needed for 70% margin",
        ],
        [
            [
                money(r["enterprise"], 0),
                money(r["contribution"]),
                f"{r['margin']:.1%}",
                money(r["required_revenue_target"]),
            ]
            for r in ent
        ],
    )
    tables["VOLUME"] = table(
        [
            "Monthly attempts",
            "Default-equivalent $0.0001/action",
            "Hybrid revenue",
            "Delivery cost",
            "Hybrid margin",
        ],
        [
            [
                f"{n:,}",
                money(n * 0.0001),
                money(r["revenue"]),
                money(r["cogs"]),
                f"{r['margin']:.1%}",
            ]
            for n in [10000, 100000, 1000000, 10000000]
            for r in [account(a, {**base, "actions": n})]
        ],
    )
    tables["SUPPORT"] = table(
        ["Routine support hours / month", "At $75 / hour", "Contribution", "Margin"],
        [
            [h, money(h * 75), money(r["contribution"]), f"{r['margin']:.1%}"]
            for h in [1, 3, 5, 10, 20]
            for r in [account(a, {**base, "support_hours": h})]
        ],
    )
    tables["EXCEPTIONS"] = table(
        [
            "Exception rate",
            "Exceptions per million",
            "Human hours (10% escalated, 15 min each)",
            "Labor cost",
            "Margin",
        ],
        [
            [
                f"{q:.3%}",
                f"{1000000 * q:,.0f}",
                f"{r['exception_hours']:,.2f}",
                money(r["exceptions"]),
                f"{r['margin']:.1%}",
            ]
            for q in [0.00001, 0.00005, 0.0001, 0.001, 0.01]
            for r in [account(a, {**base, "exception_rate": q})]
        ],
    )
    tables["RETENTION"] = table(
        [
            "Logical bytes per new action",
            "12-month data at 1M/month, 3x footprint (GB)",
            "Monthly volume cost at month 12",
            "At 10M/month",
        ],
        [
            [
                f"{kb:,} KB",
                f"{kb * 1000 * 1000000 * 12 * 3 / 1e9:,.0f}",
                money(kb * 1000 * 1000000 * 12 * 3 / 1e9 * 0.15),
                money(kb * 1000 * 10000000 * 12 * 3 / 1e9 * 0.15),
            ]
            for kb in [4, 12, 100, 1000]
        ],
    )
    tables["CPU"] = table(
        [
            "Aggregate CPU seconds / new action",
            "CPU dollars / million",
            "CPU dollars / 1,000",
        ],
        [
            [
                f"{ms} ms",
                money(ms / 1000 * 1000000 * 0.00000772),
                money(ms / 1000 * 1000 * 0.00000772, 6),
            ]
            for ms in [5, 20, 100, 500]
        ],
    )
    tables["BREAK_EVEN"] = table(
        [
            "Incremental Enterprise allocation / customer",
            "Customers for $3K overhead",
            "For $10K",
            "For $30K",
        ],
        [
            [
                money(e, 0),
                *[
                    math.ceil(f / r["contribution"])
                    if r["contribution"] > 0
                    else "No finite break-even"
                    for f in [3000, 10000, 30000]
                ],
            ]
            for e in [0, 500, 1000, 2000]
            for r in [account(a, base, e)]
        ],
    )
    tables["CAC"] = table(
        ["Acquisition cost / customer", "Payback with E=$0", "Payback with E=$1,000"],
        [
            [
                money(c, 0),
                f"{c / b['contribution']:.2f} months",
                f"{c / account(a, base, 1000)['contribution']:.2f} months",
            ]
            for c in [2000, 8000, 20000]
        ],
    )
    tables["LTV"] = table(
        [
            "Monthly logo churn assumption",
            "12-month logo survival",
            "36-month capped contribution value",
            "Value / $8K CAC",
        ],
        [
            [f"{q:.0%}", f"{(1 - q) ** 12:.1%}", money(v), f"{v / 8000:.2f}x"]
            for q in [0.01, 0.03, 0.05, 0.10]
            for v in [b["contribution"] * sum((1 - q) ** m for m in range(36))]
        ],
    )
    tables["PAYMENTS"] = table(
        [
            "Single customer payment",
            "Domestic card fee",
            "Effective card rate",
            "ACH processing illustration",
        ],
        [
            [
                money(r, 0),
                money(r * 0.029 + 0.3),
                f"{(r * 0.029 + 0.3) / r:.2%}",
                money(min(r * 0.008, 5)),
            ]
            for r in [5, 20, 100, 500, 2400]
        ],
    )
    return tables


def validate(a: dict, accounts: list[dict]) -> int:
    checks = 0
    assert 0 <= a["card_percent"] + a["reserve_percent"] + a["target_margin"] < 1
    checks += 1
    for s, r in zip(a["scenarios"], accounts):
        assert r["actions"] > 0 and 0 <= s["human_fraction"] <= 1
        assert 0 <= s["exception_rate"] <= 1
        assert math.isclose(r["revenue"], r["cogs"] + r["contribution"])
        assert math.isclose(r["margin"], 1 - r["cogs"] / r["revenue"])
        assert math.isclose(r["cogs_per_1000"] * r["actions"] / 1000, r["cogs"])
        checks += 5
    b = accounts[1]
    no_enterprise = account(a, a["scenarios"][1], 0)
    assert math.isclose(
        account(a, a["scenarios"][1], 1000)["contribution"],
        no_enterprise["contribution"] - 1000,
    )
    assert math.isclose(
        account(a, {**a["scenarios"][1], "actions": a["included_actions"]})["revenue"],
        a["base_monthly_fee"],
    )
    assert math.isclose(
        b["support"],
        a["scenarios"][1]["support_hours"] * a["scenarios"][1]["hourly_cost"],
    )
    assert math.isclose(
        b["exceptions"], b["exception_hours"] * a["scenarios"][1]["hourly_cost"]
    )
    assert b["required_revenue_target"] >= 0
    checks += 5
    return checks


def main() -> None:
    a = json.loads((ROOT / "assumptions.json").read_text())
    accounts = [account(a, s) for s in a["scenarios"]]
    checks = validate(a, accounts)
    with (ROOT / "scenarios.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(accounts[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(accounts)
    tables = build_tables(a, accounts)
    (ROOT / "calculated-tables.md").write_text(
        "\n\n".join(f"## {k}\n\n{v}" for k, v in tables.items()) + "\n"
    )
    (ROOT / "model-results.json").write_text(
        json.dumps(
            {"accounts": accounts, "checks_passed": checks, "status": a["status"]},
            indent=2,
        )
        + "\n"
    )
    print(json.dumps({"checks_passed": checks, "accounts": accounts}, indent=2))


if __name__ == "__main__":
    main()
