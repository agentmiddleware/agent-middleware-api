"""Scenario economics and evidence reconciliation. USD, no application imports."""

from __future__ import annotations
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = {
    "price": 999.0,
    "actions": 100_000,
    "resource_allowance": 50.0,
    "other_delivery": 20.0,
    "support_hours": 3.0,
    "hourly_cost": 75.0,
    "exception_rate": 0.00005,
    "human_fraction": 0.1,
    "hours_per_case": 0.25,
    "payment_rate": 0.029,
    "payment_fixed": 0.3,
    "reserve_rate": 0.01,
    "target_margin": 0.7,
}
# Resource allowances are hypotheses, not costs inferred from the demo bill.
SCENARIOS = [
    {
        "name": "Bounded, low-touch",
        **BASE,
        "price": 499.0,
        "actions": 10_000,
        "resource_allowance": 20.0,
        "other_delivery": 10.0,
        "support_hours": 1.0,
    },
    {"name": "Working illustration", **BASE},
    {"name": "Same workload, higher price", **BASE, "price": 1500.0},
    {
        "name": "Support-heavy",
        **BASE,
        "support_hours": 8.0,
        "exception_rate": 0.001,
        "human_fraction": 0.2,
    },
    {
        "name": "Volume stress, unbenchmarked",
        **BASE,
        "actions": 1_000_000,
        "resource_allowance": 250.0,
        "support_hours": 5.0,
    },
]


def account(s: dict) -> dict:
    """Delivery contribution excludes acquisition and shared company overhead."""
    for k, v in s.items():
        if k != "name" and (not math.isfinite(v) or v < 0):
            raise ValueError(f"Invalid nonnegative input: {k}")
    for k in ("exception_rate", "human_fraction", "payment_rate", "reserve_rate"):
        if s[k] > 1:
            raise ValueError(f"Invalid fraction: {k}")
    denom = 1 - s["payment_rate"] - s["reserve_rate"] - s["target_margin"]
    if denom <= 0:
        raise ValueError("Impossible margin target under proportional costs")
    hours = (
        s["actions"] * s["exception_rate"] * s["human_fraction"] * s["hours_per_case"]
    )
    labor = (s["support_hours"] + hours) * s["hourly_cost"]
    base_cost = s["resource_allowance"] + s["other_delivery"] + labor
    payment = s["price"] * s["payment_rate"] + (s["payment_fixed"] if s["price"] else 0)
    reserve = s["price"] * s["reserve_rate"]
    delivery = base_cost + payment + reserve
    contribution = s["price"] - delivery
    return {
        **s,
        "exception_hours": hours,
        "labor": labor,
        "payment": payment,
        "reserve": reserve,
        "delivery": delivery,
        "contribution": contribution,
        "margin": contribution / s["price"] if s["price"] else None,
        "delivery_per_1000": delivery / s["actions"] * 1000 if s["actions"] else None,
        "target_price": (base_cost + s["payment_fixed"]) / denom,
        "cash_ex_unpaid_labor": delivery - labor,
        "total_delivery_hours": s["support_hours"] + hours,
    }


def workspace(
    n: int, commitment: float, usage_each: float = 20.0, noncredited_fixed: float = 0.0
) -> dict:
    """Generic usage-credit model; no actual Enterprise contract is known."""
    if min(n, commitment, usage_each, noncredited_fixed) < 0:
        raise ValueError("Negative commitment model input")
    used = n * usage_each
    total = max(commitment, used) + noncredited_fixed
    next_total = max(commitment, (n + 1) * usage_each) + noncredited_fixed
    return {
        "customers": n,
        "commitment": commitment,
        "usage": used,
        "total": total,
        "unabsorbed": max(0.0, commitment - used),
        "allocated_each": total / n if n else None,
        "next_increment": next_total - total,
    }


def money(x: float | None) -> str:
    if x is None:
        return "Undefined"
    return ("-$" if x < 0 else "$") + f"{abs(x):,.2f}"


def pct(x: float | None) -> str:
    return "Undefined" if x is None else f"{x:.1%}"


def table(headers: list, rows: list) -> str:
    return "\n".join(
        [
            "| " + " | ".join(map(str, headers)) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *["| " + " | ".join(map(str, r)) + " |" for r in rows],
        ]
    )


