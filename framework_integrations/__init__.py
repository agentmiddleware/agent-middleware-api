"""
Agent Middleware API — Framework Integrations
================================================

Start with the governed wrappers: every call runs the permit plus
idempotency key plus signed receipt loop.

- LangGraph: ``LangGraphGovernedTools`` (this folder)
- Pydantic AI: ``PydanticAIGovernedTools`` (this folder)
- CrewAI: ``bridges.get_crewai_governed_tool`` (wraps
  ``wrappers/crewai-agent-middleware``)
- OpenAI: ``bridges.get_openai_governed_runner`` (wraps
  ``wrappers/openai-agent-middleware``)

## Installation

No PyPI package is published; import this module from a checkout of the
repository after `python -m pip install -r requirements.txt`.

## Quick Start (governed)

```python
from b2a_sdk.edge_client import GovernedEdgeSession
from framework_integrations import LangGraphGovernedTools

session = await GovernedEdgeSession.open(sdk, permit_id="...", wallet_id="...")
tools = LangGraphGovernedTools(session)

@tools.wrap
async def notes_write(note: str = "") -> dict:
    "Client-side stub; the registered tool runs through the governed loop."
    raise AssertionError("stub body never runs locally")

result = await notes_write(note="hello", idempotency_key="run-1-notes-1")
receipt = notes_write.last_receipt  # typed Receipt for this call
```

## Legacy factories (UNGOVERNED)

`get_langgraph_tools`, `get_llamaindex_tools`, and `get_autogen_tools`
skip permits and receipts and emit `DeprecationWarning`. They stay for
existing callers only.

`get_crewai_tools` raises `NotImplementedError`: CrewAI runs each async tool
on a fresh event loop, which the async `B2AClient` cannot survive between
calls. Use the governed `bridges.get_crewai_governed_tool` instead.

## Framework-Specific Guides

See individual README files for each framework:
- README.langgraph.md
- README.pydantic_ai.md
- README.crewai.md
- README.autogen.md
- README.llamaindex.md
"""

__version__ = "0.4.1"

from .bridges import get_crewai_governed_tool, get_openai_governed_runner
from .client import B2AClient, B2AConfig
from .tools import (
    get_langgraph_tools,
    get_crewai_tools,
    get_autogen_tools,
    get_llamaindex_tools,
)

# Governed middleware surfaces (permit-verified in-process validation over the
# b2a_sdk governed loop). Exported lazily via PEP 562 so importing this
# package keeps working when the b2a_sdk sources are not on the path (the
# legacy client/tools above need only httpx) — and the middleware modules
# themselves import pydantic_ai / langgraph only inside their as_*_tool
# functions, so neither framework needs to be installed either.
_LAZY_ATTRS = {
    "LangGraphGovernedTools": "langgraph_middleware",
    "PydanticAIGovernedTools": "pydantic_ai_middleware",
}


def __getattr__(name):
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value  # cache so later access is a plain attribute lookup
    return value


__all__ = [
    "B2AClient",
    "B2AConfig",
    "LangGraphGovernedTools",
    "PydanticAIGovernedTools",
    "get_crewai_governed_tool",
    "get_openai_governed_runner",
    "get_langgraph_tools",
    "get_crewai_tools",
    "get_autogen_tools",
    "get_llamaindex_tools",
]
