# LangChain + Agent Middleware API

LangChain integration for the Agent Middleware API, providing MCP tools and AWI web interactions as LangChain tools.

## Installation

This package is not published to PyPI. Install it from a checkout of
this repository:

```bash
git clone https://github.com/PetrefiedThunder/agent-middleware-api.git
cd agent-middleware-api
python -m pip install -e ./b2a_sdk
python -m pip install -e wrappers/langchain-agent-middleware
```

`b2a_sdk` must be installed from the local path first: this package
depends on `b2a-sdk>=0.3.0`, which is not on PyPI, so installing the
wrapper on its own fails to resolve. That installs the `langchain_b2a`
module used below.

## Quick Start

```python
from langchain_b2a import B2AClient, get_langgraph_tools
from langgraph.prebuilt import create_react_agent

# Initialize client
client = B2AClient(
    api_url="http://localhost:8000",
    api_key="your-api-key",
    wallet_id="agent-001",
)

# Get LangGraph-compatible tools
tools = get_langgraph_tools(client)

# Create agent
model = ChatOpenAI(model="gpt-4o")
agent = create_react_agent(model, tools)
```

## MCP Tools

> **Warning**: The LangChain wrapper's MCP tool calls bypass the trust-plane
> loop (no permit, no idempotency key, no signed receipt, no replay protection).
> Each call dispatches and charges independently. Retrying a call will execute
> and charge again.
>
> For production use with replay protection and signed receipts, use
> `AgentMiddlewareClient` from `b2a_sdk` with the governed flow:
> `discover_tools() → create_permit() → invoke_tool()`.

```python
from langchain_b2a import B2AClient, get_mcp_tools

client = B2AClient(api_key="...", wallet_id="...")
mcp_tool = get_mcp_tools(client)

# Call an MCP tool (WARNING: bypasses trust plane, no replay protection)
result = await mcp_tool.ainvoke({
    "tool_name": "data-indexer",
    "arguments": {"documents": ["..."]},
})
```

## AWI Web Interactions

```python
from langchain_b2a import B2AClient
from langchain_b2a.tools import create_awi_tool

client = B2AClient(api_key="...", wallet_id="...")
awi_tool = create_awi_tool(client)

# Execute web actions
result = await awi_tool.ainvoke({
    "target_url": "https://shop.example.com",
    "action": "search_and_sort",
    "parameters": {"query": "laptops", "sort_by": "price"},
})
```

## Requirements

- Python 3.11+
- LangChain 0.1.0+
- httpx 0.25.0+