def validate(evidence: dict, results: list) -> list[str]:
    checks = []

    def check(ok: bool, label: str) -> None:
        if not ok:
            raise AssertionError(label)
        checks.append(label)

    for period in evidence["periods"]:
        check(
            math.isclose(
                sum(s["totalDollars"] for s in period["services"]),
                period["project_usage_usd"],
                abs_tol=1e-10,
            ),
            f"{period['period']}: service totals match project",
        )
        for s in period["services"]:
            components = sum(
                v for k, v in s.items() if k.endswith("Dollars") and k != "totalDollars"
            )
            check(
                math.isclose(components, s["totalDollars"], abs_tol=1e-10),
                f"{period['period']}: {s['name']} cost components reconcile",
            )
    b = results[1]
    check(math.isclose(b["delivery"], 343.636), "Independent base cost arithmetic")
    check(
        math.isclose(b["contribution"], 655.364),
        "Independent base contribution arithmetic",
    )
    check(
        math.isclose(b["exception_hours"], 0.125),
        "Exception units: events to human hours",
    )
    check(
        account({**BASE, "price": 0})["margin"] is None,
        "Zero revenue has undefined margin",
    )
    check(
        account({**BASE, "price": 0})["payment"] == 0,
        "No collection means no fixed card fee",
    )
    check(
        account({**BASE, "actions": 0})["delivery_per_1000"] is None,
        "Zero actions has undefined unit cost",
    )
    check(
        account({**BASE, "actions": 0})["labor"] == 225,
        "Idle customer retains routine labor",
    )
    for h in [0, 1, 3, 10]:
        low, high = (
            account({**BASE, "support_hours": h}),
            account({**BASE, "support_hours": h + 1}),
        )
        check(
            math.isclose(low["contribution"] - high["contribution"], 75),
            f"One additional support hour costs $75 at h={h}",
        )
    check(workspace(1, 20)["total"] == 20, "Included usage is not counted twice")
    check(
        workspace(1, 1000)["next_increment"] == 0,
        "Unused commitment absorbs next resource increment",
    )
    check(
        workspace(50, 1000)["next_increment"] == 20,
        "Above commitment, next resource usage is incremental",
    )
    check(
        workspace(0, 1000)["allocated_each"] is None,
        "No allocation to nonexistent customers",
    )
    check(
        workspace(5, 1000, noncredited_fixed=100)["total"] == 1100,
        "Noncredited fixed fee added once",
    )
    for bad in [
        {"support_hours": -1},
        {"human_fraction": 1.1},
        {"target_margin": 1},
        {"price": float("nan")},
    ]:
        try:
            account({**BASE, **bad})
        except ValueError:
            checks.append(f"Rejected invalid input: {next(iter(bad))}")
        else:
            raise AssertionError(bad)
    floor = account({**BASE, "price": b["target_price"]})
    check(math.isclose(floor["margin"], 0.7), "Price floor returns target margin")
    return checks


