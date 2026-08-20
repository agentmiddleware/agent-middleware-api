# AutoGen + Agent Middleware API

AutoGen integration for the Agent Middleware API, providing MCP tools and AWI web interactions as callable functions.

## Installation

This package is not published to PyPI. Install it from a checkout of
this repository:

```bash
git clone https://github.com/PetrefiedThunder/agent-middleware-api.git
cd agent-middleware-api
python -m pip install -e ./b2a_sdk
python -m pip install -e wrappers/autogen-agent-middleware
```

`b2a_sdk` must be installed from the local path first: this package
depends on `b2a-sdk>=0.3.0`, which is not on PyPI, so installing the
wrapper on its own fails to resolve. That installs the `autogen_b2a`
module used below.

## Quick Start

```python
import asyncio
from autogen_agentchat import ConversableAgent
from autogen_agentchat.agents import AssistantAgent
from autogen_b2a import B2AClient, B2AFunctionTool, register_b2a_tools

# Initialize tool
b2a_tool = B2AFunctionTool(
    api_url="http://localhost:8000",
    api_key="your-api-key",
    wallet_id="agent-001",
)

# Create agent
agent = ConversableAgent(
    name="assistant",
    system_message="You are a helpful assistant with access to MCP tools.",
    tools=b2a_tool.get_function_schemas(),
)

# Register tools
register_b2a_tools(agent, b2a_tool)

# Run agent
async def main():
    result = await agent.run(
        task="List available MCP tools and check the wallet balance"
    )
    print(result)

asyncio.run(main())
```

## Direct Tool Usage

> **Warning**: The `call_mcp_tool` method shown below bypasses the trust-plane
> loop (no permit, no idempotency key, no signed receipt, no replay protection).
> Each call dispatches and charges independently. Calling the same tool twice
> will execute and charge twice.
>
> For production use with replay protection and signed receipts, use
> `AgentMiddlewareClient` from `b2a_sdk` with the governed flow:
> `discover_tools() → create_permit() → invoke_tool()`.

```python
import asyncio
from autogen_b2a import B2AFunctionTool

tool = B2AFunctionTool(
    api_url="http://localhost:8000",
    api_key="...",
    wallet_id="...",
)

async def main():
    # List tools
    tools = await tool.list_mcp_tools()
    print(f"Available tools: {len(tools)}")

    # Call a tool (WARNING: bypasses trust plane, no replay protection)
    result = await tool.call_mcp_tool(
        "data-indexer",
        {"documents": ["doc1", "doc2"]},
    )
    print(result)

    # Check balance
    balance = await tool.get_wallet_balance()
    print(f"Balance: {balance} credits")

asyncio.run(main())
```

## Requirements

- Python 3.11+
- AutoGen AgentChat 0.2.0+
- httpx 0.25.0+
