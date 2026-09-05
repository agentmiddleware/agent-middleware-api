# AutoGen + Agent Middleware API

AutoGen integration for the Agent Middleware API via governed **permit → invoke → receipt** flow.

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
python -m pip install -e wrappers/autogen-agent-middleware
```

`b2a_sdk` must be installed from the local path first: this package
depends on `b2a-sdk>=0.3.0`, which is not on PyPI, so installing the
wrapper on its own fails to resolve. That installs the `autogen_b2a`
module used below.

### Running the tests

From the repository root, in a fresh virtual environment:

```bash
python -m pip install -e ./b2a_sdk -e "wrappers/autogen-agent-middleware[dev]"
python -m pytest wrappers/autogen-agent-middleware/tests
```

## Quick Start (Governed Flow)

This wrapper targets AutoGen 0.2 (`import autogen`, `ConversableAgent`,
`register_function`). The assistant advertises the tool schemas through its
LLM config; a separate executor agent runs the registered functions.

```python
import asyncio
from autogen import AssistantAgent, UserProxyAgent
from autogen_b2a import B2AFunctionTool, register_b2a_tools

# Initialize tool with required wallet_id and api_key
b2a_tool = B2AFunctionTool(
    api_key="your-api-key",
    wallet_id="agent-001",
)

# The assistant proposes tool calls; the schemas go in its llm_config.
assistant = AssistantAgent(
    name="assistant",
    system_message="You are a helpful assistant with access to MCP tools.",
    llm_config={
        "config_list": [{"model": "gpt-4o", "api_key": "your-openai-key"}],
        "tools": b2a_tool.get_function_schemas(),
    },
)

# The executor runs the registered functions.
executor = UserProxyAgent(
    name="executor",
    human_input_mode="NEVER",
    code_execution_config=False,
)
register_b2a_tools(executor, b2a_tool)

# The registered functions are async. AutoGen 0.2 awaits them only on the
# async chat path, so start the chat with a_initiate_chat, not initiate_chat.
async def main():
    await executor.a_initiate_chat(
        assistant,
        message="Discover available MCP tools and check the wallet balance",
    )

asyncio.run(main())
```

## Async only

`B2AFunctionTool` methods are coroutines, and `register_b2a_tools` registers
them as such. AutoGen 0.2's sync `initiate_chat` calls registered functions
without awaiting, so it would record the coroutine object as the tool result
instead of the signed receipt. Use `a_initiate_chat` (or await the methods
directly, as below).

## Direct Tool Usage (Governed Flow)

```python
import asyncio
from autogen_b2a import B2AFunctionTool

tool = B2AFunctionTool(
    api_key="...",
    wallet_id="agent-001",
)

async def main():
    # Discover tools
    tools = await tool.discover_tools()
    print(f"Available tools: {len(tools)}")

    # Call a tool with caller-supplied idempotency keys
    # The wrapper creates a permit, invokes the tool, and returns a signed receipt
    result = await tool.call_mcp_tool(
        tool_name="data-indexer",
        idempotency_key="unique-invoke-123",  # REQUIRED: caller must supply
        permit_idempotency_key="permit-invoke-123",  # REQUIRED: stable for replay
        arguments={"documents": ["doc1", "doc2"]},
    )
    print(result)
    # Result: {'content': [...], 'receipt_id': '...', 'credits_charged': '2', 'signature': '...'}

    # Check balance
    balance = await tool.get_wallet_balance()
    print(f"Balance: {balance} credits")

asyncio.run(main())
```

## Idempotency and Replay Protection

Both `idempotency_key` and `permit_idempotency_key` are **required** and must be supplied by the caller. Do not auto-generate keys.

An identical replay with the same invocation key returns the original receipt
without recharging. `idempotency_key` identifies one governed invocation, and
the gateway rejects that key reused with changed invocation input with an
idempotency conflict (HTTP 409). `permit_idempotency_key` makes permit creation
repeatable; it does not make a changed invocation an idempotent replay.

```python
async def main():
    tool = B2AFunctionTool(api_key="...", wallet_id="agent-001")

    # First call: charges credits
    result1 = await tool.call_mcp_tool(
        tool_name="partner.search",
        idempotency_key="search-abc-123",
        permit_idempotency_key="permit-abc-123",
        arguments={"query": "test"},
    )

    # Valid replay: same request returns the cached receipt, no additional charge
    result2 = await tool.call_mcp_tool(
        tool_name="partner.search",
        idempotency_key="search-abc-123",  # same invoke key
        permit_idempotency_key="permit-abc-123",  # same permit key
        arguments={"query": "test"},  # same arguments
    )
```

## Permit Configuration

Control permit budget and TTL:

```python
from decimal import Decimal

tool = B2AFunctionTool(
    api_key="your-api-key",
    wallet_id="agent-001",
    permit_budget=Decimal("50"),  # max 50 credits per permit
    permit_ttl_minutes=15,         # permit expires in 15 minutes
)
```

## Requirements

- Python 3.11+
- AutoGen 0.2.x (`autogen-agentchat>=0.2.0,<0.4`). The 0.4+ rewrite ships a
  different package (`autogen_agentchat`) with a different agent and tool API
  and is not supported by this wrapper.
- httpx 0.25.0+
