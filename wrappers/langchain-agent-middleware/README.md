# LangChain + Agent Middleware API

LangChain integration for the Agent Middleware API, providing MCP tools and AWI web interactions as LangChain tools.

## Installation

```bash
pip install langchain-agent-middleware
```

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

```python
from langchain_b2a import B2AClient, get_mcp_tools

client = B2AClient(api_key="...", wallet_id="...")
mcp_tool = get_mcp_tools(client)

# Call an MCP tool
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
