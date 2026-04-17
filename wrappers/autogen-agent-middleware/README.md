# AutoGen + Agent Middleware API

AutoGen integration for the Agent Middleware API, providing MCP tools and AWI web interactions as callable functions.

## Installation

```bash
pip install autogen-agent-middleware
```

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

    # Call a tool
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
