"""Illustrative pilot economics; no app imports, measured demand, or credit revenue.

Run: python3 docs/research/2026-08-31-deep-market-lab/economics_model.py
Writes economics_results.json beside this script, deterministically.
All scenario quantities are assumptions except the cited public resource rates.
"""

from dataclasses import asdict, dataclass, replace
import json
from math import ceil, isclose
from pathlib import Path


@dataclass(frozen=True)
class Scenario:
    name: str
    enterprise_commitment_usd: float
    ram_gb_per_tenant: float
    idle_vcpu_per_tenant: float
    cpu_seconds_per_attempt: float
    attempt_multiplier: float
    evidence_kb_per_action: float
    support_hours_per_tenant: float
    onboarding_hours_per_tenant: float
    uncertain_fraction: float
    vendor_minutes_per_uncertain: float
    partner_minutes_per_uncertain: float
    labor_usd_per_hour: float
    sentinel_fixed_usd_per_tenant: float
    sentinel_usd_per_action: float


SCENARIOS = [
    Scenario("optimistic", 250, 1, 0.05, 0.05, 1.05, 10, 1, 6, 0.0001, 2, 5, 50, 0, 0),
    Scenario("base", 1000, 2, 0.10, 0.2, 1.2, 25, 3, 12, 0.001, 5, 15, 75, 100, 0.002),
    Scenario(
        "pessimistic", 2000, 4, 0.25, 1, 1.5, 50, 6, 24, 0.005, 15, 30, 100, 250, 0.01
    ),
    Scenario("stress", 5000, 8, 0.5, 5, 3, 100, 10, 40, 0.02, 30, 60, 125, 500, 0.05),
]
ACTION_SCALES = [10, 100, 1000, 10_000, 100_000, 1_000_000]
RATES = {
    "ram_gb_month": 10,
    "vcpu_month": 20,
    "volume_gb_month": 0.15,
    "egress_gb": 0.05,
}
MONTH_SECONDS = 30 * 24 * 60 * 60
RETENTION_MONTHS = 12
STORAGE_MULTIPLIER = 3  # Assumed index/backups allowance, not a measured ratio.
ONBOARDING_AMORTIZATION_MONTHS = 6  # Sensitivity convention, not known retention.
SHARED_TOOLS_USD = 25
SHARED_OPERATING_HOURS = 8
FOUNDER_HOURS_AVAILABLE = 40
SCALE_REVIEW_ACTIONS = 100_000


