# Archived announcement draft

> **Status: superseded — do not publish.**
>
> The former draft described Agent Middleware API as a broad, production-ready
> agent platform and advertised integrations and package installs that were not
> verified. It also predated the current design-partner direction. It is retained
> only as a record of messaging that should not be reused.

## Current public-message boundary

Agent Middleware API is a governed MCP control layer for one narrow loop:

```text
discover -> authenticate -> authorize -> invoke -> meter -> receipt -> audit -> govern
```

Public messaging may say that the gateway provides scoped permits, retry-safe
metering, signed receipts, and audit evidence for governed MCP tool calls.
Public messaging must not claim customer traction, production readiness for
arbitrary agent fleets, published SDK packages, settlement, compliance, or a
complete agent platform.

The next outbound message is not a launch thread. It is a personalized request
to a qualified platform engineering, AI infrastructure, or security operator to
bring one real internal MCP tool to a scoped design-partner pilot. Use the
verified booking and monitored email contacts on
`https://www.thisisatest.tech/`; do not publish until both flows work.

Canonical links:

- Marketing: `https://www.thisisatest.tech/`
- API discovery: `https://api.thisisatest.tech/.well-known/agent.json`
- MCP tools: `https://api.thisisatest.tech/mcp/tools.json`
- Proof: `https://www.thisisatest.tech/proof/`

The proof must be labeled “self-issued live gateway proof, not customer
traction.” Pricing remains private during fit qualification.
