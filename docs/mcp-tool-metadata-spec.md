# MCP tool metadata — honesty fields (Phase 0)

Autonomous clients use `GET /mcp/tools.json` as the canonical tool list. Every
tool in that manifest includes **annotations** beyond pricing:

| Field | Type | Meaning |
|-------|------|--------|
| `simulation` | boolean | `true` if this tool’s billing category maps to a runtime pillar that is **currently simulated** (`is_simulation(category)`). |
| `integrationStatus` | string | `simulated` — pillar is synthetic; `integrated` — pillar flag is off (real path expected); `platform` — not a gated pillar (billing, sandbox helper, etc.). |
| `runtimeService` | string or omitted | When status is `simulated` or `integrated`, the **runtime registry** pillar id (`oracle`, `agent_comms`, …). Omitted / `null` for `platform`. |

Existing fields (`creditsPerCall`, `unitName`, `category`, …) are unchanged.

## Implementation

- Logic: `app/services/mcp_integration_truth.py` → `truth_for_category(category)`.
- Applied in: `app/services/mcp_generator.py` → `_service_to_mcp_tool`.

## Agent integration snippet

After `tools/list` or fetching `tools.json`, filter or label:

```python
for tool in manifest["tools"]:
    ann = tool.get("annotations") or {}
    if ann.get("simulation") is True:
        # Synthetic outcomes for this deployment unless SIMULATION_MODE_* is off
        ...
```

Cross-check deployment truth with `GET /health/dependencies` → `simulation_modes`.
