# Agent Ops War Room Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a one-command Agent Ops War Room proof that shows a wallet-scoped agent discovering the platform, receiving bounded authority, invoking a governed MCP tool, producing billing/audit/receipt evidence, replaying safely, and getting denied when it exceeds scope.

**Architecture:** Build on the current trust-plane branch instead of adding a broad new product surface. The proof is an executable Python demo plus tests and docs: it drives the existing FastAPI app in-process for reliability, uses existing wallet/key/permit/MCP/receipt/audit endpoints, and prints an operator timeline that can be shown to a reviewer without hand-waving.

**Tech Stack:** FastAPI ASGI app, httpx `ASGITransport`, SQLModel/SQLite test database, existing `ServiceRegistry`, permit/receipt/audit-chain services, pytest/anyio, Markdown docs.

---

## Current Worktree Context

The branch may already contain uncommitted trust-plane changes in these files:

- `DEMO_SCRIPT.md`
- `DESIGN_PARTNER_GUIDE.md`
- `WEDGE.md`
- `app/core/config.py`
- `app/core/trust_mode.py`
- `app/main.py`
- `app/routers/mcp.py`
- `app/routers/permits.py`
- `app/routers/receipts.py`
- `app/routers/keys.py`
- `app/schemas/trust.py`
- `app/services/permits.py`
- `app/services/receipts.py`
- `app/services/signing_keys.py`
- `tests/test_mcp_trust.py`
- `tests/test_mcp_trust_mode.py`
- `tests/test_signing_key_lifecycle.py`
- `tests/test_trust_mode_guardrails.py`
- `tests/test_trust_operator_inspection.py`

Treat those as relevant in-progress work. Do not revert them. Do not stage unrelated files by wildcard. Every task must stage exact files it owns.

## File Structure

- `scripts/agent_ops_war_room_demo.py`: one-command demo runner and reusable `run_war_room()` function.
- `tests/test_agent_ops_war_room_demo.py`: regression test for the executable proof contract.
- `DEMO_SCRIPT.md`: short partner-facing runbook pointing to the new command and proof artifacts.
- `README.md`, `docs/golden-path.md`, `static/llm.txt`: public narrative surfaces that should say "agent operations control plane" and make the War Room proof obvious.
- `app/routers/well_known.py`, `app/routers/discover.py`, `app/main.py`: only touch if the discovery payloads still contain generic marketplace/plugin wording after the current dirty branch is stabilized.
- `docs/openapi.json`: regenerate only if FastAPI route metadata/docstrings change.

---

### Task 1: Stabilize Existing Trust-Plane Baseline

**Files:**
- Modify/commit existing dirty trust-plane files listed in "Current Worktree Context" only after review.
- Test: `tests/test_mcp_trust.py`
- Test: `tests/test_mcp_trust_mode.py`
- Test: `tests/test_permits.py`
- Test: `tests/test_receipts.py`
- Test: `tests/test_audit_chain.py`
- Test: `tests/test_signing_key_lifecycle.py`
- Test: `tests/test_trust_mode_guardrails.py`
- Test: `tests/test_trust_operator_inspection.py`

- [ ] **Step 1: Inspect current dirty trust-plane diff**

Run:

```bash
git status --short
git diff --stat
git diff -- app/routers/mcp.py app/routers/permits.py app/routers/receipts.py app/services/permits.py app/services/receipts.py app/services/signing_keys.py app/schemas/trust.py
```

Expected: changes are scoped to trust mode, permits, receipts, governed MCP invoke, signing keys, and operator inspection.

- [ ] **Step 2: Run focused trust-plane tests**

Run:

```bash
pytest tests/test_mcp_trust.py tests/test_mcp_trust_mode.py tests/test_permits.py tests/test_receipts.py tests/test_audit_chain.py tests/test_signing_key_lifecycle.py tests/test_trust_mode_guardrails.py tests/test_trust_operator_inspection.py -q
```

Expected: all pass. If failures are present, fix only the trust-plane files required by the failing tests.

- [ ] **Step 3: Check public trust-mode guardrails**

Verify these properties in code and tests:

- `TRUST_MODE_ENABLED=true` with `ALLOW_LEGACY_UNPERMITTED_MCP=false` requires permit-backed MCP calls.
- Missing permit produces `permit_required` and an audit denial.
- Missing idempotency key produces `idempotency_key_required` and an audit denial.
- Wrong key, wrong wallet, or wrong tool produces a permit denial with audit evidence.
- Successful governed call returns a signed receipt that references permit, ledger entry, and audit event.
- Replay returns the same receipt and does not double-charge.

- [ ] **Step 4: Commit stabilized trust-plane baseline**

Stage exact files from the trust-plane baseline, not new War Room files:

