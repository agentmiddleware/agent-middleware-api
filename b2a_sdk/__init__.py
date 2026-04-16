"""
B2A SDK - Agent-Native Middleware API Client
============================================

The Python SDK for building agents on the Agent-Native Middleware Platform.

Example Usage:
    from b2a_sdk import B2AClient, monitored, billable

    b2a = B2AClient(api_key="agt-xyz123")

    @monitored(b2a, service_name="web_scraper")
    async def scrape_website(url: str):
        ...

    @billable(b2a, wallet_id="agt-123", service_category="content_factory", units=5.0)
    async def generate_video(url: str):
        ...
"""

__version__ = "0.2.0"
__author__ = "Agent-Native Middleware"

from .client import B2AClient, InsufficientFundsError
from .decorators import billable, combined, monitored

__all__ = [
    "B2AClient",
    "InsufficientFundsError",
    "monitored",
    "billable",
    "combined",
]