def main() -> None:
    evidence = json.loads((ROOT / "provider-usage-evidence.json").read_text())
    results = [account(s) for s in SCENARIOS]
    checks = validate(evidence, results)
    t = {}
    old, current = evidence["periods"]
    names = ["Postgres", "api-service", "Redis", "partner-mcp-pilot", "deleted service"]
    t["OBSERVED"] = table(
        ["Service", "Previous period usage", "Current partial period usage"],
        [
            [
                name,
                *[
                    money(
                        sum(
                            s["totalDollars"]
                            for s in p["services"]
                            if s["name"] == name
                        )
                    )
                    for p in [old, current]
                ],
            ]
            for name in names
        ]
        + [
            [
                "Project total",
                money(old["project_usage_usd"]),
                money(current["project_usage_usd"]),
            ]
        ],
    )
    t["SCENARIOS"] = table(
        [
            "Scenario",
            "Fee / month",
            "Actions / month",
            "Delivery hours",
            "Delivery cost",
            "Contribution",
            "Margin",
        ],
        [
            [
                r["name"],
                money(r["price"]),
                f"{r['actions']:,}",
                f"{r['total_delivery_hours']:.3f}",
                money(r["delivery"]),
                money(r["contribution"]),
                pct(r["margin"]),
            ]
            for r in results
        ],
    )
    t["WATERFALL"] = table(
        ["Working illustration, 100K attempts", "USD per customer-month"],
        [
            ["Revenue", money(BASE["price"])],
            ["Resource allowance", money(BASE["resource_allowance"])],
            ["Other delivery allowance", money(BASE["other_delivery"])],
            ["Routine support: 3h x $75", "$225.00"],
            ["Exceptions: 0.125h x $75", money(results[1]["exception_hours"] * 75)],
            ["Collection fees", money(results[1]["payment"])],
            ["Planning reserve", money(results[1]["reserve"])],
            ["Delivery cost", money(results[1]["delivery"])],
            ["Contribution", money(results[1]["contribution"])],
        ],
    )
    t["PRICE_HOURS"] = table(
        [
            "Monthly price",
            "1 routine hour",
            "3 routine hours",
            "8 routine hours",
            "70% margin: max routine hours",
        ],
        [
            [
                money(p),
                *[
                    pct(account({**BASE, "price": p, "support_hours": h})["margin"])
                    for h in [1, 3, 8]
                ],
                f"{((p * (1 - 0.039 - 0.7) - 70 - 0.3) / 75 - 0.125):.2f}h",
            ]
            for p in [249, 499, 999, 1500, 2500]
        ],
    )
    t["RESOURCE"] = table(
        [
            "Resource allowance / month",
            "Contribution at $999",
            "Margin",
            "Revenue for 70% margin",
        ],
        [
            [
                money(c),
                money(r["contribution"]),
                pct(r["margin"]),
                money(r["target_price"]),
            ]
            for c in [5, 20, 50, 150, 500, 1000]
            for r in [account({**BASE, "resource_allowance": c})]
        ],
    )
    t["COMMITMENT"] = table(
        [
            "Illustrative workspace commitment",
            "Customers",
            "Usage total ($20 each)",
            "Workspace bill",
            "Unabsorbed minimum",
            "Allocated / customer",
            "Next resource increment",
        ],
        [
            [
                money(m),
                n,
                money(r["usage"]),
                money(r["total"]),
                money(r["unabsorbed"]),
                money(r["allocated_each"]),
                money(r["next_increment"]),
            ]
            for m in [20, 1000]
            for n in [1, 5, 20, 50]
            for r in [workspace(n, m)]
        ],
    )
    t["ONBOARD"] = table(
        ["Setup fee", "10 delivery hours", "20 delivery hours", "40 delivery hours"],
        [
            [money(p), *[money(p * 0.961 - 0.3 - 100 - h * 75) for h in [10, 20, 40]]]
            for p in [1000, 2500, 5000]
        ],
    )
    t["CAC"] = table(
        [
            "Acquisition effort per win",
            "Acquisition cost",
            "Payback at working illustration",
            "12-month contribution after acquisition",
        ],
        [
            [
                f"{h}h + $300 expenses",
                money(c),
                f"{c / results[1]['contribution']:.1f} months",
                money(12 * results[1]["contribution"] - c),
            ]
            for h in [10, 40, 100]
            for c in [h * 75 + 300]
        ],
    )
    t["COMPANY"] = table(
        [
            "Shared monthly overhead",
            "Customers to cover overhead",
            "Monthly direct delivery hours",
        ],
        [
            [money(f), n, f"{n * results[1]['total_delivery_hours']:.1f}h"]
            for f in [3000, 10000, 30000]
            for n in [math.ceil(f / results[1]["contribution"])]
        ],
    )
    t["ROI"] = table(
        [
            "Monthly platform fee",
            "Buyer hours to break even ($100/h)",
            "Hours for 3x gross benefit",
            "$500 net incidents avoided to break even",
        ],
        [
            [money(p), f"{p / 100:.2f}h", f"{3 * p / 100:.2f}h", f"{p / 500:.3f}"]
            for p in [499, 999, 1500, 2500]
        ],
    )
    t["RETENTION"] = table(
        [
            "Net logical bytes / action",
            "100K/month, month 12 with 3x footprint",
            "1M/month, month 12",
        ],
        [
            [
                f"{kb} KB",
                f"{kb * 1000 * 100000 * 12 * 3 / 1e9:.1f} GB",
                f"{kb * 1000 * 1000000 * 12 * 3 / 1e9:.1f} GB",
            ]
            for kb in [4, 12, 100]
        ],
    )
    outputs = {
        "base": BASE,
        "scenarios": SCENARIOS,
        "results": results,
        "validation_count": len(checks),
        "validation_checks": checks,
    }
    (ROOT / "model-results.json").write_text(json.dumps(outputs, indent=2) + "\n")
    (ROOT / "assumptions.json").write_text(
        json.dumps(
            {
                "classification": "Illustrative, not actual customer economics",
                "base": BASE,
                "scenarios": SCENARIOS,
            },
            indent=2,
        )
        + "\n"
    )
    (ROOT / "calculated-tables.md").write_text(
        "\n\n".join(f"## {k}\n\n{v}" for k, v in t.items()) + "\n"
    )
    with (ROOT / "scenarios.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(results)
    print(
        json.dumps(
            {
                "checks_passed": len(checks),
                "scenarios": len(results),
                "base_contribution": results[1]["contribution"],
                "base_floor": results[1]["target_price"],
            }
        )
    )


if __name__ == "__main__":
    main()
