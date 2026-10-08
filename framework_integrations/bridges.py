"""Governed bridges to the sibling framework wrappers.

The governed LangGraph and Pydantic AI wrappers live in this folder. The
governed CrewAI and OpenAI helpers live in ``wrappers/`` (they need those
frameworks installed). These two thin helpers are the in-folder path to
them: they lazily import the wrapper so this package still loads with no
framework installed, and they fail with a message that names the install
when the wrapper or framework is missing.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def get_crewai_governed_tool(
    *,
    api_key: str,
    wallet_id: str,
    base_url: str = "http://localhost:8000",
    permit_budget: Decimal = Decimal("100"),
    permit_ttl_minutes: int = 30,
) -> Any:
    """Build the governed CrewAI tool (permit, invoke, signed receipt).

    Every call goes through the permit plus idempotency key plus signed
    receipt loop. This is the supported CrewAI path:
    ``framework_integrations.get_crewai_tools`` only raises.
    """
    try:
        from crewai_b2a.tool import CrewAIB2ATool
    except ImportError as exc:
        raise ImportError(
            "The governed CrewAI tool needs the CrewAI wrapper installed: "
            "pip install -e wrappers/crewai-agent-middleware "
            "(plus the crewai package). See "
            "framework_integrations/README.crewai.md."
        ) from exc
    return CrewAIB2ATool(
        api_key=api_key,
        wallet_id=wallet_id,
        base_url=base_url,
        permit_budget=permit_budget,
        permit_ttl_minutes=permit_ttl_minutes,
    )


def get_openai_governed_runner(
    *,
    api_key: str,
    wallet_id: str,
    run_id: str,
    base_url: str = "http://localhost:8000",
) -> Any:
    """Build the governed OpenAI tool runner for one agent run.

    The runner derives one idempotency key per model tool call id and
    persists it before any network call, so retries replay the original
    receipt instead of charging again. ``run_id`` must stay the same when
    a crashed run is resumed.
    """
    try:
        from openai_b2a.client import B2AClient as OpenAIB2AClient
        from openai_b2a.runner import GovernedToolRunner
    except ImportError as exc:
        raise ImportError(
            "The governed OpenAI runner needs the OpenAI wrapper installed: "
            "pip install -e wrappers/openai-agent-middleware "
            "(plus the openai package)."
        ) from exc
    client = OpenAIB2AClient(api_key=api_key, base_url=base_url)
    return GovernedToolRunner(client, wallet_id=wallet_id, run_id=run_id)


__all__ = ["get_crewai_governed_tool", "get_openai_governed_runner"]
