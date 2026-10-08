# Break Report: policy bundles, evaluation, and governance

## Summary

Probed five target areas with adversarial tests against local test setups only. Found 4 real breaks, all fixed with regression tests: 15 tests in tests/test_policy_governance_breaks.py, 11 of which fail on the old code and pass on the new code (the other 4 are semantic pins that pass on both). Two areas tested clean (no break). Nothing is fixed-but-failing. One residual risk is documented below, plus open questions.

Counts: breaks found 4, fixed and tested 4, fixed but failing 0, blocked 0.

## Findings (by severity)

### 1. High: concurrent billing charges overshoot the daily spend cap
What broke: five concurrent charge requests against a daily cap of 5 credits all returned 200, spending 7.5. The same five charges run one after another correctly yield three approvals and two 403 denials.
How to reproduce: create a wallet with a policy bundle carrying daily_spend_limit 5 and agent_comms allowed, then fire five simultaneous POST /v1/billing/charge calls with units=1 (1.5 credits each). See test_concurrent_charges_respect_daily_cap.
Root cause: app/routers/billing.py, charge_wallet. The policy check reads the spend total from the ledger and the debit writes to it later, with awaits in between, so concurrent requests all read the pre-charge total. Classic check-then-act race.
Fix: a per-wallet asyncio lock (app/routers/billing.py, _wallet_charge_guard) now covers the policy check plus the ledger debit. Charges for different wallets still run in parallel.
Test results: the new test fails on old code ([200 x5]) and passes on new code ([200 x3, 403 x2] plus a follow-up 403). Full billing suite: 76 passed. Residual risk: the lock is per process, so a multi-worker deployment could still interleave; the MCP invoke path has the same shape of window around its own policy check and was left alone because its approval waits must not hold a lock.

### 2. High: missing or negative action cost waives both money caps
What broke: evaluate_wallet_policy approved any action when estimated_cost was None, even under max_cost_per_action and daily_spend_limit bundles. A negative cost was also approved, and on the planner path a negative credit_cost additionally inflated the action score (utility 40 for a cost of -50). The planner takes credit_cost from caller-supplied candidate data, so omitting the field waived both caps and got the action selected.
How to reproduce: evaluate a capped wallet with estimated_cost=None or -50, or POST /v1/planner/optimize with a candidate missing credit_cost. See test_policy_denies_unknown_cost_under_caps, test_policy_denies_negative_cost, test_planner_rejects_candidate_without_cost, test_planner_rejects_negative_cost_candidate.
Root cause: app/services/policies.py, evaluate_wallet_policy. Both cap comparisons required est to be non-None, so an unknown cost skipped them silently.
Fix: unknown cost under any money cap now denies with reason cost_unknown; negative cost denies with reason invalid_estimated_cost. Bundles without caps are unaffected, and MCP/billing callers always pass real costs (verified Decimal sources), so only the planner path changes behavior.
Test results: new tests fail on old code (allowed) and pass on new code. Policy suites: 58 passed (test_policy_bundles.py, test_policy_decisions.py).

### 3. Medium: unstated task tier waives the risk ceiling on the planner path
What broke: a candidate with an in-cap cost but no task tier was selected under a low-risk-only bundle, because a missing tier meant nothing to compare.
How to reproduce: POST /v1/planner/optimize without task_context.tier against a risk_tier low bundle. See test_planner_unstated_tier_denied_under_low_bundle.
Root cause: app/routers/planner.py passed the caller-supplied tier straight through, and app/services/policies.py skips the ceiling when the requested tier is None.
Fix: the planner now defaults an unstated tier to high (most restrictive assumption) before evaluation. Stated tiers, including unknown strings, keep their existing fail-closed handling, and direct evaluate_wallet_policy calls with no tier (used by MCP/billing, which have no tier concept) are unchanged.
Test results: new test fails on old code (selected) and passes on new code (risk_tier_not_allowed). Planner suite: 56 passed (test_planner_constraints.py).

### 4. Medium: explicit nulls in policy PATCH crash with 500
What broke: PATCH /v1/policies/{id} with an explicit null for risk_tier, name, require_real_effects, human_approval_required, or is_active raised an unhandled IntegrityError (NOT NULL constraint) and answered 500.
How to reproduce: create a bundle, PATCH {"risk_tier": null}. See test_policy_patch_rejects_explicit_null (5 params).
Root cause: app/schemas/policies.py, PolicyBundlePatch. Those fields accept None in the schema but map to NOT NULL columns, and patch_policy_bundle writes the null straight through.
Fix: a schema validator rejects explicit nulls on the five non-nullable fields, so the API answers 422 and the stored bundle is untouched. Nullable columns (allowed_tools, allowed_service_categories, money caps) keep their clear-the-restriction meaning, pinned by test_policy_patch_null_still_clears_nullable_caps.
Test results: new tests fail on old code (IntegrityError) and pass on new code. Stored values verified unchanged after the rejected patch.

## Tested, no break found

Deny-then-allow ordering: with two active bundles where one denies and one allows, the denial wins regardless of creation order (evaluation returns on the first failing bundle). Pinned by test_deny_wins_regardless_of_bundle_order. No race in evaluation order exists.
Empty policy: a wallet with no bundles is allowed (documented default); a bundle with allowed_tools [] denies every tool; malformed allowlist shapes at create are refused with 422. Pinned by test_empty_allowlist_denies_everything and test_malformed_allowlist_shape_rejected.
Unknown action vocab: AWI action names are a closed enum validated at the HTTP boundary (unknown values get 422 before any policy runs), validate_parameters and check_preconditions run in the session manager, and register_custom_action has no callers, so unknown actions cannot reach execution. Verified by code reading; no test added since the boundary is framework validation.

## Open questions

1. Should the MCP invoke path gain a real risk tier per tool so the ceiling means something there, or is tier purely a planner concept by design? MCP and billing currently pass no tier, so low-only bundles do not constrain direct tool calls.
2. Is defaulting an unstated planner tier to high the right product call, or should unstated tiers be rejected outright with 422 at the planner schema?
3. The planner trusts caller-supplied per-candidate credit_cost and the task tier (self-attested). Should candidate costs come from server-side pricing instead?
4. For the charge race, is a per-process lock sufficient for the deployment topology, or is a database-level atomic check-and-debit wanted?
