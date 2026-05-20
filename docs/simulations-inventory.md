# Simulation & MCP honesty inventory

**Auto-generated.** Do not edit by hand. Regenerate with:

```bash
python scripts/generate_sim_inventory.py
```

- **Local MCP tools:** 10

_Canonical timestamp and machine-readable snapshot: `docs/sim-inventory.json`._

## Runtime pillars (`SIMULATION_MODE_*`)

| Runtime service | Settings field | Current simulated |
|-----------------|----------------|-------------------|
| `agent_comms` | `SIMULATION_MODE_AGENT_COMMS` | `True` |
| `content_factory` | `SIMULATION_MODE_CONTENT_FACTORY` | `True` |
| `iot_bridge` | `SIMULATION_MODE_IOT_BRIDGE` | `True` |
| `media_engine` | `SIMULATION_MODE_MEDIA_ENGINE` | `True` |
| `oracle` | `SIMULATION_MODE_ORACLE` | `True` |
| `red_team` | `SIMULATION_MODE_RED_TEAM` | `True` |
| `rtaas` | `SIMULATION_MODE_RTAAS` | `True` |
| `telemetry_pm` | `SIMULATION_MODE_TELEMETRY_PM` | `True` |

## MCP tools (local registry only)

| Tool | simulation | integrationStatus | runtimeService | category |
|------|------------|-------------------|----------------|----------|
| `awi_dom_action_preview` | `True` | `simulated` | `agent_comms` | `agent_comms` |
| `awi_dom_bridge_session` | `True` | `simulated` | `agent_comms` | `agent_comms` |
| `awi_dom_state` | `True` | `simulated` | `agent_comms` | `agent_comms` |
| `awi_dom_sync` | `True` | `simulated` | `agent_comms` | `agent_comms` |
| `awi_memory_index` | `True` | `simulated` | `agent_comms` | `agent_comms` |
| `awi_passkey_challenge` | `True` | `simulated` | `agent_comms` | `agent_comms` |
| `awi_passkey_verify` | `True` | `simulated` | `agent_comms` | `agent_comms` |
| `awi_rag_query` | `True` | `simulated` | `agent_comms` | `agent_comms` |
| `awi_session_context` | `True` | `simulated` | `agent_comms` | `agent_comms` |
| `regengine.agent_reviews.list` | `False` | `platform` | `None` | `platform_fee` |
