# X Announcement Thread

## Copy-paste ready for @SmallFounder or project account

---

**1/7**
Just shipped **v1.1.0** of agent-middleware-api — the first open-source B2A platform with full Agentic Web Interface (AWI) support.

We took the vision from arXiv:2506.10953 ("Build the web for agents, not agents for the web") and made it real.

**Live at:** https://api-service-production-433c.up.railway.app

---

**2/7**
What's inside:
- MCP Server Generator + dynamic proxy
- Full AWI control plane (stateful sessions, 13 unified higher-level actions, progressive representations, task queues)
- Bidirectional Playwright DOM bridge
- WebAuthn/passkey protection for high-risk actions
- Built-in RAG over AWI session memory
- Behavioral + dry-run sandboxes
- KYC, velocity monitoring, key rotation, billing, transfers

---

**3/7**
Everything is self-hostable, agent-first, and now fully discoverable:
- https://api-service-production-433c.up.railway.app/.well-known/agent.json
- https://api-service-production-433c.up.railway.app/v1/discover
- https://api-service-production-433c.up.railway.app/mcp/tools.json
- https://api-service-production-433c.up.railway.app/llm.txt

Autonomous agents can find, evaluate, and use it with zero human help.

---

**4/7**
Plus official wrappers so it's dead simple to integrate:
- langchain-agent-middleware
- crewai-agent-middleware  
- autogen-agent-middleware

Just `pip install` and go.

---

**5/7**
We also added production hardening: structured logging, circuit breakers, graceful shutdown, health endpoints, and background cleanup.

---

**6/7**
The platform is now ready for real agent fleets.

If you're building agents (or want your website to be agent-native), this is the open-source control plane you've been waiting for.

---

**7/7**
Repo: https://github.com/PetrefiedThunder/agent-middleware-api
Try it: `curl https://api-service-production-433c.up.railway.app/mcp/tools.json`

Also submitted to the official MCP Registry: https://registry.modelcontextprotocol.io/servers

Feedback, stars, and PRs very welcome.

#AI #AgenticAI #MCP #OpenSource #AgentMiddleware
