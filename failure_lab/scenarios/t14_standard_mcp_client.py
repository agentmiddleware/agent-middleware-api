"""Test 14 -- Standard MCP client."""

from __future__ import annotations

from failure_lab.configurations import GATEWAY_CONFIGURATIONS, Configuration, Target
from failure_lab.scenarios.base import ConfigurationResult, EventLog, Scenario, Verdict


class StandardMcpClient(Scenario):
    """Drive the standards-compliant transport with somebody else's client.

    The client here is the official MCP SDK (``mcp.ClientSession`` over
    ``mcp.client.streamable_http``). The product's own SDK is deliberately NOT
    used: a vendor SDK talking to its own server proves interoperability with
    itself.

    WHAT TO IMPLEMENT
    -----------------
    Use ``gateway.standard_endpoint_enabled()`` and
    ``gateway.mcp_client_session(tenant, idempotency_key=...)``.

    Steps, each recorded in ``extra["steps"]`` with a pass/fail and detail:

    ``initialize``            session.initialize() succeeds and negotiates a
                              protocol version; record the version.
    ``capability_negotiation`` the initialize result advertises tools.
    ``authentication``        a session with no API key is refused. Open a
                              second ``mcp_client_session``-style client with
                              the auth header stripped and record the refusal.
                              An exception during initialize IS the refusal;
                              catch it and record it rather than letting it
                              fail the run.
    ``tools_list``            the refund tool appears in ``list_tools()``.
    ``tools_call``            calling it settles, returns a receipt under
                              ``_meta["io.agentmiddleware/receipt"]``, and
                              produces exactly one downstream execution.
    ``error_handling``        a call to a nonexistent tool, and a call with a
                              malformed argument, both produce structured
                              errors rather than a transport break, and
                              neither produces a downstream effect.
    ``retry``                 a second session using the SAME
                              ``Idempotency-Key`` header re-issues the same
                              call and gets the SAME receipt id back, with no
                              second execution and no second debit.

    Also record, in ``extra["transports"]``, that the standards-compliant
    endpoint (``POST /mcp``, exercised here by the SDK) was tested separately
    from the project-specific compatibility endpoint (``POST /mcp/messages``,
    exercised by every other scenario). Drive one governed call over
    ``/mcp/messages`` here too, using a distinct key, purely to record that
    both transports were covered by this run.

    Verdict: ``PASS`` iff every step passes. ``FAIL`` otherwise, naming the
    step.
    """

    test_id = "T14"
    title = "Standard MCP client"
    claim = (
        "An independent, standards-compliant MCP client completes the full "
        "lifecycle against the standard endpoint, including an idempotent "
        "retry that does not execute twice."
    )
    tier = "fast"
    configurations = GATEWAY_CONFIGURATIONS
    inapplicable_reason = "a direct integration exposes no MCP endpoint of its own here"
    expected = {
        Configuration.DIRECT_NAIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.DIRECT_NATIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.GATEWAY_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NAIVE.value: Verdict.PASS.value,
    }
    limitations = (
        "One client implementation (the reference SDK) over one transport "
        "(Streamable HTTP, JSON mode). Not a conformance suite.",
        "The standard endpoint mints a permit server-side, so this exercises "
        "that path rather than a caller-supplied permit.",
    )

    async def run_configuration(self, target: Target, log: EventLog) -> ConfigurationResult:
        raise NotImplementedError
