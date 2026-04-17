# LlamaIndex Integration

Use Agent-Native Middleware tools with LlamaIndex agents.

## Installation

```bash
pip install agent-middleware-api llama-index
```

## Quick Start

```python
from llama_index.core.agent import ReActAgent
from agent_middleware import B2AClient, get_llamaindex_tools

# Initialize client
client = B2AClient(
    api_url="http://localhost:8000",
    api_key="your-api-key",
    wallet_id="your-wallet-id"
)

# Get LlamaIndex-compatible tools
tools = get_llamaindex_tools(client)

# Create agent
agent = ReActAgent.from_tools(tools, llm=llm, verbose=True)

# Use the agent
result = agent.chat("Check my balance and emit a telemetry event")
```

## Available Tools

| Tool | Description | Credits |
|------|-------------|---------|
| `emit_telemetry` | Track agent events | 1 |
| `get_balance` | Check wallet balance | 0 |
| `send_message` | Message another agent | 1 |
| `ai_decide` | Make AI decision | 10 |
| `self_heal` | Diagnose and fix issues | 15 |
| `awi_session` | Start web automation | 5 |

## Example: Data Processing Agent

```python
from llama_index.core.agent import ReActAgent

tools = get_llamaindex_tools(client)

agent = ReActAgent.from_tools(
    tools,
    llm=llm,
    system_prompt="You are a data processing agent. Use tools to handle data."
)

result = agent.chat("Process the uploaded dataset")
```

## Example: Query Engine with Tools

```python
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.agent import FnRetriever

# Combine retrieval with B2A tools
tools = get_llamaindex_tools(client)

agent = ReActAgent.from_tools(tools, llm=llm)
result = agent.chat("Find documents and summarize them")
```
