# Examples

These scripts are source-level demonstrations for the Agent Middleware API and
its Python SDK (`b2a_sdk`). Start with the [documentation guide](../docs/README.md)
for the supported evaluation, integration, security, and pilot paths.

## Start with the supported trust loop

For a real local server, your own wallet-scoped key, one governed tool, a
replay attempt, and offline receipt verification, run:

```bash
make quickstart
```

Then follow [docs/quickstart.md](../docs/quickstart.md). The scripts below are
not the supported design-partner deployment path.

## Prerequisites

- Python 3.11+
- The API running locally (see [docs/quickstart.md](../docs/quickstart.md))
- `b2a_sdk` installed: `python -m pip install -e './b2a_sdk[dev]'`

## Available Examples

### `dry_run_example.py` — Legacy Billing Simulation

Demonstrates safe cost estimation without affecting real wallet balances.

**What it shows:**
- Creating a sponsor wallet
- Simulating a multi-step workflow (`generate_video` → `distribute_clip` → `send_iot_message`)
- Comparing two workflow strategies side by side
- Single-shot charge estimation

**Status:** proof-surface demonstration only. It is not a pilot or production
integration path.

**Run locally:**

```bash
# Follow README.md "Run the API locally" first, then use local-only proof flags.
export ENABLE_PROOF_SURFACES=true
uv run --with-requirements requirements.txt uvicorn app.main:app \
  --host 127.0.0.1 --port 8000

# In another shell
B2A_API_KEY=<wallet-scoped-local-key> python examples/dry_run_example.py
```

**Note:** This example uses the **billing router**, which is a proof surface. Production-like deployments keep `ENABLE_PROOF_SURFACES=false`, so these endpoints return 404 unless explicitly enabled. See [docs/PROOF_SURFACES.md](../docs/PROOF_SURFACES.md).

---

### `mcp_tool_example.py` — MCP Tool Definition & Discovery

Demonstrates how to define MCP-enabled tools with decorators and how to read
the gateway manifest.

**Status:** source-level definition example. It does not enroll tools on any
server and does not configure the supported one-tool upstream gateway path;
use the [partner first-tool runbook](../docs/partner-first-tool-runbook.md)
for that.

**What it shows:**
- Defining billable tools with `@mcp_tool`
- Inspecting local tool metadata (no server enrollment)
- Generating a `tools.json` manifest from a running API

**Run:**

```bash
# 1. Show locally defined tools (local decorator metadata only;
#    nothing is enrolled on any server)
python examples/mcp_tool_example.py --register

# 2. List available tools from a running API
python examples/mcp_tool_example.py --list

# 3. Generate tools.json from a running API
python examples/mcp_tool_example.py --generate
```

Standalone serving (`--serve`) is retired: it exits with guidance instead of
starting a server. The retired shim never implemented the permit to receipt
loop and its invoke path targets a route the gateway does not expose.

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
