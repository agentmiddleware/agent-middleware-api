"""B2A Client for LangChain integration.

Thin subclass of ``b2a_sdk.B2AEdgeClient``. All HTTP plumbing lives in the
shared base; this module exists so framework-specific helpers can hang off a
LangChain-flavored client name.
"""

from b2a_sdk import B2AEdgeClient


class B2AClient(B2AEdgeClient):
    """Client for Agent Middleware API with LangChain compatibility."""
