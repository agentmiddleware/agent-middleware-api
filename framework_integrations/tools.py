"""
Framework-Specific Tool Adapters
===============================
Convert B2A tools to framework-specific formats.
"""

from typing import Any, Callable, TypeVar, Union
from .client import B2AClient

T = TypeVar("T")


def get_langgraph_tools(client: B2AClient) -> list[Any]:
    """
    Get LangGraph-compatible tools from B2A client.

    Usage:
    ```python
    from langgraph.prebuilt import create_react_agent
    from agent_middleware import B2AClient, get_langgraph_tools

    client = B2AClient(api_key="...", wallet_id="...")
    tools = get_langgraph_tools(client)

    agent = create_react_agent(model, tools)
    result = agent.invoke({"messages": ["..."]})
    ```

    Returns a list of LangChain BaseTool-compatible objects.
    """
    try:
        from langchain_core.tools import tool
    except ImportError:
        raise ImportError("LangGraph not installed. Run: pip install langgraph")

    @tool
    def emit_telemetry(event: str, properties: str = "{}") -> str:
        """Emit a telemetry event to track agent activity.

        Args:
            event: Name of the event (e.g., 'task_completed', 'error')
            properties: JSON string of event properties
        """
        import json

        props = json.loads(properties) if properties else {}
        return client.emit_telemetry(event, props)

    @tool
    def get_balance() -> str:
        """Get the current wallet balance in credits."""
        balance = client.get_balance()
        return f"Current balance: {balance} credits"

    @tool
    def send_message(to_agent: str, content: str, priority: str = "normal") -> str:
        """Send a message to another agent.

        Args:
            to_agent: Target agent ID
            content: Message content (JSON string)
            priority: Message priority (normal, high, critical)
        """
        import json

        content_dict = json.loads(content)
        return client.send_message(to_agent, content_dict, priority)

    @tool
    def ai_decide(context: str, options: str) -> str:
        """Make an AI-powered decision based on context.

        Args:
            context: JSON string with decision context
            options: JSON array of option strings
        """
        import json

        ctx = json.loads(context)
        opts = json.loads(options)
        decision = client.decide(ctx, opts)
        return f"Decision: {decision}"

    @tool
    def self_heal(issue: str, error_log: str = "{}") -> str:
        """AI-powered self-healing diagnostics.

        Args:
            issue: Description of the problem
            error_log: JSON string with error context
        """
        import json

        ctx = json.loads(error_log)
        result = client.heal(issue, ctx)
        return str(result)

    @tool
    def awi_session(target_url: str, max_steps: int = 100) -> str:
        """Create an AWI session for web automation.

        Args:
            target_url: URL of the website to interact with
            max_steps: Maximum steps for the session
        """
        result = client.create_awi_session(target_url, max_steps)
        return f"Session created: {result.get('session_id', 'unknown')}"

    return [
        emit_telemetry,
        get_balance,
        send_message,
        ai_decide,
        self_heal,
        awi_session,
    ]


def get_crewai_tools(client: B2AClient) -> list[Any]:
    """
    Get CrewAI-compatible tools from B2A client.

    Usage:
    ```python
    from crewai import Agent
    from agent_middleware import B2AClient, get_crewai_tools

    client = B2AClient(api_key="...", wallet_id="...")
    tools = get_crewai_tools(client)

    researcher = Agent(
        role="Researcher",
        goal="Find and analyze information",
        tools=tools
    )
    ```

    Returns a list of CrewAI Tool objects.
    """
    try:
        from crewai.tools import BaseTool
        from pydantic import Field
    except ImportError:
        raise ImportError("CrewAI not installed. Run: pip install crewai")

    class TelemetryTool(BaseTool):
        name: str = "emit_telemetry"
        description: str = "Emit a telemetry event to track agent activity"

        def _run(self, event: str, properties: str = "{}") -> str:
            import json

            props = json.loads(properties) if properties else {}
            return client.emit_telemetry(event, props)

    class BalanceTool(BaseTool):
        name: str = "get_balance"
        description: str = "Get the current wallet balance in credits"

        def _run(self) -> str:
            balance = client.get_balance()
            return f"Current balance: {balance} credits"

    class MessageTool(BaseTool):
        name: str = "send_message"
        description: str = "Send a message to another agent"

        def _run(self, to_agent: str, content: str, priority: str = "normal") -> str:
            import json

            content_dict = json.loads(content)
            return client.send_message(to_agent, content_dict, priority)

    class DecideTool(BaseTool):
        name: str = "ai_decide"
        description: str = "Make an AI-powered decision"

        def _run(self, context: str, options: str) -> str:
            import json

            ctx = json.loads(context)
            opts = json.loads(options)
            decision = client.decide(ctx, opts)
            return f"Decision: {decision}"

    class HealTool(BaseTool):
        name: str = "self_heal"
        description: str = "AI-powered self-healing diagnostics"

        def _run(self, issue: str, error_log: str = "{}") -> str:
            import json

            ctx = json.loads(error_log)
            result = client.heal(issue, ctx)
            return str(result)

    class AWISessionTool(BaseTool):
        name: str = "awi_session"
        description: str = "Create an AWI session for web automation"

        def _run(self, target_url: str, max_steps: int = 100) -> str:
            result = client.create_awi_session(target_url, max_steps)
            return f"Session created: {result.get('session_id', 'unknown')}"

    return [
        TelemetryTool(),
        BalanceTool(),
        MessageTool(),
        DecideTool(),
        HealTool(),
        AWISessionTool(),
    ]


