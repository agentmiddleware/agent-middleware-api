# LangChain + Agent Middleware API

LangChain integration for the Agent Middleware API via governed **permit → invoke → receipt** flow.

All tool invocations go through the trust plane: scoped permits, signed receipts, replay protection, and metered billing.

**Status:** source-only integration example, not a published package. Start
with the [documentation guide](../../docs/README.md) to evaluate the supported
one-tool MCP path before adopting a framework wrapper.

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

### Running the tests

From the repository root, in a fresh virtual environment:

```bash
python -m pip install -e ./b2a_sdk -e "wrappers/langchain-agent-middleware[dev]"
python -m pytest wrappers/langchain-agent-middleware/tests
```

## Quick Start (Governed Flow)

```python
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI  # any tool-calling chat model; not a dependency

from langchain_b2a import B2AClient, get_langgraph_tools

# Initialize client
client = B2AClient(api_key="your-api-key")

# Get LangGraph-compatible tools with wallet_id
tools = get_langgraph_tools(client, wallet_id="agent-001")

# Create agent. LangGraph 1.x deprecates langgraph.prebuilt.create_react_agent
# in favour of langchain.agents.create_agent.
model = ChatOpenAI(model="gpt-4o")
agent = create_agent(model, tools)

# The tools are async-only (the SDK client is an httpx.AsyncClient), so drive
# the agent with the async entry point.
result = await agent.ainvoke({"messages": [{"role": "user", "content": "..."}]})
```

## Async only

Both tools implement only the async path. `await tool.ainvoke(...)` and
`await agent.ainvoke(...)` work; `tool.invoke(...)` raises
`NotImplementedError` because there is no sync implementation to fall back to.

## MCP Tools via Governed Flow

```python
from langchain_b2a import B2AClient, get_mcp_tools

client = B2AClient(api_key="...")
mcp_tools = get_mcp_tools(client, wallet_id="agent-001")
tool = mcp_tools[0]

# Call an MCP tool with caller-supplied idempotency keys
# The wrapper creates a permit, invokes the tool, and returns a signed receipt
result = await tool.ainvoke({
    "tool_name": "data-indexer",
    "idempotency_key": "unique-invoke-123",  # REQUIRED: caller must supply
    "permit_idempotency_key": "permit-invoke-123",  # REQUIRED: stable for replay
    "arguments": {"documents": ["..."]},
})

# Result includes signed receipt
# {'content': [...], 'receipt_id': '...', 'credits_charged': '2', 'signature': '...'}
```

## Idempotency and Replay Protection

Both `idempotency_key` and `permit_idempotency_key` are **required** and must be supplied by the caller. Do not auto-generate keys.

An identical replay with the same invocation key returns the original receipt
without recharging. `idempotency_key` identifies one governed invocation, and
the gateway rejects that key reused with changed invocation input with an
idempotency conflict (HTTP 409). `permit_idempotency_key` makes permit creation
repeatable; it does not make a changed invocation an idempotent replay.

```python
# First call: charges credits
result1 = await tool.ainvoke({
    "tool_name": "partner.search",
    "idempotency_key": "search-abc-123",
    "permit_idempotency_key": "permit-abc-123",
    "arguments": {"query": "test"},
})

# Valid replay: same request returns the cached receipt, no additional charge
result2 = await tool.ainvoke({
    "tool_name": "partner.search",
    "idempotency_key": "search-abc-123",  # same invoke key
    "permit_idempotency_key": "permit-abc-123",  # same permit key
    "arguments": {"query": "test"},  # same arguments
})
```

## Permit Configuration

Control permit budget and TTL:

```python
from decimal import Decimal

tools = get_mcp_tools(
    client,
    wallet_id="agent-001",
    permit_budget=Decimal("50"),  # max 50 credits per permit
    permit_ttl_minutes=15,         # permit expires in 15 minutes
)
```

## Requirements

- Python 3.11+
- LangChain 1.3.9+ and LangGraph 1.0.10+ (the range `pyproject.toml` declares)
- httpx 0.25.0+
