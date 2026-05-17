# Phase 0 — Honest simulation surface (delivered)

Agent-first discovery is only credible if **simulation state** and **MCP tool
metadata** stay aligned with runtime settings. Phase 0 adds **generated**
inventory, **contract tests**, and **manifest annotations** — no hand-written
inventory that rots.

## Acceptance checklist

- [x] `scripts/generate_sim_inventory.py` writes `docs/simulations-inventory.md`
      and `docs/sim-inventory.json` from Settings + `runtime_mode` + local MCP tools.
- [x] `python scripts/generate_sim_inventory.py --check` exits 0 when files match CI.
- [x] `tests/test_health_sim_parity.py` — every `SIMULATION_MODE_*` in Settings
      maps 1:1 to `runtime_mode` services; `/health/dependencies` exposes the full set.
- [x] `tests/test_discovery_consistency.py` — every `/mcp/tools.json` tool includes
      honesty fields under `annotations` (see `docs/mcp-tool-metadata-spec.md`).
- [x] `app/services/mcp_integration_truth.py` — single mapping from registry
      `category` → simulation truth.
- [x] `app/audit/lightweight.py` — structured MCP invoke audit (JSON per log line).
- [x] CI runs `--check` on Python 3.12 (alongside OpenAPI check).

## How to ship after API changes

1. `python scripts/generate_sim_inventory.py`
2. `python scripts/export_openapi.py`
3. `pytest`
4. Commit generated `docs/simulations-inventory.md`, `docs/sim-inventory.json`,
   `docs/openapi.json` with code changes.

## Next (Phase 1)

Pick one vertical slice (e.g. Oracle durable index **or** Agent Comms store)
with written acceptance criteria before flipping a `SIMULATION_MODE_*` to false.