```bash
git add DEMO_SCRIPT.md DESIGN_PARTNER_GUIDE.md WEDGE.md \
  app/core/config.py app/core/trust_mode.py app/main.py \
  app/routers/mcp.py app/routers/permits.py app/routers/receipts.py app/routers/keys.py \
  app/schemas/trust.py app/services/permits.py app/services/receipts.py app/services/signing_keys.py \
  tests/test_mcp_trust.py tests/test_mcp_trust_mode.py tests/test_signing_key_lifecycle.py \
  tests/test_trust_mode_guardrails.py tests/test_trust_operator_inspection.py
git commit -m "feat: add governed MCP trust mode"
```

---

### Task 2: Add One-Command War Room Demo

**Files:**
- Create: `scripts/agent_ops_war_room_demo.py`
- Test: `tests/test_agent_ops_war_room_demo.py`

- [ ] **Step 1: Write failing test for the War Room proof**

Create `tests/test_agent_ops_war_room_demo.py` with a test that imports `run_war_room` and asserts:

```python
@pytest.mark.anyio
async def test_agent_ops_war_room_demo_proves_control_plane_loop(
    client,
    clean_database,
    strict_trust_mode,
):
    result = await run_war_room(
        client=client,
        bootstrap_api_key="test-key",
        emit=False,
    )

    assert result["status"] == "pass"
    assert result["agent"]["wallet_id"].startswith("wallet-")
    assert result["permit"]["permit_id"].startswith("permit-")
    assert result["invoke"]["receipt"]["outcome"] == "success"
    assert result["replay"]["same_receipt"] is True
    assert result["ledger"]["matching_debits"] == 1
    assert result["audit"]["chain"]["valid"] is True
    assert result["denial"]["reason"] == "permit_tool_not_allowed"
    assert result["denial"]["ledger_debits_after"] == result["ledger"]["matching_debits"]
```

The fixture may reuse the strict trust-mode setup pattern from `tests/test_mcp_trust_mode.py`.

- [ ] **Step 2: Run the failing test**

Run:

```bash
pytest tests/test_agent_ops_war_room_demo.py -q
```

Expected: fail because `scripts.agent_ops_war_room_demo` does not exist.

- [ ] **Step 3: Implement `scripts/agent_ops_war_room_demo.py`**

Implement a script with these public functions:

```python
async def run_war_room(
    *,
    client: httpx.AsyncClient,
    bootstrap_api_key: str,
    emit: bool = True,
) -> dict[str, Any]:
    ...

async def run_in_process(
    *,
    database_url: str | None = None,
    bootstrap_api_key: str = "war-room-bootstrap-key",
) -> dict[str, Any]:
    ...
```

`run_war_room()` must:

1. Fetch `/.well-known/agent.json`, `/mcp/tools.json`, and `/openapi.json`.
2. Create a sponsor wallet through `/v1/billing/wallets/sponsor`.
3. Create an agent wallet through `/v1/billing/wallets/agent`.
4. Create an agent API key through `/v1/api-keys`.
5. Register two local tools through `get_service_registry()`:
   - `war-room-echo`
   - `war-room-denied`
6. Create a signed permit for `war-room-echo` through `/v1/permits` using an ISO UTC expiration generated in Python.
7. Invoke `/mcp/messages` with:
   - `mcpContext.wallet_id`
   - `mcpContext.permit_id`
   - `mcpContext.idempotency_key`
8. Replay the same request and confirm the same receipt ID is returned.
9. Fetch `/v1/billing/ledger/{wallet_id}` and count matching debits for `war-room-echo`.
10. Verify the receipt through `/v1/receipts/verify`.
11. Fetch `/v1/audit/events?wallet_id=...&tool=war-room-echo`.
12. Verify `/v1/audit/verify-chain`.
13. Attempt `war-room-denied` with the same permit and assert the response error is `permit_tool_not_allowed`.
14. Fetch the ledger again and confirm no extra `war-room-echo` debit was created by replay or denial.
15. Unregister both local tools in a `finally` block.

`run_in_process()` must:

- set safe local defaults before importing/running the app when used as `python scripts/agent_ops_war_room_demo.py`;
- use a temporary SQLite database by default;
- initialize the database with existing app DB helpers;
- use `httpx.ASGITransport(app=app)` so no external server or `jq` is required;
- print a compact operator timeline and a final `AGENT OPS WAR ROOM: PASS` line.

- [ ] **Step 4: Run the War Room test**

Run:

```bash
pytest tests/test_agent_ops_war_room_demo.py -q
```

Expected: pass.

- [ ] **Step 5: Run the script manually**

Run:

```bash
python scripts/agent_ops_war_room_demo.py
```

Expected output includes:

```text
AGENT OPS WAR ROOM: PASS
```

- [ ] **Step 6: Commit demo script**