def model(
    s: Scenario,
    actions: int,
    tenants: int = 1,
    *,
    enterprise_minimum_per_tenant: bool = False,
) -> dict:
    """actions = monthly new logical actions PER tenant; 1 customer/tenant here.

    Projects remain isolated. Both shared and per-tenant commercial minimums
    are hypothetical billing conventions; Enterprise contract terms are unknown.
    """
    attempts = actions * s.attempt_multiplier
    scale_steps = ceil(max(0, actions - SCALE_REVIEW_ACTIONS) / SCALE_REVIEW_ACTIONS)
    # Step proxy for extra used memory/operations above each 100k block.
    # Neither these steps nor the volume scale assert benchmarked capacity.
    ram = s.ram_gb_per_tenant + scale_steps * 0.5
    steady_storage_gb = (
        5
        + actions
        * s.evidence_kb_per_action
        / 1_000_000
        * RETENTION_MONTHS
        * STORAGE_MULTIPLIER
    )
    raw_cloud_per_tenant = (
        ram * RATES["ram_gb_month"]
        + s.idle_vcpu_per_tenant * RATES["vcpu_month"]
        + attempts * s.cpu_seconds_per_attempt / MONTH_SECONDS * RATES["vcpu_month"]
        + steady_storage_gb * RATES["volume_gb_month"]
        + attempts * 25 / 1_000_000 * RATES["egress_gb"]
    )
    commitment = s.enterprise_commitment_usd * (
        tenants if enterprise_minimum_per_tenant else 1
    )
    cloud = max(commitment, tenants * raw_cloud_per_tenant)
    sentinel = tenants * (
        s.sentinel_fixed_usd_per_tenant + actions * s.sentinel_usd_per_action
    )
    uncertain = tenants * actions * s.uncertain_fraction
    vendor_reconciliation = uncertain * s.vendor_minutes_per_uncertain / 60
    partner_reconciliation = uncertain * s.partner_minutes_per_uncertain / 60
    operations = (
        SHARED_OPERATING_HOURS
        + tenants * s.support_hours_per_tenant
        + vendor_reconciliation
    )
    coordination_steps = ceil(max(0, operations - FOUNDER_HOURS_AVAILABLE) / 40)
    coordination = coordination_steps * 8
    recurring_hours = operations + coordination
    onboarding = tenants * s.onboarding_hours_per_tenant
    economic_hours = recurring_hours + onboarding / ONBOARDING_AMORTIZATION_MONTHS
    first_month_hours = recurring_hours + onboarding
    # Excludes ALL labor, including hires needed beyond founder capacity.
    # This proxy is not total cash requirements, burn, or runway.
    nonlabor_cash = cloud + sentinel + SHARED_TOOLS_USD
    economic = nonlabor_cash + economic_hours * s.labor_usd_per_hour
    first_month_economic = nonlabor_cash + first_month_hours * s.labor_usd_per_hour
    return {
        "scenario": s.name,
        "customers": tenants,
        "isolated_tenants": tenants,
        "enterprise_commitment_scope": (
            "per_dedicated_tenant"
            if enterprise_minimum_per_tenant
            else "shared_across_isolated_projects"
        ),
        "new_logical_actions_per_tenant": actions,
        "total_new_logical_actions": tenants * actions,
        "attempts_including_replays_per_tenant": attempts,
        "uncertain_actions_scenario_count": uncertain,
        "steady_storage_gb_per_tenant": steady_storage_gb,
        "cloud_resource_proxy_per_tenant_usd": raw_cloud_per_tenant,
        "cloud_after_hypothetical_commitment_usd": cloud,
        "sentinel_assumed_usd": sentinel,
        "external_nonlabor_cash_proxy_usd": nonlabor_cash,
        "vendor_reconciliation_hours": vendor_reconciliation,
        "partner_reconciliation_hours_not_vendor_cost": partner_reconciliation,
        "coordination_step_hours": coordination,
        "recurring_vendor_hours": recurring_hours,
        "first_month_vendor_hours_all_tenants_new": first_month_hours,
        "first_month_within_40_founder_hours": first_month_hours
        <= FOUNDER_HOURS_AVAILABLE,
        "economic_cost_with_amortized_onboarding_usd": economic,
        "first_month_economic_cost_all_tenants_new_usd": first_month_economic,
        "break_even_monthly_fee_per_tenant_usd": economic / tenants,
        "break_even_usage_only_usd_per_new_action": economic / (tenants * actions),
        "fee_for_50pct_economic_margin_per_tenant_usd": economic / tenants / 0.5,
        "first_month_service_cost_excluding_cloud_sentinel_per_tenant_usd": (
            first_month_economic - cloud - sentinel
        )
        / tenants,
    }


