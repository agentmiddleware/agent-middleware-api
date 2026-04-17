# LangGraph Integration

Use Agent-Native Middleware tools directly in LangGraph agents.

## Installation

```bash
pip install agent-middleware-api langgraph langchain-core
```

## Quick Start

```python
from langgraph.prebuilt import create_react_agent
from agent_middleware import B2AClient, get_langgraph_tools

# Initialize client
client = B2AClient(
    api_url="http://localhost:8000",
    api_key="your-api-key",
    wallet_id="your-wallet-id"
)

# Get LangGraph-compatible tools
tools = get_langgraph_tools(client)

# Create agent
agent = create_react_agent(model, tools)

# Use the agent
result = agent.invoke({"messages": ["Check my balance and emit a telemetry event"]})
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

## Example: Research Agent

```python
from langgraph.prebuilt import create_react_agent

tools = get_langgraph_tools(client)

researcher = create_react_agent(
    model,
    tools=tools,
    state_modifier="You are a research agent. Use tools to gather information."
)

result = researcher.invoke({
    "messages": [
        "Research the latest AI developments and send results to researcher-002"
    ]
})
```

## Example: Autonomous Task Agent

```python
tools = get_langgraph_tools(client)

task_agent = create_react_agent(
    model,
    tools=tools,
    prompt="You autonomously complete tasks. Monitor your budget and heal when needed."
)

result = task_agent.invoke({
    "messages": ["Process the pending task queue"]
})
```