def get_autogen_tools(client: B2AClient) -> list[Any]:
    """
    Get AutoGen-compatible tools from B2A client.

    Usage:
    ```python
    import autogen
    from agent_middleware import B2AClient, get_autogen_tools

    client = B2AClient(api_key="...", wallet_id="...")
    tools = get_autogen_tools(client)

    agent = autogen.AssistantAgent(
        name="agent",
        llm_config=llm_config,
        function_map=tools
    )
    ```

    Returns a dict mapping function names to functions for AutoGen.
    """
    return {
        "emit_telemetry": client.emit_telemetry,
        "get_balance": client.get_balance,
        "send_message": client.send_message,
        "ai_decide": client.decide,
        "self_heal": client.heal,
        "create_awi_session": client.create_awi_session,
    }


def get_llamaindex_tools(client: B2AClient) -> list[Any]:
    """
    Get LlamaIndex-compatible tools from B2A client.

    Usage:
    ```python
    from llama_index.core.agent import ReActAgent
    from llama_index.core.tools import FunctionTool
    from agent_middleware import B2AClient, get_llamaindex_tools

    client = B2AClient(api_key="...", wallet_id="...")
    tools = get_llamaindex_tools(client)

    agent = ReActAgent.from_tools(tools, llm=llm)
    ```

    Returns a list of LlamaIndex FunctionTool objects.
    """
    try:
        from llama_index.core.tools import FunctionTool
    except ImportError:
        raise ImportError("LlamaIndex not installed. Run: pip install llama-index")

    def emit_telemetry(event: str, properties: str = "{}") -> str:
        """Emit a telemetry event to track agent activity."""
        import json

        props = json.loads(properties) if properties else {}
        return str(client.emit_telemetry(event, props))

    def get_balance() -> str:
        """Get the current wallet balance in credits."""
        balance = client.get_balance()
        return f"Current balance: {balance} credits"

    def send_message(to_agent: str, content: str, priority: str = "normal") -> str:
        """Send a message to another agent."""
        import json

        content_dict = json.loads(content)
        return str(client.send_message(to_agent, content_dict, priority))

    def ai_decide(context: str, options: str) -> str:
        """Make an AI-powered decision based on context."""
        import json

        ctx = json.loads(context)
        opts = json.loads(options)
        decision = client.decide(ctx, opts)
        return f"Decision: {decision}"

    def self_heal(issue: str, error_log: str = "{}") -> str:
        """AI-powered self-healing diagnostics."""
        import json

        ctx = json.loads(error_log)
        result = client.heal(issue, ctx)
        return str(result)

    def awi_session(target_url: str, max_steps: int = 100) -> str:
        """Create an AWI session for web automation."""
        result = client.create_awi_session(target_url, max_steps)
        return f"Session created: {result.get('session_id', 'unknown')}"

    return [
        FunctionTool.from_defaults(fn=emit_telemetry, name="emit_telemetry"),
        FunctionTool.from_defaults(fn=get_balance, name="get_balance"),
        FunctionTool.from_defaults(fn=send_message, name="send_message"),
        FunctionTool.from_defaults(fn=ai_decide, name="ai_decide"),
        FunctionTool.from_defaults(fn=self_heal, name="self_heal"),
        FunctionTool.from_defaults(fn=awi_session, name="awi_session"),
    ]