def sanity_checks() -> list[str]:
    """Independent hand-derived base-case arithmetic plus directional checks."""
    base = SCENARIOS[1]
    r = model(base, 10_000)
    assert isclose(r["vendor_reconciliation_hours"], 10 * 5 / 60)
    assert isclose(r["partner_reconciliation_hours_not_vendor_cost"], 10 * 15 / 60)
    # Independently: 5 GB initial + 10k * 25kB * 12 months * 3 copies = 14 GB.
    assert isclose(r["steady_storage_gb_per_tenant"], 14)
    assert isclose(r["cloud_resource_proxy_per_tenant_usd"], 24.133518518518517)
    # $1k assumed cloud minimum + $100 Sentinel + 10k*$0.002 + $25 tools.
    assert isclose(r["external_nonlabor_cash_proxy_usd"], 1145)
    # Founder: 8 shared + 3 support + 5/6 recon + 12/6 onboarding = 13 5/6 h.
    assert isclose(r["economic_cost_with_amortized_onboarding_usd"], 2182.5)
    assert isclose(r["first_month_economic_cost_all_tenants_new_usd"], 2932.5)
    assert isclose(
        r["first_month_service_cost_excluding_cloud_sentinel_per_tenant_usd"], 1812.5
    )
    for s in SCENARIOS:
        rows = [model(s, n) for n in ACTION_SCALES]
        assert all(
            b["economic_cost_with_amortized_onboarding_usd"]
            >= a["economic_cost_with_amortized_onboarding_usd"]
            for a, b in zip(rows, rows[1:])
        )
    assert model(base, 1_000_000)["coordination_step_hours"] == 16
    assert (
        model(replace(base, uncertain_fraction=0), 10_000)[
            "vendor_reconciliation_hours"
        ]
        == 0
    )
    assert model(base, 100_001)["cloud_resource_proxy_per_tenant_usd"] > (
        model(base, 100_000)["cloud_resource_proxy_per_tenant_usd"] + 5
    )
    shared = model(base, 10_000, 10)
    dedicated = model(base, 10_000, 10, enterprise_minimum_per_tenant=True)
    assert isclose(shared["break_even_monthly_fee_per_tenant_usd"], 780)
    assert isclose(dedicated["break_even_monthly_fee_per_tenant_usd"], 1680)
    assert isclose(
        dedicated["external_nonlabor_cash_proxy_usd"]
        - shared["external_nonlabor_cash_proxy_usd"],
        9000,
    )
    assert isclose(
        model(base, 10_000, enterprise_minimum_per_tenant=True)[
            "economic_cost_with_amortized_onboarding_usd"
        ],
        r["economic_cost_with_amortized_onboarding_usd"],
    )
    return [
        "8 independently derived base arithmetic checks passed",
        "four scenario cost-monotonicity checks passed",
        "zero-uncertainty and two nonlinear-step checks passed",
        "four shared-versus-dedicated Enterprise minimum checks passed",
    ]


def main() -> None:
    base = SCENARIOS[1]
    results = {
        "as_of": "2026-08-31",
        "status": "Illustrative deterministic sensitivities, not measured economics or forecasts",
        "public_rates_source": "https://docs.railway.com/pricing/plans",
        "public_rates_usd": RATES,
        "all_other_inputs_are_illustrative": True,
        "enterprise_contract_and_sentinel_prices": "not verified; obtain written quotes",
        "external_nonlabor_cash_proxy_scope": (
            "Cloud, assumed Sentinel, and shared tools only; excludes ALL labor, "
            "including hires required beyond founder capacity. Not total cash "
            "requirements, burn, or runway."
        ),
        "constants": {
            "retention_months": RETENTION_MONTHS,
            "storage_multiplier": STORAGE_MULTIPLIER,
            "onboarding_amortization_months": ONBOARDING_AMORTIZATION_MONTHS,
            "shared_tools_usd_month": SHARED_TOOLS_USD,
            "shared_operating_hours_month": SHARED_OPERATING_HOURS,
            "founder_hours_available_month": FOUNDER_HOURS_AVAILABLE,
        },
        "scenario_assumptions": [asdict(s) for s in SCENARIOS],
        "single_tenant_scale": [model(s, n) for s in SCENARIOS for n in ACTION_SCALES],
        "tenant_sensitivity_10k_actions_each": [
            model(base, 10_000, t, enterprise_minimum_per_tenant=per_tenant)
            for per_tenant in [False, True]
            for t in [1, 2, 5, 10]
        ],
        "enterprise_floor_sensitivity_10k_actions": [
            {
                "assumed_commitment_usd": floor,
                **model(replace(base, enterprise_commitment_usd=floor), 10_000),
            }
            for floor in [0, 250, 1000, 2000, 5000]
        ],
        "uncertainty_sensitivity_10k_actions": [
            {
                "assumed_uncertain_fraction": u,
                **model(replace(base, uncertain_fraction=u), 10_000),
            }
            for u in [0, 0.0001, 0.001, 0.005, 0.02]
        ],
        "customer_value_thresholds_not_expected_losses": [
            {
                "fee_usd": fee,
                "assumed_monthly_incremental_events_avoided": events,
                "break_even_loss_per_event_usd": fee / events,
            }
            for fee in [500, 2000, 5000]
            for events in [0.01, 0.1, 1]
        ],
        "checks": sanity_checks(),
    }
    output = Path(__file__).with_name("economics_results.json")
    output.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "checks": results["checks"]}, indent=2))


if __name__ == "__main__":
    main()
