# CrewAI + Agent Middleware API

CrewAI integration for the Agent Middleware API, providing MCP tools and AWI web interactions as CrewAI tools.

## Installation

This package is not published to PyPI. Install it from a checkout of
this repository:

```bash
git clone https://github.com/PetrefiedThunder/agent-middleware-api.git
cd agent-middleware-api
python -m pip install -e ./b2a_sdk
python -m pip install -e wrappers/crewai-agent-middleware
```

`b2a_sdk` must be installed from the local path first: this package
depends on `b2a-sdk>=0.3.0`, which is not on PyPI, so installing the
wrapper on its own fails to resolve. That installs the `crewai_b2a`
module used below.

## Quick Start

```python
from crewai import Agent
from crewai_b2a import B2AClient, CrewAIB2ATool

# Initialize tool
b2a_tool = CrewAIB2ATool(
    api_url="http://localhost:8000",
    api_key="your-api-key",
    wallet_id="agent-001",
)

# Create agent with B2A tool
researcher = Agent(
    role="Researcher",
    goal="Research topics using available tools",
    backstory="An expert researcher with access to MCP tools",
    tools=[b2a_tool],
)
```

## Operations

```python
# List available MCP tools
result = b2a_tool.run(operation="list_tools")

# Call an MCP tool
result = b2a_tool.run(
    operation="call_tool",
    tool_name="data-indexer",
    arguments={"documents": ["..."]},
)

# Create AWI session
result = b2a_tool.run(
    operation="create_session",
    target_url="https://shop.example.com",
)

# Check wallet balance
result = b2a_tool.run(operation="balance")
```

## Requirements

- Python 3.11+
- CrewAI 0.1.0+
- httpx 0.25.0+