```bash
git add scripts/agent_ops_war_room_demo.py tests/test_agent_ops_war_room_demo.py
git commit -m "feat: add agent ops war room demo"
```

---

### Task 3: Red-Line War Room Docs And Agent-Facing Narrative

**Files:**
- Modify: `DEMO_SCRIPT.md`
- Modify: `README.md`
- Modify: `docs/golden-path.md`
- Modify: `static/llm.txt`
- Modify if needed: `app/routers/well_known.py`
- Modify if needed: `app/routers/discover.py`
- Modify if route metadata changes: `docs/openapi.json`
- Test: `tests/test_discovery.py`
- Test: `tests/test_discovery_drift.py`

- [ ] **Step 1: Add failing discovery/narrative assertions**

Add compact tests asserting:

- `GET /llm.txt` contains `Agent Ops War Room` or `agent operations control plane`.
- `GET /.well-known/agent.json` description is about an operational control plane, not plugin directories.
- `GET /v1/discover` shares the same `agent_first` contract and includes control-plane language.

Run:

```bash
pytest tests/test_discovery.py tests/test_discovery_drift.py -q
```

Expected: fail on stale wording if docs/routes have not yet been updated.

- [ ] **Step 2: Update docs**

Update docs so the first impression is:

```text
Agent Ops War Room proves the control plane loop:
discover -> authorize -> invoke -> meter -> receipt -> audit -> verify
```

Keep these claims explicit:

- The demo is a proof, not a claim of complete production agent banking.
- Trust artifacts are signed permits and signed receipts.
- Replay is safe and does not double charge.
- Out-of-scope actions are denied and audited.
- Audit-chain verification gives operators tamper evidence.

Remove or demote generic copy:

- "plugin registry"
- "directories"
- "free tier"
- "unlimited everything"
- public "Phase 7/8/9" labels
- feature-list language that makes AWI or marketplace tools sound like the core product.

- [ ] **Step 3: Regenerate OpenAPI only if source route metadata changed**

If `app/main.py`, `app/routers/well_known.py`, or `app/routers/discover.py` changed route metadata:

```bash
uv run --with-requirements requirements.txt python scripts/export_openapi.py
```

Expected: `docs/openapi.json` reflects current app metadata.

- [ ] **Step 4: Run docs/discovery tests**

```bash
pytest tests/test_discovery.py tests/test_discovery_drift.py tests/test_discovery_consistency.py -q
```

Expected: pass.

- [ ] **Step 5: Commit docs and discovery narrative**

Stage exact changed docs/tests/source files:

```bash
git add DEMO_SCRIPT.md README.md docs/golden-path.md static/llm.txt \
  tests/test_discovery.py tests/test_discovery_drift.py tests/test_discovery_consistency.py
git add app/routers/well_known.py app/routers/discover.py app/main.py docs/openapi.json
git commit -m "docs: frame agent ops war room proof"
```

If a listed file was not changed, omit it from `git add`.

---

### Task 4: Final Verification And Release Readiness

**Files:**
- Modify if needed: `DEMO_SCRIPT.md`
- No app behavior changes unless a verification failure requires a small fix.

- [ ] **Step 1: Run targeted proof suite**

```bash
pytest tests/test_agent_ops_war_room_demo.py tests/test_mcp_trust.py tests/test_mcp_trust_mode.py tests/test_permits.py tests/test_receipts.py tests/test_audit_chain.py tests/test_trust_operator_inspection.py tests/test_golden_path.py tests/test_discovery.py tests/test_discovery_drift.py -q
```

Expected: pass.

- [ ] **Step 2: Run full test suite**

```bash
pytest -q
```

Expected: pass.

- [ ] **Step 3: Run executable demo one more time**

```bash
python scripts/agent_ops_war_room_demo.py
```

Expected: final line `AGENT OPS WAR ROOM: PASS`.

- [ ] **Step 4: Review final diff**

```bash
git status --short
git log --oneline -8
```

Expected: only intentional committed changes remain. If any unrelated dirty files remain from before the plan, report them explicitly and do not stage them.

- [ ] **Step 5: Final code review**

Dispatch one final reviewer to inspect the whole War Room proof for:

- false claims;
- demo fragility;
- trust-mode bypasses;
- double-charge regressions;
- stale generic docs;
- route/contract drift.

Fix any findings before finishing.

---

## Self-Review Checklist

- Spec coverage: The tasks create a one-command proof, test it, red-line narrative docs, and verify the full branch.
- Scope control: No new dashboard UI or broad marketplace expansion is included.
- Type consistency: The plan consistently uses `permit_id`, `idempotency_key`, `receipt_id`, `ledger_entry_id`, `audit_event_id`, and `policy_decision_id`.
- Risk handling: Existing dirty trust-plane files are treated as relevant work but must be staged explicitly.
