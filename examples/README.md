# Examples

These scripts demonstrate how to interact with the Agent Middleware API using the Python SDK (`b2a_sdk`).

## Prerequisites

- Python 3.11+
- The API running locally (see [README.md](../README.md) "Run the API locally")
- `b2a_sdk` installed: `python -m pip install -e './b2a_sdk[dev]'`

## Available Examples

### `dry_run_example.py` — Billing Simulation

Demonstrates safe cost estimation without affecting real wallet balances.

**What it shows:**
- Creating a sponsor wallet
- Simulating a multi-step workflow (`generate_video` → `distribute_clip` → `send_iot_message`)
- Comparing two workflow strategies side by side
- Single-shot charge estimation

**Run:**

```bash
# The API must be running with proof surfaces enabled
ENABLE_PROOF_SURFACES=true uvicorn app.main:app

# In another shell
B2A_API_KEY= python examples/dry_run_example.py
```

**Note:** This example uses the **billing router**, which is a proof surface. Production-like deployments keep `ENABLE_PROOF_SURFACES=false`, so these endpoints return 404 unless explicitly enabled. See [docs/PROOF_SURFACES.md](../docs/PROOF_SURFACES.md).

---

### `mcp_tool_example.py` — MCP Tool Registration & Invocation

Demonstrates how to create, register, and invoke MCP-enabled tools.

**What it shows:**
- Defining billable tools with `@mcp_tool`
- Registering tools with the service registry
- Generating a `tools.json` manifest
- Running a standalone MCP server

**Run:**

```bash
# 1. Register tools (typically done at app startup)
python examples/mcp_tool_example.py --register

# 2. List available tools
python examples/mcp_tool_example.py --list

# 3. Generate tools.json
python examples/mcp_tool_example.py --generate

# 4. Run standalone MCP server
python examples/mcp_tool_example.py --serve
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `ModuleNotFoundError: No module named 'b2a_sdk'` | SDK not installed or wrong Python path | Run `python -m pip install -e './b2a_sdk[dev]'` from the repo root |
| `404 wallet_not_found` | Using a made-up wallet ID | Let the server create the wallet (as `dry_run_example.py` does) |
| `404` on dry-run endpoints | Proof surfaces disabled | Start the API with `ENABLE_PROOF_SURFACES=true` |
| `Connection refused` | API not running | Start `uvicorn app.main:app` first |

---

## Contributing New Examples

If you add a new example, please:
1. Include a module docstring explaining what it demonstrates
2. Add a "Run:" section with copy-pasteable commands
3. Update this README with a new subsection
4. Note if the example depends on proof surfaces
