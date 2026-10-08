# Pydantic AI Integration (governed)

Run Pydantic AI tools through the governed loop: each call is screened by a
local permit check, then dispatched with a caller-owned idempotency key, and
comes back with a signed receipt. Retries with the same key replay the
original receipt instead of charging again.

Honesty note: the local permit check is an optimistic mirror. The server
decision is authoritative and can still deny a call the mirror allowed.

## Installation

No PyPI package is published. Work from a checkout of this repository:

```bash
git clone https://github.com/PetrefiedThunder/agent-middleware-api.git
cd agent-middleware-api
python -m pip install -e ./b2a_sdk
python -m pip install pydantic-ai
```

Import from `framework_integrations` (the module in this repository); there is
no `agent_middleware` package.

## Quick Start

```python
from b2a_sdk.edge_client import GovernedEdgeSession
from framework_integrations import PydanticAIGovernedTools

session = await GovernedEdgeSession.open(sdk, permit_id="...", wallet_id="...")
tools = PydanticAIGovernedTools(session)

@tools.wrap
async def notes_write(note: str = "") -> dict:
    """Client-side stub; the registered tool runs through the governed loop."""
    raise AssertionError("stub body never runs locally")

result = await notes_write(note="hello", idempotency_key="run-1-notes-1")
receipt = notes_write.last_receipt  # typed Receipt for this call
```

Prefer `wrap` (no framework needed) in plain agents and tests. Use `as_tool`
when you need a `pydantic_ai.Tool`:

```python
tool = tools.as_tool(notes_write)
```

## Receipts per task

`last_receipt` is tracked per task, so concurrent calls never mix receipts.
Repeating a call with the same idempotency key returns the same receipt
without running the tool a second time.

## Sync functions are refused

The stub must be `async`. Wrapping a sync function raises `RuntimeError` at
call time, matching the `b2a_sdk` decorator behavior.

## Legacy path

The `get_langgraph_tools`, `get_llamaindex_tools`, and `get_autogen_tools`
factories in `framework_integrations/tools.py` are legacy and ungoverned: no
permit check, no idempotency key handling, no receipt. They emit
`DeprecationWarning` and stay for existing callers only.
