# CrewAI Integration

Use Agent Middleware API tools in CrewAI agents and crews.

## Installation

No PyPI package is published. Work from a checkout of this repository:

```bash
git clone https://github.com/PetrefiedThunder/agent-middleware-api.git
cd agent-middleware-api
python -m pip install -r requirements.txt
python -m pip install crewai
```

Import from `framework_integrations` (the module in this repository); there is
no `agent_middleware` package.

## Quick Start

```python
from crewai import Agent, Crew
from framework_integrations import B2AClient, get_crewai_tools

# Initialize client
client = B2AClient(
    api_url="http://localhost:8000",
    api_key="your-api-key",
    wallet_id="your-wallet-id"
)

# Get CrewAI-compatible tools
tools = get_crewai_tools(client)

# Create agents
researcher = Agent(
    role="Research Analyst",
    goal="Find and analyze the best information",
    backstory="Expert at gathering and analyzing data",
    tools=tools
)

writer = Agent(
    role="Content Writer",
    goal="Create compelling content from research",
    backstory="Skilled writer who transforms complex info into clear content",
    tools=tools
)

# Create crew
crew = Crew(
    agents=[researcher, writer],
    tasks=[...],
    verbose=True
)

# Run crew
result = crew.kickoff()
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

## Example: Multi-Agent Research Crew

```python
from crewai import Agent, Crew, Task

researcher = Agent(
    role="Web Researcher",
    goal="Find the most relevant information online",
    tools=get_crewai_tools(client),
    verbose=True
)

analyst = Agent(
    role="Data Analyst",
    goal="Analyze research findings",
    tools=get_crewai_tools(client),
    verbose=True
)

tasks = [
    Task(
        description="Research latest developments in AI agents",
        agent=researcher
    ),
    Task(
        description="Analyze and summarize research findings",
        agent=analyst
    ),
]

crew = Crew(agents=[researcher, analyst], tasks=tasks)
result = crew.kickoff()
```
