"""
Agent-Native Middleware — Framework Integrations
================================================

Integration packages for popular agent frameworks:
- LangGraph
- CrewAI
- AutoGen
- LlamaIndex

## Installation

```bash
pip install agent-middleware-api
```

## Quick Start

```python
from agent_middleware import B2AClient, get_langgraph_tools, get_crewai_tools

# Initialize client
client = B2AClient(
    api_url="http://localhost:8000",
    api_key="your-api-key",
    wallet_id="your-wallet-id"
)

# Get tools for your framework
langgraph_tools = get_langgraph_tools(client)
crewai_tools = get_crewai_tools(client)
```

## Framework-Specific Guides

See individual README files for each framework:
- README.langgraph.md
- README.crewai.md
- README.autogen.md
- README.llamaindex.md
"""

__version__ = "0.4.1"

from .client import B2AClient, B2AConfig
from .tools import (
    get_langgraph_tools,
    get_crewai_tools,
    get_autogen_tools,
    get_llamaindex_tools,
)

__all__ = [
    "B2AClient",
    "B2AConfig",
    "get_langgraph_tools",
    "get_crewai_tools",
    "get_autogen_tools",
    "get_llamaindex_tools",
]
